"""
Library loading utilities

Takes care only on loading the needed compiled libraries.
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

def dynamically_load_library(lib_name: Optional[str] = None, load_c2pa: bool = True) -> Tuple[Optional[ctypes.CDLL], Optional[ctypes.CDLL]]:
    """
    Load the dynamic libraries based on the platform.

    Args:
        lib_name: Optional specific library name to load. If provided, only this library will be loaded.
        load_c2pa: Whether to load the c2pa library (default: True). Ignored if lib_name is provided.

    Returns:
        Tuple of (adobe_lib, c2pa_lib). If load_c2pa is False or lib_name is provided, c2pa_lib will be None.
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
                return lib, None
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
        Path(__file__).parent / "lib",
        # System library paths
        *[Path(p) for p in os.environ.get("LD_LIBRARY_PATH", "").split(os.pathsep) if p],
    ]

    if lib_name:
        # If specific library name is provided, only load that one
        lib = _load_single_library(lib_name, possible_paths)
        if not lib:
            raise RuntimeError(f"Could not find {lib_name} in any of the search paths")
        return lib

    c2pa_lib = None
    if load_c2pa:
        c2pa_lib = _load_single_library(c2pa_lib_name, possible_paths)
        if not c2pa_lib:
            raise RuntimeError(f"Could not find {c2pa_lib_name} in any of the search paths")

    return c2pa_lib
