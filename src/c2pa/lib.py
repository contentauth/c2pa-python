"""
Library loading utilities

Takes care only on loading the needed compiled library.
"""

import os
import sys
import ctypes
import logging
from pathlib import Path
from typing import Optional, Tuple

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    force=True  # Force configuration even if already configured
)
logger = logging.getLogger(__name__)


def _load_single_library(lib_name: str, search_paths: list[Path]) -> Optional[ctypes.CDLL]:
    """
    Load a single library from the given search paths.

    Args:
        lib_name: Name of the library to load
        search_paths: List of paths to search for the library

    Returns:
        The loaded library or None if loading failed
    """
    for path in search_paths:
        lib_path = path / lib_name
        if lib_path.exists():
            try:
                return ctypes.CDLL(str(lib_path))
            except Exception as e:
                logger.error(f"Failed to load library from {lib_path}: {e}")
    return None

def dynamically_load_library(lib_name: Optional[str] = None) -> Optional[ctypes.CDLL]:
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

    # Check for C2PA_LIBRARY_NAME environment variable
    env_lib_name = os.environ.get("C2PA_LIBRARY_NAME")
    if env_lib_name:
        logger.info(f"Using library name from env var C2PA_LIBRARY_NAME: {env_lib_name}")
        try:
            lib = _load_single_library(env_lib_name, possible_paths)
            if lib:
                return lib
            else:
                logger.error(f"Could not find library {env_lib_name} in any of the search paths")
                # Continue with normal loading if environment variable library name fails
        except Exception as e:
            logger.error(f"Failed to load library from C2PA_LIBRARY_NAME: {e}")
            # Continue with normal loading if environment variable library name fails

    # Try to find the libraries in various locations
    possible_paths = [
        # Current directory
        Path.cwd(),
        # Package directory
        Path(__file__).parent,
        # Additional library directory
        Path(__file__).parent / "libs",
        # System library paths
        *[Path(p) for p in os.environ.get("LD_LIBRARY_PATH", "").split(os.pathsep) if p],
    ]

    if lib_name:
        # If specific library name is provided, only load that one
        lib = _load_single_library(lib_name, possible_paths)
        if not lib:
            raise RuntimeError(f"Could not find {lib_name} in any of the search paths")
        return lib

    # Default path (no library name provided in the environment)
    c2pa_lib = _load_single_library(c2pa_lib_name, possible_paths)
    if not c2pa_lib:
        raise RuntimeError(f"Could not find {c2pa_lib_name} in any of the search paths")

    return c2pa_lib
