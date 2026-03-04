# Critique: Settings and Context API design

## Context

Design critique of the Settings and Context APIs in the c2pa Python SDK, focusing on what could be improved and made more Pythonic. This is a review document, not an implementation plan — the goal is to identify issues and propose improvements for discussion.

**Last updated:** After commits through a2c2eb9 (ContextProvider switched to ABC, `_c_context` → `execution_context`).

---

## Bugs

### 1. Resource leaks in `Builder.from_archive()`

**File:** `src/c2pa/c2pa.py`, `Builder.from_archive()` classmethod

Two leaks exist:

**a) Native builder pointer leak when `context` is provided.**
`cls({}, context=context)` runs `__init__`, which allocates a native builder pointer. Then `from_archive` immediately **overwrites** `self._builder` with a new pointer from `c2pa_builder_from_archive`. The original pointer is leaked — never freed.

**b) `stream_obj` never closed on the success path.**
`stream_obj = Stream(stream)` is created without a `with` statement. `stream_obj.close()` is only called in the error branch (`if not builder._builder`). On success, the `Stream` is abandoned — cleanup depends on `__del__`, which is non-deterministic.

**Fix (a):** `from_archive` should bypass `_init_from_context` when creating the initial Builder. It could pass `context=None` to `__init__` and then manually apply the context to the archive-loaded builder, or use `object.__new__(cls)` to skip `__init__` entirely.

**Fix (b):** Use a `try/finally` or `with` block to ensure `stream_obj` is closed regardless of outcome.

### 2. Dead code on every error-handling call site

**File:** `src/c2pa/c2pa.py`, ~20 call sites

The pattern used throughout Reader/Builder/Signer:
```python
error = _parse_operation_result_for_error(_lib.c2pa_error())
if error:                    # NEVER reached — function returns None or raises
    raise C2paError(error)   # dead code
raise C2paError("...")       # always reached
```

`_parse_operation_result_for_error` either raises a typed exception or returns `None`. It never returns a string. The `if error:` branch is dead code at every call site.

**Fix:** Remove the dead `if error:` branches. Change call sites to:
```python
_parse_operation_result_for_error(_lib.c2pa_error())
raise C2paError("...")
```

---

## Non-Pythonic patterns

### 3. `Settings.set()` requires string values — no native Python types

`set("builder.thumbnail.enabled", "false")` works, but `set("builder.thumbnail.enabled", False)` raises `AttributeError` (which is then mistyped as `C2paError.Encoding`).

This is the biggest daily-use footgun. Python developers expect `True`/`False`/`42` to work, not `"true"`/`"false"`/`"42"`.

**Fix:** Accept `Any` and auto-coerce:
```python
def set(self, path: str, value) -> 'Settings':
    if isinstance(value, bool):
        value_str = "true" if value else "false"
    elif not isinstance(value, str):
        value_str = json.dumps(value)
    else:
        value_str = value
    ...
```

### 4. `Builder.sign()` makes required parameters look optional

```python
def sign(self, signer=None, format=None, source=None, dest=None) -> bytes:
```

All four parameters default to `None`, but `format` and `source` are always required. Omitting them produces a runtime `C2paError` instead of Python's natural `TypeError`. This breaks IDE autocomplete hints and type checker expectations.

**Fix:** Make the data-flow parameters positional and required, signer keyword-only:
```python
def sign(self, format: str, source, dest=None, *, signer=None) -> bytes:
```

However, this is a **breaking API change** since existing callers use `builder.sign(signer, "image/jpeg", src, dst)` with signer as the first positional arg. A migration path would be needed.

### 5. `Settings` is write-only — no read/query/repr

Once you call `settings.set(...)`, there is no way to inspect the current value, no `get()`, no `to_dict()`, no `__repr__`. Debugging requires observing side effects (e.g., "did the thumbnail get generated?").

This is partly a C API limitation (the opaque `C2paSettings` struct has no getter function exposed). But the Python layer could:
- Track all `set()` calls in a shadow dict for `__repr__` purposes
- Provide `__repr__` showing what was configured
- Store the original JSON/dict from `from_json`/`from_dict` for introspection

### 6. `Settings.set()` paths are magic strings with no discoverability

Paths like `"builder.thumbnail.enabled"` have no autocomplete, no constants, no enum. A typo like `"builder.thumbail.enabled"` silently passes (or silently fails depending on the C library behavior).

**Possible fix:** Add a `SettingsPath` constants class:
```python
class SettingsPath:
    THUMBNAIL_ENABLED = "builder.thumbnail.enabled"
    VERIFY_AFTER_SIGN = "verify.verify_after_sign"
    ...
```

Or provide a fluent builder API:
```python
settings.builder.thumbnail.enabled = False
```

The latter requires significant refactoring. The constants class is low-effort and immediately useful.

### 7. `Settings.__setitem__` exists but `__getitem__` does not

