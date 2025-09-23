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

import ctypes
import enum
import json
import logging
import sys
import os
import warnings
from pathlib import Path
from typing import Optional, Union, Callable, Any, overload
import io
from .lib import dynamically_load_library
import mimetypes
from itertools import count

# Create a module-specific logger
logger = logging.getLogger("c2pa")
logger.addHandler(logging.NullHandler())

# Define required function names
_REQUIRED_FUNCTIONS = [
    'c2pa_version',
    'c2pa_error',
    'c2pa_string_free',
    'c2pa_load_settings',
    'c2pa_read_file',
    'c2pa_read_ingredient_file',
    'c2pa_reader_from_stream',
    'c2pa_reader_from_manifest_data_and_stream',
    'c2pa_reader_free',
    'c2pa_reader_json',
    'c2pa_reader_resource_to_stream',
    'c2pa_builder_from_json',
    'c2pa_builder_from_archive',
    'c2pa_builder_free',
    'c2pa_builder_set_no_embed',
    'c2pa_builder_set_remote_url',
    'c2pa_builder_add_resource',
    'c2pa_builder_add_ingredient_from_stream',
    'c2pa_builder_to_archive',
    'c2pa_builder_sign',
    'c2pa_manifest_bytes_free',
    'c2pa_builder_data_hashed_placeholder',
    'c2pa_builder_sign_data_hashed_embeddable',
    'c2pa_format_embeddable',
    'c2pa_signer_create',
    'c2pa_signer_from_info',
    'c2pa_signer_reserve_size',
    'c2pa_signer_free',
    'c2pa_ed25519_sign',
    'c2pa_signature_free',
    'c2pa_free_string_array',
    'c2pa_reader_supported_mime_types',
    'c2pa_builder_supported_mime_types',
]

# TODO Bindings:
# c2pa_reader_is_embedded
# c2pa_reader_remote_url


def _validate_library_exports(lib):
    """Validate that all required functions are present in the loaded library.

    This validation is crucial for several security and reliability reasons:

    1. Security:
       - Prevents loading of libraries that might be missing critical functions
       - Ensures the library has expected functionality before code execution
       - Helps detect tampered or incomplete libraries

    2. Reliability:
       - Fails fast if the library is incomplete or corrupted
       - Prevents runtime errors from missing functions
       - Ensures all required functionality is available before use

    3. Version Compatibility:
       - Helps detect version mismatches where the library
          doesn't have all expected functions
       - Prevents partial functionality that could lead to undefined behavior
       - Ensures the library matches the expected API version

    Args:
        lib: The loaded library object

    Raises:
        ImportError: If any required function is missing,
                    with a detailed message listing
                    the missing functions. This helps diagnose issues
                    with the library installation or version compatibility.
    """
    missing_functions = []
    for func_name in _REQUIRED_FUNCTIONS:
        if not hasattr(lib, func_name):  # pragma: no cover
            missing_functions.append(func_name)

    if missing_functions:  # pragma: no cover
        raise ImportError(
            f"Library is missing required function symbols: "
            f"{', '.join(missing_functions)}\n"
            "This could indicate an incomplete or corrupted library "
            "installation or a version mismatch between the library "
            "and this Python wrapper."
        )


# Determine the library name based on the platform
if sys.platform == "win32":  # pragma: no cover
    _lib_name_default = "c2pa_c.dll"
elif sys.platform == "darwin":  # pragma: no cover
    _lib_name_default = "libc2pa_c.dylib"
else:  # pragma: no cover
    _lib_name_default = "libc2pa_c.so"

# Check for C2PA_LIBRARY_NAME environment variable
env_lib_name = os.environ.get("C2PA_LIBRARY_NAME")
if env_lib_name:  # pragma: no cover
    # Use the environment variable library name
    _lib = dynamically_load_library(env_lib_name)
else:
    # Use the platform-specific name
    _lib = dynamically_load_library(_lib_name_default)

_validate_library_exports(_lib)


class C2paSeekMode(enum.IntEnum):
    """Seek mode for stream operations."""
    START = 0
    CURRENT = 1
    END = 2


class C2paSigningAlg(enum.IntEnum):
    """Supported signing algorithms."""
    ES256 = 0
    ES384 = 1
    ES512 = 2
    PS256 = 3
    PS384 = 4
    PS512 = 5
    ED25519 = 6


# Mapping from C2paSigningAlg enum to string representation,
# as the enum value currently maps by default to an integer value.
_ALG_TO_STRING_BYTES_MAPPING = {
    C2paSigningAlg.ES256: b"es256",
    C2paSigningAlg.ES384: b"es384",
    C2paSigningAlg.ES512: b"es512",
    C2paSigningAlg.PS256: b"ps256",
    C2paSigningAlg.PS384: b"ps384",
    C2paSigningAlg.PS512: b"ps512",
    C2paSigningAlg.ED25519: b"ed25519",
}


# Define callback types
ReadCallback = ctypes.CFUNCTYPE(
    ctypes.c_ssize_t,
    ctypes.c_void_p,
    ctypes.POINTER(
        ctypes.c_uint8),
    ctypes.c_ssize_t)
SeekCallback = ctypes.CFUNCTYPE(
    ctypes.c_ssize_t,
    ctypes.c_void_p,
    ctypes.c_ssize_t,
    ctypes.c_int)

# Additional callback types
WriteCallback = ctypes.CFUNCTYPE(
    ctypes.c_ssize_t,
    ctypes.c_void_p,
    ctypes.POINTER(
        ctypes.c_uint8),
    ctypes.c_ssize_t)
FlushCallback = ctypes.CFUNCTYPE(ctypes.c_ssize_t, ctypes.c_void_p)
SignerCallback = ctypes.CFUNCTYPE(
    ctypes.c_ssize_t, ctypes.c_void_p, ctypes.POINTER(
        ctypes.c_ubyte), ctypes.c_size_t, ctypes.POINTER(
            ctypes.c_ubyte), ctypes.c_size_t)


class StreamContext(ctypes.Structure):
    """Opaque structure for stream context."""
    _fields_ = []  # Empty as it's opaque in the C API


class C2paSigner(ctypes.Structure):
    """Opaque structure for signer context."""
    _fields_ = []  # Empty as it's opaque in the C API


class C2paStream(ctypes.Structure):
    """A C2paStream is a Rust Read/Write/Seek stream that can be created in C.

    This class represents a low-level stream interface that bridges Python
    and Rust/C code. It implements the Rust Read/Write/Seek traits in C,
    allowing for efficient data transfer between Python and the C2PA library
    without unnecessary copying.

    The stream is used for various operations including:
    - Reading manifest data from files
    - Writing signed content to files
    - Handling binary resources
    - Managing ingredient data

    The structure contains function pointers that implement stream operations:
    - reader: Function to read data from the stream
    - seeker: Function to change the stream position
    - writer: Function to write data to the stream
    - flusher: Function to flush any buffered data

    This is a critical component for performance as it allows direct memory
    access between Python and the C2PA library without intermediate copies.
    """
    _fields_ = [
        # Opaque context pointer for the stream
        ("context", ctypes.POINTER(StreamContext)),
        # Function to read data from the stream
        ("reader", ReadCallback),
        # Function to change stream position
        ("seeker", SeekCallback),
        # Function to write data to the stream
        ("writer", WriteCallback),
        # Function to flush buffered data
        ("flusher", FlushCallback),
    ]


class C2paSignerInfo(ctypes.Structure):
    """Configuration for a Signer."""
    _fields_ = [
        ("alg", ctypes.c_char_p),
        ("sign_cert", ctypes.c_char_p),
        ("private_key", ctypes.c_char_p),
        ("ta_url", ctypes.c_char_p),
    ]

    def __init__(self, alg, sign_cert, private_key, ta_url):
        """Initialize C2paSignerInfo with optional parameters.

        Args:
            alg: The signing algorithm, either as a
            C2paSigningAlg enum or string or bytes
            (will be converted accordingly to bytes for native library use)
            sign_cert: The signing certificate as a string
            private_key: The private key as a string
            ta_url: The timestamp authority URL as bytes
        """

        if sign_cert is None:
            raise ValueError("sign_cert must be set")
        if private_key is None:
            raise ValueError("private_key must be set")

        # Handle alg parameter: can be C2paSigningAlg enum
        # or string (or bytes), convert as needed
        if isinstance(alg, C2paSigningAlg):
            # Convert enum to string representation
            alg_str = _ALG_TO_STRING_BYTES_MAPPING.get(alg)
            if alg_str is None:
                raise ValueError(f"Unsupported signing algorithm: {alg}")
            alg = alg_str
        elif isinstance(alg, str):
            # String to bytes, as requested by native lib
            alg = alg.encode('utf-8')
        elif isinstance(alg, bytes):
            # In bytes already
            pass
        else:
            raise TypeError(
                f"alg must be C2paSigningAlg enum, string, or bytes, "
                f"got {type(alg)}"
            )

        # Handle ta_url parameter:
        # allow string or bytes, convert string to bytes as needed
        if isinstance(ta_url, str):
            # String to bytes, as requested by native lib
            ta_url = ta_url.encode('utf-8')
        elif isinstance(ta_url, bytes):
            # In bytes already
            pass
        else:
            raise TypeError(
                f"ta_url must be string or bytes, got {type(ta_url)}"
            )

        # Call parent constructor with processed values
        super().__init__(alg, sign_cert, private_key, ta_url)


class C2paReader(ctypes.Structure):
    """Opaque structure for reader context."""
    _fields_ = []  # Empty as it's opaque in the C API


class C2paBuilder(ctypes.Structure):
    """Opaque structure for builder context."""
    _fields_ = []  # Empty as it's opaque in the C API

# Helper function to set function prototypes


def _setup_function(func, argtypes, restype=None):
    func.argtypes = argtypes
    func.restype = restype


