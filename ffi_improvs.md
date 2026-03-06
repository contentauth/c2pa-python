# C FFI Improvement Opportunities

The Rust C FFI (`c2pa_c_ffi`) exports ~70 functions. The Python layer wraps ~50. This document identifies concrete opportunities to better leverage the FFI.

### Release Library Verification

| FFI Function | In Release Library? | Python Status |
|---|---|---|
| `c2pa_builder_with_archive` | YES | Wrapped as `Builder.with_archive()` |
| `c2pa_reader_with_fragment` | YES | Wrapped as `Reader.with_fragment()` |
| `c2pa_reader_with_context_from_manifest_data_and_stream` | NO | — |
