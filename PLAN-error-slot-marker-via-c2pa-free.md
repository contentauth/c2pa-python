# Plan: plant the error-slot marker via c2pa_free, drop the c2pa_error_set_last runtime dependency

Implementation handoff. All facts below were verified against the current
checkout of this branch (`mathern/error-slot-sentinel`, merge commit
`f84c088` plus the `_teardown` gate restoration) and against the c2pa-rs
sources in `../c2pa-rs`. Line numbers refer to the current state of
`src/c2pa/c2pa.py`; re-grep before editing if the file has moved.

## Why

The error-slot fix on this branch plants a marker into the native
thread-local error slot before every consuming call, and re-plants it after
every read, so a stale message left by an earlier call on the same pooled
thread is never misread as the current failure's error. That marker decides
whether a failed consuming call retains or consumes the native handle, so a
stale read can cause a wrong free decision.

Planting currently uses `c2pa_error_set_last`, an export added to c2pa-rs
for this purpose. Any native build that predates the export cannot load this
module (the unconditional prototype setup raises `AttributeError` at import).

Planting cannot be avoided altogether: the slot is a single sticky
thread-local cell, `c2pa_error()` only peeks, and no export clears it.
Detecting "this call wrote nothing" requires starting from a state no
genuine call can produce, and creating that state is planting. What can be
avoided is the new-export dependency:

`c2pa_free` on an address the registry does not track deterministically
writes an error into the same slot. Verified in c2pa-rs:
`c2pa_c_ffi/src/c_api.rs:995` routes to `cimpl_free`
(`c2pa_c_ffi/src/cimpl/utils.rs:320-345`), and a registry miss executes
`CimplError::untracked_pointer(ptr).set_last()`, whose message is
`format!("UntrackedPointer: 0x{:x}", ptr)` (`cimpl/cimpl_error.rs:101-103`).
So `_lib.c2pa_free(1)` plants a fixed, known text using only exports every
shipped native lib already has (`c2pa_free`, `c2pa_error`). Address 1 is
never a real handle: heap allocations are aligned, and the Python layer only
ever passes real handles or this constant, so the planted text cannot
collide with a genuine error about a real pointer.

The exact wire text (with or without an `"Other: "` prefix, exact hex casing)
is a native implementation detail, so the module learns it once at import by
planting and reading back, instead of hardcoding it.

## Changes to src/c2pa/c2pa.py

### 1. Marker constants and helpers (replace lines 852-856)

Delete:

```python
_NO_NATIVE_ERROR_MARKER = b"c2pa-python-no-native-error"
_NO_NATIVE_ERROR = b"Other: " + _NO_NATIVE_ERROR_MARKER


def _is_no_native_error(message: str) -> bool:
    """True for the marker meaning "no error of our own", in either spelling."""
    marker = _NO_NATIVE_ERROR_MARKER.decode('utf-8')
    return message == marker or message == f"Other: {marker}"
```

Replace with:

```python
# Address deliberately passed to c2pa_free to plant a marker in the native
# error slot. Never a real handle: allocations are aligned, and the Python
# layer only passes real handles or this constant to c2pa_free.
_MARKER_ADDR = 1

# Exact text the native lib writes for a failed free of _MARKER_ADDR.
# Learned at import by _learn_no_error_text(); the format is a native
# implementation detail, so it is read back rather than hardcoded.
_NO_NATIVE_ERROR_TEXT = None


def _plant_no_error_marker():
    """Write the no-error marker into this thread's native error slot.

    A c2pa_free of an address the registry does not track writes
    "UntrackedPointer: 0x1" (learned exactly at import) into the
    thread-local error slot and returns -1, which is expected here.
    Calls _lib.c2pa_free directly: _free_native_ptr would log each plant.
    """
    _lib.c2pa_free(_MARKER_ADDR)


def _is_no_native_error(message: str) -> bool:
    """True for the planted marker meaning "no error of our own"."""
    return message == _NO_NATIVE_ERROR_TEXT
```

### 2. Import-time learning (new code, placed immediately after line 1254's `_setup_function(_lib.c2pa_free, [ctypes.c_void_p], ctypes.c_int)`)

The learning must run after the prototypes for `c2pa_free`, `c2pa_error`,
and `c2pa_string_free` are configured. `c2pa_error`/`c2pa_string_free` are
set up at lines 1049-1051; `c2pa_free` at line 1254 is the last of the
three, so the snippet goes right below it:

```python
def _learn_no_error_text():
    """Plant the marker once and read back the exact text the native lib
    produces for it, so equality checks match this build of the lib.

    Runs on the importing thread; the text is a format constant, so the
    learned value holds for every thread. Raises at import when the read
    back text is empty, because the marker mechanism cannot work then.
    """
    _plant_no_error_marker()
    raw = _lib.c2pa_error()
    if not raw:
        raise ImportError(
            "c2pa native library did not report an error for a free of "
            "an untracked pointer; the error-slot marker cannot work")
    try:
        text = ctypes.string_at(raw).decode('utf-8')
    finally:
        _lib.c2pa_string_free(raw)
    if not text:
        raise ImportError(
            "c2pa native library reported an empty error for a free of "
            "an untracked pointer; the error-slot marker cannot work")
    return text


_NO_NATIVE_ERROR_TEXT = _learn_no_error_text()
```

Note: `_read_native_error` cannot be reused for learning — it maps the
marker to `None` and replants, and at learning time the marker text is not
yet known. The raw read above is intentional.

Sanity check to add right after (a one-line assert is fine): the learned
text must contain the hex form of `_MARKER_ADDR`
(`assert "0x1" in _NO_NATIVE_ERROR_TEXT`), so a native change that breaks
the assumption fails loudly at import, not silently at the first consume
failure.

### 3. Replace both planting call sites

- Line 594 in `_invoke_consume`:

  ```python
  # Same thread that makes the call, same thread-local slot.
  _lib.c2pa_error_set_last(_NO_NATIVE_ERROR)
  ```

  becomes

  ```python
  # Same thread that makes the call, same thread-local slot.
  _plant_no_error_marker()
  ```

- Line 884 at the end of `_read_native_error`:

  ```python
  _lib.c2pa_error_set_last(_NO_NATIVE_ERROR)
  ```

  becomes

  ```python
  _plant_no_error_marker()
  ```

  The docstring of `_read_native_error` (lines 860-869) stays accurate as
  written; no change needed there. The comment block above the deleted
  constants (lines 844-848) is replaced by the new constants' comments in
  change 1.

### 4. Make the c2pa_error_set_last prototype conditional (line 1051)

```python
_setup_function(_lib.c2pa_error_set_last, [ctypes.c_char_p], ctypes.c_int)
```

becomes

```python
# Optional: only newer native builds export this. The runtime does not
# call it; tests use it, when present, to simulate native error writes.
if getattr(_lib, 'c2pa_error_set_last', None) is not None:
    _setup_function(
        _lib.c2pa_error_set_last, [ctypes.c_char_p], ctypes.c_int)
```

Caveat for the implementer: `ctypes` raises `AttributeError` on missing
symbols at attribute access, and `getattr` with a default swallows exactly
that. Confirm with the vendored dylib (symbol present) that the guarded
branch still executes.

### 5. Grep afterward

`grep -n c2pa_error_set_last src/c2pa/c2pa.py` must show only the guarded
prototype setup from change 4. `grep -n _NO_NATIVE_ERROR src/c2pa/c2pa.py`
must show only `_NO_NATIVE_ERROR_TEXT`.

## Changes to tests/test_unit_tests.py

The test file references the old constant and the old mechanism in a few
places. Current anchors:

- Line 57 (inside the `_fail_with_native_error` mock-builder) and lines
  8368, 8396, 9246, 9322, 9357, 9689, 9710: these use `c2pa_error_set_last`
  to *simulate native code writing an error* (stand-ins for what failing
  native calls do). They keep using it — the vendored dylib exports the
  symbol, and the simulation is test-only. Do not rewrite these.

- Lines 9880-9894, `test_the_no_native_error_sentinel_never_reaches_a_caller`:
  this test plants the marker with
  `c2pa_module._lib.c2pa_error_set_last(c2pa_module._NO_NATIVE_ERROR)`
  (twice) and derives the leak-check string via
  `sentinel = c2pa_module._NO_NATIVE_ERROR.decode("utf-8")`. Rewrite it to:
  `sentinel = c2pa_module._NO_NATIVE_ERROR_TEXT` (already a str, no decode)
  and replace both plant lines with
  `c2pa_module._plant_no_error_marker()`. The assertions themselves
  (marker read maps to None; marker text never appears in a raised
  message) stay exactly as they are.

### New tests (add near the existing sentinel tests, same class)

