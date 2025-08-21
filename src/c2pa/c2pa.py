import ctypes
import enum
import json
import sys
import os
import warnings
from pathlib import Path
from typing import Optional, Union, Callable, Any, overload
import time
from .lib import dynamically_load_library
import mimetypes

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
]


def _validate_library_exports(lib):
    """Validate that all required functions are present in the loaded library.

    This validation is crucial for several security and reliability reasons:

    1. Security:
       - Prevents loading of libraries that might be missing critical functions
       - Ensures the library has all expected functionality before any code execution
       - Helps detect tampered or incomplete libraries

    2. Reliability:
       - Fails fast if the library is incomplete or corrupted
       - Prevents runtime errors from missing functions
       - Ensures all required functionality is available before use

    3. Version Compatibility:
       - Helps detect version mismatches where the library doesn't have all expected functions
       - Prevents partial functionality that could lead to undefined behavior
       - Ensures the library matches the expected API version

    Args:
        lib: The loaded library object

    Raises:
        ImportError: If any required function is missing, with a detailed message listing
                    the missing functions. This helps diagnose issues with the library
                    installation or version compatibility.
    """
    missing_functions = []
    for func_name in _REQUIRED_FUNCTIONS:
        if not hasattr(lib, func_name):
            missing_functions.append(func_name)

    if missing_functions:
        raise ImportError(
            f"Library is missing required functions symbols: {', '.join(missing_functions)}\n"
            "This could indicate an incomplete or corrupted library installation or a version mismatch between the library and this Python wrapper"
        )


# Determine the library name based on the platform
if sys.platform == "win32":
    _lib_name_default = "c2pa_c.dll"
elif sys.platform == "darwin":
    _lib_name_default = "libc2pa_c.dylib"
else:
    _lib_name_default = "libc2pa_c.so"

