#!/usr/bin/env python3

# Copyright 2025 Adobe. All rights reserved.
# This file is licensed to you under the Apache License,
# Version 2.0 (http://www.apache.org/licenses/LICENSE-2.0)
# or the MIT license (http://opensource.org/licenses/MIT),
# at your option.

# Unless required by applicable law or agreed to in writing,
# this software is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR REPRESENTATIONS OF ANY KIND, either express or
# implied. See the LICENSE-MIT and LICENSE-APACHE files for the
# specific language governing permissions and limitations under
# each license.

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

def get_platform_identifier(target_arch=None):
    """Get the full platform identifier (arch-os) for the current system or target.

    Args:
        target_arch: Optional target architecture.
          If provided, overrides auto-detection.
          For macOS: 'universal2', 'arm64', or 'x86_64'
          For Linux: 'aarch64' or 'x86_64'
          For Windows: 'arm64' or 'x64'

    Returns one of:
    - universal-apple-darwin (for macOS universal)
    - aarch64-apple-darwin (for macOS ARM64)
    - x86_64-apple-darwin (for macOS x86_64)
    - x86_64-pc-windows-msvc (for Windows 64-bit)
    - x86_64-unknown-linux-gnu (for Linux x86_64)
    - aarch64-unknown-linux-gnu (for Linux ARM64)
    """
    system = platform.system().lower()
    machine = platform.machine().lower()

    if system == "darwin":
        if target_arch == "arm64":
            return "aarch64-apple-darwin"
        elif target_arch == "x86_64":
            return "x86_64-apple-darwin"
        elif target_arch == "universal2":
            return "universal-apple-darwin"
        else:
            # Auto-detect: prefer specific architecture over universal
            if machine == "arm64":
                return "aarch64-apple-darwin"
            elif machine == "x86_64":
                return "x86_64-apple-darwin"
            else:
                return "universal-apple-darwin"
    elif system == "windows":
        if target_arch == "arm64":
            return "aarch64-pc-windows-msvc"
        else:
            return "x86_64-pc-windows-msvc"
    elif system == "linux":
        if target_arch == "aarch64" or machine in ["arm64", "aarch64"]:
            return "aarch64-unknown-linux-gnu"
        else:
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

    print(f"Downloaded zip file, extracting lib files...")
    with zipfile.ZipFile(io.BytesIO(response.content)) as zip_ref:
        # Extract only files inside the libs/ directory
        extracted_count = 0
        for member in zip_ref.namelist():
            if member.startswith("lib/") and not member.endswith("/"):
                target_path = platform_dir / os.path.relpath(member, "lib")
                target_path.parent.mkdir(parents=True, exist_ok=True)
                with zip_ref.open(member) as source, open(target_path, "wb") as target:
                    target.write(source.read())
                extracted_count += 1
                print(f"  Extracted: {member} -> {target_path}")

    print(f"Done downloading and extracting {extracted_count} library files for {platform_name}")

def copy_artifacts_to_root():
    """Copy the artifacts folder from scripts/artifacts to the root of the repository."""
    if not SCRIPTS_ARTIFACTS_DIR.exists():
        print("No artifacts found in scripts/artifacts")
        return

    print("Copying artifacts from scripts/artifacts to root...")
    print("Contents of scripts/artifacts before copying:")
    for item in sorted(SCRIPTS_ARTIFACTS_DIR.iterdir()):
        print(f"  {item.name}")
    
    if ROOT_ARTIFACTS_DIR.exists():
        shutil.rmtree(ROOT_ARTIFACTS_DIR)
    print(f"Copying from {SCRIPTS_ARTIFACTS_DIR} to {ROOT_ARTIFACTS_DIR}")
    shutil.copytree(SCRIPTS_ARTIFACTS_DIR, ROOT_ARTIFACTS_DIR)
    print("Done copying artifacts")
    print("\nFolder content of root artifacts directory:")
    for item in sorted(ROOT_ARTIFACTS_DIR.iterdir()):
        print(f"  {item.name}")

def main():
    if len(sys.argv) < 2:
        print("Usage: python download_artifacts.py <release_tag> [target_architecture]")
        print("Example: python download_artifacts.py c2pa-v0.49.5")
        print("Example: python download_artifacts.py c2pa-v0.49.5 arm64")
        sys.exit(1)

    release_tag = sys.argv[1]
    target_arch = sys.argv[2] if len(sys.argv) > 2 else None

    try:
        # Clean up any existing artifacts before starting
        print("Cleaning up existing artifacts...")
        if SCRIPTS_ARTIFACTS_DIR.exists():
            shutil.rmtree(SCRIPTS_ARTIFACTS_DIR)
        SCRIPTS_ARTIFACTS_DIR.mkdir(exist_ok=True)
        print(f"Fetching release information for tag {release_tag}...")
        release = get_release_by_tag(release_tag)
        print(f"Found release: {release['tag_name']} \n")

        # Get the platform identifier for the target architecture
        env_platform = os.environ.get("C2PA_LIBS_PLATFORM")
        if env_platform:
            print(f"Using platform from environment variable C2PA_LIBS_PLATFORM: {env_platform}")
            platform_id = env_platform
        else:
            platform_id = get_platform_identifier(target_arch)
            print(f"Using target architecture: {target_arch or 'auto-detected'}")
            print(f"Detected machine architecture: {platform.machine()}")
            print(f"Detected system: {platform.system()}")

        print("Looking up releases for platform id: ", platform_id)
        platform_source = "environment variable" if env_platform else "target architecture" if target_arch else "auto-detection"
        print(f"Target platform: {platform_id} (set through {platform_source})")

        # Construct the expected asset name
        expected_asset_name = f"{release_tag}-{platform_id}.zip"
        print(f"Looking for asset: {expected_asset_name}")

        # Find the matching asset in the release
        matching_asset = None
        print(f"Looking for asset: {expected_asset_name}")
        print("Available assets in release:")
        for asset in release['assets']:
            print(f"  - {asset['name']}")
            if asset['name'] == expected_asset_name:
                matching_asset = asset
                print(f"Using native library: {matching_asset['name']}")

        if matching_asset:
            print(f"\nDownloading asset: {matching_asset['name']}")
            download_and_extract_libs(matching_asset['browser_download_url'], platform_id)
            print("\nArtifacts have been downloaded and extracted successfully!")
            copy_artifacts_to_root()
        else:
            print(f"\nNo matching asset found for platform: {platform_id}")
            print(f"Expected asset name: {expected_asset_name}")
            print("Please check if the asset exists in the release or if the platform identifier is correct.")

    except requests.exceptions.RequestException as e:
        print(f"Error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()