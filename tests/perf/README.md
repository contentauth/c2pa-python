# Memory Profiling Harness

Uses [memray](https://github.com/bloomberg/memray) to track peak memory, allocation patterns,
and memory leaks across c2pa-python read and sign operations.

## Files

| File | Purpose |
| --- | --- |
| `scenarios.py` | Functions that exercise each profiling scenario. Imported by `run_profile.py`. |
| `run_profile.py` | Memory performance/usage analysis. Runs each scenario under `memray`, generates HTML reports, reads metrics, and compares against `baseline.json`. |
| `Dockerfiles/` | One Dockerfile per target environment. Selected via `PERF_ENV` at `make` time when running the memory analysis. |
| `entrypoint.sh` | Container entrypoint. Downloads the Linux native `libc2pa_c.so` at startup into the volume-mounted workspace so it sticks around even through the `-v` mount. |
| `reports/` | Generated HTML flamegraphs (gitignored). Two files per scenario: `<scenario>.html` (peak/high-water view) and `<scenario>-leaks.html` (leak view). |

## Scenarios

Each scenario loops multiple times so leaks accumulate and become visible in the leaks flamegraph and the memory use graph (defaults to 100). Change the count of iterations when running by setting the `MEMRAY_ITERATIONS` variable (the Makefile forwards it into the container):

```bash
MEMRAY_ITERATIONS=1000 make memory-use-bench
```

## Environments

Select the target environment with `PERF_ENV` (default: `python-3.12-slim`):

| `PERF_ENV` value | Base image | Python |
| --- | --- | --- |
| `python-3.12-slim` | `python:3.12-slim` | 3.12 |
| `python-3.10-slim` | `python:3.10-slim` | 3.10 |
| `ubuntu-22.04` | `ubuntu:22.04` | 3.10 (apt default) |
| `ubuntu-24.04` | `ubuntu:24.04` | 3.12 (apt default) |

## Running (via Docker)

```bash
# First run (if there is no baseline.json): establishes baseline.json
make memory-use-bench

# Subsequent runs: compares against baseline, fails if >10% regression
make memory-use-bench

# Refresh baseline after an intentional memory change
make memory-use-bench PERF_ARGS=--update-baseline

# Run against a different runner environment
make memory-use-bench PERF_ENV=ubuntu-24.04

# Remove all generated HTML reports
make clean-memory-perf-reports
```

Reports are written to `tests/perf/reports/` on the local machine. Two HTML files per scenario: `<scenario>.html` for the peak/high-water view and `<scenario>-leaks.html` for the leak view. Open either in a browser. After a run, the run also reports if the scenarios were or were not all within baseline threshold (baseline +10% memory use tolerance).

## Running without Docker (if memray is supported and installed locally)

```bash
pip install memray
python -m tests.perf.run_profile
```

## Environment variables

| Variable | Default | Description |
| --- | --- | --- |
| `MEMRAY_ITERATIONS` | `100` | Loop count per scenario |
| `MEMRAY_THRESHOLD` | `1.1` | Regression multiplier (1.1 = 10% tolerance) |

Override iteration count:

```bash
MEMRAY_ITERATIONS=1000 make memory-use-bench
```

## Reading baseline.json

`baseline.json` is committed to the repo and reports following data for each scenario:

```json
{
  "_meta": {
    "memray_version": "1.19.3",
    "python_version": "3.12.13",
    "c2pa_native_version": "c2pa-v0.85.0",
    "iterations": 100,
    "perf_env": "python-3.12-slim",
    "arch": "x86_64"
  },
  "scenario_name": {
    "peak_bytes": 62914560,
    "leaked_bytes": 3271766,
    "total_allocations": 12840
  },
  ...
}
```

The `_meta` block records which toolchain produced the baseline so the numbers are reproducible. It is provenance only and is never compared against. The regression check only looks at the per-scenario entries.

| `_meta` field | Meaning |
| --- | --- |
| `memray_version` | memray version that generated the metrics |
| `python_version` | Python version that ran the test harness |
| `c2pa_native_version` | native `libc2pa_c` version (from `c2pa-native-version.txt`) |
| `iterations` | `MEMRAY_ITERATIONS` used for the run |
| `perf_env` | `PERF_ENV` (target environment) |
| `arch` | machine architecture (`platform.machine()`) |

`peak_bytes`, `total_allocations` and the `arch`/`python`/`memray` versions are all environment-sensitive: a baseline is most meaningful when compared against a run from the same `_meta`.

**`peak_bytes`**: the highest amount of memory in use at any single point during the scenario.

**`leaked_bytes`**: memory that was allocated during the run but never freed before the process exited. Static allocations will persist, as there are one-time loads (e.g. the native library).

**`total_allocations`**: total number of individual memory allocation calls made.

### Why leaked_bytes is not zero

You might expect a the baseline to show `leaked_bytes: 0`. In practice it never does: when the c2pa native library (`libc2pa_c.so`) is first loaded, Rust sets up global data structures that are designed to live for the entire lifetime of the process. They get cleaned up when the process exits, which is after memray stops watching. So memray sees them as "never freed" even though they are not actually leaking.

A memory leak grows proportionally with work done. If you sign 50 images and get 3.2 MB leaked, then sign 1000 images and still get 3.2 MB leaked, that 3.2 MB is static one-time overhead, not an actual leak (since it does not grow depending on the work that ran). If signing 1000 images gave you 64 MB leaked, that would be a leak, as there is a memory leak growth growing depending on the work that was executed.

The baseline captures this expected static overhead. Future runs compare against it: if `leaked_bytes` grows beyond the baseline by more than 10%, the run fails.

### How to confirm no leak exists

Run with a higher iteration count than default (100) and compare:

```bash
MEMRAY_ITERATIONS=1000 make memory-use-bench PERF_ARGS=--update-baseline
```

If `leaked_bytes` stays flat compared to a 100-iteration run, there is no leak. If it scales with iterations, open `tests/perf/reports/<scenario>-leaks.html` in a browser to see which function is responsible.

### When to update baseline

Update `baseline.json` after any intentional change that affects memory use:

```bash
make memory-use-bench PERF_ARGS=--update-baseline
```

Commit the updated `baseline.json` alongside the code change, so it becomes the new reference to compare against.