# Set up function prototypes (some may need the types defined above)
_setup_function(_lib.c2pa_create_stream,
                [ctypes.POINTER(StreamContext),
                 ReadCallback,
                 SeekCallback,
                 WriteCallback,
                 FlushCallback],
                ctypes.POINTER(C2paStream))

# Add release_stream prototype
_setup_function(
    _lib.c2pa_release_stream,
    [ctypes.POINTER(C2paStream)],
    None
)

# Set up function prototypes not attached to an API object
_setup_function(_lib.c2pa_version, [], ctypes.c_void_p)
_setup_function(_lib.c2pa_error, [], ctypes.c_void_p)
_setup_function(_lib.c2pa_string_free, [ctypes.c_void_p], None)
_setup_function(
    _lib.c2pa_load_settings, [
        ctypes.c_char_p, ctypes.c_char_p], ctypes.c_int)
_setup_function(
    _lib.c2pa_free_string_array,
    [ctypes.POINTER(ctypes.c_char_p), ctypes.c_size_t],
    None
)

# Set up Reader function prototypes
_setup_function(_lib.c2pa_reader_from_stream,
                [ctypes.c_char_p, ctypes.POINTER(C2paStream)],
                ctypes.POINTER(C2paReader))
_setup_function(
    _lib.c2pa_reader_from_manifest_data_and_stream, [
        ctypes.c_char_p, ctypes.POINTER(C2paStream), ctypes.POINTER(
            ctypes.c_ubyte), ctypes.c_size_t], ctypes.POINTER(C2paReader))
_setup_function(_lib.c2pa_reader_free, [ctypes.POINTER(C2paReader)], None)
_setup_function(
    _lib.c2pa_reader_json, [
        ctypes.POINTER(C2paReader)], ctypes.c_void_p)
_setup_function(_lib.c2pa_reader_resource_to_stream, [ctypes.POINTER(
    C2paReader), ctypes.c_char_p, ctypes.POINTER(C2paStream)], ctypes.c_int64)
_setup_function(
    _lib.c2pa_reader_supported_mime_types,
    [ctypes.POINTER(ctypes.c_size_t)],
    ctypes.POINTER(ctypes.c_char_p)
)

# Set up Builder function prototypes
_setup_function(
    _lib.c2pa_builder_from_json, [
        ctypes.c_char_p], ctypes.POINTER(C2paBuilder))
_setup_function(_lib.c2pa_builder_from_archive,
                [ctypes.POINTER(C2paStream)],
                ctypes.POINTER(C2paBuilder))
_setup_function(_lib.c2pa_builder_free, [ctypes.POINTER(C2paBuilder)], None)
_setup_function(_lib.c2pa_builder_set_no_embed, [
                ctypes.POINTER(C2paBuilder)], None)
_setup_function(
    _lib.c2pa_builder_set_remote_url, [
        ctypes.POINTER(C2paBuilder), ctypes.c_char_p], ctypes.c_int)
_setup_function(_lib.c2pa_builder_add_resource, [ctypes.POINTER(
    C2paBuilder), ctypes.c_char_p, ctypes.POINTER(C2paStream)], ctypes.c_int)
_setup_function(_lib.c2pa_builder_add_ingredient_from_stream,
                [ctypes.POINTER(C2paBuilder),
                 ctypes.c_char_p,
                 ctypes.c_char_p,
                 ctypes.POINTER(C2paStream)],
                ctypes.c_int)
_setup_function(_lib.c2pa_builder_to_archive,
                [ctypes.POINTER(C2paBuilder), ctypes.POINTER(C2paStream)],
                ctypes.c_int)
_setup_function(_lib.c2pa_builder_sign,
                [ctypes.POINTER(C2paBuilder),
                 ctypes.c_char_p,
                 ctypes.POINTER(C2paStream),
                 ctypes.POINTER(C2paStream),
                 ctypes.POINTER(C2paSigner),
                 ctypes.POINTER(ctypes.POINTER(ctypes.c_ubyte))],
                ctypes.c_int64)
_setup_function(
    _lib.c2pa_manifest_bytes_free, [
        ctypes.POINTER(
            ctypes.c_ubyte)], None)
_setup_function(
    _lib.c2pa_builder_data_hashed_placeholder, [
        ctypes.POINTER(C2paBuilder), ctypes.c_size_t, ctypes.c_char_p,
        ctypes.POINTER(ctypes.POINTER(ctypes.c_ubyte))
    ],
    ctypes.c_int64,
)
_setup_function(_lib.c2pa_builder_sign_data_hashed_embeddable,
                [ctypes.POINTER(C2paBuilder),
                 ctypes.POINTER(C2paSigner),
                 ctypes.c_char_p,
                 ctypes.c_char_p,
                 ctypes.POINTER(C2paStream),
                 ctypes.POINTER(ctypes.POINTER(ctypes.c_ubyte))],
                ctypes.c_int64)
_setup_function(
    _lib.c2pa_format_embeddable, [
        ctypes.c_char_p, ctypes.POINTER(
            ctypes.c_ubyte), ctypes.c_size_t, ctypes.POINTER(
                ctypes.POINTER(
                    ctypes.c_ubyte))], ctypes.c_int64)
_setup_function(_lib.c2pa_signer_create,
                [ctypes.c_void_p,
                 SignerCallback,
                 ctypes.c_int,
                 ctypes.c_char_p,
                 ctypes.c_char_p],
                ctypes.POINTER(C2paSigner))
_setup_function(_lib.c2pa_signer_from_info,
                [ctypes.POINTER(C2paSignerInfo)],
                ctypes.POINTER(C2paSigner))
_setup_function(
    _lib.c2pa_read_file, [
        ctypes.c_char_p, ctypes.c_char_p], ctypes.c_void_p)
_setup_function(
    _lib.c2pa_read_ingredient_file, [
        ctypes.c_char_p, ctypes.c_char_p], ctypes.c_void_p)

# Set up Signer function prototypes
_setup_function(
    _lib.c2pa_signer_reserve_size, [
        ctypes.POINTER(C2paSigner)], ctypes.c_int64)
_setup_function(_lib.c2pa_signer_free, [ctypes.POINTER(C2paSigner)], None)
_setup_function(
    _lib.c2pa_ed25519_sign, [
        ctypes.POINTER(
            ctypes.c_ubyte), ctypes.c_size_t, ctypes.c_char_p], ctypes.POINTER(
                ctypes.c_ubyte))
_setup_function(
    _lib.c2pa_signature_free, [
        ctypes.POINTER(
            ctypes.c_ubyte)], None)
_setup_function(
    _lib.c2pa_builder_supported_mime_types,
    [ctypes.POINTER(ctypes.c_size_t)],
    ctypes.POINTER(ctypes.c_char_p)
)


class C2paError(Exception):
    """Exception raised for C2PA errors."""

    def __init__(self, message: str = ""):
        self.message = message
        super().__init__(message)

    class Assertion(Exception):
        """Exception raised for assertion errors."""
        pass

    class AssertionNotFound(Exception):
        """Exception raised when an assertion is not found."""
        pass

    class Decoding(Exception):
        """Exception raised for decoding errors."""
        pass

    class Encoding(Exception):
        """Exception raised for encoding errors."""
        pass

    class FileNotFound(Exception):
        """Exception raised when a file is not found."""
        pass

    class Io(Exception):
        """Exception raised for IO errors."""
        pass

    class Json(Exception):
        """Exception raised for JSON errors."""
        pass

    class Manifest(Exception):
        """Exception raised for manifest errors."""
        pass

    class ManifestNotFound(Exception):
        """Exception raised when a manifest is not found."""
        pass

    class NotSupported(Exception):
        """Exception raised for unsupported operations."""
        pass

    class Other(Exception):
        """Exception raised for other errors."""
        pass

    class RemoteManifest(Exception):
        """Exception raised for remote manifest errors."""
        pass

    class ResourceNotFound(Exception):
        """Exception raised when a resource is not found."""
        pass

    class Signature(Exception):
        """Exception raised for signature errors."""
        pass

    class Verify(Exception):
        """Exception raised for verification errors."""
        pass


class _StringContainer:
    """Container class to hold encoded strings,
    and prevent them from being garbage collected.

    This class is used to store encoded strings
    that need to remain in memory while being used by C functions.
    The strings are stored as instance attributes,
    to prevent them from being garbage collected.

    This is an internal implementation detail
    and should not be used outside this module.
    """

    def __init__(self):
        """Initialize an empty string container."""
        self._path_str = ""
        self._data_dir_str = ""


def _convert_to_py_string(value) -> str:
    if value is None:
        return ""

    py_string = ""

    # Validate pointer before casting and freeing
    if not isinstance(value, (int, ctypes.c_void_p)) or value == 0:
        return ""

    try:
        ptr = ctypes.cast(value, ctypes.c_char_p)

        # Only if we got a valid pointer with valid content
        if ptr and ptr.value is not None:
            try:
                py_string = ptr.value.decode('utf-8', errors='strict')
            except Exception:
                py_string = ""
            finally:
                # Only free if we have a valid pointer
                try:
                    _lib.c2pa_string_free(value)
                except Exception:
                    # Ignore clean up issues
                    pass
    except (ctypes.ArgumentError, TypeError, ValueError):
        # Invalid pointer type or value
        return ""

    return py_string


