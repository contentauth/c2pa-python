"""Stable release-line manifest policy (standard library only)."""

import json
from pathlib import Path
import re


TAG_PATTERN = re.compile(r"v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")
LINE_PATTERN = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")


def version_key(tag: str) -> tuple[int, ...]:
    if not isinstance(tag, str) or not TAG_PATTERN.fullmatch(tag):
        raise ValueError(f"Expected an exact stable vX.Y.Z tag: {tag!r}")
    return tuple(map(int, tag[1:].split(".")))


def release_line(tag: str) -> str:
    major, minor, _ = version_key(tag)
    return f"{major}.{minor}"


def validate_manifest(config: dict) -> dict:
    if not isinstance(config, dict) or set(config) != {"versions", "retiredLines", "aliases"}:
        raise ValueError("Manifest requires versions, retiredLines and aliases.")
    versions, retired, aliases = (
        config["versions"], config["retiredLines"], config["aliases"]
    )
    if not isinstance(versions, list) or not versions:
        raise ValueError("Documentation versions must be a non-empty list.")
    keys = [version_key(tag) for tag in versions]
    lines = [release_line(tag) for tag in versions]
    if len(set(lines)) != len(lines) or keys != sorted(keys, reverse=True):
        raise ValueError("Select one patch per line in numeric descending order.")
    if (
        not isinstance(retired, list)
        or any(not isinstance(line, str) or not LINE_PATTERN.fullmatch(line) for line in retired)
        or len(set(retired)) != len(retired)
        or set(lines).intersection(retired)
    ):
        raise ValueError("Retired lines must be unique X.Y lines, disjoint from active lines.")
    if not isinstance(aliases, dict):
        raise ValueError("Aliases must map historical stable tags to active lines.")
    for tag, line in aliases.items():
        if release_line(tag) != line or line not in lines:
            raise ValueError(f"Invalid historical alias: {tag!r}: {line!r}")
        selected = versions[lines.index(line)]
        if version_key(tag) > version_key(selected):
            raise ValueError("An alias cannot be newer than its selected release.")
    if any(aliases.get(tag) != release_line(tag) for tag in versions):
        raise ValueError("Every selected tag must also have a historical alias.")
    return config


def load_manifest(path: Path) -> dict:
    return validate_manifest(json.loads(path.read_text(encoding="utf-8")))


def promote(config: dict, tag: str) -> dict:
    """Advance a line, never regress it, resurrect it, or displace a newer default."""
    validate_manifest(config)
    line = release_line(tag)
    result = {
        "versions": list(config["versions"]),
        "retiredLines": list(config["retiredLines"]),
        "aliases": dict(config["aliases"]),
    }
    if line in result["retiredLines"]:
        return result
    selected = next((item for item in result["versions"] if release_line(item) == line), None)
    if selected is None:
        known = [release_line(item) for item in result["versions"]] + result["retiredLines"]
        if tuple(map(int, line.split("."))) <= max(
            tuple(map(int, item.split("."))) for item in known
        ):
            return result
    if selected and version_key(tag) <= version_key(selected):
        return result
    if selected:
        result["versions"].remove(selected)
    result["versions"].append(tag)
    result["versions"].sort(key=version_key, reverse=True)
    result["aliases"][tag] = line
    return validate_manifest(result)


def serialize(config: dict) -> str:
    return json.dumps(validate_manifest(config), indent=2) + "\n"
