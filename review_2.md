# Critical Review & Improvement Plan for c2pa-python

## Context

The `c2pa-python` library is a ~4400-line monolithic Python FFI binding (`src/c2pa/c2pa.py`) over the `c2pa-rs` Rust/C library. After thorough review, there are memory safety bugs, API design issues, and idiomatic Python violations that need addressing. This plan covers fixes, API improvements, and fluent API additions.

---

## Phase 1: Critical Memory & Safety Fixes

### 1.1 Add missing `__del__` to Signer class
- **File:** `src/c2pa/c2pa.py:3098` (after `__exit__`)
- **Bug:** Every other resource-holding class (Settings:1434, Context:1680, Stream:1906, Reader:2495, Builder:3502) has `__del__` → `_cleanup_resources()`. Signer does not. Leaked Signers never free native memory.
- **Fix:** Add `def __del__(self): self._cleanup_resources()`

### 1.2 Fix `ed25519_sign` undefined behavior on immutable bytes
- **File:** `src/c2pa/c2pa.py:4394-4396`
- **Bug:** `ctypes.memset(key_bytes, 0, len(key_bytes))` where `key_bytes` is a Python `bytes` (immutable). This is UB — can corrupt CPython internals. Gives false sense of security.
- **Fix:** Use a mutable `bytearray` + ctypes array, zero the mutable buffer in `finally`. Add comment documenting the inherent limitation that Python may cache copies.

### 1.3 Fix `_convert_to_py_string` silently swallowing decode errors
- **File:** `src/c2pa/c2pa.py:791-792`
- **Bug:** Returns `""` on UTF-8 decode failure. Callers assume success. Masks data corruption from the native library.
- **Fix:** Log the error, free the pointer, raise `C2paError.Encoding`.

### 1.4 Fix Reader `__init__` wrapping C2paError in C2paError.Io
- **File:** `src/c2pa/c2pa.py:2247-2256` and `2311-2320`
- **Bug:** `except Exception` catches `C2paError.NotSupported`, `C2paError.ManifestNotFound`, etc. and re-wraps them as `C2paError.Io`, losing the original error type.
- **Fix:** Add `except C2paError: ... raise` before the generic `except Exception` block. Apply to both code paths.

### 1.5 Remove hardcoded 1MB limit in signer callback
- **File:** `src/c2pa/c2pa.py:2980-2981`
- **Bug:** `if data_len > 1024 * 1024: return -1` silently rejects large documents. No error message. Large PDFs or high-res images will fail with no indication why.
- **Fix:** Raise the limit to 100MB (or remove it — the native library enforces its own limits). Log an error when the limit is hit.

### 1.6 Remove unnecessary temp buffer + zeroing in write_callback
- **File:** `src/c2pa/c2pa.py:1840-1850`
- **Bug:** Creates temp ctypes buffer, copies data, writes, then zeros the buffer. The zeroing serves no purpose (media content, not secrets). The copy is also unnecessary.
- **Fix:** Read directly from the C buffer via `(ctypes.c_ubyte * length).from_address(data)` → `bytes(buffer)`.

### 1.7 Fix `format_embeddable` missing try/finally for memory free
- **File:** `src/c2pa/c2pa.py:4256-4259`
- **Bug:** `result_bytes_ptr[:size]` is sliced, then `c2pa_manifest_bytes_free` is called on the next line. If the slice fails, memory leaks. Rest of codebase uses try/finally.
- **Fix:** Wrap in try/finally like `_sign_internal` does.

---

## Phase 2: API Design Improvements

### 2.1 Split the 4400-line monolith into modules
Proposed structure:
```
src/c2pa/
  _ffi.py          # Library loading, _lib, function prototypes, validation
  _errors.py       # C2paError hierarchy, _raise_typed_c2pa_error, _parse_operation_result_for_error
  _enums.py        # C2paSigningAlg, C2paSeekMode, C2paDigitalSourceType, C2paBuilderIntent, LifecycleState
  _types.py        # Opaque ctypes structures, callback types, C2paSignerInfo
  _utils.py        # _convert_to_py_string, _clear_error_state, _get_mime_type_from_path, _StringContainer
  stream.py        # Stream class
  settings.py      # Settings class
  context.py       # ContextProvider, Context class
  reader.py        # Reader class
  builder.py       # Builder class
  signer.py        # Signer class
  _deprecated.py   # load_settings, read_file, read_ingredient_file, sign_file, create_signer, etc.
  _standalone.py   # ed25519_sign, format_embeddable, version, sdk_version
```
- Keep `c2pa.py` as a backward-compat re-export shim temporarily
- `__init__.py` imports from new modules

