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
| `reports/` | Generated HTML flamegraphs (gitignored). Three files per scenario: `<scenario>-peak.html` (peak/high-water view), `<scenario>-leaks.html` (leak view), and `<scenario>-temporary.html` (temporary-allocations view). |

## Scenarios

Each scenario loops multiple times so leaks accumulate and become visible in the leaks flamegraph and the memory use graph (defaults to 100). Change the count of iterations when running by setting the `MEMRAY_ITERATIONS` variable (the Makefile forwards it into the container):

```bash
make memory-use-bench MEMRAY_ITERATIONS=1000
```

Most scenarios use the Context API: they build a `Context` once and reuse it across iterations, so its settings are parsed a single time. The jpeg and png cases also keep a `_legacy` variant that builds the `Reader`/`Builder` without a `Context`, which re-reads the thread-local settings on each construction. Running a pair (for example `builder_sign_jpeg_legacy` and `builder_sign_jpeg_with_context`) compares the two paths.

## Environments

Select the target environment with `PERF_ENV` (default: `python-3.12-slim`):

| `PERF_ENV` value | Base image | Python | Native symbols |
| --- | --- | --- | --- |
| `python-3.12-slim` | `python:3.12-slim` | 3.12 | interpreter frames unresolved |
| `python-3.10-slim` | `python:3.10-slim` | 3.10 | interpreter frames unresolved |
| `ubuntu-22.04` | `ubuntu:22.04` | 3.10 (apt default) | resolved (`python3-dbg`) |
| `ubuntu-24.04` | `ubuntu:24.04` | 3.12 (apt default) | resolved (`python3-dbg`) |

The slim images run a source-built `/usr/local/bin/python` that ships stripped, and Debian's `python3-dbg` targets a different binary (build-id mismatch), so memray cannot resolve the interpreter's native (C) frames there. You will see a "No debug information was found for the Python interpreter" warning, and native traces may lack file names and line numbers. The ubuntu images install `python3-dbg` for the matching apt interpreter, so their native flamegraphs are fully symbolized. Use an `ubuntu-*` `PERF_ENV` when you need resolved native traces.

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

# Run a single scenario instead of the whole suite
make memory-use-bench SCENARIO=builder_sign_gif

# Refresh just one scenario's baseline entry (others are preserved)
make memory-use-bench SCENARIO=builder_sign_gif PERF_ARGS=--update-baseline

# Remove all generated HTML reports
make clean-memory-perf-reports
```

The trailing `VAR=value` arguments (e.g. `PERF_ENV=ubuntu-24.04`, `PERF_ARGS=--update-baseline`) are `make` variable overrides, not shell env vars. `make` parses `word=value` argument as a variable assignment. Each overrides a `?=` default in the Makefile, and the recipe interpolates them into the `docker build`/`docker run` commands. See [Configuration](#configuration) for the full list and what each forwards to.

Reports are written to `tests/perf/reports/` on the local machine. Three HTML files per scenario, one per suffix (described below). Open any in a browser. After a run, the run also reports if the scenarios were or were not all within baseline threshold (baseline +10% memory use tolerance).

## Report views

Each scenario produces three [memray flamegraphs](https://bloomberg.github.io/memray/flamegraph.html). All three are flamegraphs of the same run. They differ only in which allocations they count.

### `<scenario>-peak.html`: peak/high-water view

What it shows: allocations that were simultaneously alive at the moment the process used the most memory (the high-water mark).

Why it's useful: tells you what drives the largest memory footprint, the working set you must hold at once. Consult this view when you care about peak RSS or OOM headroom.

How to read it: the widest frames are the biggest contributors to peak. Walk up a wide column to the top frame to find the call site holding that memory at the high-water instant.

### `<scenario>-leaks.html`: leak view

What it shows: memory that was allocated but never freed before tracking stopped (`memray --leaks`).

Why it's useful: finds memory leaks, meaning memory that grows with work done. It is never zero, because one-time static setup (the native `libc2pa_c` library loading global structures that live for the whole process) shows as "never freed." A real leak is one that scales with iterations. Profile at `MEMRAY_ITERATIONS=100` and `=1000` and compare: flat means static overhead, growing means a leak. See [Why is leaked_bytes not zero?](#why-is-leaked_bytes-not-zero).

How to read it: a wide frame here is unfreed memory. If its width grows when you raise the iteration count, that top frame is the leaking call site.

### `<scenario>-temporary.html`: temporary-allocations view

What it shows: short-lived churn, meaning memory allocated and then freed almost immediately (memray's threshold: freed before more than one other allocation happens).

Why it's useful: temporary allocations are not leaks, since the memory is returned, but high allocation and free turnover costs CPU and can fragment the heap. This view surfaces hot per-call churn that the peak and leak views hide, because those objects are freed between iterations and so barely register at the high-water mark. Use it when a loop allocates too much.

How to read it: wide frames are the biggest sources of throwaway allocations. The view may be sparse or empty for a scenario that does little churn, which is itself a valid result. See [Temporary allocations](#temporary-allocations).

## Running without Docker (if memray is supported and installed locally)

```bash
pip install memray
python -m tests.perf.run_profile
```

Run a single scenario (useful for generating data for one operation without the full suite):

```bash
python -m tests.perf.run_profile --scenario builder_sign_gif
```

With `--update-baseline`, a single-scenario run only rewrites that scenario's entry in `baseline.json`; the other scenarios' entries are preserved.

```bash
python -m tests.perf.run_profile --scenario builder_sign_gif --update-baseline
```

## Configuration

With `make memory-use-bench VAR=value` you set the **`make` variable** and the Makefile forwards it as shown in the "Forwarded as" column. Running `run_profile.py` without Docker, you set the **env var** (or pass the CLI arg) directly.

| `make` variable | Forwarded as | Default | Description |
| --- | --- | --- | --- |
| `PERF_ENV` | `PERF_ENV` env var | `python-3.12-slim` | Target environment; selects the Dockerfile, tags report filenames (`<scenario>-<PERF_ENV>-<view>.html`), recorded in `baseline.json` `_meta`. See [Environments](#environments). |
| `MEMRAY_ITERATIONS` | `MEMRAY_ITERATIONS` env var | `100` | Loop count per scenario. |
| `MEMRAY_THRESHOLD` | `MEMRAY_THRESHOLD` env var | `1.1` | Regression multiplier (1.1 = 10% tolerance). |
| `SCENARIO` | `--scenario` CLI arg | _(all)_ | Run a single scenario (e.g. `SCENARIO=builder_sign_jpeg`). |
| `PERF_ARGS` | passed straight through | _(none)_ | Extra `run_profile.py` args (e.g. `PERF_ARGS=--update-baseline`). |

`PERF_SCENARIO` is an additional env var, but internal: the runner sets it per scenario so the loop can label its progress. Not user-configurable.

Example to override iteration count:

```bash
make memory-use-bench MEMRAY_ITERATIONS=1000
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

