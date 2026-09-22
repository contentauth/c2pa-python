#!/usr/bin/env python3
# Copyright 2026 Adobe. All rights reserved.
# This file is licensed to you under the Apache License,
# Version 2.0 (http://www.apache.org/licenses/LICENSE-2.0)
# or the MIT license (http://opensource.org/licenses/MIT),
# at your option.

"""
Thread-safety invariant harness.

For each scenario in thread_scenarios.THREAD_SCENARIOS this script:
- Runs the scenario in a subprocess with faulthandler armed
- Reads the scenario's outcome counters from the subprocess's last stdout line
- Fails the run unless every round produced the expected outcome

There is no baseline file. Each scenario asserts a fixed invariant of the
binding, so there is nothing to drift against: the expected value is declared in
the registry beside the scenario.

The scenarios force a teardown to run while a native call is still open, and then
check the guard state instead of waiting for a use-after-free to fault. A fault
only happens when the allocator has reused the freed page, so crash-based detection
is probabilistic; a guard-state assertion is deterministic.

A scenario that cannot reach its injection point reports NOT_PARKED and fails,
because a scenario that stops forcing anything would otherwise keep passing
while testing nothing.

Usage:
    python -m tests.perf.run_thread_profile [--scenario NAME]
    python -m tests.perf.run_thread_profile --self-test
    python -m tests.perf.run_thread_profile --list

Environment variables:
- THREAD_ROUNDS: rounds each scenario loops (default: 20)
- THREAD_HANG_TIMEOUT: seconds before a stuck scenario is dumped and killed
  (default: 120)
"""

import argparse
import json
import os
import signal
import subprocess
import sys
from pathlib import Path

from tests.perf.thread_scenarios import (
    THREAD_SCENARIO_NAMES,
    THREAD_SCENARIOS,
)

HERE = Path(__file__).parent
REPORTS_DIR = HERE / "reports"

ROUNDS = int(os.environ.get("THREAD_ROUNDS", "20"))
HANG_TIMEOUT = int(os.environ.get("THREAD_HANG_TIMEOUT", "120"))
PERF_ENV = os.environ.get("PERF_ENV", "")

# Signals that mean native memory corruption. A container reports a signalled
# exit as 128+N while a direct child reports -N, so both encodings are accepted.
# SIGTRAP is included because the macOS allocator traps rather than aborting.
_CRASH_SIGNALS = (signal.SIGSEGV, signal.SIGABRT, signal.SIGTRAP)
_CRASH_CODES = frozenset(
    [-int(s) for s in _CRASH_SIGNALS] + [128 + int(s) for s in _CRASH_SIGNALS]
)

# faulthandler prints this banner before dumping every thread on timeout.
_HANG_MARKER = "Timeout ("

# Status values. A crash and an ordinary exception stay separate: an
# ImportError and a failed artifact download both surface as exit 1, and
# reporting either as a crash would invent a finding that does not exist.
_PASS = "pass"
_VIOLATED = "VIOLATED"
_CRASHED = "CRASHED"
_HUNG = "HUNG"
_FAILED = "FAILED"


def _child_script(name: str) -> str:
    """Source for the subprocess that runs one scenario.

    faulthandler turns a crash or a hang into a traceback naming every thread,
    which is the diagnostic for a guard that blocked instead of refusing. Its
    timer thread is a C thread, so it still fires when the main thread is parked
    inside a native call with the GIL released.
    """
    repo_root = HERE.parent.parent
    return f"""
import faulthandler, json, sys
faulthandler.enable()
faulthandler.dump_traceback_later({HANG_TIMEOUT}, exit=True)
sys.path.insert(0, {str(repo_root)!r})
sys.path.insert(0, {str(repo_root / 'src')!r})
from tests.perf.thread_scenarios import THREAD_SCENARIOS
counts = THREAD_SCENARIOS[{name!r}][0]({ROUNDS})
faulthandler.cancel_dump_traceback_later()
print("COUNTS " + json.dumps(counts))
"""


def _parse_counts(stdout: str):
    """The counter dict from the child's COUNTS line, or None if absent."""
    for line in reversed(stdout.splitlines()):
        if line.startswith("COUNTS "):
            try:
                return json.loads(line[len("COUNTS "):])
            except json.JSONDecodeError:
                return None
    return None


def _classify(returncode: int, counts, expected: str, stderr: str = ""):
    """Map a finished child onto a status and a human-readable detail."""
    if returncode in _CRASH_CODES:
        return _CRASHED, f"killed by signal (exit {returncode})"

    if returncode != 0:
        # A hang and an ordinary exception both exit 1. Only faulthandler's
        # timeout banner tells them apart, so match on it rather than guessing
        # from the exit code.
        if _HANG_MARKER in stderr:
            return _HUNG, f"no progress for {HANG_TIMEOUT}s"
        return _FAILED, f"exit {returncode}"

    if not counts:
        return _FAILED, "scenario produced no counters"

    if set(counts) == {expected}:
        return _PASS, f"{expected} x{counts[expected]}"

    unexpected = {k: v for k, v in counts.items() if k != expected}
    return _VIOLATED, f"expected {expected} x{ROUNDS}, got {json.dumps(counts)}" \
        if expected not in counts else \
        f"expected only {expected}, also saw {json.dumps(unexpected)}"


