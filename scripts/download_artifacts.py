#!/usr/bin/env python3
import os
import sys
import requests
from pathlib import Path
import zipfile
import io

# Constants
REPO_OWNER = "contentauth"
REPO_NAME = "c2pa-rs"
GITHUB_API_BASE = "https://api.github.com"
ARTIFACTS_DIR = Path("artifacts")

def get_release_by_tag(tag):
    """Get release information for a specific tag from GitHub."""
    url = f"{GITHUB_API_BASE}/repos/{REPO_OWNER}/{REPO_NAME}/releases/tags/{tag}"
    response = requests.get(url)
    response.raise_for_status()
    return response.json()

def download_and_extract_libs(url, platform_name):
    """Download a zip artifact and extract only the libs folder."""
    print(f"Downloading artifact for {platform_name}...")
    platform_dir = ARTIFACTS_DIR / platform_name
    platform_dir.mkdir(parents=True, exist_ok=True)

    response = requests.get(url)
    response.raise_for_status()

    with zipfile.ZipFile(io.BytesIO(response.content)) as zip_ref:
        # Extract only files inside the libs/ directory
        for member in zip_ref.namelist():
            if member.startswith("lib/") and not member.endswith("/"):
                target_path = platform_dir / os.path.relpath(member, "lib")
                target_path.parent.mkdir(parents=True, exist_ok=True)
                with zip_ref.open(member) as source, open(target_path, "wb") as target:
                    target.write(source.read())
    print(f"Successfully downloaded and extracted libraries for {platform_name}")

def main():
    if len(sys.argv) < 2:
        print("Usage: python download_artifacts.py <release_tag>")
        print("Example: python download_artifacts.py c2pa-v0.49.5")
        sys.exit(1)

    release_tag = sys.argv[1]
    try:
        ARTIFACTS_DIR.mkdir(exist_ok=True)
        print(f"Fetching release information for tag {release_tag}...")
        release = get_release_by_tag(release_tag)
        print(f"Found release: {release['tag_name']}")

        for asset in release['assets']:
            if not asset['name'].endswith('.zip'):
                continue

            # Example asset name: c2pa-v0.49.5-aarch64-apple-darwin.zip
            # Platform name: aarch64-apple-darwin
            parts = asset['name'].split('-')
            if len(parts) < 4:
                continue  # Unexpected naming, skip
            platform_name = '-'.join(parts[3:]).replace('.zip', '')

            download_and_extract_libs(asset['browser_download_url'], platform_name)

        print("\nAll artifacts have been downloaded and extracted successfully!")

    except requests.exceptions.RequestException as e:
        print(f"Error downloading artifacts: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()