`peak_bytes` is the highest amount of memory in use at any single point during the scenario.

`leaked_bytes` is memory that was allocated during the run but never freed before the process exited. Static allocations persist, since there are one-time loads such as the native library.

`total_allocations` is the total number of individual memory allocation calls made.

### Why is leaked_bytes not zero?

You might expect the baseline to show `leaked_bytes: 0`. In practice it never does. When the c2pa native library (`libc2pa_c.so`) is first loaded, Rust sets up global data structures designed to live for the entire lifetime of the process. They get cleaned up when the process exits, which is after memray stops watching, so memray sees them as "never freed" even though they are not leaking.

A memory leak grows proportionally with work done. If you sign 50 images and get 3.2 MB leaked, then sign 1000 images and still get 3.2 MB leaked, that 3.2 MB is static one-time overhead rather than a leak, since it does not grow with the work that ran. If signing 1000 images gave you 64 MB leaked, that would be a leak, because the leaked memory grows with the work executed.

The baseline captures this expected static overhead. Future runs compare against it: if `leaked_bytes` grows beyond the baseline by more than 10%, the run fails.

### How to confirm no leak exists?

Run with a higher iteration count than default (100) and compare:

```bash
make memory-use-bench MEMRAY_ITERATIONS=1000 PERF_ARGS=--update-baseline
```

If `leaked_bytes` stays flat compared to a 100-iteration run, there is no leak. If it scales with iterations, open `tests/perf/reports/<scenario>-leaks.html` in a browser to see which function is responsible.

### Temporary allocations

`<scenario>-temporary.html` shows temporary allocations, meaning memory that is allocated and then freed almost immediately (memray's threshold is one allocation: a block is temporary if it is freed before more than one other allocation happens). The memory is returned, so these are not leaks, but they are churn: high allocation and free turnover that costs CPU and can fragment the heap. A scenario doing lots of short-lived work can show heavy temporary allocations while `leaked_bytes` stays flat.

Open the file in a browser to see which call sites are responsible. The view may be sparse or empty if a scenario does little churn, which is a valid result. Temporary allocations are not part of the baseline regression check; the graph is a debugging aid only.

### When to update the baseline

Update `baseline.json` after any intentional change that affects memory use:

```bash
make memory-use-bench PERF_ARGS=--update-baseline
```

Commit the updated `baseline.json` alongside the code change, so it becomes the new reference to compare against.
