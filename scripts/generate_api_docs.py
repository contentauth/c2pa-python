#!/usr/bin/env python3
"""
Generate API documentation using Sphinx + AutoAPI.

This script builds HTML docs into docs/_build/html.
It avoids importing the package by relying on sphinx-autoapi
to parse source files directly.
"""

import shutil
import sys
from pathlib import Path
import importlib


def ensure_tools_available() -> None:
    try:
        importlib.import_module("sphinx")
        importlib.import_module("autoapi")
        importlib.import_module("myst_parser")
    except Exception as exc:
        root = Path(__file__).resolve().parents[1]
        req = root / "requirements-dev.txt"
        print(
            "Missing documentation dependencies. "
            f"Install with: python3 -m pip install -r {req}",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc


def build_docs() -> None:
    root = Path(__file__).resolve().parents[1]
    docs_dir = root / "docs"
    build_dir = docs_dir / "_build" / "html"
    api_dir = docs_dir / "api"

    # Clean AutoAPI output to avoid stale pages
    if api_dir.exists():
        shutil.rmtree(api_dir)

    build_dir.mkdir(parents=True, exist_ok=True)

    try:
        sphinx_build_mod = importlib.import_module("sphinx.cmd.build")
        sphinx_main = getattr(sphinx_build_mod, "main")
        code = sphinx_main([
            "-b",
            "html",
            str(docs_dir),
            str(build_dir),
        ])
        if code != 0:
            raise SystemExit(code)
    except Exception:
        # Fallback to subprocess if needed
        import subprocess

        cmd = [
            sys.executable,
            "-m",
            "sphinx",
            "-b",
            "html",
            str(docs_dir),
            str(build_dir),
        ]
        subprocess.run(cmd, check=True)

    print(f"API docs generated at: {build_dir}")


if __name__ == "__main__":
    ensure_tools_available()
    build_docs()


