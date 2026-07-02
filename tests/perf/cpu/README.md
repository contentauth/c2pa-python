# CPU profiling framework

Uses [py-spy](https://github.com/benfred/py-spy) to profile where CPU time goes across c2pa-python operations, plus plain timing measurements to track wall/CPU time per scenario against a baseline.

## Files

| File | Purpose |
| --- | --- |
| `../scenarios.py` | Functions that exercise each profiling scenario. Imported by `run_profile.py`. |
| `run_profile.py` | CPU analysis. Times each scenario in a plain child process, renders a py-spy flamegraph per scenario, and compares timings against `baseline.json`. |
| `baseline.json` | Committed reference timings (`_meta` provenance block + per-scenario `wall_seconds`, `cpu_seconds`, `children_cpu_seconds`). |
| `../Dockerfiles/` | One Dockerfile per target environment (shared with the memory benchmark). Selected via `PERF_ENV` at `make` time. |
| `../entrypoint.sh` | Container entrypoint (shared). Downloads the Linux native `libc2pa_c.so` at startup. |
| `reports/` | Generated profiles (gitignored). One file per scenario: `<scenario>-cpu.svg` (or `.speedscope.json` with `PYSPY_FORMAT=speedscope`). |

## Approach: two passes per scenario

1. Timing pass: the scenario runs in a plain child process with no profiler attached. The child measures three metrics around the scenario call only, excluding interpreter startup, and hands the result back as JSON: `wall_seconds` (`time.perf_counter`), `cpu_seconds` (`time.process_time`, process-wide so the thread-pool scenarios count all threads), and `children_cpu_seconds` (`resource.getrusage(RUSAGE_CHILDREN)`, the CPU burned in forked children, which `process_time` cannot see; relevant for the `fork_*` scenarios). These numbers feed the baseline comparison.
2. Profile pass: the scenario runs again under `py-spy record` to produce a flamegraph. Profile numbers never feed the baseline, since sampling adds rate-dependent overhead that would bake profiler cost into the timings.

Scenario children run with `PERF_DISABLE_TSA=1` by default, so signing scenarios skip the network round-trip to the timestamp authority that every `sign` call otherwise makes. Timings then measure code, not network latency. Pass `PERF_DISABLE_TSA=0` to restore the TSA call. The memory benchmark is unaffected either way; it keeps TSA on.

When a scenario's first timing pass finishes in under 1 second, the harness runs 4 more passes and records the median of each metric, because single-shot timing at that scale is mostly jitter. Set `CPU_REPEATS=N` to force a fixed pass count instead.

Locally the default `--mode all` runs both passes back to back. In CI they run as two parallel jobs on separate runners (`--mode timing` / `--mode profile`), so sampling never contends with the timed run and wall-clock cost stays at one pass.

## CI/CD report

Timings on shared CI runners are noisy (±10-20% wall-clock swing is normal). The harness therefore ships report-only: baseline deltas are printed and shown in the CI step summary: rows over the threshold get a `drift` status, but the run always exits 0.

## Running

The benchmarks run inside Docker and need the perf Docker image:

```bash
make perf-image-rebuild                 # once, or after dependency changes
```

Once the image is built, run the benchmarks:

```bash
# all scenarios, timing + flamegraphs
make cpu-bench

# run only one scenario
make cpu-bench SCENARIO=builder_sign_gif

# timings only
make cpu-bench CPU_MODE=timing

# flamegraphs only
make cpu-bench CPU_MODE=profile

# update baselines
make cpu-bench PERF_ARGS=--update-baseline
```

The `cpu-bench` target runs the container with `--cap-add SYS_PTRACE --security-opt seccomp=unconfined`. `py-spy` samples the child process via ptrace and `process_vm_readv`, which the default container security profile blocks.

## Variables

| Variable | Default | Meaning |
| --- | --- | --- |
| `CPU_ITERATIONS` | `100` | Loop count per scenario (the Makefile forwards it into the container). |
| `CPU_THRESHOLD` | `1.25` | Drift multiplier vs baseline (1.25 = +25%) used for the `drift` status. |
| `CPU_MODE` | `all` | `all`, `timing`, or `profile` (maps to `--mode`). |
| `CPU_REPEATS` | `0` | Fixed timing pass count per scenario, median recorded. `0` = adaptive: 1 pass, extended to 5 when the first pass runs under 1 s. |
| `PERF_DISABLE_TSA` | `1` (set by the harness) | Skip the timestamp-authority network call during signing. Set `0` to restore it. |
| `PYSPY_RATE` | `100` | Sampling rate in Hz. Raise (up to ~500) if flamegraphs for fast scenarios look sparse. |
| `PYSPY_FORMAT` | `flamegraph` | `flamegraph` writes self-contained SVGs; `speedscope` writes JSON for [speedscope.app](https://www.speedscope.app/). |
| `PERF_ENV` | `python-3.12-slim` | Which Docker environment to use (see `../Dockerfiles/`). |
| `SCENARIO` | unset | Run a single scenario. |
| `PERF_ARGS` | unset | Extra args for `run_profile.py`, e.g. `--update-baseline`. |

## Interpreting the flamegraphs

Profiles show Python frames only. Time spent inside the Rust `libc2pa_c` library is attributed to the Python frame that made the FFI call. Fast scenarios at the default 100 Hz can produce thin profiles; raise `PYSPY_RATE` or `CPU_ITERATIONS` for more samples.

## Updating the baseline

Run with `--update-baseline` on. Single-scenario updates merge into the existing file and warn if the environment (`_meta`) does not match the other entries.

Without a committed `baseline.json`, a run creates one and reports no deltas.

## Reading the CI/CD report

The step summary table compares each scenario's current metrics against `baseline.json`, showing deltas (Δ) as percentages. Rows exceeding the drift threshold (default +25%) are marked with `drift` status in the rightmost column.

### Table columns

| Column | Meaning |
| --- | --- |
| `scenario` | Scenario name. |
| `wall` | Wall-clock time (seconds), across all iterations. |
| `cpu` | CPU time (seconds), process-wide; excludes I/O, sleep, time in child processes. |
| `cpu/iter` | Per-iteration CPU cost (cpu ÷ iterations). |
| `child cpu` | CPU burned in forked child processes (`fork_*` scenarios). Parent CPU time does not include this. |
| `wall Δ%` | Wall-clock drift: `(current - baseline) / baseline × 100`. Exceeds threshold → marked `drift`. |
| `cpu Δ%` | CPU time drift (same calculation). Informational only; does not trigger drift. |
| `status` | `ok` if within threshold; `drift` if over +25%. Informational; never fails the run. |

### Common sources of large drifts (>25%)

**Hardware mismatch**: Baseline generated on aarch64 ARM CPU; new run on x86_64 or different CPU generation. Check baseline `_meta.arch` (e.g., `aarch64`); if it doesn't match your runner's `platform.machine()`, re-baseline.

**Native library version mismatch**: `_meta.c2pa_native_version` changed (e.g., c2pa-v0.89.0 → c2pa-v0.90.0). Native library performance can shift between releases, especially for asset hashing (GIF parsing, ingredient re-encoding). Re-baseline with `make cpu-bench PERF_ARGS=--update-baseline`.

**CI runner contention**: Shared runners see ±10–20% wall-clock variance as normal. Burst load (other jobs, system activity) can push drifts to 50–80%. A single run with high drift is often temporary; re-run to confirm.

**TSA re-enabled**: By default, CPU runs disable timestamp-authority network calls (`PERF_DISABLE_TSA=1`). If re-enabled (`PERF_DISABLE_TSA=0`), signing scenarios add unpredictable network latency (typically +5–10 seconds per run, high variance). This looks like a CPU regression but is external latency.

### When drifts indicate a real problem

**Both `cpu_seconds` and `wall_seconds` drift together (same direction/magnitude)**, and the environment matches the baseline (`_meta.arch` = `platform.machine()`, native lib version unchanged) is a possible real CPU regression. Compare the scenario's logic against recent code changes.

**Only `wall_seconds` drifts; `cpu_seconds` is stable** is due to I/O contention or CI runner load, not a CPU regression.

**Only `cpu_seconds` drifts; `wall_seconds` is stable** should be rare, likely a measurement artifact or GC timing variation in a single run.

### When to update the baseline

**Native library upgrade**: `c2pa-native-version.txt` changed.

**Environment change**: Different `PERF_ENV`, CPU architecture, or Python version.

**Parameter change**: Modified `CPU_ITERATIONS` (e.g., from 100 to 200).

Command:
```bash
make cpu-bench PERF_ARGS=--update-baseline
```

This rewrites `baseline.json` with current metrics and metadata (`_meta`). Commit the updated baseline alongside your code changes.

## CI

`.github/workflows/cpu-benchmark.yml` runs on PRs labeled `check-cpu-benchmark`, on `ubuntu-24.04-arm` to match the baseline arch.

Two parallel jobs run for this workflow:

- `cpu-timing` measures timing metrics; the baseline comparison table lands in the job's step summary.
- `cpu-profile` renders the py-spy flamegraphs and uploads them as the `pyspy-cpu-flamegraphs` artifact.
