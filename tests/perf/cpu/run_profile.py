#!/usr/bin/env python3
# Copyright 2026 Adobe. All rights reserved.
# This file is licensed to you under the Apache License,
# Version 2.0 (http://www.apache.org/licenses/LICENSE-2.0)
# or the MIT license (http://opensource.org/licenses/MIT),
# at your option.

"""
CPU profiling harness using py-spy.

For each scenario in scenarios.SCENARIOS this script runs up to two passes:
- Timing pass: runs the scenario in a plain child process and measures
  wall_seconds (time.perf_counter) and cpu_seconds (time.process_time,
  process-wide so thread-pool scenarios count all threads) around the
  scenario call only, excluding interpreter startup. No profiler is
  attached, so the numbers are free of sampling overhead.
- Profile pass: re-runs the scenario under `py-spy record` to produce a
  flamegraph (SVG by default, speedscope JSON via PYSPY_FORMAT). The
  artifact is diagnostic only.

Usage:
    python -m tests.perf.cpu.run_profile [--scenario NAME] [--mode {all,timing,profile}]

--mode exists so CI could run the two passes as parallel jobs on separate
runners: `timing` is unaffected by py-spy CPU contention, `profile` only
produces flamegraphs.

Environment variables:
- CPU_ITERATIONS: number of times each scenario loops (default: 100)
- CPU_REPEATS: fixed number of timing passes per scenario, median recorded
  (default: adaptive — 1 pass, extended to 5 when the first pass finishes
  under 1 second, where single-shot timing is mostly jitter)
- PERF_DISABLE_TSA: forwarded to scenario children; defaults to 1 here so
  sign timings measure code rather than the network round-trip to the
  timestamp authority. Pass PERF_DISABLE_TSA=0 to restore the TSA call.
- PYSPY_RATE: py-spy sampling rate in Hz (default: 100)
- PYSPY_FORMAT: 'flamegraph' (SVG, default) or 'speedscope'
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Scenario name list
from tests.perf.scenarios import SCENARIO_NAMES

HERE = Path(__file__).parent
REPO_ROOT = HERE.parent.parent.parent
REPORTS_DIR = HERE / "reports"

ITERATIONS = int(os.environ.get("CPU_ITERATIONS", "100"))
REPEATS = int(os.environ.get("CPU_REPEATS", "0"))  # 0 = adaptive
PYSPY_RATE = int(os.environ.get("PYSPY_RATE", "100"))
PYSPY_FORMAT = os.environ.get("PYSPY_FORMAT", "flamegraph")
PERF_ENV = os.environ.get("PERF_ENV", "")

# Scenarios whose first pass finishes under this many seconds get re-run to
# _FAST_REPEATS total passes (median recorded): single-shot timing there is
# mostly jitter. A CPU_REPEATS value overrides the adaptive rule.
_FAST_WALL_SECONDS = 1.0
_FAST_REPEATS = 5

_ALL_METRICS = ("wall_seconds", "cpu_seconds", "children_cpu_seconds")
# Below this, child-cpu is not worth printing; percent-scale noise on a
# ~0 base isn't informative.
_CHILDREN_CPU_MIN_BASE = 0.01


def _scenario_script(name: str, timing_json: Path | None = None) -> str:
    """Child-process source that runs one scenario.

    When timing_json is given, the scenario call is bracketed with
    perf_counter/process_time and the metrics are written to that file as
    JSON. Writing to a file rather than stdout keeps scenario prints from
    corrupting the metrics.
    """
    body = f"""
import sys
sys.path.insert(0, "{REPO_ROOT}")
sys.path.insert(0, "{REPO_ROOT / 'src'}")
from tests.perf.scenarios import SCENARIOS
"""
    if timing_json is None:
        body += f"""
SCENARIOS["{name}"]({ITERATIONS})
"""
    else:
        body += f"""
import json, resource, time
children_start = resource.getrusage(resource.RUSAGE_CHILDREN)
wall_start = time.perf_counter()
cpu_start = time.process_time()
SCENARIOS["{name}"]({ITERATIONS})
wall = time.perf_counter() - wall_start
cpu = time.process_time() - cpu_start
children_end = resource.getrusage(resource.RUSAGE_CHILDREN)
children_cpu = (
    children_end.ru_utime - children_start.ru_utime
    + children_end.ru_stime - children_start.ru_stime
)
with open("{timing_json}", "w") as fh:
    json.dump({{"wall_seconds": wall, "cpu_seconds": cpu,
               "children_cpu_seconds": children_cpu}}, fh)
