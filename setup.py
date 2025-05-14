from setuptools import setup, find_packages
import sys
import os
import platform
import shutil
from pathlib import Path

# Define platform to library extension mapping (for reference only)
PLATFORM_EXTENSIONS = {
    'win_amd64': 'dll',
    'win_arm64': 'dll',
    'macosx_x86_64': 'dylib',
    'apple-darwin': 'dylib', # we need to update the published keys
    'linux_x86_64': 'so',
    'linux_aarch64': 'so',
}

# Directory structure
ARTIFACTS_DIR = Path('artifacts')  # Where downloaded libraries are stored
PACKAGE_LIBS_DIR = Path('src/c2pa/libs')  # Where libraries will be copied for the wheel

def get_current_platform():
    """Determine the current platform name."""
    if sys.platform == "win32":
        if platform.machine() == "ARM64":
            return "win_arm64"
        return "win_amd64"
    elif sys.platform == "darwin":
        if platform.machine() == "arm64":
            return "macosx_aarch64"
        return "macosx_x86_64"
    else:  # Linux
        if platform.machine() == "aarch64":
            return "linux_aarch64"
        return "linux_x86_64"

def copy_platform_libraries(platform_name, clean_first=False):
    """Copy libraries for a specific platform to the package libs directory.

    Args:
        platform_name: The platform to copy libraries for
        clean_first: If True, remove existing files in PACKAGE_LIBS_DIR first
    """
    platform_dir = ARTIFACTS_DIR / platform_name

    # Ensure the platform directory exists and contains files
    if not platform_dir.exists():
        raise ValueError(f"Platform directory not found: {platform_dir}")

    # Get list of all files in the platform directory
    platform_files = list(platform_dir.glob('*'))
    if not platform_files:
        raise ValueError(f"No files found in platform directory: {platform_dir}")

    # Clean and recreate the package libs directory if requested
    if clean_first and PACKAGE_LIBS_DIR.exists():
        shutil.rmtree(PACKAGE_LIBS_DIR)

    # Ensure the package libs directory exists
    PACKAGE_LIBS_DIR.mkdir(parents=True, exist_ok=True)

    # Copy files from platform-specific directory to the package libs directory
    for file in platform_files:
        if file.is_file():
            shutil.copy2(file, PACKAGE_LIBS_DIR / file.name)

def get_platform_classifier(platform_name):
    """Get the appropriate classifier for a platform."""
    if platform_name.startswith('win'):
        return "Operating System :: Microsoft :: Windows"
    elif platform_name.startswith('macosx') or platform_name.startswith('apple-darwin'):
        return "Operating System :: MacOS"
    elif platform_name.startswith('linux'):
        return "Operating System :: POSIX :: Linux"
    else:
        raise ValueError(f"Unknown platform: {platform_name}")

def find_available_platforms():
    """Scan the artifacts directory for available platform-specific libraries."""
    if not ARTIFACTS_DIR.exists():
        raise ValueError(f"Artifacts directory not found: {ARTIFACTS_DIR}")

    available_platforms = []
    for platform_name in PLATFORM_EXTENSIONS.keys():
        platform_dir = ARTIFACTS_DIR / platform_name
        if platform_dir.exists() and any(platform_dir.iterdir()):
            available_platforms.append(platform_name)

    if not available_platforms:
        raise ValueError("No platform-specific libraries found in artifacts directory")

    return available_platforms

# For development installation
if 'develop' in sys.argv or 'install' in sys.argv:
    current_platform = get_current_platform()
    copy_platform_libraries(current_platform)

# For wheel building
if 'bdist_wheel' in sys.argv:
    available_platforms = find_available_platforms()
    print(f"Found libraries for platforms: {', '.join(available_platforms)}")

    for platform_name in available_platforms:
        print(f"\nBuilding wheel for {platform_name}...")
        try:
            # Copy libraries for this platform (cleaning first)
            copy_platform_libraries(platform_name, clean_first=True)

            # Build the wheel
            setup(
                name="c2pa",
                version="1.0.0",
                package_dir={"": "src"},
                packages=find_packages(where="src"),
                include_package_data=True,
                package_data={
                    "c2pa": ["libs/*"],  # Include all files in libs directory
                },
                classifiers=[
                    "Programming Language :: Python :: 3",
                    get_platform_classifier(platform_name),
                ],
            )
        finally:
            # Clean up by removing the package libs directory
            if PACKAGE_LIBS_DIR.exists():
                shutil.rmtree(PACKAGE_LIBS_DIR)
    sys.exit(0)

# For development installation
setup(
    name="c2pa",
    version="1.0.0",
    package_dir={"": "src"},
    packages=find_packages(where="src"),
    include_package_data=True,
    package_data={
        "c2pa": ["libs/*"],  # Include all files in libs directory
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        get_platform_classifier(get_current_platform()),
    ],
)