def _parse_operation_result_for_error(
        result: ctypes.c_void_p | None,
        check_error: bool = True) -> Optional[str]:
    """Helper function to handle string results from C2PA functions."""
    if not result:  # pragma: no cover
        if check_error:
            error = _lib.c2pa_error()
            if error:
                error_str = ctypes.cast(
                    error, ctypes.c_char_p).value.decode('utf-8')
                _lib.c2pa_string_free(error)
                parts = error_str.split(' ', 1)
                if len(parts) > 1:
                    error_type, message = parts
                    if error_type == "Assertion":
                        raise C2paError.Assertion(message)
                    elif error_type == "AssertionNotFound":
                        raise C2paError.AssertionNotFound(message)
                    elif error_type == "Decoding":
                        raise C2paError.Decoding(message)
                    elif error_type == "Encoding":
                        raise C2paError.Encoding(message)
                    elif error_type == "FileNotFound":
                        raise C2paError.FileNotFound(message)
                    elif error_type == "Io":
                        raise C2paError.Io(message)
                    elif error_type == "Json":
                        raise C2paError.Json(message)
                    elif error_type == "Manifest":
                        raise C2paError.Manifest(message)
                    elif error_type == "ManifestNotFound":
                        raise C2paError.ManifestNotFound(message)
                    elif error_type == "NotSupported":
                        raise C2paError.NotSupported(message)
                    elif error_type == "Other":
                        raise C2paError.Other(message)
                    elif error_type == "RemoteManifest":
                        raise C2paError.RemoteManifest(message)
                    elif error_type == "ResourceNotFound":
                        raise C2paError.ResourceNotFound(message)
                    elif error_type == "Signature":
                        raise C2paError.Signature(message)
                    elif error_type == "Verify":
                        raise C2paError.Verify(message)
                return error_str
        return None

    # In the case result would be a string already (error message)
    return _convert_to_py_string(result)


def sdk_version() -> str:
    """
    Returns the underlying c2pa-rs/c2pa-c-ffi version string
    """
    vstr = version()
    # Example: "c2pa-c/0.60.1 c2pa-rs/0.60.1"
    for part in vstr.split():
        if part.startswith("c2pa-rs/"):
            return part.split("/", 1)[1]
    # Fallback to full string n case format would change, eg. local builds
    return vstr  # pragma: no cover


def version() -> str:
    """Get the C2PA library version."""
    result = _lib.c2pa_version()
    return _convert_to_py_string(result)


def load_settings(settings: str, format: str = "json") -> None:
    """Load C2PA settings from a string.

    Args:
        settings: The settings string to load
        format: The format of the settings string (default: "json")

    Raises:
        C2paError: If there was an error loading the settings
    """
    result = _lib.c2pa_load_settings(
        settings.encode('utf-8'),
        format.encode('utf-8')
    )
    if result != 0:
        error = _parse_operation_result_for_error(_lib.c2pa_error())
        if error:
            raise C2paError(error)
        raise C2paError("Error loading settings")

    return result


def _get_mime_type_from_path(path: Union[str, Path]) -> str:
    """Attempt to guess the MIME type from a file path (with extension).

    Args:
        path: File path as string or Path object

    Returns:
        MIME type string

    Raises:
        C2paError.NotSupported: If MIME type cannot be determined
    """
    path_obj = Path(path)
    file_extension = path_obj.suffix.lower() if path_obj.suffix else ""

    if file_extension == ".dng":
        # mimetypes guesses the wrong type for dng,
        # so we bypass it and set the correct type
        return "image/dng"
    else:
        mime_type = mimetypes.guess_type(str(path))[0]
        if not mime_type:
            raise C2paError.NotSupported(
                f"Could not determine MIME type for file: {path}")
        return mime_type


def read_ingredient_file(
        path: Union[str, Path], data_dir: Union[str, Path]) -> str:
    """Read a file as C2PA ingredient (deprecated).
    This creates the JSON string that would be used as the ingredient JSON.

    .. deprecated:: 0.11.0
        This function is deprecated and will be removed in a future version.
        To read C2PA metadata, use the :class:`c2pa.c2pa.Reader` class.
        To add ingredients to a manifest,
        use :meth:`c2pa.c2pa.Builder.add_ingredient` instead.

    Args:
        path: Path to the file to read
        data_dir: Directory to write binary resources to

    Returns:
        The ingredient as a JSON string

    Raises:
        C2paError: If there was an error reading the file
    """
    warnings.warn(
        "The read_ingredient_file function is deprecated and will be "
        "removed in a future version. Please use Reader(path).json() for "
        "reading C2PA metadata instead, or "
        "Builder.add_ingredient(json, format, stream) to add ingredients "
        "to a manifest.",
        DeprecationWarning,
        stacklevel=2,
    )

    container = _StringContainer()

    container._path_str = str(path).encode('utf-8')
    container._data_dir_str = str(data_dir).encode('utf-8')

    result = _lib.c2pa_read_ingredient_file(
        container._path_str, container._data_dir_str)

    if result is None:
        error = _parse_operation_result_for_error(_lib.c2pa_error())
        if error:
            raise C2paError(error)
        raise C2paError(
            "Error reading ingredient file {}".format(path)
        )

    return _convert_to_py_string(result)


def read_file(path: Union[str, Path],
              data_dir: Union[str, Path]) -> str:
    """Read a C2PA manifest from a file (deprecated).

    .. deprecated:: 0.10.0
        This function is deprecated and will be removed in a future version.
        To read C2PA metadata, use the :class:`c2pa.c2pa.Reader` class.

    Args:
        path: Path to the file to read
        data_dir: Directory to write binary resources to

    Returns:
        The manifest as a JSON string

    Raises:
        C2paError: If there was an error reading the file
    """
    warnings.warn(
        "The read_file function is deprecated and will be removed in a "
        "future version. Please use the Reader class for reading C2PA "
        "metadata instead.",
        DeprecationWarning,
        stacklevel=2,
    )

    container = _StringContainer()

    container._path_str = str(path).encode('utf-8')
    container._data_dir_str = str(data_dir).encode('utf-8')

    result = _lib.c2pa_read_file(container._path_str, container._data_dir_str)
    if result is None:
        error = _parse_operation_result_for_error(_lib.c2pa_error())
        if error is not None:
            raise C2paError(error)
        raise C2paError.Other(
            "Error during read of manifest from file {}".format(path)
        )

    return _convert_to_py_string(result)


@overload
def sign_file(
    source_path: Union[str, Path],
    dest_path: Union[str, Path],
    manifest: str,
    signer_info: C2paSignerInfo,
    return_manifest_as_bytes: bool = False
) -> Union[str, bytes]:
    """Sign a file with a C2PA manifest using signer info.
    """
    ...


@overload
def sign_file(
    source_path: Union[str, Path],
    dest_path: Union[str, Path],
    manifest: str,
    signer: 'Signer',
    return_manifest_as_bytes: bool = False
) -> Union[str, bytes]:
    """Sign a file with a C2PA manifest using a signer.
    """
    ...


def sign_file(
    source_path: Union[str, Path],
    dest_path: Union[str, Path],
    manifest: str,
    signer_or_info: Union[C2paSignerInfo, 'Signer'],
    return_manifest_as_bytes: bool = False
) -> Union[str, bytes]:
    """Sign a file with a C2PA manifest (deprecated).
    For now, this function is left here to provide a backwards-compatible API.

    .. deprecated:: 0.13.0
        This function is deprecated and will be removed in a future version.
        Use :meth:`Builder.sign` instead.

    Args:
        source_path: Path to the source file. We will attempt
              to guess the mimetype of the source file based on
              the extension.
        dest_path: Path to write the signed file to
        manifest: The manifest JSON string
        signer_or_info: Either a signer configuration or a signer object
        return_manifest_as_bytes: If True, return manifest bytes instead
        of JSON string

    Returns:
        The signed manifest as a JSON string or bytes, depending
        on return_manifest_as_bytes

    Raises:
        C2paError: If there was an error signing the file
        C2paError.Encoding: If any of the string inputs contain
          invalid UTF-8 characters
        C2paError.NotSupported: If the file type cannot be determined
    """

    warnings.warn(
        "The sign_file function is deprecated and will be removed in a "
        "future version. Please use the Builder object and Builder.sign() "
        "instead.",
        DeprecationWarning,
        stacklevel=2,
    )

    try:
        # Determine if we have a signer or signer info
        if isinstance(signer_or_info, C2paSignerInfo):
            signer = Signer.from_info(signer_or_info)
            own_signer = True
        else:
            signer = signer_or_info
            own_signer = False

        # Create a builder from the manifest
        builder = Builder(manifest)

        manifest_bytes = builder.sign_file(
            source_path,
            dest_path,
            signer
        )

        if return_manifest_as_bytes:
            return manifest_bytes
        else:
            # Read the signed manifest from the destination file
            with Reader(dest_path) as reader:
                return reader.json()

    except Exception as e:
        # Clean up destination file if it exists and there was an error
        if os.path.exists(dest_path):
            try:
                os.remove(dest_path)
            except OSError:
                logger.warning("Failed to remove destination file")
                pass  # Ignore cleanup errors

        # Re-raise the error
        raise C2paError(f"Error signing file: {str(e)}") from e
    finally:
        # Ensure resources are cleaned up
        if 'builder' in locals():
            builder.close()
        if 'signer' in locals() and own_signer:
            signer.close()


