"""
Library loading utilities

Takes care only on loading the needed compiled library.
"""

import os
import sys
import ctypes
import logging
import platform
from pathlib import Path
from typing import Optional, Tuple
from enum import Enum

# Debug flag for library loading
DEBUG_LIBRARY_LOADING = False

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    force=True  # Force configuration even if already configured
)
logger = logging.getLogger(__name__)


class CPUArchitecture(Enum):
    """CPU architecture enum for platform-specific identifiers."""
    AARCH64 = "aarch64"
    X86_64 = "x86_64"


def get_platform_identifier(cpu_arch: Optional[CPUArchitecture] = None) -> str:
    """Get the full platform identifier (arch-os) for the current system,
    matching the downloaded identifiers used by the Github publisher.

    Args:
        cpu_arch: Optional CPU architecture for macOS.
        If not provided, returns universal build.
        Only used on macOS systems.

    Returns one of:
    - universal-apple-darwin (for Mac, when cpu_arch is None)
    - aarch64-apple-darwin (for Mac ARM64)
    - x86_64-apple-darwin (for Mac x86_64)
    - x86_64-pc-windows-msvc (for Windows 64-bit)
    - x86_64-unknown-linux-gnu (for Linux 64-bit)
    """
    system = platform.system().lower()

    if system == "darwin":
        if cpu_arch is None:
            return "universal-apple-darwin"
        elif cpu_arch == CPUArchitecture.AARCH64:
            return "aarch64-apple-darwin"
        elif cpu_arch == CPUArchitecture.X86_64:
            return "x86_64-apple-darwin"
        else:
            raise ValueError(
                f"Unsupported CPU architecture for macOS: {cpu_arch}")
    elif system == "windows":
        return "x86_64-pc-windows-msvc"
    elif system == "linux":
        return "x86_64-unknown-linux-gnu"
    else:
        raise ValueError(f"Unsupported operating system: {system}")


def _get_architecture() -> str:
    """
    Get the current system architecture.

    Returns:
        The system architecture (e.g., 'arm64', 'x86_64', ...)
    """
    if sys.platform == "darwin":
        # On macOS, we need to check if we're running under Rosetta
        if platform.processor() == 'arm':
            return 'arm64'
        else:
            return 'x86_64'
    elif sys.platform == "linux":
        return platform.machine()
    elif sys.platform == "win32":
        # win32 will cover all Windows versions (the 32 is a historical quirk)
        return platform.machine()
    else:
        raise RuntimeError(f"Unsupported platform: {sys.platform}")


def _get_platform_dir() -> str:
    """
    Get the platform-specific directory name.

    Returns:
        The platform-specific directory name
    """
    if sys.platform == "darwin":
        return "apple-darwin"
    elif sys.platform == "linux":
        return "unknown-linux-gnu"
    elif sys.platform == "win32":
        # win32 will cover all Windows versions (the 32 is a historical quirk)
        return "pc-windows-msvc"
    else:
        raise RuntimeError(f"Unsupported platform: {sys.platform}")


def _load_single_library(lib_name: str,
                         search_paths: list[Path]) -> Optional[ctypes.CDLL]:
    """
    Load a single library from the given search paths.

    Args:
        lib_name: Name of the library to load
        search_paths: List of paths to search for the library

    Returns:
        The loaded library or None if loading failed
    """
    if DEBUG_LIBRARY_LOADING:
        logger.info(f"Searching for library '{lib_name}' in paths: {[str(p) for p in search_paths]}")
    current_arch = _get_architecture()
    if DEBUG_LIBRARY_LOADING:
        logger.info(f"Current architecture: {current_arch}")

    for path in search_paths:
        lib_path = path / lib_name
        if DEBUG_LIBRARY_LOADING:
            logger.info(f"Checking path: {lib_path}")
        if lib_path.exists():
            if DEBUG_LIBRARY_LOADING:
                logger.info(f"Found library at: {lib_path}")
            try:
                return ctypes.CDLL(str(lib_path))
            except Exception as e:
                error_msg = str(e)
                if "incompatible architecture" in error_msg:
                    logger.error(f"Architecture mismatch: Library at {lib_path} is not compatible with current architecture {current_arch}")
                    logger.error(f"Error details: {error_msg}")
                else:
                    logger.error(f"Failed to load library from {lib_path}: {e}")
        else:
            logger.debug(f"Library not found at: {lib_path}")
    return None


