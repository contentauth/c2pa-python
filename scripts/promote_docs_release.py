#!/usr/bin/env python3
"""Promote a published release through an optimistic, manifest-only Contents PUT."""

import base64
import json
import os
import time
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

if __package__:
    from .docs_versions import TAG_PATTERN, promote, serialize, validate_manifest, version_key
else:
    from docs_versions import TAG_PATTERN, promote, serialize, validate_manifest, version_key


MANIFEST_PATH = "api-docs/versions.json"


def api(method: str, path: str, token: str, data=None):
    request = Request(
        f"https://api.github.com/repos/contentauth/c2pa-python/{path}",
        data=None if data is None else json.dumps(data).encode(),
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        },
        method=method,
    )
    with urlopen(request, timeout=30) as response:
        return json.load(response)


def promote_release(tag: str, release_id: str, read_token: str, write_token: str) -> None:
    version_key(tag)
    release = api("GET", f"releases/tags/{quote(tag, safe='')}", read_token)
    if (
        release.get("tag_name") != tag
        or str(release.get("id")) != release_id
        or release.get("draft") is not False
        or release.get("prerelease") is not False
        or not release.get("published_at")
    ):
        raise ValueError("Release metadata does not identify a published stable release.")
    tags = {tag}
    page = 1
    while True:
        releases = api("GET", f"releases?per_page=100&page={page}", read_token)
        if not isinstance(releases, list):
            raise ValueError("GitHub releases response must be a list.")
        for item in releases:
            candidate = item.get("tag_name")
            if (
                isinstance(candidate, str)
                and TAG_PATTERN.fullmatch(candidate)
                and item.get("draft") is False
                and item.get("prerelease") is False
                and item.get("published_at")
            ):
                tags.add(candidate)
        if len(releases) < 100:
            break
        page += 1
    for attempt in range(5):
        current = api("GET", f"contents/{MANIFEST_PATH}?ref=main", read_token)
        config = validate_manifest(json.loads(base64.b64decode(current["content"])))
        updated = config
        for candidate in sorted(tags, key=version_key):
            updated = promote(updated, candidate)
        if updated == config:
            print(f"No promotion needed for {tag} or other published stable releases.")
            return
        try:
            api("PUT", f"contents/{MANIFEST_PATH}", write_token, {
                "branch": "main",
                "sha": current["sha"],
                "message": f"docs: promote {tag} [docs-promotion]",
                "content": base64.b64encode(serialize(updated).encode()).decode(),
            })
            return
        except HTTPError as error:
            if error.code not in (409, 422) or attempt == 4:
                raise
            time.sleep(attempt + 1)
    raise RuntimeError("Manifest promotion exhausted concurrent-update retries.")


if __name__ == "__main__":
    promote_release(
        os.environ["RELEASE_TAG"], os.environ["RELEASE_ID"],
        os.environ["GITHUB_TOKEN"], os.environ["DOCS_WRITE_TOKEN"],
    )