class Stream:
    # Class-level somewhat atomic counter for generating
    #  unique stream IDs (useful for tracing streams usage in debug)
    _stream_id_counter = count(start=0, step=1)

    # Maximum value for a 32-bit signed integer (2^31 - 1)
    _MAX_STREAM_ID = 2**31 - 1

    # Class-level error messages to avoid multiple creation
    _ERROR_MESSAGES = {
        'stream_error': "Error cleaning up stream: {}",
        'callback_error': "Error cleaning up callback {}: {}",
        'cleanup_error': "Error during cleanup: {}",
        'read': "Stream is closed or not initialized during read operation",
        'memory_error': "Memory error during stream operation: {}",
        'read_error': "Error during read operation: {}",
        'seek': "Stream is closed or not initialized during seek operation",
        'seek_error': "Error during seek operation: {}",
        'write': "Stream is closed or not initialized during write operation",
        'write_error': "Error during write operation: {}",
        'flush': "Stream is closed or not initialized during flush operation",
        'flush_error': "Error during flush operation: {}"
    }

    def __init__(self, file_like_stream):
        """Initialize a new Stream wrapper around a file-like object
        (or an in-memory stream).

        Args:
            file_like_stream: A file-like stream object or an in-memory stream
              that implements read, write, seek, tell, and flush methods

        Raises:
            TypeError: The file stream object doesn't
              implement all required methods
        """
        # Initialize _closed first to prevent AttributeError
        # during garbage collection
        self._closed = False
        self._initialized = False
        self._stream = None

        # Generate unique stream ID using object ID and counter
        stream_counter = next(Stream._stream_id_counter)

        # Handle counter overflow by resetting the counter
        if stream_counter >= Stream._MAX_STREAM_ID:  # pragma: no cover
            # Reset the counter to 0 and get the next value
            Stream._stream_id_counter = count(start=0, step=1)
            stream_counter = next(Stream._stream_id_counter)

        self._stream_id = f"{id(self)}-{stream_counter}"

        # Rest of the existing initialization code...
        required_methods = ['read', 'write', 'seek', 'tell', 'flush']
        missing_methods = [
            method for method in required_methods if not hasattr(
                file_like_stream, method)]
        if missing_methods:
            raise TypeError(
                "Object must be a stream-like object with methods: {}. "
                "Missing: {}".format(
                    ", ".join(required_methods),
                    ", ".join(missing_methods),
                )
            )

        self._file_like_stream = file_like_stream

        def read_callback(ctx, data, length):
            """Callback function for reading data from the Python stream.

            This function is called by C2PA library when it needs to read data.
            It handles:
            - Stream state validation
            - Memory safety
            - Error handling
            - Buffer management

            Args:
                ctx: The stream context (unused)
                data: Pointer to the buffer to read into
                length: Maximum number of bytes to read

            Returns:
                Number of bytes read, or -1 on error
            """
            if not self._initialized or self._closed:
                return -1
            try:
                if not data or length <= 0:
                    return -1

                buffer = self._file_like_stream.read(length)
                if not buffer:  # EOF
                    return 0

                # Ensure we don't write beyond the allocated memory
                actual_length = min(len(buffer), length)
                # Direct memory copy
                ctypes.memmove(data, buffer, actual_length)

                return actual_length
            except Exception:
                return -1

        def seek_callback(ctx, offset, whence):
            """Callback function for seeking in the Python stream.

            This function is called by the C2PA library when it needs to change
            the stream position. It handles:
            - Stream state validation
            - Position validation
            - Error handling

            Args:
                ctx: The stream context (unused)
                offset: The offset to seek to
                whence: The reference point (0=start, 1=current, 2=end)

            Returns:
                New position in the stream, or -1 on error
            """
            file_stream = self._file_like_stream
            if not self._initialized or self._closed:
                return -1
            try:
                file_stream.seek(offset, whence)
                return file_stream.tell()
            except Exception:
                return -1

        def write_callback(ctx, data, length):
            """Callback function for writing data to the Python stream.

            This function is called by C2PA library when needing to write data.
            It handles:
            - Stream state validation
            - Memory safety
            - Error handling
            - Buffer management

            Args:
                ctx: The stream context (unused)
                data: Pointer to the data to write
                length: Number of bytes to write

            Returns:
                Number of bytes written, or -1 on error
            """
            if not self._initialized or self._closed:
                return -1
            try:
                if not data or length <= 0:
                    return -1

                # Create a temporary buffer to safely handle the data
                temp_buffer = (ctypes.c_ubyte * length)()
                try:
                    # Copy data to our temporary buffer
                    ctypes.memmove(temp_buffer, data, length)
                    # Write from our safe buffer
                    self._file_like_stream.write(bytes(temp_buffer))
                    return length
                finally:
                    # Ensure temporary buffer is cleared
                    ctypes.memset(temp_buffer, 0, length)
            except Exception:
                return -1

        def flush_callback(ctx):
            """Callback function for flushing the Python stream.

            This function is called by the C2PA library when it needs to ensure
            all buffered data is written. It handles:
            - Stream state validation
            - Error handling

            Args:
                ctx: The stream context (unused)

            Returns:
                0 on success, -1 on error
            """
            if not self._initialized or self._closed:
                return -1
            try:
                self._file_like_stream.flush()
                return 0
            except Exception:
                return -1

        # Create callbacks that will be kept alive by being instance attributes
        self._read_cb = ReadCallback(read_callback)
        self._seek_cb = SeekCallback(seek_callback)
        self._write_cb = WriteCallback(write_callback)
        self._flush_cb = FlushCallback(flush_callback)

        # Create the stream
        self._stream = _lib.c2pa_create_stream(
            None,
            self._read_cb,
            self._seek_cb,
            self._write_cb,
            self._flush_cb
        )
        if not self._stream:
            error = _parse_operation_result_for_error(_lib.c2pa_error())
            raise Exception("Failed to create stream: {}".format(error))

        self._initialized = True

    def __enter__(self):
        """Context manager entry."""
        if not self._initialized:
            raise RuntimeError("Stream was not properly initialized")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()

    def __del__(self):
        """Ensure resources are cleaned up if close()wasn't called.

        This destructor only cleans up if the object
        hasn't been explicitly closed.
        """
        try:
            # Only cleanup if not already closed and we have a valid stream
            if hasattr(self, '_closed') and not self._closed:
                stream = self._stream
                if hasattr(self, '_stream') and stream:
                    # Use internal cleanup to avoid calling close() which could
                    # cause issues
                    try:
                        _lib.c2pa_release_stream(stream)
                    except Exception:
                        # Destructors shouldn't raise exceptions
                        logger.error("Failed to release Stream")
                        pass
                    finally:
                        self._stream = None
                        self._closed = True
                        self._initialized = False
        except Exception:
            # Destructors must not raise exceptions
            pass

    def close(self):
        """Release the stream resources.

        This method ensures all resources are properly cleaned up,
        even if errors occur during cleanup.
        Errors during cleanup are logged but not raised to ensure cleanup.
        Multiple calls to close() are handled gracefully.
        """
        if self._closed:
            return

        try:
            # Clean up stream first as it depends on callbacks
            # Note: We don't close self._file_like_stream as we don't own it,
            # the opener owns it.
            stream = self._stream
            if stream:
                try:
                    _lib.c2pa_release_stream(stream)
                except Exception as e:
                    logger.error(
                        Stream._ERROR_MESSAGES['stream_error'].format(
                            str(e)))
                finally:
                    self._stream = None

            # Clean up callbacks
            for attr in ['_read_cb', '_seek_cb', '_write_cb', '_flush_cb']:
                if hasattr(self, attr):
                    try:
                        setattr(self, attr, None)
                    except Exception as e:
                        logger.error(
                            Stream._ERROR_MESSAGES['callback_error'].format(
                                attr, str(e)))

        except Exception as e:
            logger.error(
                Stream._ERROR_MESSAGES['cleanup_error'].format(
                    str(e)))
        finally:
            self._closed = True
            self._initialized = False

    def write_to_target(self, dest_stream):
        self._file_like_stream.seek(0)
        dest_stream.write(self._file_like_stream.getvalue())

    @property
    def closed(self) -> bool:
        """Check if the stream is closed.

        Returns:
            bool: True if the stream is closed, False otherwise
        """
        return self._closed

    @property
    def initialized(self) -> bool:
        """Check if the stream is properly initialized.

        Returns:
            bool: True if the stream is initialized, False otherwise
        """
        return self._initialized


