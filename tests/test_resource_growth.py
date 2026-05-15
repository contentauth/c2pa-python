# Copyright 2025 Adobe. All rights reserved.
# This file is licensed to you under the Apache License,
# Version 2.0 (http://www.apache.org/licenses/LICENSE-2.0)
# or the MIT license (http://opensource.org/licenses/MIT),
# at your option.

# Unless required by applicable law or agreed to in writing,
# this software is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR REPRESENTATIONS OF ANY KIND, either express or
# implied. See the LICENSE-MIT and LICENSE-APACHE files for the
# specific language governing permissions and limitations under
# each license.

"""
Regression tests for resource growth under concurrent Reader/Builder load.

Root causes fixed in c2pa-rs:
  - A new tokio multi-thread Runtime (= new OS thread pool) was created per
    Reader FFI call. Under load this produced hundreds of leaked threads.
  - A new reqwest::Client (= new TCP connection pool) was created per
    Reader/Builder instance and not pooled.

These tests measure OS-level thread count and RSS before/after a burst of
concurrent Reader operations and assert both stay within reasonable bounds.
They are expected to FAIL against the un-fixed c2pa-rs library.
"""

import ctypes
import ctypes.util
import gc
import io
import os
import platform
import struct
import threading
import time
import unittest
import concurrent.futures

from c2pa import Reader

FIXTURES_FOLDER = os.path.join(os.path.dirname(__file__), "fixtures")
DEFAULT_TEST_FILE = os.path.join(FIXTURES_FOLDER, "C.jpg")

# Burst parameters that reproduce production-scale pressure without being
# excessively slow in CI.
BURST_ITERATIONS = 60
BURST_WORKERS = 8

# Thresholds — intentionally generous to avoid flakiness, but tight enough
# to catch the original bugs (which produced 400+ threads and hundreds of MB).
MAX_THREAD_GROWTH = BURST_WORKERS + 4   # executor threads + small buffer
MAX_MEMORY_GROWTH_MB = 80               # generous; old code would add 300+ MB


def _proc_status() -> dict[str, str]:
    """Read /proc/self/status on Linux; return empty dict on other platforms."""
    try:
        with open("/proc/self/status") as f:
            return dict(
                line.split(":", 1) for line in f if ":" in line
            )
    except OSError:
        return {}


def _thread_count() -> int:
    """OS-level thread count (includes native tokio threads, not just Python)."""
    status = _proc_status()
    if "Threads" in status:
        return int(status["Threads"].strip())
    # macOS / Windows fallback: Python threads only (still catches Python leaks)
    return threading.active_count()


