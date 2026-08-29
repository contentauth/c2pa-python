# PR #312 — minimal fix plan

**Target:** `src/c2pa/c2pa.py` on `mathern/error-slot-sentinel` (`df29505`). Line numbers from that revision.

**Goal:** four small edits. Three fix defects confirmed by reproduction against the pinned
native build (v0.90.15); one makes the ownership logic harmless when v0.91 ships. Nothing
else changes.

All four were applied to a working copy and re-verified — before/after output in each
section.

---

## Fix 1 — After a consuming call has been issued, never free the handle

**Why:** the ownership decision currently depends on the order in which the native library
validates arguments versus taking ownership, and that order is changing.

| | `c2pa_reader_with_manifest_data_and_stream` |
|---|---|
| v0.90.15 / v0.90.16 | validate `format`/`stream`/`manifest_data`, **then** `untrack_or_return_null!(reader)` |
| `c2pa-rs` `main` (→ v0.91) | `untrack_or_return_null!(reader)` **first**; every early return drops it |

Confirmed on the pinned build:

```
with_manifest_data_and_stream(size=0)  ->  "Other: InvalidBufferSize: 0 for 'manifest_data'"
c2pa_free(old reader) -> 0             =>  handle STILL TRACKED
```

So `_PRE_CONSUME_ERROR_TAGS` is right today and wrong after the bump: the same messages will
mean "native already dropped this" while the binding keeps the pointer and frees it later.
That is the recycled-address free the PR exists to prevent.

Rather than teach the classifier to track the native ordering, remove ownership from the
classifier entirely. Under v0.91 the contract is "always consumed by native calls", so the
rule that is correct there and merely lossy on v0.90 is: **once `ffi_call` has been issued,
this binding never frees that handle.**

### Edits

`_raise_consume_failure` (lines 666–724) — all three branches collapse to the same action:

```python
        error = _read_native_error()
        if error:
            if ManagedResource._is_pre_consume_rejection(error):
                logger.warning(
                    "%s: native call rejected the handle (%s); "
                    "marked consumed, not freed",
                    type(self).__name__, error)
            self._teardown(free_handle=False)
            _raise_typed_c2pa_error(error)

        logger.debug("%s: consuming call failed without setting error",
                     type(self).__name__)
        self._teardown(free_handle=False)
        raise C2paError(error_message.format("Unknown error"))
```

`_invoke_consume` (lines 657–664) — same rule; `ctypes.ArgumentError` is still re-raised
above, so any other exception means the call reached native:

```python
        except Exception as e:
            # The call reached native, so ownership is native's to account for.
            self._teardown(free_handle=False)
            raise C2paError(error_message.format(e)) from e
```

Follow-on deletions, all mechanical:

- `_raise_consume_failure`'s `previous_state` parameter and its two call sites
  (lines 799, 817).
- `_invoke_consume`'s `reserved` keyword and its two call sites (lines 791, 809).
- `_abort_consume` (lines 745–753) is no longer reached from the failure classification.
  It stays only for the `except` branches of `_consume_no_replacement` / `_consume_into`,
  where the handle demonstrably never reached native.

`_PRE_CONSUME_ERROR_TAGS` and `_is_pre_consume_rejection` stay exactly as they are. After
this change they only pick a log line. They no longer decide whether anything is freed, so
their correctness against a given native version stops mattering.

### What this costs

On v0.90 a pre-consume rejection leaves a handle the registry still tracks and we abandon
it — a bounded leak on an error path, in exchange for making a free of a possibly-recycled
address structurally impossible. On v0.91 it is simply correct.

Retryability after a pre-consume rejection goes away: the resource is marked closed instead
of restored to ACTIVE. That promise is already false under v0.91, so it has to go regardless.
Update:

- `Reader.with_fragment` docstring (lines 3234–3239) — drop the "can be retried" wording.
- `tests/perf/scenarios.py` — `with_fragment_pre_consume_rejection`.
- the unit test asserting the resource is restored (`test_pre_consume_rejection_restores_the_resource`).

### Verified

```
Reader('image/jpeg', BytesIO(b'not an image'))   -> NotSupported: type is unsupported
Reader(..., manifest_data=b"")                   -> Other: InvalidBufferSize: 0 for 'manifest_data'
```

Both raise the same typed errors as before; neither frees the handle.

---

## Fix 2 — `_maybe_flush_pending` must re-register when a section blocks it