def _get_possible_search_paths() -> list[Path]:
    """
    Get a list of possible paths where the library might be located.

    Returns:
        List of Path objects representing possible library locations
    """
    # Get platform-specific directory and identifier
    platform_dir = _get_platform_dir()
    platform_id = get_platform_identifier()

    if DEBUG_LIBRARY_LOADING:
        logger.info(f"Using platform directory: {platform_dir}")
        logger.info(f"Using platform identifier: {platform_id}")

    # Base paths without platform-specific subdirectories
    base_paths = [
        # Current directory
        Path.cwd(),
        # Artifacts directory at root of repo
        Path.cwd() / "artifacts",
        # Libs directory at root of repo
        Path.cwd() / "libs",
        # Package directory (usually for local dev)
        Path(__file__).parent,
        # Additional library directory (usually for local dev)
        Path(__file__).parent / "libs",
    ]

    # Create the full list of paths including platform-specific subdirectories
    possible_paths = []
    for base_path in base_paths:
        # Add the base path
        possible_paths.append(base_path)
        # Add platform directory subfolder
        possible_paths.append(base_path / platform_dir)
        # Add platform identifier subfolder
        possible_paths.append(base_path / platform_id)

    # Add system library paths
    possible_paths.extend([Path(p) for p in os.environ.get(
        "LD_LIBRARY_PATH", "").split(os.pathsep) if p])

    return possible_paths


def dynamically_load_library(
        lib_name: Optional[str] = None) -> Optional[ctypes.CDLL]:
    """
    Load the dynamic library containing the C-API based on the platform.

    Args:
        lib_name: Optional specific library name to load. If provided, only this library will be loaded.
        This enables to potentially load wrapper libraries of the C-API that may have an other name
        (the presence of required symbols will nevertheless be verified once the library is loaded).

    Returns:
        The loaded library or None if loading failed
    """
    if sys.platform == "darwin":
        c2pa_lib_name = "libc2pa_c.dylib"
    elif sys.platform == "linux":
        c2pa_lib_name = "libc2pa_c.so"
    elif sys.platform == "win32":
        c2pa_lib_name = "c2pa_c.dll"
    else:
        raise RuntimeError(f"Unsupported platform: {sys.platform}")

    if DEBUG_LIBRARY_LOADING:
        logger.info(f"Current working directory: {Path.cwd()}")
        logger.info(f"Package directory: {Path(__file__).parent}")
        logger.info(f"System architecture: {_get_architecture()}")

    # Check for C2PA_LIBRARY_NAME environment variable
    env_lib_name = os.environ.get("C2PA_LIBRARY_NAME")
    if env_lib_name:
        if DEBUG_LIBRARY_LOADING:
            logger.info(
                f"Using library name from env var C2PA_LIBRARY_NAME: {env_lib_name}")
        try:
            possible_paths = _get_possible_search_paths()
            lib = _load_single_library(env_lib_name, possible_paths)
            if lib:
                return lib
            else:
                logger.error(f"Could not find library {env_lib_name} in any of the search paths")
                # Continue with normal loading if environment variable library
                # name fails
        except Exception as e:
            logger.error(f"Failed to load library from C2PA_LIBRARY_NAME: {e}")
            # Continue with normal loading if environment variable library name
            # fails

    possible_paths = _get_possible_search_paths()

    if lib_name:
        # If specific library name is provided, only load that one
        lib = _load_single_library(lib_name, possible_paths)
        if not lib:
            logger.error(f"Could not find {lib_name} in any of the search paths: {[str(p) for p in possible_paths]}")
            raise RuntimeError(f"Could not find {lib_name} in any of the search paths")
        return lib

    # Default path (no library name provided in the environment)
    c2pa_lib = _load_single_library(c2pa_lib_name, possible_paths)
    if not c2pa_lib:
        logger.error(f"Could not find {c2pa_lib_name} in any of the search paths: {[str(p) for p in possible_paths]}")
        raise RuntimeError(f"Could not find {c2pa_lib_name} in any of the search paths")

    return c2pa_lib
