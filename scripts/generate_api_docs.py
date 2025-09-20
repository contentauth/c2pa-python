#!/usr/bin/env python3
"""
Generate API documentation using Sphinx + AutoAPI.

This script builds HTML docs into docs/_build/html.
It avoids importing the package by relying on sphinx-autoapi
to parse source files directly.
"""

import shutil
import os
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
    docs_dir = root / "api-docs"
    build_dir = docs_dir / "_build" / "html"
    api_dir = docs_dir / "api"

    # Preprocess sources: convert Markdown code fences in docstrings to reST
    src_pkg_dir = root / "src" / "c2pa"
    pre_dir = docs_dir / "_preprocessed"
    pre_pkg_dir = pre_dir / "c2pa"
    if pre_dir.exists():
        shutil.rmtree(pre_dir)
    pre_pkg_dir.mkdir(parents=True, exist_ok=True)

    def convert_fences_to_rst(text: str) -> str:
        lines = text.splitlines()
        out: list[str] = []
        i = 0
        while i < len(lines):
            line = lines[i]
            stripped = line.lstrip()
            indent = line[: len(line) - len(stripped)]
            if stripped.startswith("```"):
                fence = stripped
                lang = fence[3:].strip() or "text"
                # Start directive
                out.append(f"{indent}.. code-block:: {lang}")
                out.append("")
                i += 1
                # Emit indented code until closing fence
                while i < len(lines):
                    l2 = lines[i]
                    if l2.lstrip().startswith("```"):
                        i += 1
                        break
                    out.append(f"{indent}    {l2}")
                    i += 1
                continue
            out.append(line)
            i += 1
        return "\n".join(out) + ("\n" if text.endswith("\n") else "")

    for src_path in src_pkg_dir.rglob("*.py"):
        rel = src_path.relative_to(src_pkg_dir)
        dest = pre_pkg_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        content = src_path.read_text(encoding="utf-8")
        dest.write_text(convert_fences_to_rst(content), encoding="utf-8")

    # Point AutoAPI to preprocessed sources
    os.environ["C2PA_DOCS_SRC"] = str(pre_pkg_dir)

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


