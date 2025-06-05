#!/usr/bin/env python3
import os
import sys
import requests
from pathlib import Path
import zipfile
import io
import shutil
import platform
import subprocess

# Constants
REPO_OWNER = "contentauth"
REPO_NAME = "c2pa-rs"
GITHUB_API_BASE = "https://api.github.com"
SCRIPTS_ARTIFACTS_DIR = Path("scripts/artifacts")
ROOT_ARTIFACTS_DIR = Path("artifacts")

def detect_os():
    """Detect the operating system and return the corresponding platform identifier."""
    system = platform.system().lower()
    if system == "darwin":
        return "apple-darwin"
    elif system == "linux":
        return "unknown-linux-gnu"
    elif system == "windows":
        return "pc-windows-msvc"
    else:
        raise ValueError(f"Unsupported operating system: {system}")

def detect_arch():
    """Detect the CPU architecture and return the corresponding identifier."""
    machine = platform.machine().lower()

    # Handle common architecture names
    if machine in ["x86_64", "amd64"]:
        return "x86_64"
    elif machine in ["arm64", "aarch64"]:
        return "aarch64"
    else:
        raise ValueError(f"Unsupported CPU architecture: {machine}")

def get_platform_identifier():
    """Get the full platform identifier (arch-os) for the current system,
    matching the identifiers used by the Github publisher.
    Returns one of:
    - universal-apple-darwin (for Mac)
    - x86_64-pc-windows-msvc (for Windows 64-bit)
    - x86_64-unknown-linux-gnu (for Linux 64-bit)
    """
    system = platform.system().lower()

    if system == "darwin":
        return "universal-apple-darwin"
    elif system == "windows":
        return "x86_64-pc-windows-msvc"
    elif system == "linux":
        return "x86_64-unknown-linux-gnu"
    else:
        raise ValueError(f"Unsupported operating system: {system}")

def get_release_by_tag(tag):
    """Get release information for a specific tag from GitHub."""
    url = f"{GITHUB_API_BASE}/repos/{REPO_OWNER}/{REPO_NAME}/releases/tags/{tag}"
    print(f"Fetching release information from {url}...")
    headers = {}
    if 'GITHUB_TOKEN' in os.environ:
        headers['Authorization'] = f"token {os.environ['GITHUB_TOKEN']}"
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    return response.json()

def download_and_extract_libs(url, platform_name):
    """Download a zip artifact and extract only the libs folder."""
    print(f"Downloading artifact for {platform_name}...")
    platform_dir = SCRIPTS_ARTIFACTS_DIR / platform_name
    platform_dir.mkdir(parents=True, exist_ok=True)

    headers = {}
    if 'GITHUB_TOKEN' in os.environ:
        headers['Authorization'] = f"token {os.environ['GITHUB_TOKEN']}"
    response = requests.get(url, headers=headers)
    response.raise_for_status()

    with zipfile.ZipFile(io.BytesIO(response.content)) as zip_ref:
        # Extract only files inside the libs/ directory
        for member in zip_ref.namelist():
            print(f"  Processing zip member: {member}")
            if member.startswith("lib/") and not member.endswith("/"):
                print(f"    Processing lib file from downloadedzip: {member}")
                target_path = platform_dir / os.path.relpath(member, "lib")
                print(f"      Moving file to target path: {target_path}")
                target_path.parent.mkdir(parents=True, exist_ok=True)
                with zip_ref.open(member) as source, open(target_path, "wb") as target:
                    target.write(source.read())

    print(f"Done downloading and extracting libraries for {platform_name}")

def copy_artifacts_to_root():
    """Copy the artifacts folder from scripts/artifacts to the root of the repository."""
    if not SCRIPTS_ARTIFACTS_DIR.exists():
        print("No artifacts found in scripts/artifacts")
        return

    print("Copying artifacts from scripts/artifacts to root...")
    if ROOT_ARTIFACTS_DIR.exists():
        shutil.rmtree(ROOT_ARTIFACTS_DIR)
    shutil.copytree(SCRIPTS_ARTIFACTS_DIR, ROOT_ARTIFACTS_DIR)
    print("Done copying artifacts")

def main():
    if len(sys.argv) < 2:
        print("Usage: python download_artifacts.py <release_tag>")
        print("Example: python download_artifacts.py c2pa-v0.49.5")
        sys.exit(1)

    release_tag = sys.argv[1]
    try:
        SCRIPTS_ARTIFACTS_DIR.mkdir(exist_ok=True)
        print(f"Fetching release information for tag {release_tag}...")
        release = get_release_by_tag(release_tag)
        print(f"Found release: {release['tag_name']} \n")

        # Get the platform identifier for the current system
        env_platform = os.environ.get("C2PA_LIBS_PLATFORM")
        if env_platform:
            print(f"Using platform from environment variable C2PA_LIBS_PLATFORM: {env_platform}")
        platform_id = env_platform or get_platform_identifier()
        platform_source = "environment variable" if env_platform else "auto-detection"
        print(f"Target platform: {platform_id} (set through{platform_source})")

        # Construct the expected asset name
        expected_asset_name = f"{release_tag}-{platform_id}.zip"
        print(f"Looking for asset: {expected_asset_name}")

        # Find the matching asset in the release
        matching_asset = None
        for asset in release['assets']:
            if asset['name'] == expected_asset_name:
                matching_asset = asset
                break

        if matching_asset:
            print(f"Found matching asset: {matching_asset['name']}")
            download_and_extract_libs(matching_asset['browser_download_url'], platform_id)
            print("\nArtifacts have been downloaded and extracted successfully!")
            copy_artifacts_to_root()
        else:
            print(f"\nNo matching asset found: {expected_asset_name}")

    except requests.exceptions.RequestException as e:
        print(f"Error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()