`settings["builder.thumbnail.enabled"] = "false"` works, but `settings["builder.thumbnail.enabled"]` raises `TypeError`. Half-implementing a dict interface is confusing — it violates the principle of least surprise.

**Fix:** Either add `__getitem__` (requires C API support) or remove `__setitem__` (use `set()` only). Given the C API limitation, removing `__setitem__` is simpler and more honest.

### 8. The `format` parameter in `Settings.update()` is vestigial

```python
def update(self, data, format: str = "json") -> 'Settings':
    if format != "json":
        raise C2paError("Only JSON format is supported")
```

A parameter with exactly one valid value shouldn't be a parameter. It exists for forward-compatibility (TOML support was considered), but in practice it only confuses callers.

**Fix:** Remove the `format` parameter or change to `Literal["json"]` with a deprecation warning.

### 9. MIME types are raw strings everywhere

`"image/jpeg"`, `"video/mp4"`, etc. appear as magic strings in `sign()`, `add_ingredient()`, `Reader()`. A typo like `"image/jpg"` fails at runtime.

The SDK already has `Reader.get_supported_mime_types()` and `Builder.get_supported_mime_types()`, but they return lists at runtime — no static enum exists.

**Possible fix:** A `MimeType` enum or constants namespace would catch common typos at import time:
```python
class C2paMimeType:
    JPEG = "image/jpeg"
    PNG = "image/png"
    ...
```

### 10. Error type mismatch for wrong argument types

`Settings.set("path", True)` catches the resulting `AttributeError` and re-raises it as `C2paError.Encoding`. This is misleading — it's not an encoding error, it's a type error.

**Fix:** Validate types upfront and raise `TypeError` (or `C2paError.InvalidArgument` if one existed).

---

## Inconsistencies

### 11. `_parse_operation_result_for_error` has two calling conventions

- Settings/Context use: `_parse_operation_result_for_error(None)` (let it call `c2pa_error()` internally)
- Reader/Builder/Signer use: `_parse_operation_result_for_error(_lib.c2pa_error())` (pre-fetch and pass in)

Both produce identical behavior. Pick one.

### 12. Different free strategies

- Settings/Context use generic `c2pa_free(cast(ptr, c_void_p))`
- Reader uses `c2pa_reader_free(ptr)`
- Builder uses `c2pa_builder_free(ptr)`

This works if the C API supports both, but mixing patterns makes code review harder.

### 13. `close()` sets `_closed = True` twice in Reader/Builder but once in Settings/Context

Reader/Builder set it inside `_cleanup_resources` AND in the `finally` block of `close()`. Settings/Context only set it inside `_cleanup_resources`. No functional bug, but inconsistent.

### 14. `_has_signer` set before `build()` in Context.__init__

`self._has_signer = True` is set after `set_signer` succeeds but before `build()`. If `build()` fails, the flag is stale. Not exploitable (since `is_valid` would be `False`), but inaccurate internal state.

### ~~15. `_c_context` is a private-convention name in a public Protocol~~ RESOLVED

~~`ContextProvider` is a public protocol that third-party code can implement. But it requires implementing `_c_context` — a leading-underscore property.~~

**Fixed in a2c2eb9:** `ContextProvider` is now an `ABC` (not `Protocol`) with two abstract properties: `is_valid` and `execution_context`. The underscore-prefixed `_c_context` was renamed to `execution_context`. `Context` now explicitly extends `ContextProvider`.

---

## Lower priority

### 16. `_raise_typed_c2pa_error` uses a long if-elif chain

A dict mapping `{prefix_str: ExceptionClass}` would be more maintainable than 15 if-elif branches.

### 17. `version()` is not exported from `__init__.py`

`sdk_version()` is exported, but `version()` (which returns both c2pa-c and c2pa-rs versions) is not. Users who want full version info must do `from c2pa.c2pa import version`.

### 18. `Stream` is exported but is an internal implementation detail

Users never construct `Stream` directly — the SDK wraps file objects internally. Exporting it clutters the public API surface.

### 19. Deprecated functions remain in `__all__`

`load_settings` and `read_ingredient_file` are deprecated but still in `__all__`, giving them equal prominence with the modern API.

---

## Verification

This is a review document — no code changes to verify. The findings can be validated by:
1. Reading the source at `src/c2pa/c2pa.py`
2. Running `settings.set("builder.thumbnail.enabled", False)` to confirm the `AttributeError` → `C2paError.Encoding` mistype
3. Confirming the dead-code `if error:` branches by tracing `_parse_operation_result_for_error`
4. Confirming the `from_archive` leaks: (a) add a breakpoint in `_cleanup_resources` and observe the overwritten pointer is never freed, (b) observe `stream_obj` is not closed on success path
5. Confirming item #15 is resolved: `ContextProvider` at line 1226 uses `execution_context` (no underscore) as an `@abstractmethod` on an `ABC`