class Reader:
    """High-level wrapper for C2PA Reader operations.

    Example:
        ```
        with Reader("image/jpeg", output) as reader:
            manifest_json = reader.json()
        ```
        Where `output` is either an in-memory stream or an opened file.
    """

    # Supported mimetypes cache
    _supported_mime_types_cache = None

    # Class-level error messages to avoid multiple creation
    _ERROR_MESSAGES = {
        'unsupported': "Unsupported format",
        'io_error': "IO error: {}",
        'manifest_error': "Invalid manifest data: must be bytes",
        'reader_error': "Failed to create reader: {}",
        'cleanup_error': "Error during cleanup: {}",
        'stream_error': "Error cleaning up stream: {}",
        'file_error': "Error cleaning up file: {}",
        'reader_cleanup_error': "Error cleaning up reader: {}",
        'encoding_error': "Invalid UTF-8 characters in input: {}",
        'closed_error': "Reader is closed"
    }

    @classmethod
    def get_supported_mime_types(cls) -> list[str]:
        """Get the list of supported MIME types for the Reader.
        This method retrieves supported MIME types from the native library.

        Returns:
            List of supported MIME type strings

        Raises:
            C2paError: If there was an error retrieving the MIME types
        """
        if cls._supported_mime_types_cache is not None:
            return cls._supported_mime_types_cache

        count = ctypes.c_size_t()
        arr = _lib.c2pa_reader_supported_mime_types(ctypes.byref(count))

        # Validate the returned array pointer
        if not arr:
            # If no array returned, check for errors
            error = _parse_operation_result_for_error(_lib.c2pa_error())
            if error:
                raise C2paError(f"Failed to get supported MIME types: {error}")
            # Return empty list if no error but no array
            return []

        # Validate count value
        if count.value <= 0:
            # Free the array even if count is invalid
            try:
                _lib.c2pa_free_string_array(arr, count.value)
            except Exception:
                pass
            return []

        try:
            result = []
            for i in range(count.value):
                try:
                    # Validate each array element before accessing
                    if arr[i] is None:
                        continue

                    mime_type = arr[i].decode("utf-8", errors='replace')
                    if mime_type:
                        result.append(mime_type)
                except Exception:
                    # Ignore cleanup errors
                    continue
        finally:
            # Always free the native memory, even if string extraction fails
            try:
                _lib.c2pa_free_string_array(arr, count.value)
            except Exception:
                # Ignore cleanup errors
                pass

        # Cache the result
        if result:
            cls._supported_mime_types_cache = result

        return cls._supported_mime_types_cache

    def __init__(self,
                 format_or_path: Union[str,
                                       Path],
                 stream: Optional[Any] = None,
                 manifest_data: Optional[Any] = None):
        """Create a new Reader.

        Args:
            format_or_path: The format or path to read from
            stream: Optional stream to read from (Python stream-like object)
            manifest_data: Optional manifest data in bytes

        Raises:
            C2paError: If there was an error creating the reader
            C2paError.Encoding: If any of the string inputs
              contain invalid UTF-8 characters
        """

        self._closed = False
        self._initialized = False

        self._reader = None
        self._own_stream = None

        # This is used to keep track of a file
        # we may have opened ourselves, and that we need to close later
        self._backing_file = None

        if stream is None:
            # If we don't get a stream as param:
            # Create a stream from the file path in format_or_path
            path = str(format_or_path)
            mime_type = _get_mime_type_from_path(path)

            if not mime_type:
                raise C2paError.NotSupported(
                    f"Could not determine MIME type for file: {path}")

            if mime_type not in Reader.get_supported_mime_types():
                raise C2paError.NotSupported(
                    f"Reader does not support {mime_type}")

            try:
                mime_type_str = mime_type.encode('utf-8')
            except UnicodeError as e:
                raise C2paError.Encoding(
                    Reader._ERROR_MESSAGES['encoding_error'].format(
                        str(e)))

            try:
                with open(path, 'rb') as file:
                    self._own_stream = Stream(file)

                    self._reader = _lib.c2pa_reader_from_stream(
                        mime_type_str,
                        self._own_stream._stream
                    )

                    if not self._reader:
                        self._own_stream.close()
                        error = _parse_operation_result_for_error(
                            _lib.c2pa_error())
                        if error:
                            raise C2paError(error)
                        raise C2paError(
                            Reader._ERROR_MESSAGES['reader_error'].format(
                                "Unknown error"
                            )
                        )

                    # Store the file to close it later
                    self._backing_file = file
                    self._initialized = True

            except Exception as e:
                # File automatically closed by context manager
                if self._own_stream:
                    self._own_stream.close()
                if hasattr(self, '_backing_file') and self._backing_file:
                    self._backing_file.close()
                raise C2paError.Io(
                    Reader._ERROR_MESSAGES['io_error'].format(
                        str(e)))
        elif isinstance(stream, str):
            # We may have gotten format + a file path
            # If stream is a string, treat it as a path and try to open it

            # format_or_path is a format
            format_lower = format_or_path.lower()
            if format_lower not in Reader.get_supported_mime_types():
                raise C2paError.NotSupported(
                    f"Reader does not support {format_or_path}")

            try:
                with open(stream, 'rb') as file:
                    self._own_stream = Stream(file)

                    format_str = str(format_or_path)
                    format_bytes = format_str.encode('utf-8')

                    if manifest_data is None:
                        self._reader = _lib.c2pa_reader_from_stream(
                            format_bytes, self._own_stream._stream)
                    else:
                        if not isinstance(manifest_data, bytes):
                            raise TypeError(
                                Reader._ERROR_MESSAGES['manifest_error'])
                        manifest_array = (
                            ctypes.c_ubyte *
                            len(manifest_data))(
                            *
                            manifest_data)
                        self._reader = (
                            _lib.c2pa_reader_from_manifest_data_and_stream(
                                format_bytes,
                                self._own_stream._stream,
                                manifest_array,
                                len(manifest_data),
                            )
                        )

                    if not self._reader:
                        self._own_stream.close()
                        error = _parse_operation_result_for_error(
                            _lib.c2pa_error())
                        if error:
                            raise C2paError(error)
                        raise C2paError(
                            Reader._ERROR_MESSAGES['reader_error'].format(
                                "Unknown error"
                            )
                        )

                    self._backing_file = file
                    self._initialized = True
            except Exception as e:
                # File closed by context manager
                if self._own_stream:
                    self._own_stream.close()
                if hasattr(self, '_backing_file') and self._backing_file:
                    self._backing_file.close()
                raise C2paError.Io(
                    Reader._ERROR_MESSAGES['io_error'].format(
                        str(e)))
        else:
            # format_or_path is a format string
            format_str = str(format_or_path)
            if format_str.lower() not in Reader.get_supported_mime_types():
                raise C2paError.NotSupported(
                    f"Reader does not support {format_str}")

            # Use the provided stream
            self._format_str = format_str.encode('utf-8')

            with Stream(stream) as stream_obj:
                if manifest_data is None:
                    self._reader = _lib.c2pa_reader_from_stream(
                        self._format_str, stream_obj._stream)
                else:
                    if not isinstance(manifest_data, bytes):
                        raise TypeError(
                            Reader._ERROR_MESSAGES['manifest_error'])
                    manifest_array = (
                        ctypes.c_ubyte *
                        len(manifest_data))(
                        *
                        manifest_data)
                    self._reader = (
                        _lib.c2pa_reader_from_manifest_data_and_stream(
                            self._format_str,
                            stream_obj._stream,
                            manifest_array,
                            len(manifest_data)
                        )
                    )

                if not self._reader:
                    error = _parse_operation_result_for_error(
                        _lib.c2pa_error())
                    if error:
                        raise C2paError(error)
                    raise C2paError(
                        Reader._ERROR_MESSAGES['reader_error'].format(
                            "Unknown error"
                        )
                    )

                self._initialized = True

    def __enter__(self):
        self._ensure_valid_state()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def __del__(self):
        """Ensure resources are cleaned up if close() wasn't called.

        This destructor handles cleanup without causing double frees.
        It only cleans up if the object hasn't been explicitly closed.
        """
        self._cleanup_resources()

    def _ensure_valid_state(self):
        """Ensure the reader is in a valid state for operations.

        Raises:
            C2paError: If the reader is closed, not initialized, or invalid
        """
        if self._closed:
            raise C2paError(Reader._ERROR_MESSAGES['closed_error'])
        if not self._initialized:
            raise C2paError("Reader is not properly initialized")
        if not self._reader:
            raise C2paError(Reader._ERROR_MESSAGES['closed_error'])

    def _cleanup_resources(self):
        """Internal cleanup method that releases native resources.

        This method handles the actual cleanup logic and can be called
        from both close() and __del__ without causing double frees.
        """
        try:
            # Only cleanup if not already closed and we have a valid reader
            if hasattr(self, '_closed') and not self._closed:
                self._closed = True

                # Clean up reader
                if hasattr(self, '_reader') and self._reader:
                    try:
                        _lib.c2pa_reader_free(self._reader)
                    except Exception:
                        # Cleanup failure doesn't raise exceptions
                        logger.error(
                            "Failed to free native Reader resources"
                        )
                        pass
                    finally:
                        self._reader = None

                # Clean up stream
                if hasattr(self, '_own_stream') and self._own_stream:
                    try:
                        self._own_stream.close()
                    except Exception:
                        # Cleanup failure doesn't raise exceptions
                        logger.error("Failed to close Reader stream")
                        pass
                    finally:
                        self._own_stream = None

                # Clean up backing file (if needed)
                if self._backing_file:
                    try:
                        self._backing_file.close()
                    except Exception:
                        # Cleanup failure doesn't raise exceptions
                        logger.warning("Failed to close Reader backing file")
                        pass
                    finally:
                        self._backing_file = None

                # Reset initialized state after cleanup
                self._initialized = False

        except Exception:
            # Ensure we don't raise exceptions during cleanup
            pass

    def close(self):
        """Release the reader resources.

        This method ensures all resources are properly cleaned up,
        even if errors occur during cleanup.
        Errors during cleanup are logged but not raised to ensure cleanup.
        Multiple calls to close() are handled gracefully.
        """
        if self._closed:
            return

        try:
            # Use the internal cleanup method
            self._cleanup_resources()
        except Exception as e:
            # Log any unexpected errors during close
            logger.error(
                Reader._ERROR_MESSAGES['cleanup_error'].format(
                    str(e)))
        finally:
            self._closed = True

    def json(self) -> str:
        """Get the manifest store as a JSON string.

        Returns:
            The manifest store as a JSON string

        Raises:
            C2paError: If there was an error getting the JSON
        """

        self._ensure_valid_state()

        result = _lib.c2pa_reader_json(self._reader)

        if result is None:
            error = _parse_operation_result_for_error(_lib.c2pa_error())
            if error:
                raise C2paError(error)
            raise C2paError("Error during manifest parsing in Reader")

        return _convert_to_py_string(result)

    def resource_to_stream(self, uri: str, stream: Any) -> int:
        """Write a resource to a stream.

        Args:
            uri: The URI of the resource to write
            stream: The stream to write to (any Python stream-like object)

        Returns:
            The number of bytes written

        Raises:
            C2paError: If there was an error writing the resource to stream
        """
        self._ensure_valid_state()

        uri_str = uri.encode('utf-8')
        with Stream(stream) as stream_obj:
            result = _lib.c2pa_reader_resource_to_stream(
                self._reader, uri_str, stream_obj._stream)

            if result < 0:
                error = _parse_operation_result_for_error(_lib.c2pa_error())
                if error:
                    raise C2paError(error)
                raise C2paError.Other(
                    "Error during resource {} to stream conversion".format(uri)
                )

            return result


