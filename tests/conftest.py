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

"""Pytest configuration shared by the new benchmark suites.

The existing tests (test_unit_tests.py, test_unit_tests_threaded.py,
benchmark.py) do not depend on anything here — they continue to work as
before. This module only adds opt-in fixtures and hooks that activate when
the new benchmark files are collected.
"""

import os

import pytest

_BENCH_FILES = {"benchmark_memory.py", "benchmark_stress.py"}


def _collected_bench_files(items) -> bool:
    return any(os.path.basename(str(getattr(item, "fspath", ""))) in _BENCH_FILES
               for item in items)


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "slow: opt-in slow benchmark; runs the 250MB fixture and other long tests",
    )


def pytest_collection_modifyitems(config, items):
    """Lazily ensure synthetic fixtures exist when a bench file is collected.

    Skipping this work for the regular test suites keeps `make test` fast.
    """
    if not _collected_bench_files(items):
        return
    from tests._bench_utils import ensure_fixtures, FIXTURE_SIZES

    # Keep the 250MB fixture optional even at generation time: only build it
    # when a slow-marked test will run.
    run_slow = any("slow" in item.keywords for item in items)
    sizes = FIXTURE_SIZES if run_slow else [
        (label, size) for (label, size) in FIXTURE_SIZES if label != "250MB"
    ]
    ensure_fixtures(sizes)


@pytest.fixture
def temp_dir(tmp_path):
    """Per-test temp directory backed by pytest's tmp_path."""
    return str(tmp_path)


def pytest_benchmark_update_machine_info(config, machine_info):
    """Stamp libc2pa version into pytest-benchmark JSON output."""
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    version_file = os.path.join(project_root, "c2pa-native-version.txt")
    try:
        with open(version_file, "r") as f:
            machine_info["c2pa_native_version"] = f.read().strip()
    except OSError:
        machine_info["c2pa_native_version"] = "unknown"