def _run_scenario(name: str, expected: str):
    """Run one scenario in a subprocess and classify the result."""
    proc = subprocess.run(
        [sys.executable, "-c", _child_script(name)],
        text=True,
        capture_output=True,
        env={**os.environ, "PERF_SCENARIO": name},
    )
    counts = _parse_counts(proc.stdout)
    status, detail = _classify(
        proc.returncode, counts, expected, proc.stderr)

    if status != _PASS and proc.stderr.strip():
        # The all-threads traceback is the diagnostic, so it has to reach both
        # the log and the artifact.
        print(proc.stderr.rstrip(), file=sys.stderr)
        log_name = f"{name}-{PERF_ENV}-threads.log" if PERF_ENV else f"{name}-threads.log"
        (REPORTS_DIR / log_name).write_text(proc.stderr, encoding="utf-8")

    return status, detail, counts


def _write_github_summary(results: dict) -> None:
    """Append a results table to $GITHUB_STEP_SUMMARY when running in CI."""
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path or not results:
        return

    lines = [
        "## Threading invariants",
        "",
        f"Rounds: {ROUNDS}"
        f"{f' · env: {PERF_ENV}' if PERF_ENV else ''}",
        "",
        "| scenario | rounds | expected | actual | status |",
        "|----------|--------|----------|--------|--------|",
    ]
    for name, row in results.items():
        actual = json.dumps(row["counts"]) if row["counts"] else "-"
        lines.append(
            f"| {name} | {ROUNDS} | {THREAD_SCENARIOS[name][1]} "
            f"| {actual} | {row['status']} |"
        )
    lines.append("")

    with open(summary_path, "a", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


# Synthetic children for --self-test. A detector that has never been shown to
# fire cannot be told apart from one that cannot fire, and the last case is the
# one that matters most: an exception must not be reported as a crash.
_SELF_TESTS = (
    ("segfault", "import faulthandler,ctypes; faulthandler.enable(); "
                 "ctypes.string_at(0)", _CRASHED),
    ("abort", "import os,signal; os.kill(os.getpid(), signal.SIGABRT)", _CRASHED),
    ("hang", "import faulthandler,threading; faulthandler.enable(); "
             "faulthandler.dump_traceback_later(2, exit=True); "
             "threading.Event().wait()", _HUNG),
    ("exception", "raise RuntimeError('boom')", _FAILED),
)


def _self_test() -> int:
    """Prove the classifier reports each failure class correctly."""
    print("=== self-test: classifier ===")
    failures = []
    for label, code, want in _SELF_TESTS:
        proc = subprocess.run(
            [sys.executable, "-c", code], text=True, capture_output=True)
        got, detail = _classify(
            proc.returncode, _parse_counts(proc.stdout), "n/a", proc.stderr)
        ok = got == want
        print(f"  {label:<10} want={want:<9} got={got:<9} ({detail}) "
              f"{'ok' if ok else 'MISCLASSIFIED'}")
        if not ok:
            failures.append(f"{label}: wanted {want}, got {got}")

    if failures:
        print("\nself-test FAILED - the harness cannot see the failures it "
              "exists to catch:", file=sys.stderr)
        for line in failures:
            print(f"  {line}", file=sys.stderr)
        return 1
    print("self-test passed")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="c2pa-python thread-safety invariant harness")
    parser.add_argument(
        "--scenario",
        choices=THREAD_SCENARIO_NAMES,
        default=None,
        help="Run a single scenario instead of all of them.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List the scenarios with their expected outcomes and exit.",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Check that the harness classifies crashes, hangs and exceptions "
             "correctly, then exit.",
    )
    args = parser.parse_args()

    if args.list:
        for name in THREAD_SCENARIO_NAMES:
            print(f"{name}\texpects {THREAD_SCENARIOS[name][1]}")
        return

    if args.self_test:
        sys.exit(_self_test())

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    scenarios_to_run = (args.scenario,) if args.scenario else THREAD_SCENARIO_NAMES

    # Print the knobs so a CI failure can be reproduced locally from the log.
    print(f"rounds={ROUNDS} hang_timeout={HANG_TIMEOUT}s"
          f"{f' env={PERF_ENV}' if PERF_ENV else ''}")

    results: dict = {}
    failures: list[str] = []

    total = len(scenarios_to_run)
    for idx, name in enumerate(scenarios_to_run, 1):
        expected = THREAD_SCENARIOS[name][1]
        print(f"\n=== [{idx}/{total}] {name} (expects {expected}) ===", flush=True)
        status, detail, counts = _run_scenario(name, expected)
        results[name] = {"status": status, "detail": detail, "counts": counts}
        print(f"  {status}: {detail}", flush=True)
        if status != _PASS:
            failures.append(f"{name}: {status} - {detail}")

    _write_github_summary(results)

    print("\n=== summary ===")
    for name, row in results.items():
        print(f"  {row['status']:<9} {name}")

    if failures:
        print(f"\n{len(failures)} scenario(s) failed:", file=sys.stderr)
        for line in failures:
            print(f"  {line}", file=sys.stderr)
        sys.exit(1)
    print(f"\nall {total} invariant(s) hold")


if __name__ == "__main__":
    main()