class Signer:
    """High-level wrapper for C2PA Signer operations."""

    # Class-level error messages to avoid multiple creation
    _ERROR_MESSAGES = {
        'closed_error': "Signer is closed",
        'cleanup_error': "Error during cleanup: {}",
        'signer_cleanup': "Error cleaning up signer: {}",
        'callback_error': "Error in signer callback: {}",
        'info_error': "Error creating signer from info: {}",
        'invalid_data': "Invalid data for signing: {}",
        'invalid_certs': "Invalid certificate data: {}",
        'invalid_tsa': "Invalid TSA URL: {}",
        'encoding_error': "Invalid UTF-8 characters in input: {}"
    }

    @classmethod
    def from_info(cls, signer_info: C2paSignerInfo) -> 'Signer':
        """Create a new Signer from signer information.

        Args:
            signer_info: The signer configuration

        Returns:
            A new Signer instance

        Raises:
            C2paError: If there was an error creating the signer
        """
        signer_ptr = _lib.c2pa_signer_from_info(ctypes.byref(signer_info))

        if not signer_ptr:
            error = _parse_operation_result_for_error(_lib.c2pa_error())
            if error:
                # More detailed error message when possible
                raise C2paError(error)
            raise C2paError(
                "Failed to create signer from configured signer_info")

        return cls(signer_ptr)

    @classmethod
    def from_callback(
        cls,
        callback: Callable[[bytes], bytes],
        alg: C2paSigningAlg,
        certs: str,
        tsa_url: Optional[str] = None
    ) -> 'Signer':
        """Create a signer from a callback function.

        Args:
            callback: Function that signs data and returns the signature
            alg: The signing algorithm to use
            certs: Certificate chain in PEM format
            tsa_url: Optional RFC 3161 timestamp authority URL

        Returns:
            A new Signer instance

        Raises:
            C2paError: If there was an error creating the signer
            C2paError.Encoding: If the certificate data or TSA URL
              contains invalid UTF-8 characters
        """
        # Validate inputs before creating
        if not certs:
            raise C2paError(
                cls._ERROR_MESSAGES['invalid_certs'].format(
                    "Missing certificate data"
                )
            )

        if tsa_url and not tsa_url.startswith(("http://", "https://")):
            raise C2paError(
                cls._ERROR_MESSAGES['invalid_tsa'].format(
                    "Invalid TSA URL format"
                )
            )

        # Create a wrapper callback that handles errors and memory management
        def wrapped_callback(
                context,
                data_ptr,
                data_len,
                signed_bytes_ptr,
                signed_len):
            # Returns -1 on error as it is what the native code expects.
            # The reason is that otherwise we ping-pong errors
            # between native code and Python code,
            # which can become tedious in handling.
            # So we let the native code deal with it and
            # raise the errors accordingly, since it already does checks.
            try:
                if (
                    not data_ptr
                    or data_len <= 0
                    or not signed_bytes_ptr
                    or signed_len <= 0
                ):
                    # Error: invalid input, invalid so return -1,
                    # native code will handle it!
                    return -1

                # Validate buffer sizes before memory operations
                if data_len > 1024 * 1024:  # 1MB limit
                    return -1

                # Recover signed data (copy, to avoid lifetime issues)
                temp_buffer = (ctypes.c_ubyte * data_len)()
                ctypes.memmove(temp_buffer, data_ptr, data_len)
                data = bytes(temp_buffer)

                if not data:
                    # Error: empty data, invalid so return -1,
                    # native code will also handle it!
                    return -1

                # Call the user's callback
                signature = callback(data)
                if not signature:
                    # Error: empty signature, invalid so return -1,
                    # native code will handle that too!
                    return -1

                # Copy the signature back to the C buffer
                # (since callback is used in native code)
                actual_len = min(len(signature), signed_len)
                # Use memmove for efficient memory copying instead of
                # byte-by-byte loop
                ctypes.memmove(signed_bytes_ptr, signature, actual_len)

                # Native code expects the signed len to be returned, we oblige
                return actual_len
            except Exception as e:
                logger.error(
                    cls._ERROR_MESSAGES['callback_error'].format(
                        str(e)))
                # Error: exception raised, invalid so return -1,
                # native code will handle the error when seeing -1
                return -1

        # Encode strings with error handling in case it's invalid UTF8
        try:
            # Only encode if not already bytes, avoid unnecessary encoding
            certs_bytes = certs.encode(
                'utf-8') if isinstance(certs, str) else certs
            tsa_url_bytes = tsa_url.encode(
                'utf-8') if tsa_url and isinstance(tsa_url, str) else tsa_url
        except UnicodeError as e:
            raise C2paError.Encoding(
                cls._ERROR_MESSAGES['encoding_error'].format(
                    str(e)))

        # Create the callback object using the callback function
        callback_cb = SignerCallback(wrapped_callback)

        # Create the signer with the wrapped callback
        signer_ptr = _lib.c2pa_signer_create(
            None,
            callback_cb,
            alg,
            certs_bytes,
            tsa_url_bytes
        )

        if not signer_ptr:
            error = _parse_operation_result_for_error(_lib.c2pa_error())
            if error:
                raise C2paError(error)
            raise C2paError("Failed to create signer")

        # Create and return the signer instance with the callback
        signer_instance = cls(signer_ptr)

        # Keep callback alive on the object to prevent gc of the callback
        # So the callback will live as long as the signer leaves,
        # and there is a 1:1 relationship between signer and callback.
        signer_instance._callback_cb = callback_cb

        return signer_instance

    def __init__(self, signer_ptr: ctypes.POINTER(C2paSigner)):
        """Initialize a new Signer instance.

        Note: This constructor is not meant to be called directly.
        Use from_info() or from_callback() instead.

        Args:
            signer_ptr: Pointer to the native C2PA signer

        Raises:
            C2paError: If the signer pointer is invalid
        """
        # Validate pointer before assignment
        if not signer_ptr:
            raise C2paError("Invalid signer pointer: pointer is null")

        self._signer = signer_ptr
        self._closed = False

        # Set only for signers which are callback signers
        self._callback_cb = None

    def __enter__(self):
        """Context manager entry."""
        self._ensure_valid_state()

        if not self._signer:
            raise C2paError("Invalid signer pointer: pointer is null")

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()

    def _cleanup_resources(self):
        """Internal cleanup method that releases native resources.

        This method handles the actual cleanup logic and can be called
        from both close() and __del__ without causing double frees.
        """
        try:
            if not self._closed and self._signer:
                self._closed = True

                try:
                    _lib.c2pa_signer_free(self._signer)
                except Exception:
                    # Log cleanup errors but don't raise exceptions
                    logger.error("Failed to free native Signer resources")
                finally:
                    self._signer = None

                # Clean up callback reference
                if self._callback_cb:
                    self._callback_cb = None

        except Exception:
            # Ensure we don't raise exceptions during cleanup
            pass

    def _ensure_valid_state(self):
        """Ensure the signer is in a valid state for operations.

        Raises:
            C2paError: If the signer is closed or invalid
        """
        if self._closed:
            raise C2paError(Signer._ERROR_MESSAGES['closed_error'])
        if not self._signer:
            raise C2paError(Signer._ERROR_MESSAGES['closed_error'])

    def close(self):
        """Release the signer resources.

        This method ensures all resources are properly cleaned up,
        even if errors occur during cleanup.

        Note:
            Multiple calls to close() are handled gracefully.
            Errors during cleanup are logged but not raised
            to ensure cleanup.
        """
        if self._closed:
            return

        try:
            # Validate pointer before cleanup if it exists
            if self._signer and self._signer != 0:
                # Use the internal cleanup method
                self._cleanup_resources()
            else:
                # Make sure to release the callback
                if self._callback_cb:
                    self._callback_cb = None

        except Exception as e:
            # Log any unexpected errors during close
            logger.error(
                Signer._ERROR_MESSAGES['cleanup_error'].format(
                    str(e)))
        finally:
            # Always mark as closed, regardless of cleanup success
            self._closed = True

    def reserve_size(self) -> int:
        """Get the size to reserve for signatures from this signer.

        Returns:
            The size to reserve in bytes

        Raises:
            C2paError: If there was an error getting the size
        """
        self._ensure_valid_state()

        result = _lib.c2pa_signer_reserve_size(self._signer)

        if result < 0:
            error = _parse_operation_result_for_error(_lib.c2pa_error())
            if error:
                raise C2paError(error)
            raise C2paError("Failed to get reserve size")

        return result


