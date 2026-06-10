#!/usr/bin/env python3
# Copyright 2026 Adobe. All rights reserved.
# This file is licensed to you under the Apache License,
# Version 2.0 (http://www.apache.org/licenses/LICENSE-2.0)
# or the MIT license (http://opensource.org/licenses/MIT),
# at your option.

"""
Memory profiling harness using memray.

For each scenario in scenarios.SCENARIOS this script:
- Runs the scenario under `memray run --native` -> <name>.bin
- Generates three flamegraph views: <name>-peak.html (high-water),
  <name>-leaks.html (--leaks), <name>-temporary.html (--temporary-allocations)
- Reads peak_bytes and leaked_bytes from the .bin via memray.FileReader
- Compares against baseline.json (creates it on first run)
- Exits non-zero if any metric exceeds baseline * threshold

Usage:
    python -m tests.perf.run_profile [--update-baseline]

Environment variables:
- MEMRAY_ITERATIONS: number of times each scenario loops (default: 100)
- MEMRAY_THRESHOLD: regression multiplier, e.g. 1.1 for 10% (default: 1.1)
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

import memray

# Scenario name list
from tests.perf.scenarios import SCENARIO_NAMES

HERE = Path(__file__).parent
REPORTS_DIR = HERE / "reports"
BASELINE_FILE = HERE / "baseline.json"

ITERATIONS = int(os.environ.get("MEMRAY_ITERATIONS", "100"))
THRESHOLD = float(os.environ.get("MEMRAY_THRESHOLD", "1.1"))
PERF_ENV = os.environ.get("PERF_ENV", "")


def _run_scenario_under_memray(name: str, bin_path: Path) -> None:
    """Spawn a subprocess that runs one scenario under memray --native."""
    repo_root = HERE.parent.parent
    script = f"""
