# C FFI Improvement Opportunities

The Rust C FFI (`c2pa_c_ffi`) exports ~70 functions. The Python layer wraps ~50. This document identifies concrete opportunities to better leverage the FFI.

### Release Library Verification

| FFI Function | In Release Library? |
|---|---|
| `c2pa_builder_with_archive` | YES |
| `c2pa_reader_with_fragment` | YES |
| `c2pa_reader_with_context_from_manifest_data_and_stream` | NO |

---

## 1. Add `Builder.with_archive()` instance method

The FFI exports `c2pa_builder_with_archive(builder, stream) -> *mut C2paBuilder` — a consume-and-return function that loads an archive into an existing builder, preserving its context/settings. Python has no equivalent. The existing `from_archive()` is a static factory that creates a context-free builder.

Mirrors the C++ API in `contentauth/c2pa-c`:

- `Builder::from_archive(stream)` — static factory, no context
- `Builder::with_archive(stream)` — instance method, preserves context, returns `*this`

**Add:** `Builder.with_archive(stream)` instance method. Leave `from_archive()` unchanged.

**Breaking change:** Remove `context` parameter from `from_archive()`. It currently accepts context but never uses it in the archive loading path (always calls `c2pa_builder_from_archive`). Two existing tests pass context to `from_archive()` — these must be migrated to use `with_archive()` instead.

### Existing tests to migrate

These tests currently call `Builder.from_archive(archive, context)` — they must switch to the `with_archive()` API:

- `test_archive_sign_trusted_via_context` (line 5927) → use `Builder({}, context).with_archive(archive)`
- `test_archive_sign_with_ingredient_trusted_via_context` (line 5964) → same migration

### Tests for `Builder.with_archive()`

In `TestBuilderWithContext` class. Mirrors C++ tests from `contentauth/c2pa-c` (`LoadArchiveWithContext`, `ArchiveRoundTripSettingsBehavior`) and existing `test_archive_sign*` patterns.

#### New tests

Tests 1-2 replace the migrated tests. Tests 3-7 cover new behavior.

Pruned: `test_with_archive_sign` and `test_with_archive_sign_with_added_ingredient` (without trust) would be redundant — test 1 already covers the basic archive→sign flow, and test 5 covers definition replacement. The non-trust `test_archive_sign*` variants in `TestBuilderWithSigner` already cover `from_archive` round-trips without trust and remain unchanged.

1. **`test_with_archive_sign_trusted_via_context`** (replaces existing) — Builder with trust context, `to_archive()`, new Builder with context, `with_archive()`, sign, verify "Trusted"

2. **`test_with_archive_sign_with_ingredient_trusted_via_context`** (replaces existing) — Same as above but with added ingredient after `with_archive()`

3. **`test_with_archive_preserves_settings`** (mirrors C++ `LoadArchiveWithContext`) — Builder with context that disables thumbnails, `to_archive()`, new Builder with same no-thumbnail context, `with_archive()`, sign, verify manifest has **no** `thumbnail` key

4. **`test_with_archive_returns_self`** — `result = builder.with_archive(stream)`, assert `result is builder`

5. **`test_with_archive_replaces_definition`** — Builder with title "Original" → archive, new Builder with title "Replaced" + context → `with_archive()`, sign, verify "Original" in output

6. **`test_with_archive_on_closed_builder_raises`** — Close builder, assert `with_archive()` raises `C2paError`

7. **`test_from_archive_roundtrip`** (mirrors C++ `ArchiveRoundTripSettingsBehavior`) — Builder with no-thumbnail context → archive → `from_archive(archive)` (no context) → sign, verify manifest **has** thumbnail (settings lost). Characterization test.

## Not Gaps

- **JSON parsing for field extraction** — The FFI doesn't offer field-specific getters (e.g., get_active_manifest). Python's approach of parsing `c2pa_reader_json()` output is the correct and only option.
- **`c2pa_reader_new()`** — Creates an empty reader. Python always creates readers with streams, so this isn't needed.
- **Error codes** — The FFI uses string-prefix error typing (`"ErrorType: message"`). Python already parses these into typed exceptions via `_raise_typed_c2pa_error()`.
