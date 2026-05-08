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

"""Shared helpers for memory and stress benchmark suites.

Leading underscore in the filename keeps pytest from collecting it as tests.
"""

import contextlib
import dataclasses
import gc
import os
import struct
import tracemalloc
from typing import Iterable, List, Tuple

import psutil

from c2pa import (
    Builder,
    C2paSignerInfo,
    Reader,  # noqa: F401  (re-exported for benchmark modules)
    Signer,
)


PROJECT_PATH = os.getcwd()
FIXTURES_DIR = os.path.join(PROJECT_PATH, "tests", "fixtures")
GENERATED_DIR = os.path.join(FIXTURES_DIR, "generated")
BASE_JPEG = os.path.join(FIXTURES_DIR, "C.jpg")

# (label, byte size). 250MB is opt-in for slow runs.
FIXTURE_SIZES: List[Tuple[str, int]] = [
    ("1MB", 1 << 20),
    ("10MB", 10 << 20),
    ("50MB", 50 << 20),
    ("250MB", 250 << 20),
]

MANIFEST_DEF = {
    "claim_generator": "python_bench",
    "claim_generator_info": [{
        "name": "python_bench",
        "version": "0.0.1",
    }],
    "format": "image/jpeg",
    "title": "Python Benchmark Image",
    "ingredients": [],
    "assertions": [
        {
            "label": "c2pa.actions",
            "data": {
                "actions": [
                    {
                        "action": "c2pa.created",
                        "digitalSourceType": (
                            "http://cv.iptc.org/newscodes/digitalsourcetype/"
                            "digitalCreation"
                        ),
                    }
                ]
            },
        }
    ],
}


def make_signer() -> Signer:
    """Build a ps256 signer for benches.

    Note: c2pa-rs requires a non-empty TSA URL when `ta_url` is provided.
    For loops with many iterations, prefer the file-only signers used in
    the c2pa-rs test suite. Here we keep the same TSA used by
    `tests/benchmark.py` for parity.
    """
    with open(os.path.join(FIXTURES_DIR, "ps256.pem"), "rb") as f:
        private_key = f.read()
    with open(os.path.join(FIXTURES_DIR, "ps256.pub"), "rb") as f:
        certs = f.read()
    info = C2paSignerInfo(
        alg=b"ps256",
        sign_cert=certs,
        private_key=private_key,
        ta_url=b"http://timestamp.digicert.com",
    )
    return Signer.from_info(info)


def make_builder() -> Builder:
    return Builder(MANIFEST_DEF)


def _pad_jpeg_to_size(src_path: str, dst_path: str, target_size: int) -> None:
    """Grow a JPEG to target_size by appending APP15 (0xFFEF) padding segments
    inserted before the final EOI marker.

    APPn segments carry application-specific data and are skipped by JPEG
    decoders that don't recognize the marker, including the c2pa parser.
    Each segment can hold up to 65533 bytes of payload (length field is u16
    and includes its own two bytes).
    """
    with open(src_path, "rb") as f:
        original = f.read()

    if not original.endswith(b"\xff\xd9"):
        raise RuntimeError(f"{src_path} is not a JPEG (missing EOI marker)")

    body = original[:-2]
    eoi = original[-2:]
    needed = target_size - len(body) - len(eoi)
    if needed <= 0:
        # Source already at or above target; copy through.
        with open(dst_path, "wb") as f:
            f.write(original)
        return

    max_payload = 65533  # 0xFFFD; segment length includes 2 bytes for itself
    segments = []
    remaining = needed
    while remaining > 0:
        # Segment overhead: 2 bytes marker + 2 bytes length.
        overhead = 4
        if remaining <= max_payload + overhead:
            payload = max(0, remaining - overhead)
        else:
            payload = max_payload
        seg_len = payload + 2  # length field counts itself + payload
        segments.append(b"\xff\xef" + struct.pack(">H", seg_len) + b"\x00" * payload)
        remaining -= payload + overhead

    with open(dst_path, "wb") as f:
        f.write(body)
        for seg in segments:
            f.write(seg)
        f.write(eoi)


def make_jpeg(size_bytes: int, path: str) -> None:
    """Idempotently create a synthetic JPEG of approx size_bytes at path."""
    if os.path.exists(path):
        actual = os.path.getsize(path)
        # Allow a small tolerance for the final-segment rounding.
        if abs(actual - size_bytes) <= 8:
            return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    _pad_jpeg_to_size(BASE_JPEG, path, size_bytes)


def fixture_path(label: str) -> str:
    """Return path for a labeled fixture; "C.jpg" returns the source asset."""
    if label == "C.jpg":
        return BASE_JPEG
    return os.path.join(GENERATED_DIR, f"C_{label}.jpg")


def ensure_fixtures(sizes: Iterable[Tuple[str, int]] = FIXTURE_SIZES) -> None:
    """Generate all sized fixtures up front. Idempotent."""
    for label, size in sizes:
        make_jpeg(size, fixture_path(label))


@dataclasses.dataclass
class MemSample:
    peak_traced: int
    current_traced: int
    rss_delta_bytes: int
    alloc_count: int

    def as_dict(self) -> dict:
        return {
            "peak_traced": self.peak_traced,
            "current_traced": self.current_traced,
            "rss_delta_bytes": self.rss_delta_bytes,
            "alloc_count": self.alloc_count,
        }


@contextlib.contextmanager
def track_memory():
    """Context manager yielding a list whose only element is filled with a
    MemSample on exit. Caller pattern:

        with track_memory() as box:
            do_work()
        sample = box[0]
    """
    gc.collect()
    proc = psutil.Process()
    rss_before = proc.memory_info().rss
    tracemalloc.start(25)
    snapshot_before = tracemalloc.take_snapshot()
    box: list = []
    try:
        yield box
    finally:
        snapshot_after = tracemalloc.take_snapshot()
        current_traced, peak_traced = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        gc.collect()
        rss_after = proc.memory_info().rss
        diff = snapshot_after.compare_to(snapshot_before, "filename")
        alloc_count = sum(stat.count_diff for stat in diff if stat.count_diff > 0)
        box.append(
            MemSample(
                peak_traced=peak_traced,
                current_traced=current_traced,
                rss_delta_bytes=rss_after - rss_before,
                alloc_count=alloc_count,
            )
        )


def compute_slope(rss_samples: List[Tuple[int, int]]) -> float:
    """Manual least-squares slope on (iter, rss). Returns slope in
    bytes/iter; does not raise.
    """
    n = len(rss_samples)
    if n < 2:
        raise ValueError("need at least 2 samples to compute slope")
    sx = sum(x for x, _ in rss_samples)
    sy = sum(y for _, y in rss_samples)
    sxx = sum(x * x for x, _ in rss_samples)
    sxy = sum(x * y for x, y in rss_samples)
    denom = n * sxx - sx * sx
    if denom == 0:
        return 0.0
    return (n * sxy - sx * sy) / denom


def assert_no_growth(
    rss_samples: List[Tuple[int, int]],
    max_slope_bytes_per_iter: float = 1024.0,
) -> float:
    """Compute least-squares slope and assert it does not exceed the cap."""
    slope = compute_slope(rss_samples)
    assert slope <= max_slope_bytes_per_iter, (
        f"RSS growth slope {slope:.1f} bytes/iter exceeds "
        f"threshold {max_slope_bytes_per_iter:.1f} bytes/iter "
        f"(samples={rss_samples!r})"
    )
    return slope
