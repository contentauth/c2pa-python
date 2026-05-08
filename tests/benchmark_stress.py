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

"""Stress benchmarks for c2pa-python.

Concurrency, large-file scaling, leak detection over many iterations, and
mixed long-running workload. These are correctness/stability checks that
also report timing — they are NOT primarily wall-time benchmarks.

Run with:  make benchmark-stress
Slow tests (250MB):  make benchmark-stress-slow
"""

import gc
import io
import os
import time
from concurrent.futures import ThreadPoolExecutor

import psutil
import pytest
from c2pa import Reader

from tests._bench_utils import (
    assert_no_growth,
    compute_slope,
    fixture_path,
    make_builder,
    make_signer,
)


BASE_FIXTURE = fixture_path("C.jpg")


@pytest.fixture(scope="module")
def signer():
    return make_signer()


def _do_read(path):
    with open(path, "rb") as f:
        reader = Reader("image/jpeg", f)
        try:
            return len(reader.json())
        finally:
            reader.close()


def _do_sign(path, signer):
    builder = make_builder()
    try:
        out = io.BytesIO()
        with open(path, "rb") as src:
            builder.sign(signer, "image/jpeg", src, out)
        return out.tell()
    finally:
        try:
            builder.close()
        except Exception:
            pass


# ----- concurrency -----


@pytest.mark.parametrize("workers", [2, 4, 8, 16])
def test_stress_concurrent_read(benchmark, workers):
    iterations_per_worker = 5

    def run():
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futs = [
                pool.submit(_do_read, BASE_FIXTURE)
                for _ in range(workers * iterations_per_worker)
            ]
            for fut in futs:
                fut.result()

    benchmark(run)


@pytest.mark.parametrize("workers", [2, 4, 8])
def test_stress_concurrent_sign(benchmark, workers, signer):
    iterations_per_worker = 3

    def run():
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futs = [
                pool.submit(_do_sign, BASE_FIXTURE, signer)
                for _ in range(workers * iterations_per_worker)
            ]
            for fut in futs:
                fut.result()

    benchmark(run)


# ----- scaling -----


@pytest.mark.parametrize("size_label", ["1MB", "10MB", "50MB"])
def test_stress_large_file_scaling(benchmark, size_label):
    path = fixture_path(size_label)
    benchmark(_do_read, path)
    benchmark.extra_info["size_label"] = size_label
    benchmark.extra_info["file_size_bytes"] = os.path.getsize(path)


@pytest.mark.slow
def test_stress_large_file_scaling_250mb(benchmark):
    path = fixture_path("250MB")
    benchmark(_do_read, path)
    benchmark.extra_info["size_label"] = "250MB"
    benchmark.extra_info["file_size_bytes"] = os.path.getsize(path)


# ----- leak detection -----


def _sample_rss(proc):
    return proc.memory_info().rss


def test_stress_repeated_read_no_leak():
    iterations = 500
    sample_every = 50
    proc = psutil.Process()

    # Warmup so first samples don't include FFI/library load deltas.
    for _ in range(10):
        _do_read(BASE_FIXTURE)
    gc.collect()

    samples = []
    for i in range(iterations):
        _do_read(BASE_FIXTURE)
        if i % sample_every == 0:
            gc.collect()
            samples.append((i, _sample_rss(proc)))
    gc.collect()
    samples.append((iterations, _sample_rss(proc)))

    slope = assert_no_growth(samples, max_slope_bytes_per_iter=1024.0)
    print(f"\nrepeated_read_no_leak slope = {slope:.2f} bytes/iter")


def test_stress_repeated_sign_no_leak(signer):
    # Report-only: the sign path's per-iteration growth lives in
    # `c2pa_builder_sign` (Rust) and is not addressable from the Python
    # bindings.  We capture the slope so cross-version comparison stays
    # possible, but we do not gate on it — that would always fail and
    # mask real Python-side regressions.
    #
    # Lower iteration count than the read leak test: each sign hits the
    # TSA, and public TSAs rate-limit past a few hundred requests/min.
    iterations = 50
    sample_every = 5
    proc = psutil.Process()

    for _ in range(5):
        _do_sign(BASE_FIXTURE, signer)
    gc.collect()

    samples = []
    for i in range(iterations):
        _do_sign(BASE_FIXTURE, signer)
        if i % sample_every == 0:
            gc.collect()
            samples.append((i, _sample_rss(proc)))
    gc.collect()
    samples.append((iterations, _sample_rss(proc)))

    slope = compute_slope(samples)
    print(f"\nrepeated_sign_no_leak slope = {slope:.2f} bytes/iter "
          f"(Rust-side; report-only)")


# ----- long-running mixed -----


def test_stress_long_running_mixed(signer):
    """Runs a mixed read/sign workload for ~60s and reports RSS slope.

    Report-only: the workload includes signing, which inherits the
    Rust-side growth from `c2pa_builder_sign`.  We report the slope but
    do not gate on it — see test_stress_repeated_sign_no_leak.
    """
    deadline = time.monotonic() + 60.0
    proc = psutil.Process()

    for _ in range(5):
        _do_read(BASE_FIXTURE)
        _do_sign(BASE_FIXTURE, signer)
    gc.collect()

    samples = []
    i = 0
    next_sample = 0
    while time.monotonic() < deadline:
        _do_read(BASE_FIXTURE)
        _do_sign(BASE_FIXTURE, signer)
        i += 1
        if i >= next_sample:
            gc.collect()
            samples.append((i, _sample_rss(proc)))
            next_sample = i + 25

    gc.collect()
    samples.append((i, _sample_rss(proc)))

    if len(samples) < 2:
        pytest.skip("host too slow to gather >=2 samples in 60s")

    slope = compute_slope(samples)
    print(f"\nlong_running_mixed slope = {slope:.2f} bytes/iter "
          f"over {i} iterations (Rust-side; report-only)")
