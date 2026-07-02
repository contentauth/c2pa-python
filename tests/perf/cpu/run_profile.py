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
  flamegraph (SVG by default, speedscope JSON via PYSPY_FORMAT). Profile
  numbers never feed the baseline; the artifact is diagnostic only.

Results are compared against baseline.json (created on first run). The
comparison is REPORT-ONLY: over-threshold drift is printed and highlighted
in the CI step summary, but never fails the run. CPU timings on shared
runners are too noisy to gate CI; the memory benchmark is the gate.

Usage:
    python -m tests.perf.cpu.run_profile [--update-baseline]
        [--scenario NAME] [--mode {all,timing,profile}]

--mode exists so CI can run the two passes as parallel jobs on separate
runners: `timing` is unpolluted by py-spy CPU contention, `profile` only
produces flamegraphs.

Environment variables:
- CPU_ITERATIONS: number of times each scenario loops (default: 100)
- CPU_THRESHOLD: drift multiplier, e.g. 1.25 for +25% (default: 1.25)
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

import platform

# Scenario name list
from tests.perf.scenarios import SCENARIO_NAMES

HERE = Path(__file__).parent
REPO_ROOT = HERE.parent.parent.parent
REPORTS_DIR = HERE / "reports"
BASELINE_FILE = HERE / "baseline.json"

ITERATIONS = int(os.environ.get("CPU_ITERATIONS", "100"))
THRESHOLD = float(os.environ.get("CPU_THRESHOLD", "1.25"))
REPEATS = int(os.environ.get("CPU_REPEATS", "0"))  # 0 = adaptive
PYSPY_RATE = int(os.environ.get("PYSPY_RATE", "100"))
PYSPY_FORMAT = os.environ.get("PYSPY_FORMAT", "flamegraph")
PERF_ENV = os.environ.get("PERF_ENV", "")

# Scenarios whose first pass finishes under this many seconds get re-run to
# _FAST_REPEATS total passes (median recorded): single-shot timing there is
# mostly jitter. A CPU_REPEATS value overrides the adaptive rule.
_FAST_WALL_SECONDS = 1.0
_FAST_REPEATS = 5

# Metrics compared against the baseline. cpu_seconds is the primary signal
# (stable under runner load); wall_seconds also catches blocking/sleep
# regressions that never burn CPU. children_cpu_seconds (CPU burned in
# forked children, invisible to process_time) is reported but not part of
# the gate list.
_METRICS = ("wall_seconds", "cpu_seconds")
_ALL_METRICS = ("wall_seconds", "cpu_seconds", "children_cpu_seconds")
# Drift on children_cpu_seconds is only meaningful when the baseline value
# is non-trivial; below this, percent deltas are pure noise.
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


def _pyspy_version() -> str:
    try:
        out = subprocess.run(["py-spy", "--version"], capture_output=True, text=True)
        # "py-spy 0.4.2" -> "0.4.2"
        return out.stdout.strip().split()[-1] if out.returncode == 0 else ""
    except OSError:
        return ""


def _build_meta() -> dict:
    """Provenance for the baseline: which toolchain produced these numbers.
    Recorded so a committed baseline is reproducible under same conditions.
    """
    native_version = ""
    try:
        native_version = (REPO_ROOT / "c2pa-native-version.txt").read_text().strip()
    except OSError:
        pass
    return {
        "pyspy_version": _pyspy_version(),
        "python_version": platform.python_version(),
        "c2pa_native_version": native_version,
        "iterations": ITERATIONS,
        "perf_env": PERF_ENV,
        "arch": platform.machine(),
    }


def _fmt_secs(s: float) -> str:
    if s < 1:
        return f"{s * 1000:.1f} ms"
    return f"{s:.3f} s"


def _delta_pct(current: float, base: float) -> str:
    """Signed percentage change vs baseline, or '-' when no baseline."""
    if not base:
        return "-"
    return f"{(current - base) / base * 100:+.1f}%"


