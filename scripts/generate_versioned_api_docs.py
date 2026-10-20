#!/usr/bin/env python3
"""Build a GitHub Pages site from the explicitly selected GitHub releases."""

import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile

import requests


ROOT = Path(__file__).resolve().parents[1]
RELEASES_URL = "https://api.github.com/repos/contentauth/c2pa-python/releases/tags"
TAG_PATTERN = re.compile(r"v[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9][A-Za-z0-9.-]*)?")


def load_versions(path: Path) -> list[str]:
    config = json.loads(path.read_text(encoding="utf-8"))
    versions = config.get("versions") if isinstance(config, dict) else None
    if not isinstance(versions, list) or not versions:
        raise ValueError("Documentation versions must be a non-empty list.")
    for tag in versions:
        if not isinstance(tag, str) or not TAG_PATTERN.fullmatch(tag):
            raise ValueError("Documentation versions must be release tags such as v0.38.0.")
    if len(set(versions)) != len(versions):
        raise ValueError("Documentation versions must not contain duplicate tags.")
    return versions


def verify_release(tag: str) -> None:
    headers = {"Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    response = requests.get(
        f"{RELEASES_URL}/{tag}", headers=headers, timeout=30, allow_redirects=False
    )
    if response.status_code != 200:
        raise RuntimeError(
            f"Cannot verify GitHub release {tag}: HTTP {response.status_code}."
        )
    release = response.json()
    if (
        not isinstance(release, dict)
        or release.get("tag_name") != tag
        or release.get("draft") is not False
    ):
        raise ValueError(f"{tag} is not a published GitHub release.")


def export_sources(root: Path, tag: str, destination: Path) -> None:
    # Resolve the exact tag, not a similarly named branch, and never run tagged code.
    commit = subprocess.run(
        ["git", "rev-parse", "--verify", f"refs/tags/{tag}^{{commit}}"],
        cwd=root, check=True, capture_output=True, text=True,
    ).stdout.strip()
    archive = subprocess.run(
        ["git", "archive", "--format=zip", commit, "src/c2pa"],
        cwd=root, check=True, capture_output=True,
    ).stdout
    with zipfile.ZipFile(io.BytesIO(archive)) as sources:
        count = 0
        for entry in sources.infolist():
            path = PurePosixPath(entry.filename)
            if (
                path.is_absolute()
                or ".." in path.parts
                or any("\\" in part or ":" in part for part in path.parts)
                or (
                    path.parts[:2] != ("src", "c2pa")
                    and not (entry.is_dir() and path.parts == ("src",))
                )
                or stat.S_ISLNK(entry.external_attr >> 16)
            ):
                raise ValueError(f"Unsafe source archive in release {tag}.")
            if entry.is_dir() or path.suffix != ".py":
                continue
            target = destination.joinpath(*path.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(sources.read(entry))
            count += 1
        if not count:
            raise ValueError(f"Release {tag} contains no Python API sources.")


def build_site() -> Path:
    docs = ROOT / "api-docs"
    versions = load_versions(docs / "versions.json")
    for tag in versions:
        verify_release(tag)

    build = docs / "_build"
    build.mkdir(exist_ok=True)
    output = build / "versioned"
    with tempfile.TemporaryDirectory(prefix="versioned-docs-", dir=build) as temporary:
        workspace = Path(temporary)
        site = workspace / "site"
        for tag in versions:
            stage = workspace / tag
            stage.mkdir()
            shutil.copytree(
                docs, stage / "api-docs",
                ignore=shutil.ignore_patterns(
                    "_build", "_preprocessed", "api", "__pycache__", ".DS_Store"
                ),
            )
            scripts = stage / "scripts"
            scripts.mkdir()
            shutil.copy2(ROOT / "scripts" / "generate_api_docs.py", scripts)
            export_sources(ROOT, tag, stage)
            environment = os.environ.copy()
            environment.update(
                C2PA_DOCS_TAG=tag,
                C2PA_DOCS_VERSIONS=json.dumps(versions),
                C2PA_DOCS_PREFIX=f"versions/{tag}",
            )
            subprocess.run(
                [sys.executable, str(scripts / "generate_api_docs.py")],
                cwd=stage, env=environment, check=True,
            )
            html = stage / "api-docs" / "_build" / "html"
            shutil.copytree(html, site / "versions" / tag)

        # Rebuild the default at the root so all switcher links remain relative.
        default = workspace / versions[0]
        environment.update(C2PA_DOCS_TAG=versions[0], C2PA_DOCS_PREFIX="")
        shutil.rmtree(default / "api-docs" / "_build" / "html")
        subprocess.run(
            [sys.executable, str(default / "scripts" / "generate_api_docs.py")],
            cwd=default, env=environment, check=True,
        )
        shutil.copytree(
            default / "api-docs" / "_build" / "html", site, dirs_exist_ok=True
        )
        (site / ".nojekyll").touch()
        if output.exists():
            shutil.rmtree(output)
        shutil.move(str(site), str(output))
    return output


if __name__ == "__main__":
    print(f"Versioned API docs generated at: {build_site()}")