class Builder:
    """High-level wrapper for C2PA Builder operations."""

    # Supported mimetypes cache
    _supported_mime_types_cache = None

    # Class-level error messages to avoid multiple creation
    _ERROR_MESSAGES = {
        'builder_error': "Failed to create builder: {}",
        'cleanup_error': "Error during cleanup: {}",
        'builder_cleanup': "Error cleaning up builder: {}",
        'closed_error': "Builder is closed",
        'manifest_error': "Invalid manifest data: must be string or dict",
        'url_error': "Error setting remote URL: {}",
        'resource_error': "Error adding resource: {}",
        'ingredient_error': "Error adding ingredient: {}",
        'archive_error': "Error writing archive: {}",
        'sign_error': "Error during signing: {}",
        'encoding_error': "Invalid UTF-8 characters in manifest: {}",
        'json_error': "Failed to serialize manifest JSON: {}"
    }

    @classmethod
    def get_supported_mime_types(cls) -> list[str]:
        """Get the list of supported MIME types for the Builder.
        This method retrieves supported MIME types from the native library.

        Returns:
            List of supported MIME type strings

        Raises:
            C2paError: If there was an error retrieving the MIME types
        """
        if cls._supported_mime_types_cache is not None:
            return cls._supported_mime_types_cache

        count = ctypes.c_size_t()
        arr = _lib.c2pa_builder_supported_mime_types(ctypes.byref(count))

        # Validate the returned array pointer
        if not arr:
            # If no array returned, check for errors
            error = _parse_operation_result_for_error(_lib.c2pa_error())
            if error:
                raise C2paError(f"Failed to get supported MIME types: {error}")
            # Return empty list if no error but no array
            return []

        # Validate count value
        if count.value <= 0:
            # Free the array even if count is invalid
            try:
                _lib.c2pa_free_string_array(arr, count.value)
            except Exception:
                pass
            return []

        try:
            result = []
            for i in range(count.value):
                try:
                    # Validate each array element before accessing
                    if arr[i] is None:
                        continue

                    mime_type = arr[i].decode("utf-8", errors='replace')
                    if mime_type:
                        result.append(mime_type)
                except Exception:
                    # Ignore decoding failures
                    continue
        finally:
            # Always free the native memory, even if string extraction fails
            try:
                _lib.c2pa_free_string_array(arr, count.value)
            except Exception:
                # Ignore cleanup errors
                pass

        # Cache the result
        if result:
            cls._supported_mime_types_cache = result

        return cls._supported_mime_types_cache

    @classmethod
    def from_json(cls, manifest_json: Any) -> 'Builder':
        """Create a new Builder from a JSON manifest.

        Args:
            manifest_json: The JSON manifest definition

        Returns:
            A new Builder instance

        Raises:
            C2paError: If there was an error creating the builder
        """
        return cls(manifest_json)

    @classmethod
    def from_archive(cls, stream: Any) -> 'Builder':
        """Create a new Builder from an archive stream.

        Args:
            stream: The stream containing the archive
                (any Python stream-like object)

        Returns:
            A new Builder instance

        Raises:
            C2paError: If there was an error creating the builder from archive
        """
        builder = cls({})
        stream_obj = Stream(stream)
        builder._builder = _lib.c2pa_builder_from_archive(stream_obj._stream)

        if not builder._builder:
            # Clean up the stream object if builder creation fails
            stream_obj.close()

            error = _parse_operation_result_for_error(_lib.c2pa_error())
            if error:
                raise C2paError(error)
            raise C2paError("Failed to create builder from archive")

        builder._initialized = True
        return builder

    def __init__(self, manifest_json: Any):
        """Initialize a new Builder instance.

        Args:
            manifest_json: The manifest JSON definition (string or dict)

        Raises:
            C2paError: If there was an error creating the builder
            C2paError.Encoding: If manifest JSON contains invalid UTF-8 chars
            C2paError.Json: If the manifest JSON cannot be serialized
        """
        self._closed = False
        self._initialized = False
        self._builder = None

        if not isinstance(manifest_json, str):
            try:
                manifest_json = json.dumps(manifest_json)
            except (TypeError, ValueError) as e:
                raise C2paError.Json(
                    Builder._ERROR_MESSAGES['json_error'].format(
                        str(e)))

        try:
            json_str = manifest_json.encode('utf-8')
        except UnicodeError as e:
            raise C2paError.Encoding(
                Builder._ERROR_MESSAGES['encoding_error'].format(
                    str(e)))

        self._builder = _lib.c2pa_builder_from_json(json_str)

        if not self._builder:
            error = _parse_operation_result_for_error(_lib.c2pa_error())
            if error:
                raise C2paError(error)
            raise C2paError(
                Builder._ERROR_MESSAGES['builder_error'].format(
                    "Unknown error"
                )
            )

        self._initialized = True

    def __del__(self):
        """Ensure resources are cleaned up if close() wasn't called."""
        self._cleanup_resources()

    def __enter__(self):
        self._ensure_valid_state()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def _ensure_valid_state(self):
        """Ensure the builder is in a valid state for operations.

        Raises:
            C2paError: If the builder is closed, not initialized, or invalid
        """
        if self._closed:
            raise C2paError(Builder._ERROR_MESSAGES['closed_error'])
        if not self._initialized:
            raise C2paError("Builder is not properly initialized")
        if not self._builder:
            raise C2paError(Builder._ERROR_MESSAGES['closed_error'])

    def _cleanup_resources(self):
        """Internal cleanup method that releases native resources.

        This method handles the actual cleanup logic and can be called
        from both close() and __del__ without causing double frees.
        """
        try:
            # Only cleanup if not already closed and we have a valid builder
            if hasattr(self, '_closed') and not self._closed:
                self._closed = True

                if hasattr(
                        self,
                        '_builder') and self._builder and self._builder != 0:
                    try:
                        _lib.c2pa_builder_free(self._builder)
                    except Exception:
                        # Log cleanup errors but don't raise exceptions
                        logger.error(
                            "Failed to release native Builder resources"
                        )
                        pass
                    finally:
                        self._builder = None

                # Reset initialized state after cleanup
                self._initialized = False
        except Exception:
            # Ensure we don't raise exceptions during cleanup
            pass

    def close(self):
        """Release the builder resources.

        This method ensures all resources are properly cleaned up,
        even if errors occur during cleanup.
        Errors during cleanup are logged but not raised to ensure cleanup.
        Multiple calls to close() are handled gracefully.
        """
        if self._closed:
            return

        try:
            # Use the internal cleanup method
            self._cleanup_resources()
        except Exception as e:
            # Log any unexpected errors during close
            logger.error(
                Builder._ERROR_MESSAGES['cleanup_error'].format(
                    str(e)))
        finally:
            self._closed = True

    def set_no_embed(self):
        """Set the no-embed flag.

        When set, the builder will not embed a C2PA manifest store
        into the asset when signing.
        This is useful when creating cloud or sidecar manifests.
        """
        self._ensure_valid_state()
        _lib.c2pa_builder_set_no_embed(self._builder)

    def set_remote_url(self, remote_url: str):
        """Set the remote URL.

        When set, the builder embeds a remote URL into the asset when signing.
        This is useful when creating cloud based Manifests.

        Args:
            remote_url: The remote URL to set

        Raises:
            C2paError: If there was an error setting the remote URL
        """
        self._ensure_valid_state()

        url_str = remote_url.encode('utf-8')
        result = _lib.c2pa_builder_set_remote_url(self._builder, url_str)

        if result != 0:
            error = _parse_operation_result_for_error(_lib.c2pa_error())
            if error:
                raise C2paError(error)
            raise C2paError(
                Builder._ERROR_MESSAGES['url_error'].format("Unknown error"))

    def add_resource(self, uri: str, stream: Any):
        """Add a resource to the builder.

        Args:
            uri: The URI to identify the resource
            stream: The stream containing the resource data
              (any Python stream-like object)

        Raises:
            C2paError: If there was an error adding the resource
        """
        self._ensure_valid_state()

        uri_str = uri.encode('utf-8')
        with Stream(stream) as stream_obj:
            result = _lib.c2pa_builder_add_resource(
                self._builder, uri_str, stream_obj._stream)

            if result != 0:
                error = _parse_operation_result_for_error(_lib.c2pa_error())
                if error:
                    raise C2paError(error)
                raise C2paError(
                    Builder._ERROR_MESSAGES['resource_error'].format(
                        "Unknown error"
                    )
                )

    def add_ingredient(self, ingredient_json: str, format: str, source: Any):
        """Add an ingredient to the builder (facade method).
        The added ingredient's source should be a stream-like object
        (for instance, a file opened as stream).

        Args:
            ingredient_json: The JSON ingredient definition
            format: The MIME type or extension of the ingredient
            source: The stream containing the ingredient data
              (any Python stream-like object)

        Raises:
            C2paError: If there was an error adding the ingredient
            C2paError.Encoding: If the ingredient JSON contains
              invalid UTF-8 characters

        Example:
            ```
            with open(ingredient_file_path, 'rb') as a_file:
                builder.add_ingredient(ingredient_json, "image/jpeg", a_file)
            ```
        """
        return self.add_ingredient_from_stream(ingredient_json, format, source)

    def add_ingredient_from_stream(
            self,
            ingredient_json: str,
            format: str,
            source: Any):
        """Add an ingredient from a stream to the builder.
        Explicitly named API requiring a stream as input parameter.

        Args:
            ingredient_json: The JSON ingredient definition
            format: The MIME type or extension of the ingredient
            source: The stream containing the ingredient data
              (any Python stream-like object)

        Raises:
            C2paError: If there was an error adding the ingredient
            C2paError.Encoding: If the ingredient JSON or format
              contains invalid UTF-8 characters
        """
        self._ensure_valid_state()

        try:
            ingredient_str = ingredient_json.encode('utf-8')
            format_str = format.encode('utf-8')
        except UnicodeError as e:
            raise C2paError.Encoding(
                Builder._ERROR_MESSAGES['encoding_error'].format(
                    str(e)))

        with Stream(source) as source_stream:
            result = (
                _lib.c2pa_builder_add_ingredient_from_stream(
                    self._builder,
                    ingredient_str,
                    format_str,
                    source_stream._stream
                )
            )

            if result != 0:
                error = _parse_operation_result_for_error(_lib.c2pa_error())
                if error:
                    raise C2paError(error)
                raise C2paError(
                    Builder._ERROR_MESSAGES['ingredient_error'].format(
                        "Unknown error"
                    )
                )

    def add_ingredient_from_file_path(
            self,
            ingredient_json: str,
            format: str,
            filepath: Union[str, Path]):
        """Add an ingredient from a file path to the builder (deprecated).
        This is a legacy method.

        .. deprecated:: 0.13.0
           This method is deprecated and will be removed in a future version.
           Use :meth:`add_ingredient` with a file stream instead.

        Args:
            ingredient_json: The JSON ingredient definition
            format: The MIME type or extension of the ingredient
            filepath: The path to the file containing the ingredient data
              (can be a string or Path object)

        Raises:
            C2paError: If there was an error adding the ingredient
            C2paError.Encoding: If the ingredient JSON or format
              contains invalid UTF-8 characters
            FileNotFoundError: If the file at the specified path does not exist
        """
        warnings.warn(
            "add_ingredient_from_file_path is deprecated and will "
            "be removed in a future version. Use add_ingredient "
            "with a file stream instead.",
            DeprecationWarning,
            stacklevel=2,
        )

        try:
            # Convert Path object to string if necessary
            filepath_str = str(filepath)

            # Does the stream handling to use add_ingredient_from_stream
            with open(filepath_str, 'rb') as file_stream:
                self.add_ingredient_from_stream(
                    ingredient_json, format, file_stream)
        except FileNotFoundError as e:
            raise C2paError.FileNotFound(f"File not found: {filepath}") from e
        except Exception as e:
            raise C2paError.Other(f"Could not add ingredient: {e}") from e

    def to_archive(self, stream: Any) -> None:
        """Write an archive of the builder to a stream.

        Args:
            stream: The stream to write the archive to
              (any Python stream-like object)

        Raises:
            C2paError: If there was an error writing the archive
        """
        self._ensure_valid_state()

        with Stream(stream) as stream_obj:
            result = _lib.c2pa_builder_to_archive(
                self._builder, stream_obj._stream)

            if result != 0:
                error = _parse_operation_result_for_error(_lib.c2pa_error())
                if error:
                    raise C2paError(error)
                raise C2paError(
                    Builder._ERROR_MESSAGES["archive_error"].format(
                        "Unknown error"
                    )
                )

    def _sign_internal(
            self,
            signer: Signer,
            format: str,
            source_stream: Stream,
            dest_stream: Stream) -> bytes:
        """Internal signing logic shared between sign() and sign_file() methods
        to use same native calls but expose different API surface.

        Args:
            signer: The signer to use
            format: The MIME type or extension of the content
            source_stream: The source stream
            dest_stream: The destination stream,
            opened in w+b (write+read binary) mode.

        Returns:
            Manifest bytes

        Raises:
            C2paError: If there was an error during signing
        """
        self._ensure_valid_state()

        # Validate signer pointer before use
        if not signer or not hasattr(signer, '_signer') or not signer._signer:
            raise C2paError("Invalid or closed signer")

        format_lower = format.lower()
        if format_lower not in Builder.get_supported_mime_types():
            raise C2paError.NotSupported(
                f"Builder does not support {format}")

        format_str = format.encode('utf-8')
        manifest_bytes_ptr = ctypes.POINTER(ctypes.c_ubyte)()

        # c2pa_builder_sign uses streams
        try:
            result = _lib.c2pa_builder_sign(
                self._builder,
                format_str,
                source_stream._stream,
                dest_stream._stream,
                signer._signer,
                ctypes.byref(manifest_bytes_ptr)
            )
        except Exception as e:
            # Handle errors during the C function call
            raise C2paError(f"Error calling c2pa_builder_sign: {str(e)}")

        if result < 0:
            error = _parse_operation_result_for_error(_lib.c2pa_error())
            if error:
                raise C2paError(error)
            raise C2paError("Error during signing")

        # Capture the manifest bytes if available
        manifest_bytes = b""
        if manifest_bytes_ptr and result > 0:
            try:
                # Convert the C pointer to Python bytes
                temp_buffer = (ctypes.c_ubyte * result)()
                ctypes.memmove(temp_buffer, manifest_bytes_ptr, result)
                manifest_bytes = bytes(temp_buffer)
            except Exception:
                manifest_bytes = b""
            finally:
                # Always free the C-allocated memory,
                # even if we failed to copy manifest bytes
                try:
                    _lib.c2pa_manifest_bytes_free(manifest_bytes_ptr)
                except Exception:
                    logger.error(
                        "Failed to release native manifest bytes memory"
                    )
                    pass

        return manifest_bytes

    def sign(
            self,
            signer: Signer,
            format: str,
            source: Any,
            dest: Any = None) -> bytes:
        """Sign the builder's content and write to a destination stream.

        Args:
            format: The MIME type or extension of the content
            source: The source stream (any Python stream-like object)
            dest: The destination stream (any Python stream-like object),
              opened in w+b (write+read binary) mode.
            signer: The signer to use

        Returns:
            Manifest bytes

        Raises:
            C2paError: If there was an error during signing
        """
        # Convert Python streams to Stream objects
        source_stream = Stream(source)

        if dest:
            # dest is optional, only if we write back somewhere
            dest_stream = Stream(dest)
        else:
            # no destination?
            # we keep things in-memory for validation and processing
            mem_buffer = io.BytesIO()
            dest_stream = Stream(mem_buffer)

        # Use the internal stream-base signing logic
        manifest_bytes = self._sign_internal(
            signer,
            format,
            source_stream,
            dest_stream
        )

        if not dest:
            # Close temporary in-memory stream since we own it
            dest_stream.close()

        return manifest_bytes

    def sign_file(self,
                  source_path: Union[str,
                                     Path],
                  dest_path: Union[str,
                                   Path],
                  signer: Signer) -> bytes:
        """Sign a file and write the signed data to an output file.

        Args:
            source_path: Path to the source file. We will attempt
              to guess the mimetype of the source file based on
              the extension.
            dest_path: Path to write the signed file to
            signer: The signer to use

        Returns:
            Manifest bytes

        Raises:
            C2paError: If there was an error during signing
        """
        # Get the MIME type from the file extension
        mime_type = _get_mime_type_from_path(source_path)

        try:
            # Open source file and destination file, then use the sign method
            with open(source_path, 'rb') as source_file, \
                 open(dest_path, 'w+b') as dest_file:
                return self.sign(signer, mime_type, source_file, dest_file)
        except Exception as e:
            raise C2paError(f"Error signing file: {str(e)}") from e