def _write_github_summary(results: dict, baseline: dict) -> None:
    """Append a values table to $GITHUB_STEP_SUMMARY when running in CI.
    """
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path or not results:
        return

    lines = [
        "## CPU benchmark (py-spy)",
        "",
        f"Iterations: {ITERATIONS} · drift threshold: +{(THRESHOLD - 1) * 100:.0f}%"
        f" · report-only"
        f"{f' · env: {PERF_ENV}' if PERF_ENV else ''}",
        "",
        "| scenario | wall | cpu | cpu/iter | child cpu | wall Δ% | cpu Δ% | status |",
        "|----------|------|-----|----------|-----------|---------|--------|--------|",
    ]
    for name, m in results.items():
        b = baseline.get(name, {}) if baseline else {}
        wall_base = b.get("wall_seconds", 0)
        cpu_base = b.get("cpu_seconds", 0)
        over = (
            (wall_base and m["wall_seconds"] > wall_base * THRESHOLD)
            or (cpu_base and m["cpu_seconds"] > cpu_base * THRESHOLD)
        )
        status = "drift" if over else "ok"
        lines.append(
            f"| {name} | {_fmt_secs(m['wall_seconds'])} "
            f"| {_fmt_secs(m['cpu_seconds'])} "
            f"| {_fmt_secs(m['cpu_seconds'] / ITERATIONS)} "
            f"| {_fmt_secs(m.get('children_cpu_seconds', 0))} "
            f"| {_delta_pct(m['wall_seconds'], wall_base)} "
            f"| {_delta_pct(m['cpu_seconds'], cpu_base)} | {status} |"
        )
    lines.append("")

    with open(summary_path, "a", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="c2pa-python CPU profiler")
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="Overwrite baseline.json with current measurements and exit 0",
    )
    parser.add_argument(
        "--scenario",
        choices=SCENARIO_NAMES,
        default=None,
        help="Run a single scenario instead of all of them. With --update-baseline, "
             "only that scenario's entry in baseline.json is updated; the rest are kept.",
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

    if args.update_baseline and not run_timing:
        parser.error("--update-baseline requires a mode that measures timing")

    scenarios_to_run = (args.scenario,) if args.scenario else SCENARIO_NAMES

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    # prior_baseline: the existing file, always loaded so a single-scenario
    # update can preserve the other scenarios' entries when it rewrites the file.
    prior_baseline: dict = {}

    # baseline: the subset used for the drift comparison below, which is
    # suppressed when --update-baseline is set (because we are re-baselining).
    if BASELINE_FILE.exists():
        prior_baseline = json.loads(BASELINE_FILE.read_text())
    baseline: dict = {} if args.update_baseline else prior_baseline

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

            if baseline and name in baseline:
                b = baseline[name]
                # children_cpu_seconds joins the drift check only when the
                # baseline value is non-trivial (percent deltas on ~0 bases
                # are pure noise).
                checked: list[str] = list(_METRICS)
                if b.get("children_cpu_seconds", 0) >= _CHILDREN_CPU_MIN_BASE:
                    checked.append("children_cpu_seconds")
                for metric in checked:
                    current = metrics.get(metric, 0)
                    base = b.get(metric, 0)
                    limit = base * THRESHOLD
                    if current <= limit:
                        continue
                    diff_pct = (current - base) / base * 100 if base else float("inf")
                    print(
                        f"  drift note: {name}.{metric}: {_fmt_secs(current)} "
                        f"> baseline {_fmt_secs(base)}"
                        f" (+{diff_pct:.1f}%, threshold {(THRESHOLD-1)*100:.0f}%)",
                        flush=True,
                    )

        if run_profile:
            out_path = REPORTS_DIR / f"{name}{env_tag}-cpu{ext}"
            if _run_pyspy_pass(name, out_path):
                print(f"  cpu profile: {out_path}")
            else:
                render_failures.append(name)

    if run_timing and (args.update_baseline or not prior_baseline):
        # When running a single scenario, merge its result into the existing
        # baseline so the other scenarios' entries are preserved. A full run
        # replaces the file wholesale.
        if args.scenario and prior_baseline:
            output = dict(prior_baseline)
        else:
            output = {}
        new_meta = _build_meta()
        # On a single-scenario merge the new entry must come from the same
        # toolchain as the entries it is being merged next to, or the numbers
        # are not comparable. Warn if _meta would change (e.g. wrong PERF_ENV,
        # iteration count, or native version) instead of silently overwriting it.
        if args.scenario and prior_baseline:
            old_meta = prior_baseline.get("_meta", {})
            if old_meta and old_meta != new_meta:
                diffs = sorted(
                    set(old_meta) | set(new_meta),
                    key=str,
                )
                changed = [
                    f"{k}: {old_meta.get(k)!r} -> {new_meta.get(k)!r}"
                    for k in diffs if old_meta.get(k) != new_meta.get(k)
                ]
                print(
                    "\nWARNING: this run's environment differs from the existing "
                    "baseline's _meta; the merged entry will NOT be comparable to "
                    "the other scenarios:\n  " + "\n  ".join(changed),
                    file=sys.stderr,
                )
        output["_meta"] = new_meta
        output.update(results)
        BASELINE_FILE.write_text(json.dumps(output, indent=2))
        verb = "Updated" if prior_baseline else "Created"
        print(f"\n{verb} baseline: {BASELINE_FILE}")

    # Emit the report table to the PR's Step Summary in CI.
    _write_github_summary(results, baseline)

    if render_failures:
        print("\nPY-SPY PROFILES FAILED (timing metrics still recorded):", file=sys.stderr)
        for name in render_failures:
            print(f"  {name}", file=sys.stderr)

    if run_timing:
        print("\nDone. Baseline comparison is report-only; drift never fails the run.")


if __name__ == "__main__":
    main()
