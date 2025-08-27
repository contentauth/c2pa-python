from setuptools import setup, find_namespace_packages
import sys
import platform
import shutil
from pathlib import Path
import toml

# Read version from pyproject.toml
def get_version():
    pyproject = toml.load("pyproject.toml")
    return pyproject["project"]["version"]

VERSION = get_version()
PACKAGE_NAME = "c2pa-python"  # Define package name as a constant

# Define platform to library extension mapping (for reference only)
PLATFORM_EXTENSIONS = {
    'win_amd64': 'dll',
    'win_arm64': 'dll',
    'apple-darwin': 'dylib', # universal
    'linux_x86_64': 'so',
    'linux_aarch64': 'so',
}

# Based on what c2pa-rs repo publishes
PLATFORM_FOLDERS = {
    'universal-apple-darwin': 'dylib',
    'x86_64-pc-windows-msvc': 'dll',
    'x86_64-unknown-linux-gnu': 'so',
    'aarch64-unknown-linux-gnu': 'so',
}

# Directory structure
ARTIFACTS_DIR = Path('artifacts')  # Where downloaded libraries are stored
PACKAGE_LIBS_DIR = Path('src/c2pa/libs')  # Where libraries will be copied for the wheel


def detect_arch():
    """Detect the CPU architecture and return the corresponding identifier."""

    if sys.platform == "darwin":
        # On macOS, we need to check if we're running under Rosetta
        # platform.processor() gives us the actual CPU, not the emulated one
        if platform.processor() == 'arm':
            return "aarch64"
        else:
            return "x86_64"
    else:
        # For other platforms, use platform.machine()
        machine = platform.machine().lower()

        # Handle common architecture names
        if machine in ["x86_64", "amd64"]:
            return "x86_64"
        elif machine in ["arm64", "aarch64"]:
            return "aarch64"
        else:
            raise ValueError(f"Unsupported CPU architecture: {machine}")


def get_platform_identifier() -> str:
    """Get a platform identifier (arch-os) for the current system,
    matching downloaded identifiers used by the Github publisher.

    Args:
        Only used on macOS systems.:
            cpu_arch: Optional CPU architecture for macOS. If not provided, returns universal build.

    Returns one of:
    - universal-apple-darwin (for Mac, when CPU arch is None)
    - aarch64-apple-darwin (for Mac ARM64)
    - x86_64-apple-darwin (for Mac Intel)
    - x86_64-pc-windows-msvc (for Windows 64-bit)
    - x86_64-unknown-linux-gnu (for Linux 64-bit)
    - aarch64-unknown-linux-gnu (for Linux ARM64)
    """
    system = platform.system().lower()

    if system == "darwin":
        # Identify the CPU architecture for macOS
        current_arch = detect_arch()
        if current_arch == "aarch64":
            return "aarch64-apple-darwin"
        elif current_arch == "x86_64":
            return "x86_64-apple-darwin"
        else:
            # Fallback to universal if architecture detection fails
            return "universal-apple-darwin"
    elif system == "windows":
        return "x86_64-pc-windows-msvc"
    elif system == "linux":
        if platform.machine() == "aarch64":
            return "aarch64-unknown-linux-gnu"
        return "x86_64-unknown-linux-gnu"
    else:
        raise ValueError(f"Unsupported operating system: {system}")

def get_platform_classifier(platform_name):
    """Get the appropriate classifier for a platform."""
    if platform_name.startswith('win') or platform_name.endswith('windows-msvc'):
        return "Operating System :: Microsoft :: Windows"
    elif platform_name.startswith('macosx') or platform_name.endswith('apple-darwin'):
        return "Operating System :: MacOS"
    elif platform_name.startswith('linux') or platform_name.endswith('linux-gnu'):
        return "Operating System :: POSIX :: Linux"
    else:
        raise ValueError(f"Unknown platform: {platform_name}")

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

def find_available_platforms():
    """Scan the artifacts directory for available platform-specific libraries."""
    if not ARTIFACTS_DIR.exists():
        print(f"Warning: Artifacts directory not found: {ARTIFACTS_DIR}")
        return []

    available_platforms = []
    for platform_name in PLATFORM_FOLDERS.keys():
        platform_dir = ARTIFACTS_DIR / platform_name
        if platform_dir.exists() and any(platform_dir.iterdir()):
            available_platforms.append(platform_name)

    if not available_platforms:
        print("Warning: No platform-specific libraries found in artifacts directory")
        return []

    return available_platforms

# For development installation
if 'develop' in sys.argv or 'install' in sys.argv:
    current_platform = get_platform_identifier()
    print("Installing in development mode for platform ", current_platform)
    copy_platform_libraries(current_platform)

# For wheel building (both bdist_wheel and build)
if 'bdist_wheel' in sys.argv or 'build' in sys.argv:
    available_platforms = find_available_platforms()
    if not available_platforms:
        print("No platform-specific libraries found. Building wheel without platform-specific libraries.")
        setup(
            name=PACKAGE_NAME,
            version=VERSION,
            package_dir={"": "src"},
            packages=find_namespace_packages(where="src"),
            include_package_data=True,
            package_data={
                "c2pa": ["libs/*"],  # Include all files in libs directory
            },
            classifiers=[
                "Programming Language :: Python :: 3",
                get_platform_classifier(get_current_platform()),
            ],
            python_requires=">=3.10",
            long_description=open("README.md").read(),
            long_description_content_type="text/markdown",
            license="MIT OR Apache-2.0",
        )
        sys.exit(0)

    print(f"Found libraries for platforms: {', '.join(available_platforms)}")

    for platform_name in available_platforms:
        print(f"\nBuilding wheel for {platform_name}...")
        try:
            # Copy libraries for this platform (cleaning first)
            copy_platform_libraries(platform_name, clean_first=True)

            # Build the wheel
            setup(
                name=PACKAGE_NAME,
                version=VERSION,
                package_dir={"": "src"},
                packages=find_namespace_packages(where="src"),
                include_package_data=True,
                package_data={
                    "c2pa": ["libs/*"],  # Include all files in libs directory
                },
                classifiers=[
                    "Programming Language :: Python :: 3",
                    get_platform_classifier(platform_name),
                ],
                python_requires=">=3.10",
                long_description=open("README.md").read(),
                long_description_content_type="text/markdown",
                license="MIT OR Apache-2.0",
            )
        finally:
            # Clean up by removing the package libs directory
            if PACKAGE_LIBS_DIR.exists():
                shutil.rmtree(PACKAGE_LIBS_DIR)
    sys.exit(0)

# For sdist and development installation
setup(
    name=PACKAGE_NAME,
    version=VERSION,
    package_dir={"": "src"},
    packages=find_namespace_packages(where="src"),
    include_package_data=True,
    package_data={
        "c2pa": ["libs/*"],  # Include all files in libs directory
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        get_platform_classifier(get_current_platform()),
    ],
    python_requires=">=3.10",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    license="MIT OR Apache-2.0",
)