def _rss_mb_macos() -> float | None:
    """Current RSS on macOS via mach task_info(TASK_BASIC_INFO). No dependencies."""
    if platform.system() != "Darwin":
        return None
    # task_basic_info layout (arm64 / x86_64):
    #   uint32  virtual_size       (but mach_vm_size_t = uint64 on 64-bit)
    #   uint64  virtual_size
    #   uint64  resident_size
    #   uint64  resident_size_max
    #   int32   user_time.seconds
    #   int32   user_time.microseconds
    #   int32   system_time.seconds
    #   int32   system_time.microseconds
    #   int32   policy
    #   int32   suspend_count
    # Defined in <mach/task_info.h>; TASK_BASIC_INFO = 5, count = 10 (32-bit integers).
    # On 64-bit the sizes are natural_t (32) + mach_vm_size_t (64) fields;
    # easier to use MACH_TASK_BASIC_INFO (20) which has a well-known struct layout.
    MACH_TASK_BASIC_INFO = 20
    # struct mach_task_basic_info { uint64 vsize, rsize, rsize_max; time_value_t utime, stime; int32 policy, suspend }
    # time_value_t = { int32 sec, int32 usec } → total struct = 3×8 + 2×(2×4) + 2×4 = 24 + 16 + 8 = 48 bytes
    fmt = "QQQiiiiii"  # 3 uint64 + 6 int32 = 24+24 = 48 bytes
    buf = (ctypes.c_uint32 * (struct.calcsize(fmt) // 4))()
    count = ctypes.c_uint32(struct.calcsize(fmt) // 4)
    try:
        libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
        ret = libc.task_info(
            libc.mach_task_self(),
            ctypes.c_uint32(MACH_TASK_BASIC_INFO),
            ctypes.byref(buf),
            ctypes.byref(count),
        )
        if ret != 0:
            return None
        rss_bytes = struct.unpack_from(fmt, buf)[1]  # resident_size is second uint64
        return rss_bytes / (1024.0 * 1024.0)
    except Exception:
        return None


def _rss_mb() -> float | None:
    """Resident set size in MB, or None if not measurable."""
    macos_rss = _rss_mb_macos()
    if macos_rss is not None:
        return macos_rss
    status = _proc_status()
    if "VmRSS" in status:
        kb = int(status["VmRSS"].strip().split()[0])
        return kb / 1024.0
    return None


class TestConcurrentReaderResourceGrowth(unittest.TestCase):
    """Verify that concurrent Reader operations do not leak threads or memory.

    The burst deliberately mirrors the production pattern: many goroutines /
    asyncio tasks simultaneously calling the C2PA signing stack, each going
    through Reader.json() which triggers post-validation via the Rust FFI.
    """

    @classmethod
    def setUpClass(cls):
        with open(DEFAULT_TEST_FILE, "rb") as f:
            cls.test_data = f.read()

    def _read_once(self) -> None:
        buf = io.BytesIO(self.test_data)
        reader = Reader("image/jpeg", buf)
        _ = reader.json()
        reader.close()

    def _burst(self, iterations: int = BURST_ITERATIONS, workers: int = BURST_WORKERS) -> None:
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(self._read_once) for _ in range(iterations)]
            for f in concurrent.futures.as_completed(futures):
                f.result()  # re-raise any exception from the worker

    def test_thread_count_stable_under_load(self):
        """OS thread count must not grow unboundedly during a Reader burst.

        Before fix: each Reader FFI call created a new tokio multi-thread
        Runtime (Builder::new_multi_thread()) = ~8 new OS threads each call.
        60 calls × 8 threads = 480+ leaked threads on top of baseline.

        After fix: one shared static Runtime; thread count stays near baseline.
        """
        # Warm up: let the static runtime and connection pool initialise once.
        self._burst(iterations=10, workers=4)
        gc.collect()
        time.sleep(0.2)

        threads_before = _thread_count()

        self._burst()
        gc.collect()
        time.sleep(0.5)  # allow OS to reap any transient threads

        threads_after = _thread_count()
        growth = threads_after - threads_before

        self.assertLessEqual(
            growth,
            MAX_THREAD_GROWTH,
            f"Thread count grew by {growth} (before={threads_before}, after={threads_after}). "
            f"Indicates a tokio Runtime is being created per FFI call instead of shared. "
            f"Expected growth ≤ {MAX_THREAD_GROWTH}.",
        )

    def test_memory_stable_under_load(self):
        """RSS must not grow unboundedly during a Reader burst.

        Before fix: each Reader held a private reqwest::Client (TCP connection
        pool ~100-500 KB each). 60 concurrent Readers = 30-300 MB of pools
        accumulating before GC can collect them.

        After fix: one shared static reqwest::Client; RSS stays near baseline.
        """
        rss_before = _rss_mb()
        if rss_before is None:
            self.skipTest("RSS measurement not available on this platform")

        # Warm up
        self._burst(iterations=10, workers=4)
        gc.collect()
        time.sleep(0.2)

        rss_before = _rss_mb()

        self._burst()
        gc.collect()
        time.sleep(0.5)

        rss_after = _rss_mb()
        growth_mb = rss_after - rss_before

        self.assertLess(
            growth_mb,
            MAX_MEMORY_GROWTH_MB,
            f"RSS grew by {growth_mb:.1f} MB (before={rss_before:.1f} MB, after={rss_after:.1f} MB). "
            f"Indicates connection pools or Rust objects are not being shared/freed. "
            f"Expected growth < {MAX_MEMORY_GROWTH_MB} MB.",
        )

    def test_stream_callbacks_released_on_close(self):
        """Stream callbacks must be None after close(), not held until GC.

        Callbacks hold references to the backing BytesIO which delays
        memory reclamation under concurrent load.
        """
        buf = io.BytesIO(self.test_data)
        # Access internal Stream via Reader internals is not possible directly;
        # test via the public Stream class used by Builder.
        from c2pa.c2pa import Stream

        inner_buf = io.BytesIO(self.test_data)
        stream = Stream(inner_buf)
        self.assertTrue(stream._read_cb is not None, "callback should exist before close")
        stream.close()
        self.assertIsNone(stream._read_cb, "_read_cb must be None after close()")
        self.assertIsNone(stream._seek_cb, "_seek_cb must be None after close()")
        self.assertIsNone(stream._write_cb, "_write_cb must be None after close()")
        self.assertIsNone(stream._flush_cb, "_flush_cb must be None after close()")


if __name__ == "__main__":
    unittest.main()
