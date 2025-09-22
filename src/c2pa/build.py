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
import requests  # type: ignore
from pathlib import Path
import zipfile
import io

# Constants
REPO_OWNER = "contentauth"
REPO_NAME = "c2pa-rs"
GITHUB_API_BASE = "https://api.github.com"
ARTIFACTS_DIR = Path("artifacts")


def get_latest_release() -> dict:
    """Get the latest release information from GitHub."""
    url = f"{GITHUB_API_BASE}/repos/{REPO_OWNER}/{REPO_NAME}/releases/latest"
    response = requests.get(url)
    response.raise_for_status()
    return response.json()


def download_artifact(url: str, platform_name: str) -> None:
    """
    Download and extract an artifact
    to the appropriate platform directory.
    """
    print(f"Downloading artifact for {platform_name}...")

    # Create platform directory
    platform_dir = ARTIFACTS_DIR / platform_name
    platform_dir.mkdir(parents=True, exist_ok=True)

    # Download the zip file
    response = requests.get(url)
    response.raise_for_status()

    # Extract the zip file
    with zipfile.ZipFile(io.BytesIO(response.content)) as zip_ref:
        # Extract all files to the platform directory
        zip_ref.extractall(platform_dir)

    print(f"Successfully downloaded and extracted artifacts for {platform_name}")


def download_artifacts() -> None:
    """Main function to download artifacts.
    Can be called as a script or from hatch."""
    try:
        # Create artifacts directory if it doesn't exist
        ARTIFACTS_DIR.mkdir(exist_ok=True)

        # Get latest release
        print("Fetching latest release information...")
        release = get_latest_release()
        print(f"Found release: {release['tag_name']}")

        # Download each asset
        for asset in release['assets']:
            # Skip non-zip files
            if not asset['name'].endswith('.zip'):
                continue

            # Determine platform from asset name
            # Example: c2pa-rs-v1.0.0-macosx-arm64.zip
            platform_name = asset['name'].split('-')[-1].replace('.zip', '')

            # Download and extract the artifact
            download_artifact(asset['browser_download_url'], platform_name)

        print("\nAll artifacts have been downloaded successfully!")

    except requests.exceptions.RequestException as e:
        print(f"Error downloading artifacts: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        sys.exit(1)


def inject_version():
    """Inject the version from pyproject.toml
    into src/c2pa/__init__.py as __version__."""
    import toml  # type: ignore
    pyproject_path = os.path.abspath(
        os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "pyproject.toml"))
    init_path = os.path.abspath(
        os.path.join(
            os.path.dirname(__file__),
            "..",
            "c2pa",
            "__init__.py"))
    with open(pyproject_path, "r") as f:
        pyproject = toml.load(f)
    version = pyproject["project"]["version"]
    # Read and update __init__.py
    lines = []
    if os.path.exists(init_path):
        with open(init_path, "r") as f:
            lines = [line for line in f if not line.startswith("__version__")]
    lines.insert(0, f'__version__ = "{version}"\n')
    with open(init_path, "w") as f:
        f.writelines(lines)


def initialize_build() -> None:
    """Initialize the build process by downloading artifacts."""
    inject_version()
    download_artifacts()


if __name__ == "__main__":
    inject_version()
    download_artifacts()