"""
    return body


def _child_env(name: str) -> dict:
    """Environment for scenario child processes.

    TSA is disabled by default so sign timings measure code, not the network
    round-trip to the timestamp authority; an explicit PERF_DISABLE_TSA=0
    from the caller wins.
    """
    env = {**os.environ, "PERF_SCENARIO": name}
    env.setdefault("PERF_DISABLE_TSA", "1")
    return env


def _run_timing_pass(name: str) -> dict:
    """Run one scenario in a plain child process and read its timing metrics."""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        timing_json = Path(tmp.name)
    try:
        cmd = [sys.executable, "-c", _scenario_script(name, timing_json)]
        result = subprocess.run(cmd, text=True, env=_child_env(name))
        if result.returncode != 0:
            print(f"  timing run failed for {name} (exit {result.returncode})", file=sys.stderr)
            sys.exit(1)
        metrics = json.loads(timing_json.read_text())
    finally:
        timing_json.unlink(missing_ok=True)
    return {k: round(v, 4) for k, v in metrics.items()}


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def _run_timing(name: str) -> dict:
    """Run the timing pass, repeating fast scenarios, and record the median.

    A CPU_REPEATS value fixes the pass count; otherwise one pass, extended to
    _FAST_REPEATS when the first pass finishes under _FAST_WALL_SECONDS.
    """
    passes = [_run_timing_pass(name)]
    if REPEATS > 0:
        target = REPEATS
    elif passes[0]["wall_seconds"] < _FAST_WALL_SECONDS:
        target = _FAST_REPEATS
        print(f"  fast scenario, repeating ({target} passes, median)...", flush=True)
    else:
        target = 1
    while len(passes) < target:
        passes.append(_run_timing_pass(name))
    if len(passes) == 1:
        return passes[0]
    return {
        metric: round(_median([p[metric] for p in passes]), 4)
        for metric in _ALL_METRICS
    }


def _run_pyspy_pass(name: str, out_path: Path) -> bool:
    """Re-run one scenario under py-spy record to produce a flamegraph.

    Launch mode (py-spy is the parent of the profiled process) avoids
    pid-attach races and satisfies Yama ptrace_scope without host changes.
    A failed render does not abort the run: the timing metrics are recorded
    separately and still good.
    """
    pyspy = shutil.which("py-spy")
    if pyspy is None:
        print(f"  py-spy not found on PATH; skipping profile for {name}", file=sys.stderr)
        return False
    cmd = [
        pyspy, "record",
        "-o", str(out_path),
        "--format", PYSPY_FORMAT,
        "--rate", str(PYSPY_RATE),
        "--subprocesses",
        "--", sys.executable, "-c", _scenario_script(name),
    ]
    print(f"    py-spy record ({PYSPY_FORMAT}, {PYSPY_RATE} Hz)...", flush=True)
    result = subprocess.run(cmd, text=True, env=_child_env(name))
    if result.returncode != 0:
        print(f"  py-spy record failed for {name} (exit {result.returncode})", file=sys.stderr)
        return False
    return True


def _fmt_secs(s: float) -> str:
    if s < 1:
        return f"{s * 1000:.1f} ms"
    return f"{s:.3f} s"


def _write_github_summary(results: dict) -> None:
    """Append a values table to $GITHUB_STEP_SUMMARY when running in CI.
    """
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path or not results:
        return

    lines = [
        "## CPU benchmark (py-spy)",
        "",
        f"Iterations: {ITERATIONS} · report-only"
        f"{f' · env: {PERF_ENV}' if PERF_ENV else ''}",
        "",
        "| scenario | wall | cpu | cpu/iter | child cpu |",
        "|----------|------|-----|----------|-----------|",
    ]
    for name, m in results.items():
        lines.append(
            f"| {name} | {_fmt_secs(m['wall_seconds'])} "
            f"| {_fmt_secs(m['cpu_seconds'])} "
            f"| {_fmt_secs(m['cpu_seconds'] / ITERATIONS)} "
            f"| {_fmt_secs(m.get('children_cpu_seconds', 0))} |"
        )
    lines.append("")

    with open(summary_path, "a", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="c2pa-python CPU profiler")
    parser.add_argument(
        "--scenario",
        choices=SCENARIO_NAMES,
        default=None,
        help="Run a single scenario instead of all of them.",
    )
    parser.add_argument(
        "--mode",
        choices=("all", "timing", "profile"),
        default="all",
        help="'timing' measures metrics only, 'profile' renders py-spy flamegraphs "
             "only, 'all' does both. CI runs the two as parallel jobs on separate "
             "runners so sampling never contends with the timed run.",
    )
    args = parser.parse_args()

    run_timing = args.mode in ("all", "timing")
    run_profile = args.mode in ("all", "profile")

    scenarios_to_run = (args.scenario,) if args.scenario else SCENARIO_NAMES

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    results: dict = {}
    render_failures: list[str] = []

    ext = ".svg" if PYSPY_FORMAT == "flamegraph" else ".speedscope.json"
    total = len(scenarios_to_run)
    for idx, name in enumerate(scenarios_to_run, 1):
        print(f"\n=== [{idx}/{total}] {name} (iterations={ITERATIONS}) ===")
        env_tag = f"-{PERF_ENV}" if PERF_ENV else ""

        if run_timing:
            print("  timing...", flush=True)
            metrics = _run_timing(name)
            results[name] = metrics
            print(f"  wall: {_fmt_secs(metrics['wall_seconds'])}"
                  f"  ({_fmt_secs(metrics['wall_seconds'] / ITERATIONS)}/iter)")
            print(f"  cpu:  {_fmt_secs(metrics['cpu_seconds'])}"
                  f"  ({_fmt_secs(metrics['cpu_seconds'] / ITERATIONS)}/iter)")
            children_cpu = metrics.get("children_cpu_seconds", 0)
            if children_cpu >= _CHILDREN_CPU_MIN_BASE:
                print(f"  child cpu: {_fmt_secs(children_cpu)}")

        if run_profile:
            out_path = REPORTS_DIR / f"{name}{env_tag}-cpu{ext}"
            if _run_pyspy_pass(name, out_path):
                print(f"  cpu profile: {out_path}")
            else:
                render_failures.append(name)

    # Emit the report table to the PR's Step Summary in CI.
    _write_github_summary(results)

    if render_failures:
        print("\nPY-SPY PROFILES FAILED (timing metrics still recorded):", file=sys.stderr)
        for name in render_failures:
            print(f"  {name}", file=sys.stderr)

    if run_timing:
        print("\nDone. Timings are report-only and never fail the run.")


if __name__ == "__main__":
    main()
