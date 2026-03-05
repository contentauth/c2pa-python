# Integrate LifecycleState from PR #228 into Settings, Context, and all objects

## Context

PR #228 (`mathern/improvs`) refactors Reader and Builder to replace dual-boolean state tracking (`_closed` + `_initialized`) with a single `LifecycleState` enum. The current branch (`mathern/context`) has Settings and Context classes that use the same dual-boolean pattern. This plan extends the LifecycleState pattern to **all** stateful objects: Settings, Context, Reader, Builder, and Signer. Stream is excluded (callbacks check booleans in hot paths, and PR #228 also excluded it).

**Approach**: Manually integrate the patterns from PR #228 (not a git merge, since the branches have diverged significantly — PR #228 removed Context/Settings entirely).

## Changes

### 1. Add LifecycleState enum (~line 202, after `C2paBuilderIntent`)

```python
class LifecycleState(enum.IntEnum):
    """Internal state for lifecycle management.
    Object transitions: UNINITIALIZED -> ACTIVE -> CLOSED
    """
    UNINITIALIZED = 0
    ACTIVE = 1
    CLOSED = 2
```

`enum` import already exists at line 15.

### 2. Convert each class (in [c2pa.py](src/c2pa/c2pa.py))

For **each** of Settings, Context, Reader, Builder, Signer — apply the same mechanical transformation:

| Before | After |
|--------|-------|
| `self._closed = False; self._initialized = False` | `self._state = LifecycleState.UNINITIALIZED` |
| `self._initialized = True` | `self._state = LifecycleState.ACTIVE` |
| `if self._closed: return` | `if self._state == LifecycleState.CLOSED: return` |
| `self._closed = True` | `self._state = LifecycleState.CLOSED` |
| `not self._closed and self._initialized` | `self._state == LifecycleState.ACTIVE` |
| `hasattr(self, '_closed') and not self._closed` | `hasattr(self, '_state') and self._state != LifecycleState.CLOSED` |

Class-specific notes:
- **All classes**: Keep using `_lib.c2pa_free(ctypes.cast(...))` — no dedicated typed free functions exist in the native library
- **Signer**: Only has `_closed` (no `_initialized`), so init directly to `ACTIVE`
- **Stream**: Leave unchanged (hot-path callbacks, public `closed`/`initialized` properties)

### 4. Reader `__init__` file management improvement

Change `with open(path, 'rb') as file:` to manual `file = open(path, 'rb')` with explicit cleanup in error paths. This prevents the context manager from closing the file while Reader still needs it.

### 5. frozenset cache for MIME types (Reader + Builder)

- Change `_supported_mime_types_cache` from list to `frozenset`
- Return `list(cache)` from `get_supported_mime_types()` (defensive copy)
- Add `_is_mime_type_supported(cls, mime_type)` classmethod for O(1) lookup

### 6. Update tests ([test_unit_tests.py](tests/test_unit_tests.py))

- Add `LifecycleState` to imports from `c2pa.c2pa`
- Replace all `reader._closed` / `reader._initialized` assertions with `reader._state == LifecycleState.CLOSED` / `LifecycleState.ACTIVE`
- Same for Builder, Signer test assertions
- Settings/Context tests already use `is_valid` property — no changes needed

## Verification

1. Run `python -m pytest tests/test_unit_tests.py -v` — all tests pass
2. Verify Settings/Context lifecycle: create, use, close, verify `_state` transitions
3. Verify Stream is unchanged and still works
4. Formatting must pass
