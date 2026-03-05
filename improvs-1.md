# Code Review & Refactoring Opportunities: c2pa.py

## Context
Review of [c2pa.py](src/c2pa/c2pa.py) — the main module of the c2pa-python SDK. This file contains FFI bindings to a native Rust/C library, high-level Python classes (Reader, Builder, Signer, Context, Settings, Stream), error handling, and deprecated legacy APIs.

---

## Code Review: Issues & Critiques

### 1. File is a monolith (4,367 lines)
The single file contains everything: ctypes setup, enums, error hierarchy, utility functions, 7+ major classes, and deprecated functions. This makes navigation, testing, and maintenance harder than it needs to be.

### 2. Massive code duplication

#### 2b. Lifecycle management boilerplate duplicated across 5 classes
Settings, Context, Reader, Builder, and Signer all have nearly identical:
- `_ensure_valid_state()` methods
- `_cleanup_resources()` methods (with `hasattr` checks, try/except/finally, state transitions)
- `close()` methods
- `__enter__` / `__exit__` / `__del__` methods

This is ~60-80 lines of boilerplate repeated 5 times (~350 lines total).

---

## Refactoring Opportunities

### R1. Extract a `ManagedResource` base class (HIGH IMPACT)
Create a base class that handles the lifecycle boilerplate:
```python
class ManagedResource:
    def __init__(self):
        self._state = LifecycleState.UNINITIALIZED

    def _ensure_valid_state(self): ...
    def _cleanup_resources(self): ...  # calls abstract _free_native()
    def close(self): ...
    def __enter__(self): ...
    def __exit__(self, ...): ...
    def __del__(self): ...
```
Settings, Context, Reader, Builder, and Signer would each implement `_free_native()` only. Eliminates ~300 lines of duplication.

---

## Verification
- Run existing tests: `make test` or `pytest tests/`
- Any refactoring should pass all existing tests without modification
- For the bug fixes (R5, R6), add targeted unit tests

---

## Summary
The code is well-structured at the API design level (context managers, lifecycle management, typed errors, deprecation warnings). The main issues are **extensive duplication** (lifecycle boilerplate, MIME type helpers, signing methods) and a few **bugs** (stream leaks in `_sign_common`, ineffective key erasure in `ed25519_sign`). The refactoring opportunities focus on DRY improvements that would remove ~400+ lines while making the code more maintainable.