Test 1 — the plant writes the learned text:

```python
def test_plant_marker_writes_learned_text(self):
    c2pa_module._plant_no_error_marker()
    raw = c2pa_module._lib.c2pa_error()
    try:
        text = ctypes.string_at(raw).decode('utf-8')
    finally:
        c2pa_module._lib.c2pa_string_free(raw)
    self.assertEqual(text, c2pa_module._NO_NATIVE_ERROR_TEXT)
```

Test 2 — the planted marker reads back as "no error":

```python
def test_read_native_error_maps_marker_to_none(self):
    c2pa_module._plant_no_error_marker()
    self.assertIsNone(c2pa_module._read_native_error())
```

Test 3 — a stale error is not misattributed to a failure that set nothing.
This is the scenario the whole mechanism exists for; it may already be
covered by the existing sentinel tests around line 9884 once they are
switched to the helper — if so, verify that coverage instead of duplicating
it. The shape, if needed:

```python
def test_stale_error_not_misattributed_after_plant(self):
    # A realistic stale tag from an earlier, unrelated call.
    c2pa_module._lib.c2pa_error_set_last(
        b"Other: UntrackedPointer: 0xdeadbeef")

    res = self._FakeHandleResource()
    res._activate(0xCAFE)

    # Fails without setting any error of its own. The plant inside
    # _invoke_consume must have cleared the stale tag, so this routes
    # to the "no error of our own" branch: consumed, not retained.
    with self.assertRaises(Error):
        res._consume_no_replacement(lambda h: -1, "op failed: {}")

    self.assertIsNone(res._handle)
    self.assertEqual(res._lifecycle_state, LifecycleState.CLOSED)
    self.assertEqual(self.freed, [], "consumed branch must not free")
```

(`_FakeHandleResource`, `self.freed`, and the free instrumentation already
exist in that test class — reuse them, do not reinvent. Check the class
`setUp` for how `_free_native_ptr` is patched and restored.)

Test 4 — the runtime no longer depends on the export. A source-inspection
test, since the symbol cannot be removed from a loaded dylib:

```python
def test_runtime_does_not_call_error_set_last(self):
    import inspect
    for fn in (c2pa_module.ManagedResource._invoke_consume,
               c2pa_module._read_native_error,
               c2pa_module._plant_no_error_marker):
        self.assertNotIn(
            'c2pa_error_set_last', inspect.getsource(fn))
```

## Testing — run all of it, in this order

1. The new tests by name, reading each test's own result line:
   `python -m unittest tests.test_unit_tests.<Class>.<test> -v` for each.
2. The full plain suite: `python -m unittest tests.test_unit_tests -v`.
3. The full threaded suite (the marker interacts with the native-section
   deferral machinery, and the threaded suite is what caught the last merge
   regression): `python -m unittest tests.test_unit_tests_threaded -v`.
   All 543 tests across both suites currently pass; that number must hold.
4. Red proof for test 3 (only if test 3 was added): temporarily comment out
   the `_plant_no_error_marker()` line inside `_invoke_consume`, run test 3
   by name, confirm it fails (the stale tag is then read and the handle is
   wrongly retained), restore the line, confirm green. One inversion, one
   targeted run — do not replay the whole suite around it.
5. The subprocess-based crash tests in the threaded suite
   (`TestSharedSignerTeardownRace`, `TestForkedChildDoesNotDeadlock`) run as
   part of step 3; they cover the free/error-slot interplay under real
   threads. Do not skip them for speed.

## Out of scope

- The registry's address-only keying (no generation counter) is a native
  c2pa-rs gap and cannot be fixed here.
- c2pa-rs v0.91.0 makes pointers always-consumed, which removes the whole
  retain-vs-consume decision this marker feeds. When the binding moves to
  that version, `_plant_no_error_marker`, `_NO_NATIVE_ERROR_TEXT`,
  `_learn_no_error_text`, and `_is_no_native_error` all become removable —
  worth a code comment on `_plant_no_error_marker` saying so.
- Performance: each plant briefly takes the native registry mutex (a
  `HashMap` lookup miss under `Mutex`), where `c2pa_error_set_last` only
  touched thread-local storage. Consuming calls are not hot-path; if the
  perf suite (`tests/perf`) disagrees, the fallback is to prefer
  `c2pa_error_set_last` when the symbol exists. Run
  `tests/perf/scenarios.py` only if the baseline is already set up locally;
  do not treat it as a gate.