def format_embeddable(format: str, manifest_bytes: bytes) -> tuple[int, bytes]:
    """Convert a binary C2PA manifest into an embeddable version.

    Args:
        format: The MIME type or extension of the target format
        manifest_bytes: The raw manifest bytes

    Returns:
        A tuple of (size of result bytes, embeddable manifest bytes)

    Raises:
        C2paError: If there was an error converting the manifest
    """
    format_str = format.encode('utf-8')
    manifest_array = (ctypes.c_ubyte * len(manifest_bytes))(*manifest_bytes)
    result_bytes_ptr = ctypes.POINTER(ctypes.c_ubyte)()

    result = _lib.c2pa_format_embeddable(
        format_str,
        manifest_array,
        len(manifest_bytes),
        ctypes.byref(result_bytes_ptr)
    )

    if result < 0:
        error = _parse_operation_result_for_error(_lib.c2pa_error())
        if error:
            raise C2paError(error)
        raise C2paError("Failed to format embeddable manifest")

    # Convert the result bytes to a Python bytes object
    size = result
    result_bytes = bytes(result_bytes_ptr[:size])
    _lib.c2pa_manifest_bytes_free(result_bytes_ptr)

    return size, result_bytes


def create_signer(
    callback: Callable[[bytes], bytes],
    alg: C2paSigningAlg,
    certs: str,
    tsa_url: Optional[str] = None
) -> Signer:
    """Create a signer from a callback function (deprecated).

    .. deprecated:: 0.11.0
        This function is deprecated and will be removed in a future version.
        Please use the Signer class method instead.
        Example:
            ```python
            signer = Signer.from_callback(callback, alg, certs, tsa_url)
            ```

    Args:
        callback: Function that signs data and returns the signature
        alg: The signing algorithm to use
        certs: Certificate chain in PEM format
        tsa_url: Optional RFC 3161 timestamp authority URL

    Returns:
        A new Signer instance

    Raises:
        C2paError: If there was an error creating the signer
        C2paError.Encoding: If the certificate data or TSA URL
          contains invalid UTF-8 characters
    """
    warnings.warn(
        "The create_signer function is deprecated and will be removed in a "
        "future version. Please use Signer.from_callback() instead.",
        DeprecationWarning,
        stacklevel=2,
    )

    return Signer.from_callback(callback, alg, certs, tsa_url)


def create_signer_from_info(signer_info: C2paSignerInfo) -> Signer:
    """Create a signer from signer information (deprecated).

    .. deprecated:: 0.11.0
        This function is deprecated and will be removed in a future version.
        Please use the Signer class method instead.
        Example:
            ```python
            signer = Signer.from_info(signer_info)
            ```

    Args:
        signer_info: The signer configuration

    Returns:
        A new Signer instance

    Raises:
        C2paError: If there was an error creating the signer
    """
    warnings.warn(
        "The create_signer_from_info function is deprecated and will be "
        "removed in a future version. Please use Signer.from_info() instead.",
        DeprecationWarning,
        stacklevel=2,
    )

    return Signer.from_info(signer_info)


def ed25519_sign(data: bytes, private_key: str) -> bytes:
    """Sign data using the Ed25519 algorithm.

    Args:
        data: The data to sign
        private_key: The private key in PEM format

    Returns:
        The signature bytes

    Raises:
        C2paError: If there was an error signing the data
        C2paError.Encoding: If the private key contains invalid UTF-8 chars
    """
    if not data:
        raise C2paError("Data to sign cannot be empty")

    if not private_key or not isinstance(private_key, str):
        raise C2paError("Private key must be a non-empty string")

    # Create secure memory buffer for data
    data_array = None
    key_bytes = None

    try:
        # Create data array with size validation
        data_size = len(data)
        data_array = (ctypes.c_ubyte * data_size)(*data)

        # Encode private key to bytes
        try:
            key_bytes = private_key.encode('utf-8')
        except UnicodeError as e:
            raise C2paError.Encoding(
                f"Invalid UTF-8 characters in private key: {str(e)}")

        # Perform the signing operation
        signature_ptr = _lib.c2pa_ed25519_sign(
            data_array,
            data_size,
            key_bytes
        )

        if not signature_ptr:
            error = _parse_operation_result_for_error(_lib.c2pa_error())
            if error:
                raise C2paError(error)
            raise C2paError("Failed to sign data with Ed25519")

        try:
            # Ed25519 signatures are always 64 bytes
            signature = bytes(signature_ptr[:64])
        finally:
            _lib.c2pa_signature_free(signature_ptr)

        return signature

    finally:
        if key_bytes:
            ctypes.memset(key_bytes, 0, len(key_bytes))
            del key_bytes


__all__ = [
    'C2paError',
    'C2paSeekMode',
    'C2paSigningAlg',
    'C2paSignerInfo',
    'Stream',
    'Reader',
    'Builder',
    'Signer',
    'load_settings',
    'read_file',
    'read_ingredient_file',
    'sign_file',
    'format_embeddable',
    'version',
    'sdk_version'
]
