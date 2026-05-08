#!/usr/bin/env bash
# Capture 5 main vs 5 changes replicates of the memory and stress
# benchmark suites for an evidence-grade comparison. The bench harness
# (tests/_bench_utils.py, conftest.py, benchmark_memory.py,
# benchmark_stress.py) is held constant; only src/c2pa/c2pa.py flips.
#
# Tolerates per-replicate failures (e.g. TSA flake on stress) so that
# the pipeline runs to completion. The aggregator picks up whatever
# JSONs exist.

set -uo pipefail

cd "$(git rev-parse --show-toplevel)"

MAIN_SHA=$(git rev-parse main)
PY=.venv/bin/python3
REPLICATES=5

if [ ! -x "$PY" ]; then
  echo "expected venv at $PY" >&2
  exit 1
fi

mkdir -p .benchmarks

# Snapshot the modified file inside the repo (.benchmarks/ is gitignored
# and survives mac auto-tmp cleaning) so the restore-on-exit trap is
# robust against unexpected interpreter exits.
SNAPSHOT=".benchmarks/.c2pa_modified.snapshot.py"
cp src/c2pa/c2pa.py "$SNAPSHOT"

restore_modified() {
  if [ -f "$SNAPSHOT" ]; then
    cp "$SNAPSHOT" src/c2pa/c2pa.py
    rm -f "$SNAPSHOT"
    echo "restored modified src/c2pa/c2pa.py from snapshot"
  fi
}
trap restore_modified EXIT INT TERM

STRESS_DESELECT=(
  --deselect tests/benchmark_stress.py::test_stress_long_running_mixed
  --deselect tests/benchmark_stress.py::test_stress_repeated_read_no_leak
  --deselect tests/benchmark_stress.py::test_stress_repeated_sign_no_leak
)

run_side() {
  local label="$1"
  echo
  echo "===== capturing $REPLICATES replicates: $label ====="
  for i in $(seq 1 "$REPLICATES"); do
    echo "--- $label replicate $i / $REPLICATES (memory) ---"
    "$PY" -m pytest tests/benchmark_memory.py --benchmark-only -m "not slow" \
      --benchmark-json=".benchmarks/${label}-memory-${i}.json" -q || \
      echo "(memory replicate $i for $label exited with non-zero; continuing)"

    echo "--- $label replicate $i / $REPLICATES (stress) ---"
    "$PY" -m pytest tests/benchmark_stress.py -p no:cacheprovider -m "not slow" \
      "${STRESS_DESELECT[@]}" \
      --benchmark-json=".benchmarks/${label}-stress-${i}.json" -q || \
      echo "(stress replicate $i for $label exited with non-zero; continuing)"
  done
}

# 1. main side: restore main's src/c2pa/c2pa.py, run 5 reps each.
git checkout "$MAIN_SHA" -- src/c2pa/c2pa.py
run_side "main"

# 2. changes side: restore the modified file, run 5 reps each.
cp "$SNAPSHOT" src/c2pa/c2pa.py
run_side "changes"

echo
echo "raw JSONs in .benchmarks/.  generating evidence report..."
"$PY" scripts/aggregate_benchmark_results.py
echo "wrote tests/BENCHMARK_RESULTS.md"
