# C FFI Improvement Opportunities

The Rust C FFI (`c2pa_c_ffi`) exports ~70 functions. The Python layer wraps ~50. This document identifies concrete opportunities to better leverage the FFI.

### BMFF Fragment Support

`c2pa_reader_with_fragment(reader, format, stream, fragment_stream) -> *mut C2paReader`

Allows reading fragmented BMFF media (e.g., fragmented MP4). Consume-and-return pattern like `c2pa_reader_with_stream`.

### Context-Aware Manifest Data Reader

`c2pa_reader_with_context_from_manifest_data_and_stream(reader, format, stream, manifest_data, manifest_len) -> *mut C2paReader`

Context-aware variant of `c2pa_reader_from_manifest_data_and_stream`. Currently Python only has the non-context version, so passing context + manifest_data together is not possible.

## Underutilized FFI Functions

### `from_archive()` ignores context

`Builder.from_archive()` (c2pa.py:3077-3116) accepts a `context` parameter but never uses it in the archive loading path. It always calls the old `c2pa_builder_from_archive()`. The FFI has `c2pa_builder_with_archive()` (c_api.rs:1310) for the context-based flow — a consume-and-return function designed for this purpose.

## Not Gaps

- **JSON parsing for field extraction** — The FFI doesn't offer field-specific getters (e.g., get_active_manifest). Python's approach of parsing `c2pa_reader_json()` output is the correct and only option.
- **`c2pa_reader_new()`** — Creates an empty reader. Python always creates readers with streams, so this isn't needed.
- **Error codes** — The FFI uses string-prefix error typing (`"ErrorType: message"`). Python already parses these into typed exceptions via `_raise_typed_c2pa_error()`.