### 2.2 Use dict dispatch for `_raise_typed_c2pa_error`
- **File:** `src/c2pa/c2pa.py:807-860`
- Replace the 30-line if/elif chain with a `_ERROR_TYPE_MAP` dictionary lookup.

### 2.3 Replace `Builder.sign()` *args/**kwargs with explicit methods
- **File:** `src/c2pa/c2pa.py:3971-4080`
- **Problem:** `_parse_sign_args` manually inspects positional args by type. Breaks IDE autocompletion, type checking, is un-Pythonic.
- **Fix:** Create `sign(signer, format, source, dest=None)` and `sign_with_context(format, source, dest=None)` as explicit methods.

### 2.4 Replace `C2paSignerInfo` ctypes.Structure with a dataclass
- **File:** `src/c2pa/c2pa.py:313-374`
- Expose a `@dataclass SignerInfo` to users. Convert to ctypes internally. Keep `C2paSignerInfo` as deprecated alias.

### 2.5 De-duplicate `get_supported_mime_types`
- **File:** Reader:2029, Builder:3252 — nearly identical ~50-line methods
- Extract a shared `_get_supported_mime_types(lib_func)` helper.

### 2.6 Refactor Reader.__init__ to eliminate duplication
- **File:** `src/c2pa/c2pa.py:2150-2364` — 200+ lines, three near-identical branches
- Add `Reader.from_file(path)` and `Reader.from_stream(format, stream)` classmethods. Have `__init__` delegate to them.

### 2.7 Fix `_parse_operation_result_for_error` dead code
- **File:** `src/c2pa/c2pa.py:863-898`
- Returns `Optional[str]` but always returns `None` or raises. Callers check `if error:` on the return — always False. Fix return type and remove dead checks.

### 2.8 Clean up deprecated exports
- Remove `read_ingredient_file` and `load_settings` from `__all__` in `__init__.py`. Keep importable but not discoverable.

---

## Phase 3: Fluent API

### 3.1 Builder method chaining (backward-compatible)
Add `return self` to these Builder methods (currently return `None`):
- `set_no_embed()` → `return self`
- `set_remote_url(url)` → `return self`
- `set_intent(intent, digital_source_type)` → `return self`
- `add_resource(uri, stream)` → `return self`
- `add_ingredient(json, format, source)` → `return self`
- `add_action(action_json)` → `return self`

Enables:
```python
manifest_bytes = (
    Builder(manifest_def)
    .add_ingredient(ingredient_json, "image/jpeg", stream)
    .add_action(action_json)
    .set_intent(C2paBuilderIntent.EDIT)
    .sign(signer, "image/jpeg", source, dest)
)
```

### 3.2 Context fluent construction (optional)
Add `Context.builder()` returning a `ContextBuilder` with `.with_settings()` / `.with_signer()` / `.build()`. The current constructor API remains unchanged.

### 3.3 Settings already supports chaining
`Settings.set()` and `Settings.update()` already return `self`. No changes needed.

---

## Phase 4: Idiomatic Python Polish

### 4.1 Add `__repr__` to all public classes
No class has `__repr__` currently. Add for debugging:
```python
def __repr__(self): return f"Reader(state={self._state.name})"
```

### 4.2 Add `__slots__` to resource classes
Reduces per-instance memory ~40% for Reader, Builder, Signer, Stream, Settings, Context.

### 4.3 Use `threading.Lock` for Stream counter overflow
- **File:** `src/c2pa/c2pa.py:1730-1733` — counter reset is not atomic under threading.

### 4.4 Define a `StreamLike` Protocol
Replace runtime duck-type checks (line 1738-1749) with `typing.Protocol` for better static analysis.

### 4.5 Use `pathlib.Path` consistently
Accept `Path` objects throughout. Convert internally. Update docstrings.

---

## Verification

1. **Run existing tests:** `pytest tests/test_unit_tests.py -v` — all must pass after each phase
2. **Run threaded tests:** `pytest tests/test_unit_tests_threaded.py -v`
3. **Test fluent API:** Add new tests exercising method chaining on Builder
4. **Test error type preservation:** Verify `C2paError.ManifestNotFound` is not wrapped as `C2paError.Io`
5. **Test Signer cleanup:** Create Signer without `with` block, verify `__del__` cleans up
6. **Manual smoke test:** Run `examples/sign.py` and `examples/read.py` end-to-end