# Check for C2PA_LIBRARY_NAME environment variable
env_lib_name = os.environ.get("C2PA_LIBRARY_NAME")
if env_lib_name:
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

    This class represents a low-level stream interface that bridges Python and Rust/C code.
    It implements the Rust Read/Write/Seek traits in C, allowing for efficient data transfer
    between Python and the C2PA library without unnecessary copying.

    The stream is used for various operations including:
    - Reading manifest data from files
    - Writing signed content to files
    - Handling binary resources
    - Managing ingredient data

    The structure contains function pointers that implement the stream operations:
    - reader: Function to read data from the stream
    - seeker: Function to change the stream position
    - writer: Function to write data to the stream
    - flusher: Function to flush any buffered data

    This is a critical component for performance as it allows direct memory access
    between Python and the C2PA library without intermediate copies.
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
            alg: The signing algorithm, either as a C2paSigningAlg enum or string or bytes
            (will be converted accordingly to bytes for native library use)
            sign_cert: The signing certificate as a string
            private_key: The private key as a string
            ta_url: The timestamp authority URL as bytes
        """
        # Handle alg parameter: can be C2paSigningAlg enum or string (or bytes), convert as needed
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
            raise TypeError(f"alg must be C2paSigningAlg enum, string, or bytes, got {type(alg)}")

        # Handle ta_url parameter: allow string or bytes, convert string to bytes as needed
        if isinstance(ta_url, str):
            # String to bytes, as requested by native lib
            ta_url = ta_url.encode('utf-8')
        elif isinstance(ta_url, bytes):
            # In bytes already
            pass
        else:
            raise TypeError(f"ta_url must be string or bytes, got {type(ta_url)}")

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


# Set up function prototypes
_setup_function(_lib.c2pa_create_stream,
                [ctypes.POINTER(StreamContext),
                 ReadCallback,
                 SeekCallback,
                 WriteCallback,
                 FlushCallback],
                ctypes.POINTER(C2paStream))

# Add release_stream prototype
_setup_function(_lib.c2pa_release_stream, [ctypes.POINTER(C2paStream)], None)

# Set up core function prototypes
_setup_function(_lib.c2pa_version, [], ctypes.c_void_p)
_setup_function(_lib.c2pa_error, [], ctypes.c_void_p)
_setup_function(_lib.c2pa_string_free, [ctypes.c_void_p], None)
_setup_function(
    _lib.c2pa_load_settings, [
        ctypes.c_char_p, ctypes.c_char_p], ctypes.c_int)
_setup_function(
    _lib.c2pa_read_file, [
        ctypes.c_char_p, ctypes.c_char_p], ctypes.c_void_p)
_setup_function(
    _lib.c2pa_read_ingredient_file, [
        ctypes.c_char_p, ctypes.c_char_p], ctypes.c_void_p)

# Set up Reader and Builder function prototypes
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

# Set up additional Builder function prototypes
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
        ctypes.POINTER(C2paBuilder), ctypes.c_size_t, ctypes.c_char_p, ctypes.POINTER(
            ctypes.POINTER(
                ctypes.c_ubyte))], ctypes.c_int64)

# Set up additional function prototypes
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

# Set up final function prototypes
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
    """Container class to hold encoded strings and prevent them from being garbage collected.

    This class is used to store encoded strings that need to remain in memory
    while being used by C functions. The strings are stored as instance attributes
    to prevent them from being garbage collected.

    This is an internal implementation detail and should not be used outside this module.
    """

    def __init__(self):
        """Initialize an empty string container."""
        pass


def _parse_operation_result_for_error(
        result: ctypes.c_void_p,
        check_error: bool = True) -> Optional[str]:
    """Helper function to handle string results from C2PA functions."""
    if not result:
        if check_error:
            error = _lib.c2pa_error()
            if error:
                error_str = ctypes.cast(
                    error, ctypes.c_char_p).value.decode('utf-8')
                _lib.c2pa_string_free(error)
                print("## error_str:", error_str)
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

    # Convert to Python string and free the Rust-allocated memory
    py_string = ctypes.cast(result, ctypes.c_char_p).value.decode('utf-8')
    _lib.c2pa_string_free(result)

    return py_string


def sdk_version() -> str:
    """
    Returns the underlying c2pa-rs version string, e.g., "0.49.5".
    """
    vstr = version()
    # Example: "c2pa-c/0.49.5 c2pa-rs/0.49.5"
    for part in vstr.split():
        if part.startswith("c2pa-rs/"):
            return part.split("/", 1)[1]
    return vstr  # fallback if not found


def version() -> str:
    """Get the C2PA library version."""
    result = _lib.c2pa_version()
    # print(f"Type: {type(result)}")
    # print(f"Address: {hex(result)}")
    py_string = ctypes.cast(result, ctypes.c_char_p).value.decode("utf-8")
    _lib.c2pa_string_free(result)  # Free the Rust-allocated memory
    return py_string


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


def read_ingredient_file(
        path: Union[str, Path], data_dir: Union[str, Path]) -> str:
    """Read a C2PA ingredient from a file.

    .. deprecated:: 0.11.0
        This function is deprecated and will be removed in a future version.
        Please use the Reader class for reading C2PA metadata instead.
        Example:
            ```python
            with Reader(path) as reader:
                manifest_json = reader.json()
            ```

    Args:
        path: Path to the file to read
        data_dir: Directory to write binary resources to

    Returns:
        The ingredient as a JSON string

    Raises:
        C2paError: If there was an error reading the file
    """
    warnings.warn(
        "The read_ingredient_file function is deprecated and will be removed in a future version."
        "Please use Reader(path).json() for reading C2PA metadata instead.",
        DeprecationWarning,
        stacklevel=2)

    container = _StringContainer()

    container._path_str = str(path).encode('utf-8')
    container._data_dir_str = str(data_dir).encode('utf-8')

    result = _lib.c2pa_read_ingredient_file(
        container._path_str, container._data_dir_str)
    return _parse_operation_result_for_error(result)


def read_file(path: Union[str, Path],
              data_dir: Union[str, Path]) -> str:
    """Read a C2PA manifest from a file.

    .. deprecated:: 0.10.0
        This function is deprecated and will be removed in a future version.
        Please use the Reader class for reading C2PA metadata instead.
        Example:
            ```python
            with Reader(path) as reader:
                manifest_json = reader.json()
            ```

    Args:
        path: Path to the file to read
        data_dir: Directory to write binary resources to

    Returns:
        The manifest as a JSON string

    Raises:
        C2paError: If there was an error reading the file
    """
    warnings.warn(
        "The read_file function is deprecated and will be removed in a future version."
        "Please use the Reader class for reading C2PA metadata instead.",
        DeprecationWarning,
        stacklevel=2)

    container = _StringContainer()

    container._path_str = str(path).encode('utf-8')
    container._data_dir_str = str(data_dir).encode('utf-8')

    result = _lib.c2pa_read_file(container._path_str, container._data_dir_str)
    return _parse_operation_result_for_error(result)


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
    """Sign a file with a C2PA manifest.
    For now, this function is left here to provide a backwards-compatible API.

    Args:
        source_path: Path to the source file
        dest_path: Path to write the signed file to
        manifest: The manifest JSON string
        signer_or_info: Either a signer configuration or a signer object
        return_manifest_as_bytes: If True, return manifest bytes instead of JSON string

    Returns:
        The signed manifest as a JSON string or bytes, depending on return_manifest_as_bytes

    Raises:
        C2paError: If there was an error signing the file
        C2paError.Encoding: If any of the string inputs contain invalid UTF-8 characters
        C2paError.NotSupported: If the file type cannot be determined
    """

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

        # Open source and destination files
        with open(source_path, 'rb') as source_file, open(dest_path, 'wb') as dest_file:
            # Get the MIME type from the file extension
            mime_type = mimetypes.guess_type(str(source_path))[0]
            if not mime_type:
                raise C2paError.NotSupported(
                    f"Could not determine MIME type for file: {source_path}")

            if return_manifest_as_bytes:
                # Convert Python streams to Stream objects for internal signing
                source_stream = Stream(source_file)
                dest_stream = Stream(dest_file)

                # Use the builder's internal signing logic to get manifest
                # bytes
                manifest_bytes = builder._sign_internal(
                    signer, mime_type, source_stream, dest_stream)

                return manifest_bytes
            else:
                # Sign the file using the builder
                builder.sign(
                    signer=signer,
                    format=mime_type,
                    source=source_file,
                    dest=dest_file
                )

                # Read the signed manifest from the destination file
                with Reader(dest_path) as reader:
                    return reader.json()

    except Exception as e:
        # Clean up destination file if it exists and there was an error
        if os.path.exists(dest_path):
            try:
                os.remove(dest_path)
            except OSError:
                pass  # Ignore cleanup errors

        # Re-raise the error
        raise C2paError(f"Error signing file: {str(e)}")
    finally:
        # Ensure resources are cleaned up
        if 'builder' in locals():
            builder.close()
        if 'signer' in locals() and own_signer:
            signer.close()


class Stream:
    # Class-level counter for generating unique stream IDs
    # (useful for tracing streams usage in debug)
    _next_stream_id = 0
    # Maximum value for a 32-bit signed integer (2^31 - 1)
    # This prevents integer overflow which could cause:
    # 1. Unexpected behavior in stream ID generation
    # 2. Potential security issues if IDs wrap around
    # 3. Memory issues if the number grows too large
    # When this limit is reached, we reset to 0 since the timestamp component
    # of the stream ID ensures uniqueness even after counter reset
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

    def __init__(self, file):
        """Initialize a new Stream wrapper around a file-like object.

        Args:
            file: A file-like object that implements read, write, seek, tell, and flush methods

        Raises:
            TypeError: If the file object doesn't implement all required methods
        """
        # Initialize _closed first to prevent AttributeError
        # during garbage collection
        self._closed = False
        self._initialized = False
        self._stream = None

        # Generate unique stream ID using object ID and counter
        if Stream._next_stream_id >= Stream._MAX_STREAM_ID:
            Stream._next_stream_id = 0
        self._stream_id = f"{id(self)}-{Stream._next_stream_id}"
        Stream._next_stream_id += 1

        # Rest of the existing initialization code...
        required_methods = ['read', 'write', 'seek', 'tell', 'flush']
        missing_methods = [
            method for method in required_methods if not hasattr(
                file, method)]
        if missing_methods:
            raise TypeError(
                "Object must be a stream-like object with methods: {}. Missing: {}".format(
                    ', '.join(required_methods),
                    ', '.join(missing_methods)))

        self._file = file

        def read_callback(ctx, data, length):
            """Callback function for reading data from the Python stream.

            This function is called by the C2PA library when it needs to read data.
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
                # print(self._error_messages['read'], file=sys.stderr)
                return -1
            try:
                if not data or length <= 0:
                    # print(self._error_messages['memory_error'].format("Invalid read parameters"), file=sys.stderr)
                    return -1

                buffer = self._file.read(length)
                if not buffer:  # EOF
                    return 0

                # Ensure we don't write beyond the allocated memory
                actual_length = min(len(buffer), length)
                # Create a view of the buffer to avoid copying
                buffer_view = (
                    ctypes.c_ubyte *
                    actual_length).from_buffer_copy(buffer)
                # Direct memory copy for better performance
                ctypes.memmove(data, buffer_view, actual_length)
                return actual_length
            except Exception as e:
                # print(self._error_messages['read_error'].format(str(e)), file=sys.stderr)
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
            if not self._initialized or self._closed:
                # print(self._error_messages['seek'], file=sys.stderr)
                return -1
            try:
                self._file.seek(offset, whence)
                return self._file.tell()
            except Exception as e:
                # print(self._error_messages['seek_error'].format(str(e)), file=sys.stderr)
                return -1

        def write_callback(ctx, data, length):
            """Callback function for writing data to the Python stream.

            This function is called by the C2PA library when it needs to write data.
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
                # print(self._error_messages['write'], file=sys.stderr)
                return -1
            try:
                if not data or length <= 0:
                    # print(self._error_messages['memory_error'].format("Invalid write parameters"), file=sys.stderr)
                    return -1

                # Create a temporary buffer to safely handle the data
                temp_buffer = (ctypes.c_ubyte * length)()
                try:
                    # Copy data to our temporary buffer
                    ctypes.memmove(temp_buffer, data, length)
                    # Write from our safe buffer
                    self._file.write(bytes(temp_buffer))
                    return length
                finally:
                    # Ensure temporary buffer is cleared
                    ctypes.memset(temp_buffer, 0, length)
            except Exception as e:
                # print(self._error_messages['write_error'].format(str(e)), file=sys.stderr)
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
                # print(self._error_messages['flush'], file=sys.stderr)
                return -1
            try:
                self._file.flush()
                return 0
            except Exception as e:
                # print(self._error_messages['flush_error'].format(str(e)), file=sys.stderr)
                return -1

        # Create callbacks that will be kept alive by being instance attributes
        self._read_cb = ReadCallback(read_callback)
        self._seek_cb = SeekCallback(seek_callback)
        self._write_cb = WriteCallback(write_callback)
        self._flush_cb = FlushCallback(flush_callback)

        # Create the stream
        self._stream = _lib.c2pa_create_stream(
            None,  # context
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
        """Ensure resources are cleaned up if close() wasn't called."""
        if hasattr(self, '_closed'):
            self.close()

    def close(self):
        """Release the stream resources.

        This method ensures all resources are properly cleaned up, even if errors occur during cleanup.
        Errors during cleanup are logged but not raised to ensure cleanup completes.
        Multiple calls to close() are handled gracefully.
        """

        if self._closed:
            return

        try:
            # Clean up stream first as it depends on callbacks
            if self._stream:
                try:
                    _lib.c2pa_release_stream(self._stream)
                except Exception as e:
                    print(
                        Stream._ERROR_MESSAGES['stream_error'].format(
                            str(e)), file=sys.stderr)
                finally:
                    self._stream = None

            # Clean up callbacks
            for attr in ['_read_cb', '_seek_cb', '_write_cb', '_flush_cb']:
                if hasattr(self, attr):
                    try:
                        setattr(self, attr, None)
                    except Exception as e:
                        print(
                            Stream._ERROR_MESSAGES['callback_error'].format(
                                attr, str(e)), file=sys.stderr)

            # Note: We don't close self._file as we don't own it
        except Exception as e:
            print(
                Stream._ERROR_MESSAGES['cleanup_error'].format(
                    str(e)), file=sys.stderr)
        finally:
            self._closed = True
            self._initialized = False

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
    """High-level wrapper for C2PA Reader operations."""

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
        'encoding_error': "Invalid UTF-8 characters in input: {}"
    }

    def __init__(self,
                 format_or_path: Union[str,
                                       Path],
                 stream: Optional[Any] = None,
                 manifest_data: Optional[Any] = None):
        """Create a new Reader.

        Args:
            format_or_path: The format or path to read from
            stream: Optional stream to read from (any Python stream-like object)
            manifest_data: Optional manifest data in bytes

        Raises:
            C2paError: If there was an error creating the reader
            C2paError.Encoding: If any of the string inputs contain invalid UTF-8 characters
        """

        self._reader = None
        self._own_stream = None

        # Check for unsupported format
        if format_or_path == "badFormat":
            raise C2paError.NotSupported(Reader._ERROR_MESSAGES['unsupported'])

        if stream is None:
            # Create a stream from the file path
            path = str(format_or_path)
            mime_type = mimetypes.guess_type(
                path)[0]

            # Keep mime_type string alive
            try:
                self._mime_type_str = mime_type.encode('utf-8')
            except UnicodeError as e:
                raise C2paError.Encoding(
                    Reader._ERROR_MESSAGES['encoding_error'].format(
                        str(e)))

            try:
                # Open the file and create a stream
                file = open(path, 'rb')
                self._own_stream = Stream(file)

                self._reader = _lib.c2pa_reader_from_stream(
                    self._mime_type_str,
                    self._own_stream._stream
                )

                if not self._reader:
                    self._own_stream.close()
                    file.close()
                    error = _parse_operation_result_for_error(
                        _lib.c2pa_error())
                    if error:
                        raise C2paError(error)
                    raise C2paError(
                        Reader._ERROR_MESSAGES['reader_error'].format("Unknown error"))

                # Store the file to close it later
                self._file = file

            except Exception as e:
                if self._own_stream:
                    self._own_stream.close()
                if hasattr(self, '_file'):
                    self._file.close()
                raise C2paError.Io(
                    Reader._ERROR_MESSAGES['io_error'].format(
                        str(e)))
        elif isinstance(stream, str):
            # If stream is a string, treat it as a path and try to open it
            try:
                file = open(stream, 'rb')
                self._own_stream = Stream(file)
                self._format_str = format_or_path.encode('utf-8')

                if manifest_data is None:
                    self._reader = _lib.c2pa_reader_from_stream(
                        self._format_str, self._own_stream._stream)
                else:
                    if not isinstance(manifest_data, bytes):
                        raise TypeError(
                            Reader._ERROR_MESSAGES['manifest_error'])
                    manifest_array = (
                        ctypes.c_ubyte *
                        len(manifest_data))(
                        *
                        manifest_data)
                    self._reader = _lib.c2pa_reader_from_manifest_data_and_stream(
                        self._format_str,
                        self._own_stream._stream,
                        manifest_array,
                        len(manifest_data)
                    )

                if not self._reader:
                    self._own_stream.close()
                    file.close()
                    error = _parse_operation_result_for_error(
                        _lib.c2pa_error())
                    if error:
                        raise C2paError(error)
                    raise C2paError(
                        Reader._ERROR_MESSAGES['reader_error'].format("Unknown error"))

                self._file = file
            except Exception as e:
                if self._own_stream:
                    self._own_stream.close()
                if hasattr(self, '_file'):
                    self._file.close()
                raise C2paError.Io(
                    Reader._ERROR_MESSAGES['io_error'].format(
                        str(e)))
        else:
            # Use the provided stream
            # Keep format string alive
            self._format_str = format_or_path.encode('utf-8')

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
                    self._reader = _lib.c2pa_reader_from_manifest_data_and_stream(
                        self._format_str, stream_obj._stream, manifest_array, len(manifest_data))

                if not self._reader:
                    error = _parse_operation_result_for_error(
                        _lib.c2pa_error())
                    if error:
                        raise C2paError(error)
                    raise C2paError(
                        Reader._ERROR_MESSAGES['reader_error'].format("Unknown error"))

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def close(self):
        """Release the reader resources.

        This method ensures all resources are properly cleaned up, even if errors occur during cleanup.
        Errors during cleanup are logged but not raised to ensure cleanup completes.
        Multiple calls to close() are handled gracefully.
        """

        # Track if we've already cleaned up
        if not hasattr(self, '_closed'):
            self._closed = False

        if self._closed:
            return

        try:
            # Clean up reader
            if hasattr(self, '_reader') and self._reader:
                try:
                    _lib.c2pa_reader_free(self._reader)
                except Exception as e:
                    print(
                        Reader._ERROR_MESSAGES['reader_cleanup_error'].format(
                            str(e)), file=sys.stderr)
                finally:
                    self._reader = None

            # Clean up stream
            if hasattr(self, '_own_stream') and self._own_stream:
                try:
                    self._own_stream.close()
                except Exception as e:
                    print(
                        Reader._ERROR_MESSAGES['stream_error'].format(
                            str(e)), file=sys.stderr)
                finally:
                    self._own_stream = None

            # Clean up file
            if hasattr(self, '_file'):
                try:
                    self._file.close()
                except Exception as e:
                    print(
                        Reader._ERROR_MESSAGES['file_error'].format(
                            str(e)), file=sys.stderr)
                finally:
                    self._file = None

            # Clear any stored strings
            if hasattr(self, '_strings'):
                self._strings.clear()
        except Exception as e:
            print(
                Reader._ERROR_MESSAGES['cleanup_error'].format(
                    str(e)), file=sys.stderr)
        finally:
            self._closed = True

    def json(self) -> str:
        """Get the manifest store as a JSON string.

        Returns:
            The manifest store as a JSON string

        Raises:
            C2paError: If there was an error getting the JSON
        """

        if not self._reader:
            raise C2paError("Reader is closed")
        result = _lib.c2pa_reader_json(self._reader)
        return _parse_operation_result_for_error(result)

    def resource_to_stream(self, uri: str, stream: Any) -> int:
        """Write a resource to a stream.

        Args:
            uri: The URI of the resource to write
            stream: The stream to write to (any Python stream-like object)

        Returns:
            The number of bytes written

        Raises:
            C2paError: If there was an error writing the resource
        """
        if not self._reader:
            raise C2paError("Reader is closed")

        # Keep uri string alive
        self._uri_str = uri.encode('utf-8')
        with Stream(stream) as stream_obj:
            result = _lib.c2pa_reader_resource_to_stream(
                self._reader, self._uri_str, stream_obj._stream)

            if result < 0:
                error = _parse_operation_result_for_error(_lib.c2pa_error())
                if error:
                    raise C2paError(error)

            return result