**Why:** it returns early on `_in_native_section()` without calling
`_register_for_section_flush(self)`, so the deferral has no remaining flush path.
`Builder.sign` nests the guards — `signer._native_call()` (line 4313) inside
`self._native_call()` (line 4308) — so the inner exit runs while the outer section is still
open. A `signer.close()` from another thread is then stranded, and since
`_cleanup_resources` skips a CLOSED resource, `close()` and `__del__` are both no-ops
afterwards. Same for `_context_guard(self._context)` at line 4332.

### Edit (lines 504–515)

```python
    def _maybe_flush_pending(self):
        if is_foreign_process(self):
            return
        with self._state_lock():
            if self._pending_teardown is None:
                return
            if getattr(self, '_inflight', 0) > 0:
                return
            if _in_native_section():
                _register_for_section_flush(self)
                return
            free_handle, self._pending_teardown = self._pending_teardown, None
            self._finish_teardown(free_handle)
```

Three changes: the `is_foreign_process` guard `_teardown` already has at line 438 (this
function is called from the section drain, where a child process would otherwise raise
`C2paError` out of an unrelated `with`); the missing registration; and moving
`_finish_teardown` inside the lock (Fix 3).

### Verified

Two `Context` objects, nested `_native_call`, `close()` from another thread:

```
before:  pending=True   handle set=True   released=False   (second close() also a no-op)
after:   pending=None   handle set=False  released=True
```

The existing `test_context_close_during_sign_defers_teardown` covers only one nesting level
— adding an enclosing `with builder._native_call():` makes it fail before this edit.

---

## Fix 3 — `_finish_teardown` idempotency

**Why:** `_released` is set as the *first* statement of `_finish_teardown` (line 492) and
`_maybe_flush_pending` calls it outside the lock, so a second entrant that arrives before
that assignment runs the whole teardown again. This breaks the invariant
`test_concurrent_close_runs_release_once` states explicitly.

### Edit (line 492)

```python
        if self._released:
            return
        self._released = True
```

Combined with running it under the lock (Fix 2), this closes both the duplicate `_release()`
and the narrow double-free window at line 496.

### Verified

Forced interleave, one resource, two threads:

```
before:  _release ran 2 times -> ['B', 'A']
after:   _release ran 1 time  -> ['A']
```

---

## Fix 4 — Re-mark the slot after a failed free

**Why:** `_free_native_ptr` logs a non-zero result and leaves
`UntrackedPointer: 0x<addr>` in the thread-local slot — and its own docstring calls that
"expected on the eager-free path". The next non-consuming failure that sets no error of its
own reads it back, with the wrong exception type. That is the defect this PR set out to
remove, displaced rather than fixed.

### Edit (lines 385–390)

```python
        result = _lib.c2pa_free(ptr)
        if result != 0:
            logger.debug("c2pa_free returned %s for an untracked pointer ", result)
            _mark_sentinel_no_native_error()
        return result
```

### Verified

```
_free_native_ptr(0x9999) -> -1
before:  next unrelated failure -> _C2paOther: Other: UntrackedPointer: 0x9999
after:   next unrelated failure -> C2paError: unrelated later op failed: Unknown error
```

---

## Deliberately out of scope

Raised in review, not fixed here — each is either subsumed or too large for this PR:

- **`_abort_consume` reviving a resource with a queued teardown.** Reachable state
  (`is_valid == True` with `_pending_teardown` set), but after Fix 1 it is no longer on the
  failure-classification path. A one-line `if self._pending_teardown is not None: return`
  can be added if the reviewer wants it; it is not required for correctness of the paths
  that exist today.
- **`_release_handle` mutating state outside the lock** (lines 517–525). After Fix 1 its
  last caller in the consume paths is gone.
- **`_native_section`'s `finally` masking the body's exception** (lines 1091–1092). Real,
  but the fix touches the section generator's control flow; not worth the blast radius here.
- **`with_fragment` same-thread re-entrancy** (`RLock` + `blocking=False`, lines 3142, 3256).
  Under Fix 1 a re-entered call no longer leads to a free of the reused handle.
- **Import-time `ImportError` from `_learn_sentinel_no_native_error_text`** (line 1450) and
  the registry-mutex cost of planting the marker. Both are policy calls for the author.
- **Argument preflighting in Python** (rejecting `manifest_data=b""` and similar before the
  FFI call). Worth doing, but it is a behavioural change across several public entry points
  and Fix 1 already removes the ownership hazard it was proposed to close.

---

## Landing order

Fixes 2, 3 and 4 are independent of the native version and of each other; they can go in
first. Fix 1 carries the behaviour change and the test updates, and is the one that has to
land before v0.91.
