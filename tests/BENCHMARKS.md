# c2pa-python benchmarks

Operator guide for the three benchmark suites that live in this directory.

## Suites

| File | Measures |
|------|----------|
| `benchmark.py` | Wall-time for the four core scenarios on `C.jpg`. Original suite. |
| `benchmark_memory.py` | Peak traced bytes, retained bytes, RSS delta, allocation count for file/stream × read/sign across `C.jpg / 1MB / 10MB / 50MB` (and `250MB` under `slow`). |
| `benchmark_stress.py` | Concurrent read/sign (2/4/8/16 workers), large-file scaling, 500-iteration leak detection for read and sign, 60-second mixed-load stability. |

## Running

```sh
make benchmark              # original wall-time only
make benchmark-memory       # memory profile (excludes 250MB)
make benchmark-stress       # stress (excludes 250MB)
make benchmark-stress-slow  # adds 250MB fixture
make benchmark-all          # benchmark + memory + stress (no slow)
```

Single test:

```sh
python3 -m pytest tests/benchmark_memory.py::test_mem_streams_build -v
python3 -m pytest tests/benchmark_stress.py::test_stress_repeated_sign_no_leak -v
```

Slow tests are gated by the `slow` marker. Run them explicitly:

```sh
python3 -m pytest tests/benchmark_stress.py -v -m slow
python3 -m pytest tests/benchmark_memory.py -v -m slow
```

## Fixtures

Synthetic JPEGs are generated under `tests/fixtures/generated/` on first run
of any benchmark file (1MB, 10MB, 50MB by default; 250MB only when slow tests
are collected). They are produced by appending APP15 padding segments to
`tests/fixtures/C.jpg`. APP15 is application-defined and skipped by JPEG
decoders, including the c2pa parser, so the files remain valid.

The directory is gitignored. Delete it to force regeneration:

```sh
rm -rf tests/fixtures/generated
```

## Baseline workflow

```sh
make benchmark-memory
cp .benchmarks/memory-latest.json .benchmarks/baseline-memory.json

make benchmark-stress
cp .benchmarks/stress-latest.json .benchmarks/baseline-stress.json
```

After applying optimizations, compare:

```sh
python3 -m pytest tests/benchmark_memory.py \
  --benchmark-compare=.benchmarks/baseline-memory.json \
  --benchmark-compare-fail=mean:5%
```

## Reading the results

`pytest-benchmark` writes JSON to `.benchmarks/`. For each test the
`extra_info` block contains the memory metrics:

| Key | Meaning |
|-----|---------|
| `peak_traced` | Maximum bytes simultaneously held by Python objects during the run, per `tracemalloc.get_traced_memory()`. |
| `current_traced` | Bytes still held by Python objects at end-of-run. Should be near zero. |
| `rss_delta_bytes` | Process RSS difference after vs before the run, post-`gc.collect()`. Includes ctypes/libc2pa allocations Python can't see. |
| `alloc_count` | Net count of new allocation sites recorded by tracemalloc (added minus released). |
| `size_label` | Fixture label (`C.jpg`, `1MB`, etc.). |
| `file_size_bytes` | Actual size of the fixture used. |

The wall-time fields (`min`, `mean`, `median`, etc.) are pytest-benchmark
defaults and are still useful for catching speed regressions while
optimizing for memory.

## Regression criteria

- **Wall time:** no scenario regresses by more than 5%.
- **`peak_traced`:** must not increase for any scenario.
- **`current_traced`:** below 200 KB (post-gc no-leak floor).
- **Leak slope:** the 500-iteration tests pass when growth is below
  1 KB/iteration (`assert_no_growth` enforces this).

## Dependencies

- `pytest`, `pytest-benchmark` — already pinned in
  [`requirements-dev.txt`](../requirements-dev.txt).
- `psutil` — for RSS sampling.
- `pytest-repeat` — for reuse in soak tests.
- `tracemalloc` — Python standard library.

`memray` is intentionally not used. It's Linux-only in CI and adds
significant install weight; `tracemalloc` covers the Python-side question
and `psutil` covers the OS-side question.

## Comparing against main

To produce a clean before/after vs. the `main` branch, use the comparison
targets. They snapshot the working-tree `src/c2pa/c2pa.py`, swap in
`main`'s copy, capture 5 replicate runs of memory and stress, then
restore the modified file and capture another 5 replicates. The bench
harness itself (this directory + the Makefile + scripts) is held
constant.

```sh
make benchmark-compare        # 5 main + 5 changes replicates (~10 min)
make benchmark-compare-leak   # 1 leak suite per side (~5 min)
```

Both targets refuse to run if the working tree has uncommitted edits
to anything other than `src/c2pa/c2pa.py`.

The aggregator writes [`BENCHMARK_RESULTS.md`](BENCHMARK_RESULTS.md)
with per-scenario peak/wall-time tables and the leak slopes. Regenerate
the report from existing JSONs without re-running the benches:

```sh
.venv/bin/python3 scripts/aggregate_benchmark_results.py
```

## Caveats

- **macOS RSS.** macOS reports RSS including shared library pages, so
  absolute `rss_delta_bytes` numbers run higher than Linux for the same
  workload. Compare deltas on the same OS.
- **Concurrent sign past 8 workers.** Signing is CPU-bound at the Rust
  layer and the GIL serializes Python-side work. More workers add
  contention without throughput.
- **250MB run.** Approaches ~1.5 GB RSS during signing because the signed
  output is buffered into a `BytesIO`. Pass a file destination to
  `Builder.sign` for production workloads.
- **JIT effects.** First read after process start includes shared-library
  load. The leak tests warm up before sampling; ad-hoc runs may show a
  one-time RSS jump on the first iteration.