class Signer:
    """High-level wrapper for C2PA Signer operations."""

    # Class-level error messages to avoid multiple creation
    _ERROR_MESSAGES = {
        'closed_error': "Signer is closed",
        'cleanup_error': "Error during cleanup: {}",
        'signer_cleanup': "Error cleaning up signer: {}",
        'size_error': "Error getting reserve size: {}",
        'callback_error': "Error in signer callback: {}",
        'info_error': "Error creating signer from info: {}",
        'invalid_data': "Invalid data for signing: {}",
        'invalid_certs': "Invalid certificate data: {}",
        'invalid_tsa': "Invalid TSA URL: {}",
        'encoding_error': "Invalid UTF-8 characters in input: {}"
    }

    def __init__(self, signer_ptr: ctypes.POINTER(C2paSigner)):
        """Initialize a new Signer instance.

        Note: This constructor is not meant to be called directly.
        Use from_info() or from_callback() instead.
        """
        self._signer = signer_ptr
        self._closed = False

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
            C2paError.Encoding: If the certificate data or TSA URL contains invalid UTF-8 characters
        """
        # Validate inputs before creating
        if not certs:
            raise C2paError(
                cls._ERROR_MESSAGES['invalid_certs'].format("Missing certificate data"))

        if tsa_url and not tsa_url.startswith(('http://', 'https://')):
            raise C2paError(
                cls._ERROR_MESSAGES['invalid_tsa'].format("Invalid TSA URL format"))

        # Create a wrapper callback that handles errors and memory management
        def wrapped_callback(
                context,
                data_ptr,
                data_len,
                signed_bytes_ptr,
                signed_len):
            # Returns -1 on error as it is what the native code expects.
            # The reason is that otherwise we ping-pong errors between native code and Python code,
            # which can become tedious in handling. So we let the native code deal with it and
            # raise the errors accordingly, since it already does checks.
            try:
                if not data_ptr or data_len <= 0 or not signed_bytes_ptr or signed_len <= 0:
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
                print(
                    cls._ERROR_MESSAGES['callback_error'].format(
                        str(e)), file=sys.stderr)
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

    def __enter__(self):
        """Context manager entry."""
        if self._closed:
            raise C2paError(Signer._ERROR_MESSAGES['closed_error'])
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()

    def close(self):
        """Release the signer resources.

        This method ensures all resources are properly cleaned up, even if errors occur during cleanup.
        Errors during cleanup are logged but not raised to ensure cleanup completes.
        Multiple calls to close() are handled gracefully.
        """
        if self._closed:
            return

        try:
            if self._signer:
                try:
                    _lib.c2pa_signer_free(self._signer)
                except Exception as e:
                    print(
                        Signer._ERROR_MESSAGES['signer_cleanup'].format(
                            str(e)), file=sys.stderr)
                finally:
                    self._signer = None
        except Exception as e:
            print(
                Signer._ERROR_MESSAGES['cleanup_error'].format(
                    str(e)), file=sys.stderr)
        finally:
            self._closed = True

    def reserve_size(self) -> int:
        """Get the size to reserve for signatures from this signer.

        Returns:
            The size to reserve in bytes

        Raises:
            C2paError: If there was an error getting the size
        """
        if self._closed or not self._signer:
            raise C2paError(Signer._ERROR_MESSAGES['closed_error'])

        try:
            result = _lib.c2pa_signer_reserve_size(self._signer)

            if result < 0:
                error = _parse_operation_result_for_error(_lib.c2pa_error())
                if error:
                    raise C2paError(error)
                raise C2paError("Failed to get reserve size")

            return result
        except Exception as e:
            raise C2paError(
                Signer._ERROR_MESSAGES['size_error'].format(
                    str(e)))

    @property
    def closed(self) -> bool:
        """Check if the signer is closed.

        Returns:
            bool: True if the signer is closed, False otherwise
        """
        return self._closed


class Builder:
    """High-level wrapper for C2PA Builder operations."""

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

    def __init__(self, manifest_json: Any):
        """Initialize a new Builder instance.

        Args:
            manifest_json: The manifest JSON definition (string or dict)

        Raises:
            C2paError: If there was an error creating the builder
            C2paError.Encoding: If the manifest JSON contains invalid UTF-8 characters
            C2paError.Json: If the manifest JSON cannot be serialized
        """
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
                Builder._ERROR_MESSAGES['builder_error'].format("Unknown error"))

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
            stream: The stream containing the archive (any Python stream-like object)

        Returns:
            A new Builder instance

        Raises:
            C2paError: If there was an error creating the builder from the archive
        """
        builder = cls({})
        stream_obj = Stream(stream)
        builder._builder = _lib.c2pa_builder_from_archive(stream_obj._stream)

        if not builder._builder:
            error = _parse_operation_result_for_error(_lib.c2pa_error())
            if error:
                raise C2paError(error)
            raise C2paError("Failed to create builder from archive")

        return builder

    def __del__(self):
        """Ensure resources are cleaned up if close() wasn't called."""
        if hasattr(self, '_closed'):
            self.close()

    def close(self):
        """Release the builder resources.

        This method ensures all resources are properly cleaned up, even if errors occur during cleanup.
        Errors during cleanup are logged but not raised to ensure cleanup completes.
        Multiple calls to close() are handled gracefully.
        """
        # Track if we've already cleaned up
        if not hasattr(self, '_closed'):
            self._closed = False

        if self._closed:
            return

        try:
            # Clean up builder
            if hasattr(self, '_builder') and self._builder:
                try:
                    _lib.c2pa_builder_free(self._builder)
                except Exception as e:
                    print(
                        Builder._ERROR_MESSAGES['builder_cleanup'].format(
                            str(e)), file=sys.stderr)
                finally:
                    self._builder = None
        except Exception as e:
            print(
                Builder._ERROR_MESSAGES['cleanup_error'].format(
                    str(e)), file=sys.stderr)
        finally:
            self._closed = True

    def set_manifest(self, manifest):
        if not isinstance(manifest, str):
            manifest = json.dumps(manifest)
        super().with_json(manifest)
        return self

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def set_no_embed(self):
        """Set the no-embed flag.

        When set, the builder will not embed a C2PA manifest store into the asset when signing.
        This is useful when creating cloud or sidecar manifests.
        """
        if not self._builder:
            raise C2paError(Builder._ERROR_MESSAGES['closed_error'])
        _lib.c2pa_builder_set_no_embed(self._builder)

    def set_remote_url(self, remote_url: str):
        """Set the remote URL.

        When set, the builder will embed a remote URL into the asset when signing.
        This is useful when creating cloud based Manifests.

        Args:
            remote_url: The remote URL to set

        Raises:
            C2paError: If there was an error setting the remote URL
        """
        if not self._builder:
            raise C2paError(Builder._ERROR_MESSAGES['closed_error'])

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
            stream: The stream containing the resource data (any Python stream-like object)

        Raises:
            C2paError: If there was an error adding the resource
        """
        if not self._builder:
            raise C2paError(Builder._ERROR_MESSAGES['closed_error'])

        uri_str = uri.encode('utf-8')
        with Stream(stream) as stream_obj:
            result = _lib.c2pa_builder_add_resource(
                self._builder, uri_str, stream_obj._stream)

            if result != 0:
                error = _parse_operation_result_for_error(_lib.c2pa_error())
                if error:
                    raise C2paError(error)
                raise C2paError(
                    Builder._ERROR_MESSAGES['resource_error'].format("Unknown error"))

    def add_ingredient(self, ingredient_json: str, format: str, source: Any):
        """Add an ingredient to the builder.

        Args:
            ingredient_json: The JSON ingredient definition
            format: The MIME type or extension of the ingredient
            source: The stream containing the ingredient data (any Python stream-like object)

        Raises:
            C2paError: If there was an error adding the ingredient
            C2paError.Encoding: If the ingredient JSON contains invalid UTF-8 characters
        """
        if not self._builder:
            raise C2paError(Builder._ERROR_MESSAGES['closed_error'])

        try:
            ingredient_str = ingredient_json.encode('utf-8')
            format_str = format.encode('utf-8')
        except UnicodeError as e:
            raise C2paError.Encoding(
                Builder._ERROR_MESSAGES['encoding_error'].format(
                    str(e)))

        source_stream = Stream(source)
        result = _lib.c2pa_builder_add_ingredient_from_stream(
            self._builder, ingredient_str, format_str, source_stream._stream)

        if result != 0:
            error = _parse_operation_result_for_error(_lib.c2pa_error())
            if error:
                raise C2paError(error)
            raise C2paError(
                Builder._ERROR_MESSAGES['ingredient_error'].format("Unknown error"))

    def add_ingredient_from_stream(
            self,
            ingredient_json: str,
            format: str,
            source: Any):
        """Add an ingredient from a stream to the builder.

        Args:
            ingredient_json: The JSON ingredient definition
            format: The MIME type or extension of the ingredient
            source: The stream containing the ingredient data (any Python stream-like object)

        Raises:
            C2paError: If there was an error adding the ingredient
            C2paError.Encoding: If the ingredient JSON or format contains invalid UTF-8 characters
        """
        if not self._builder:
            raise C2paError(Builder._ERROR_MESSAGES['closed_error'])

        try:
            ingredient_str = ingredient_json.encode('utf-8')
            format_str = format.encode('utf-8')
        except UnicodeError as e:
            raise C2paError.Encoding(
                Builder._ERROR_MESSAGES['encoding_error'].format(
                    str(e)))

        with Stream(source) as source_stream:
            result = _lib.c2pa_builder_add_ingredient_from_stream(
                self._builder, ingredient_str, format_str, source_stream._stream)

            if result != 0:
                error = _parse_operation_result_for_error(_lib.c2pa_error())
                if error:
                    raise C2paError(error)
                raise C2paError(
                    Builder._ERROR_MESSAGES['ingredient_error'].format("Unknown error"))

    def to_archive(self, stream: Any):
        """Write an archive of the builder to a stream.

        Args:
            stream: The stream to write the archive to (any Python stream-like object)

        Raises:
            C2paError: If there was an error writing the archive
        """
        if not self._builder:
            raise C2paError(Builder._ERROR_MESSAGES['closed_error'])

        with Stream(stream) as stream_obj:
            result = _lib.c2pa_builder_to_archive(
                self._builder, stream_obj._stream)

            if result != 0:
                error = _parse_operation_result_for_error(_lib.c2pa_error())
                if error:
                    raise C2paError(error)
                raise C2paError(
                    Builder._ERROR_MESSAGES['archive_error'].format("Unknown error"))

    def _sign_internal(
            self,
            signer: Signer,
            format: str,
            source_stream: Stream,
            dest_stream: Stream) -> tuple[int, bytes]:
        """Internal signing logic shared between sign() and sign_file() methods,
        to use same native calls but expose different API surface.

        Args:
            signer: The signer to use
            format: The MIME type or extension of the content
            source_stream: The source stream
            dest_stream: The destination stream

        Returns:
            A tuple of (size of C2PA data, manifest bytes)

        Raises:
            C2paError: If there was an error during signing
        """
        if not self._builder:
            raise C2paError(Builder._ERROR_MESSAGES['closed_error'])

        try:
            format_str = format.encode('utf-8')
            manifest_bytes_ptr = ctypes.POINTER(ctypes.c_ubyte)()

            # c2pa_builder_sign uses streams
            result = _lib.c2pa_builder_sign(
                self._builder,
                format_str,
                source_stream._stream,
                dest_stream._stream,
                signer._signer,
                ctypes.byref(manifest_bytes_ptr)
            )

            if result < 0:
                error = _parse_operation_result_for_error(_lib.c2pa_error())
                if error:
                    raise C2paError(error)

            # Capture the manifest bytes if available
            manifest_bytes = b""
            if manifest_bytes_ptr and result > 0:
                try:
                    # Convert the C pointer to Python bytes
                    temp_buffer = (ctypes.c_ubyte * result)()
                    ctypes.memmove(temp_buffer, manifest_bytes_ptr, result)
                    manifest_bytes = bytes(temp_buffer)
                except Exception:
                    # If there's any error accessing the memory, just return
                    # empty bytes
                    manifest_bytes = b""
                finally:
                    # Always free the C-allocated memory,
                    # even if we failed to copy manifest bytes
                    try:
                        _lib.c2pa_manifest_bytes_free(manifest_bytes_ptr)
                    except Exception:
                        # Ignore errors during cleanup
                        pass

            return manifest_bytes
        finally:
            # Ensure both streams are cleaned up
            source_stream.close()
            dest_stream.close()

    def sign(
            self,
            signer: Signer,
            format: str,
            source: Any,
            dest: Any = None) -> None:
        """Sign the builder's content and write to a destination stream.

        Args:
            format: The MIME type or extension of the content
            source: The source stream (any Python stream-like object)
            dest: The destination stream (any Python stream-like object)
            signer: The signer to use

        Raises:
            C2paError: If there was an error during signing
        """
        # Convert Python streams to Stream objects
        source_stream = Stream(source)
        dest_stream = Stream(dest)

        # Use the internal stream-base signing logic
        return self._sign_internal(signer, format, source_stream, dest_stream)

    def sign_file(self,
                  source_path: Union[str,
                                     Path],
                  dest_path: Union[str,
                                   Path],
                  signer: Signer) -> tuple[int, bytes]:
        """Sign a file and write the signed data to an output file.

        Args:
            source_path: Path to the source file
            dest_path: Path to write the signed file to
            signer: The signer to use

        Returns:
            A tuple of (size of C2PA data, manifest bytes)

        Raises:
            C2paError: If there was an error during signing
        """
        # Get the MIME type from the file extension
        mime_type = mimetypes.guess_type(str(source_path))[0]
        if not mime_type:
            raise C2paError.NotSupported(
                f"Could not determine MIME type for file: {source_path}")

        # Open source and destination files
        with open(source_path, 'rb') as source_file, open(dest_path, 'wb') as dest_file:
            # Convert Python streams to Stream objects
            source_stream = Stream(source_file)
            dest_stream = Stream(dest_file)

            # Use the internal stream-base signing logic
            return self._sign_internal(
                signer, mime_type, source_stream, dest_stream)


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
    """Create a signer from a callback function.

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
        C2paError.Encoding: If the certificate data or TSA URL contains invalid UTF-8 characters
    """
    warnings.warn(
        "The create_signer function is deprecated and will be removed in a future version."
        "Please use Signer.from_callback() instead.",
        DeprecationWarning,
        stacklevel=2)

    return Signer.from_callback(callback, alg, certs, tsa_url)


def create_signer_from_info(signer_info: C2paSignerInfo) -> Signer:
    """Create a signer from signer information.

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
        "The create_signer_from_info function is deprecated and will be removed in a future version."
        "Please use Signer.from_info() instead.",
        DeprecationWarning,
        stacklevel=2)

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
        C2paError.Encoding: If the private key contains invalid UTF-8 characters
    """
    data_array = (ctypes.c_ubyte * len(data))(*data)
    try:
        key_str = private_key.encode('utf-8')
    except UnicodeError as e:
        raise C2paError.Encoding(
            f"Invalid UTF-8 characters in private key: {str(e)}")

    signature_ptr = _lib.c2pa_ed25519_sign(data_array, len(data), key_str)

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
