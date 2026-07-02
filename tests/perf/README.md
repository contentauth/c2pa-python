# Performance benchmarks

## Overview

Two benchmark frameworks share the scenario set and Docker environments in this folder:

- `scenarios.py`: the scenario functions and the `SCENARIOS` registry.
- `Dockerfiles/`: one image per target environment (selected with `PERF_ENV`), containing both memray and py-spy.
- `entrypoint.sh`: container entrypoint that adds the Linux native library used by the wheel at startup.

| Folder | Tool | Measures | Docs |
| --- | --- | --- | --- |
| [`memory/`](memory/) | [memray](https://github.com/bloomberg/memray) | peak memory, leaks, allocations | [memory/README.md](memory/README.md) |
| [`cpu/`](cpu/) | [py-spy](https://github.com/benfred/py-spy) | wall/CPU time, CPU flamegraphs | [cpu/README.md](cpu/README.md) |

## Why two frameworks?

Each framework focuses on different indicators:

- **`memory/`** tracks memory usage, not time: peak RSS, leaks, temporary-allocation churn. Catches a change that holds more memory at once or leaks with iteration count, even if it runs just as fast.
- **`cpu/`** tracks time, not memory usage: wall/CPU seconds plus a flamegraph of where cycles go. Catches a slowdown and the call site causing it, even if memory use is unchanged.

Both run inside the Docker perf image (`../Dockerfiles/`), with a fixed Python version, fixed OS, fixed dependency set, and no other host processes competing for CPU/memory. That isolation is why they carry a committed `baseline.json`: same environment every run, so a delta means the code changed, not that the host did.

## Quickstart

Building the Docker images is a pre-requisite to run the benchmarks:

```bash
make perf-image-rebuild
```

To run the benchmarks:

```bash
# memory benchmark
make memory-use-bench

 # cpu benchmark
make cpu-bench
```
