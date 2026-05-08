#!/usr/bin/env bash
# Run the leak suite (500-iter read, 50-iter sign, 60-s mixed) once
# against main, once against changes. Single replicate per side; the
# leak tests are themselves regressions over many samples.
set -uo pipefail

cd "$(git rev-parse --show-toplevel)"

MAIN_SHA=$(git rev-parse main)
PY=.venv/bin/python3
LEAK_TESTS=(
  tests/benchmark_stress.py::test_stress_repeated_read_no_leak
  tests/benchmark_stress.py::test_stress_repeated_sign_no_leak
  tests/benchmark_stress.py::test_stress_long_running_mixed
)

mkdir -p .benchmarks

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

run_leak() {
  local label="$1"
  echo
  echo "===== leak suite: $label ====="
  "$PY" -m pytest -p no:cacheprovider -s --no-header \
    --benchmark-json=".benchmarks/${label}-leak.json" \
    "${LEAK_TESTS[@]}" 2>&1 | tee ".benchmarks/${label}-leak.log" || \
    echo "(leak suite for $label exited with non-zero; continuing)"
}

git checkout "$MAIN_SHA" -- src/c2pa/c2pa.py
run_leak "main"

cp "$SNAPSHOT" src/c2pa/c2pa.py
run_leak "changes"

echo
echo "leak logs in .benchmarks/{main,changes}-leak.log"
echo "regenerate the combined report with: $PY scripts/aggregate_benchmark_results.py"