import sys
sys.path.insert(0, "{repo_root}")
sys.path.insert(0, "{repo_root / 'src'}")
from tests.perf.scenarios import SCENARIOS
SCENARIOS["{name}"]({ITERATIONS})
# Collect cycle garbage before tracking ends so leaked_bytes means
# "still allocated but unreachable" (true leaks + one-time statics).
import gc
gc.collect()
gc.collect()
"""
    cmd = [
        sys.executable, "-m", "memray", "run",
        "--native",
        "--trace-python-allocators",
        "--force",
        "-o", str(bin_path),
        "-c", script,
    ]
    # Pass the scenario name so the loop can label its progress
    env = {**os.environ, "PERF_SCENARIO": name}
    result = subprocess.run(cmd, text=True, env=env)
    if result.returncode != 0:
        print(f"  memray run failed for {name} (exit {result.returncode})", file=sys.stderr)
        sys.exit(1)


def _generate_flamegraph(bin_path: Path, out_path: Path, mode: str = "peak") -> bool:
    """Render one flamegraph view of a capture file.

    mode:
    - 'peak':      high-water-mark view (the default flamegraph render).
    - 'leaks':     memory still live when tracking stopped (--leaks).
    - 'temporary': allocations freed before more than one other allocation
                   occurs, i.e. short-lived churn (--temporary-allocations).
    These are mutually exclusive views, so each is a separate render.
    """
    cmd = [sys.executable, "-m", "memray", "flamegraph", str(bin_path), "-o", str(out_path), "--force"]
    if mode == "leaks":
        cmd.append("--leaks")
    elif mode == "temporary":
        # --temporary-allocations == --temporary-allocation-threshold=1
        cmd.append("--temporary-allocations")
    # Stream memray's output instead of capturing it, so run does not look stuck
    print(f"    flamegraph ({mode})...", flush=True)
    result = subprocess.run(cmd, text=True)
    if result.returncode != 0:
        # -9 is SIGKILL, almost always the OOM killer reaping the heavy
        # temporary render on a large capture. Do not abort the whole run:
        # the capture and metrics are recorded separately and still good.
        reason = "killed (likely OOM)" if result.returncode == -9 else f"exit {result.returncode}"
        print(f"  flamegraph {mode} render failed for {out_path.name} ({reason})", file=sys.stderr)
        return False
    return True


# get_allocation_records() yields deallocation records too...
# They carry size 0, so they don't affect byte sums, but they
# inflate record count, so we filter them out when counting alloc calls.
_DEALLOCATORS = {
    memray.AllocatorType.FREE,
    memray.AllocatorType.MUNMAP,
    memray.AllocatorType.PYMALLOC_FREE,
}


def _read_metrics(bin_path: Path) -> dict:
    """Extract peak_bytes, leaked_bytes and total_allocations from a memray .bin file."""
    with memray.FileReader(str(bin_path)) as reader:
        # peak_bytes: the high-water mark of live memory, i.e. the most memory
        # in use at any single instant.
        peak_bytes = reader.metadata.peak_memory

        # total_allocations: number of allocation calls.
        # We exclude deallocator records to count just allocations.
        total_allocations = sum(
            1
            for record in reader.get_allocation_records()
            if record.allocator not in _DEALLOCATORS
        )

        # leaked_bytes: memory still reachable when tracking ended (never freed).
        leaked_bytes = sum(
            record.size
            for record in reader.get_leaked_allocation_records(merge_threads=True)
        )

    return {
        "peak_bytes": peak_bytes,
        "leaked_bytes": leaked_bytes,
        "total_allocations": total_allocations,
    }


def _build_meta() -> dict:
    """Provenance for the baseline: which toolchain produced these numbers.
    Recorded so a committed baseline is reproducible under same conditions.
    """
    native_version = ""
    try:
        native_version = (HERE.parent.parent / "c2pa-native-version.txt").read_text().strip()
    except OSError:
        pass
    return {
        "memray_version": getattr(memray, "__version__", ""),
        "python_version": platform.python_version(),
        "c2pa_native_version": native_version,
        "iterations": ITERATIONS,
        "perf_env": PERF_ENV,
        "arch": platform.machine(),
    }


def _fmt(n: int) -> str:
    if n >= 1024 ** 2:
        return f"{n / 1024**2:.1f} MiB"
    if n >= 1024:
        return f"{n / 1024:.1f} KiB"
    return f"{n} B"


def main() -> None:
    parser = argparse.ArgumentParser(description="c2pa-python memory profiler")
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
    args = parser.parse_args()

    scenarios_to_run = (args.scenario,) if args.scenario else SCENARIO_NAMES

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    baseline: dict = {}
    if BASELINE_FILE.exists() and not args.update_baseline:
        baseline = json.loads(BASELINE_FILE.read_text())

    results: dict = {}
    failures: list[str] = []
    render_failures: list[dict] = []

    total = len(scenarios_to_run)
    for idx, name in enumerate(scenarios_to_run, 1):
        print(f"\n=== [{idx}/{total}] {name} (iterations={ITERATIONS}) ===")

        with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as tmp:
            bin_path = Path(tmp.name)

        env_tag = f"-{PERF_ENV}" if PERF_ENV else ""
        scenario_render_failed = False
        failed_modes: list[dict] = []
        try:
            print(f"  profiling...")
            _run_scenario_under_memray(name, bin_path)

            peak_html = REPORTS_DIR / f"{name}{env_tag}-peak.html"
            leaks_html = REPORTS_DIR / f"{name}{env_tag}-leaks.html"
            temporary_html = REPORTS_DIR / f"{name}{env_tag}-temporary.html"
            print(f"  generating flamegraphs (peak + leaks + temporary)...")
            scenario_render_failed = False
            failed_modes: list[dict] = []
            for mode, html in (("peak", peak_html),
                               ("leaks", leaks_html),
                               ("temporary", temporary_html)):
                if not _generate_flamegraph(bin_path, html, mode=mode):
                    scenario_render_failed = True
                    failed_modes.append({"name": name, "mode": mode, "html": html.name})

            print(f"  reading metrics...", flush=True)
            metrics = _read_metrics(bin_path)
            results[name] = metrics

            print(f"  peak:   {_fmt(metrics['peak_bytes'])}")
            print(f"  leaked: {_fmt(metrics['leaked_bytes'])}")
            print(f"  allocs: {metrics['total_allocations']}")
            print(f"  peak report:      {peak_html}")
            print(f"  leaks report:     {leaks_html}")
            print(f"  temporary report: {temporary_html}")

            if baseline and name in baseline:
                b = baseline[name]
                for metric in ("peak_bytes", "leaked_bytes"):
                    current = metrics[metric]
                    base = b.get(metric, 0)
                    limit = base * THRESHOLD
                    if current > limit:
                        diff_pct = (current - base) / base * 100 if base else float("inf")
                        failures.append(
                            f"{name}.{metric}: {_fmt(current)} > baseline {_fmt(base)}"
                            f" (+{diff_pct:.1f}%, threshold {(THRESHOLD-1)*100:.0f}%)"
                        )
        finally:
            if scenario_render_failed:
                # Keep the capture so the failed view can be re-rendered
                # offline (with a higher --temporary-allocation-threshold)
                # instead of re-profiling the whole scenario.
                kept = REPORTS_DIR / f"{name}{env_tag}.bin"
                shutil.move(str(bin_path), str(kept))
                for fm in failed_modes:
                    fm["bin"] = str(kept)
                render_failures.extend(failed_modes)
            else:
                bin_path.unlink(missing_ok=True)

    if args.update_baseline or not baseline:
        # When running a single scenario, merge its result into the existing
        # baseline so the other scenarios' entries are preserved. A full run
        # replaces the file wholesale.
        if args.scenario and baseline:
            output = dict(baseline)
        else:
            output = {}
        output["_meta"] = _build_meta()
        output.update(results)
        BASELINE_FILE.write_text(json.dumps(output, indent=2))
        verb = "Updated" if baseline else "Created"
        print(f"\n{verb} baseline: {BASELINE_FILE}")

    if render_failures:
        print("\nFLAMEGRAPH RENDERS FAILED (capture + metrics still recorded):", file=sys.stderr)
        for r in render_failures:
            print(f"  {r['name']} [{r['mode']}] -> {r['html']}  (capture kept: {r['bin']})", file=sys.stderr)
        print("  Recover without re-profiling, e.g.:", file=sys.stderr)
        print("    python3 -m memray flamegraph <kept.bin> -o <out.html> "
              "--temporary-allocations --temporary-allocation-threshold=10 --force", file=sys.stderr)

    if failures:
        print("\nREGRESSIONS DETECTED:", file=sys.stderr)
        for f in failures:
            print(f"  {f}", file=sys.stderr)
        sys.exit(1)

    print("\nAll scenarios within baseline thresholds.")


if __name__ == "__main__":
    main()
