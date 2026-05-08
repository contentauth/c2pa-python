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

"""Memory-profile benchmarks for c2pa-python.

Measures peak traced bytes, retained bytes, RSS delta, and allocation count
for the four core scenarios (file/stream × read/sign) across fixture sizes.
First-run policy: record numbers via pytest-benchmark `extra_info` only.
Envelope assertions are commented out until a baseline exists; uncomment
once `.benchmarks/baseline-memory.json` has been captured.

Run with:  make benchmark-memory
"""

import io
import os

import pytest
from c2pa import Reader

from tests._bench_utils import (
    fixture_path,
    make_builder,
    make_signer,
    track_memory,
)


SIZE_LABELS = ["C.jpg", "1MB", "10MB", "50MB"]
SLOW_SIZE_LABELS = ["250MB"]


@pytest.fixture(scope="module")
def signer():
    return make_signer()


def _record(benchmark, sample):
    benchmark.extra_info.update(sample.as_dict())


def _read_from_file(path):
    with open(path, "rb") as f:
        reader = Reader("image/jpeg", f)
        try:
            result = reader.json()
        finally:
            reader.close()
    assert result is not None
    return len(result)


def _read_from_stream(path):
    with open(path, "rb") as f:
        data = f.read()
    reader = Reader("image/jpeg", io.BytesIO(data))
    try:
        result = reader.json()
    finally:
        reader.close()
    assert result is not None
    return len(result)


def _sign_to_file(path, signer, dest_path):
    # Builder is single-use after sign; build fresh per iteration.
    builder = make_builder()
    try:
        with open(path, "rb") as src, open(dest_path, "w+b") as dst:
            builder.sign(signer, "image/jpeg", src, dst)
    finally:
        try:
            builder.close()
        except Exception:
            pass


def _sign_to_stream(path, signer):
    builder = make_builder()
    try:
        out = io.BytesIO()
        with open(path, "rb") as src:
            builder.sign(signer, "image/jpeg", src, out)
    finally:
        try:
            builder.close()
        except Exception:
            pass


@pytest.mark.parametrize("size_label", SIZE_LABELS)
def test_mem_files_read(benchmark, size_label):
    path = fixture_path(size_label)
    with track_memory() as box:
        benchmark(_read_from_file, path)
    sample = box[0]
    benchmark.extra_info["size_label"] = size_label
    benchmark.extra_info["file_size_bytes"] = os.path.getsize(path)
    _record(benchmark, sample)


@pytest.mark.parametrize("size_label", SIZE_LABELS)
def test_mem_streams_read(benchmark, size_label):
    path = fixture_path(size_label)
    with track_memory() as box:
        benchmark(_read_from_stream, path)
    sample = box[0]
    benchmark.extra_info["size_label"] = size_label
    benchmark.extra_info["file_size_bytes"] = os.path.getsize(path)
    _record(benchmark, sample)


@pytest.mark.parametrize("size_label", SIZE_LABELS)
def test_mem_files_build(benchmark, size_label, signer, temp_dir):
    path = fixture_path(size_label)
    dest = os.path.join(temp_dir, f"out_{size_label}.jpg")
    with track_memory() as box:
        benchmark(_sign_to_file, path, signer, dest)
    sample = box[0]
    benchmark.extra_info["size_label"] = size_label
    benchmark.extra_info["file_size_bytes"] = os.path.getsize(path)
    _record(benchmark, sample)


@pytest.mark.parametrize("size_label", SIZE_LABELS)
def test_mem_streams_build(benchmark, size_label, signer):
    path = fixture_path(size_label)
    with track_memory() as box:
        benchmark(_sign_to_stream, path, signer)
    sample = box[0]
    benchmark.extra_info["size_label"] = size_label
    benchmark.extra_info["file_size_bytes"] = os.path.getsize(path)
    _record(benchmark, sample)


@pytest.mark.slow
@pytest.mark.parametrize("size_label", SLOW_SIZE_LABELS)
def test_mem_files_read_slow(benchmark, size_label):
    path = fixture_path(size_label)
    with track_memory() as box:
        benchmark(_read_from_file, path)
    sample = box[0]
    benchmark.extra_info["size_label"] = size_label
    benchmark.extra_info["file_size_bytes"] = os.path.getsize(path)
    _record(benchmark, sample)


@pytest.mark.slow
@pytest.mark.parametrize("size_label", SLOW_SIZE_LABELS)
def test_mem_streams_build_slow(benchmark, size_label, signer):
    path = fixture_path(size_label)
    with track_memory() as box:
        benchmark(_sign_to_stream, path, signer)
    sample = box[0]
    benchmark.extra_info["size_label"] = size_label
    benchmark.extra_info["file_size_bytes"] = os.path.getsize(path)
    _record(benchmark, sample)
