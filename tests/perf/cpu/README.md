# CPU profiling framework

Uses [py-spy](https://github.com/benfred/py-spy) to profile where CPU time goes across c2pa-python operations, plus plain timing measurements to report wall/CPU time per scenario.

## Files

| File | Purpose |
| --- | --- |
| `../scenarios.py` | Functions that exercise each profiling scenario. Imported by `run_profile.py`. |
| `run_profile.py` | CPU analysis. Times each scenario in a plain child process and renders a py-spy flamegraph per scenario. |
| `../Dockerfiles/` | One Dockerfile per target environment (shared with the memory benchmark). Selected via `PERF_ENV` at `make` time. |
| `../entrypoint.sh` | Container entrypoint (shared). Downloads the Linux native `libc2pa_c.so` at startup. |
| `reports/` | Generated profiles (gitignored). One file per scenario: `<scenario>-cpu.svg` (or `.speedscope.json` with `PYSPY_FORMAT=speedscope`). |

## Approach: two passes per scenario

1. Timing pass: the scenario runs in a plain child process with no profiler attached. The child measures three metrics around the scenario call only, excluding interpreter startup, and hands the result back as JSON: `wall_seconds` (`time.perf_counter`), `cpu_seconds` (`time.process_time`, process-wide so the thread-pool scenarios count all threads), and `children_cpu_seconds` (`resource.getrusage(RUSAGE_CHILDREN)`, the CPU burned in forked children, which `process_time` cannot see; relevant for the `fork_*` scenarios).
2. Profile pass: the scenario runs again under `py-spy record` to produce a flamegraph. This is diagnostic only, since sampling adds rate-dependent overhead that would bake profiler cost into the timings.

Scenario children run with `PERF_DISABLE_TSA=1` by default, so signing scenarios skip the network round-trip to the timestamp authority that every `sign` call otherwise makes. Timings then measure code, not network latency. Pass `PERF_DISABLE_TSA=0` to restore the TSA call. The memory benchmark is unaffected either way; it keeps TSA on.

When a scenario's first timing pass finishes in under 1 second, the harness runs 4 more passes and records the median of each metric, because single-shot timing at that scale is mostly jitter. Set `CPU_REPEATS=N` to force a fixed pass count instead.

Locally the default `--mode all` runs both passes back to back. In CI they run as two parallel jobs on separate runners (`--mode timing` / `--mode profile`), so sampling never contends with the timed run and wall-clock cost stays at one pass.

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
```

The `cpu-bench` target runs the container with `--cap-add SYS_PTRACE --security-opt seccomp=unconfined`. `py-spy` samples the child process via ptrace and `process_vm_readv`, which the default container security profile blocks.

## Variables

| Variable | Default | Meaning |
| --- | --- | --- |
| `CPU_ITERATIONS` | `100` | Loop count per scenario (the Makefile forwards it into the container). |
| `CPU_MODE` | `all` | `all`, `timing`, or `profile` (maps to `--mode`). |
| `CPU_REPEATS` | `0` | Fixed timing pass count per scenario, median recorded. `0` = adaptive: 1 pass, extended to 5 when the first pass runs under 1 s. |
| `PERF_DISABLE_TSA` | `1` (set by the harness) | Skip the timestamp-authority network call during signing. Set `0` to restore it. |
| `PYSPY_RATE` | `100` | Sampling rate in Hz. Raise (up to ~500) if flamegraphs for fast scenarios look sparse. |
| `PYSPY_FORMAT` | `flamegraph` | `flamegraph` writes self-contained SVGs; `speedscope` writes JSON for [speedscope.app](https://www.speedscope.app/). |
| `PERF_ENV` | `python-3.12-slim` | Which Docker environment to use (see `../Dockerfiles/`). |
| `SCENARIO` | unset | Run a single scenario. |
| `PERF_ARGS` | unset | Extra args for `run_profile.py`. |

## Interpreting the flamegraphs

Profiles show Python frames only. Time spent inside the Rust `libc2pa_c` library is attributed to the Python frame that made the FFI call. Fast scenarios can produce thin profiles: raising `PYSPY_RATE` or `CPU_ITERATIONS` will lead to getting more samples.

## Reading the CI/CD report

`.github/workflows/cpu-benchmark.yml` runs on PRs labeled `check-cpu-benchmark`, on `ubuntu-24.04-arm`. `cpu-timing` measures timing metrics; the raw timing table lands in the job's step summary.

The step summary table reports each scenario's raw timing: `wall`, `cpu`, `cpu/iter`, and `child cpu`. There is no baseline comparison or drift status.

### Table columns

| Column | Meaning |
| --- | --- |
| `scenario` | Scenario name. |
| `wall` | Wall-clock time (seconds), across all iterations. |
| `cpu` | CPU time (seconds), process-wide; excludes I/O, sleep, time in child processes. |
| `cpu/iter` | Per-iteration CPU cost (cpu ÷ iterations). |
| `child cpu` | CPU burned in forked child processes (`fork_*` scenarios). Parent CPU time does not include this. |
