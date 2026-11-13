"""File names of the native c2pa library, keyed by sys.platform.

Standard library only: setup.py and scripts/build_local_artifacts.py load
this file by path, because importing the c2pa package loads the library.
"""

import sys

LIBRARY_NAMES = {
    "darwin": "libc2pa_c.dylib",
    "linux": "libc2pa_c.so",
    "win32": "c2pa_c.dll",
}


def get_library_name() -> str:
    """Return the native library file name for the running platform."""
    library_name = LIBRARY_NAMES.get(sys.platform)
    if library_name is None:
        raise RuntimeError(f"Unsupported platform: {sys.platform}")
    return library_name
