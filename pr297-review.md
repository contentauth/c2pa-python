# Review: c2pa-python PR #297 (`mathern/open-up-api-3`, at `1883b3a`) — single-contract update

**Context change:** the restore-on-error native branch (`try-assign`) is no longer
coming; the binding targets only the released C FFI semantics (v0.90.0-style). That
collapses the dual contract to one, and it changes what the eager free is *for* — which
affects one branch of the new code.

## Integrated correctly (verified)

- **`build` leak fixed** exactly as planned: `builder_ptr` is nulled only when
  `context_ptr` is non-null, so the pre-consume rejection (the only null path in the
  released FFI) leaves the pointer for the recovery block to free. Covered by
  `test_context_build_null_return_frees_builder`.
- **`set_signer` triage** landed via a better factoring than the plan's sketch:
  `_invoke_consume` (shared call wrapper) + `_raise_consume_failure` (shared triage) +
  thin `_consume_and_swap` / `_consume_no_replacement`. The ordering trap is explicitly
  internalized — the docstring states the error is read before any free "so a free's own
  pointer-tracking error cannot overwrite it." The call-site comment now correctly says a
  rejected signer is retained. Success/retain/consumed paths each have a test.
- Both consume flavors share one `_PRE_CONSUME_ERROR_TAGS` triage, which is the
  centralization PR #294 promised.

## Findings

### 1. MEDIUM — `_safe_release()` now swallows `KeyboardInterrupt` and `SystemExit`

The change from `except Exception` to `except BaseException` makes the
interrupt-in-release tests pass by *suppressing* the interrupt: it is logged as "Failed
to release resources" and the program continues. A user pressing Ctrl-C while `close()`
runs a slow `_release()` (stream teardown) gets their interrupt eaten; `sys.exit()`
raised anywhere under a teardown path is likewise cancelled. That is a behavioral
regression reaching well beyond memory handling, and it isn't needed to fix the
stranded-handle problem — free-and-propagate does both:

```python
self._lifecycle_state = LifecycleState.CLOSED
try:
    self._safe_release()          # back to catching Exception only
finally:
    if self._handle:
        try:
            ManagedResource._free_native_ptr(self._handle)
        except Exception:
            logger.error("Failed to free native %s resources",
                         type(self).__name__, exc_info=True)
        finally:
            self._handle = None
```

The interrupt then still frees the handle on the way out (the existing
`test_interrupt_in_release_still_frees_handle` should pass unchanged if it asserts the
free, not the suppression) *and* propagates. Apply the same shape in
`_cleanup_resources`. Worth noting the stakes are low under the single contract — on
every post-native-failure use of `_release_handle` the native side already dropped the
memory, so an escaped interrupt strands nothing real; the only genuine leak case is a
second interrupt landing inside teardown that a first interrupt triggered. Suppressing
Ctrl-C globally is a high price for that corner.

### 2. MEDIUM — with restore-on-error gone, the "ownership transferred" branch should stop freeing

The eager `_release_handle()` on the non-tag error branch of `_raise_consume_failure`
was justified as forward-compatibility: mandatory under try-assign, guarded no-op under
the release. With try-assign off the table, that branch's free is **permanently** a
guaranteed `-1` that frees nothing (the released FFI drops the value inside the failing
call), and it permanently keeps two side effects:

- it writes `UntrackedPointer:` into the sticky thread-local slot on every such failure
  (harmless to the raised error, which is copied first, but it leaves the slot dirty for
  any later reader without a fresh error);
- it keeps the recycled-address race alive in multithreaded use: between the native
  internal drop (GIL released during the failing call) and our `c2pa_free`, another
  thread inside its own FFI call can allocate a tracked object at the recycled address —
  our `-1`-intended free then finds a live registry entry and destroys the other
  thread's object. Transitional before; permanent now.

Under the single contract, ownership on this branch is *known*, not defensive: a
non-tag error means the native side consumed and dropped the value. The exact action is
`_mark_consumed()` — no free call, no slot write, no race:

```python
# in _raise_consume_failure, non-tag branch:
self._mark_consumed()
_raise_typed_c2pa_error(error)
```

Keep `_release_handle()` where ownership is genuinely unknown, because there the guarded
free is the right both-ways default (we own it → real free; consumed → `-1`):
- the `except BaseException` branch of `_invoke_consume` (async exception, unknown
  timing), and
- the unknown-error fallthrough (null/-1 with an empty slot — no released-FFI path does
  this, so it's defensive by definition).

Update `test_consume_no_replacement_frees_on_other_error` to assert `_mark_consumed`
semantics (closed, handle nulled, **no** free call) — its current name and assertion
encode the dual-contract behavior that no longer applies.

### 3. LOW — docs and comments to realign with the single contract

- `_release_handle`'s docstring lost its rationale entirely (and has a ".." typo). With
  finding 2 applied its remaining roles are: unknown-ownership error paths and
  known-owned frees; one sentence on why the guarded free is correct for both is enough.
- `_safe_release`'s docstring ("safely (no raise)") should be restored to match the
  `except Exception` behavior from finding 1.
- The earlier suggestion to convert `with_definition` in the native branch is moot —
  drop it. Its Python handling is already correct under the single contract, and with
  finding 2 its post-consume failures also stop producing permanent `-1` debug noise.
- The dual-contract explanation drafted for `docs/native-resources-management.md` should
  be written single-contract instead: pre-consume tags ⇒ retained; any other error ⇒
  consumed and dropped natively, nothing to free; unknown ⇒ guarded free.

## Order

1 (`_safe_release` revert + `finally`-guarded frees) and 2 (`_mark_consumed` on the
known-consumed branch + test update) are independent and small; then 3 (doc realignment)
in the same PR.

---

# Refactoring opportunities (simplification pass)

The single-contract decision doesn't just permit simplification — several defensive
structures existed only to serve the contract ambiguity. Ranked by leverage:

## R1 — Wrap the native context builder in a `ManagedResource`; delete the recovery block

The raw-pointer juggling in `Context.__init__` (manual `builder_ptr`, the
`except BaseException` recovery block, and the `if context_ptr: builder_ptr = None`
subtlety that hosted the leak bug) exists because the native builder is the one handle
in the codebase *not* managed by the lifecycle machinery this PR series built. Close
that gap with a private ~10-line class and a third consume flavor:

```python
class _NativeContextBuilder(ManagedResource):
    """Short-lived wrapper so builder teardown rides the normal lifecycle."""
    def __init__(self):
        super().__init__()
        ptr = _lib.c2pa_context_builder_new()
        _check_ffi_operation_result(ptr, "Failed to create ContextBuilder")
        self._activate(ptr)
```

```python
def _consume_into(self, ffi_call, error_message):
    """Consuming call that produces a *different* object's pointer.

    On success this handle was consumed (mark, don't free) and the new
    pointer is returned for the caller to own. Failure triage is shared.
    """
    result = self._invoke_consume(ffi_call, error_message)
    if result:
        self._mark_consumed()
        return result
    self._raise_consume_failure(error_message)
```

`Context.__init__` then reads as the sequence it is:

```python
with _NativeContextBuilder() as nb:
    if settings is not None:
        _check_ffi_operation_result(
            _lib.c2pa_context_builder_set_settings(nb._handle, settings._c_settings),
            "Failed to set settings on Context", check=lambda r: r != 0)
    if signer is not None:
        signer._ensure_valid_state()
        self._signer_callback_cb = signer._callback_cb
        signer._consume_no_replacement(
            lambda h: _lib.c2pa_context_builder_set_signer(nb._handle, h),
            "Failed to set signer on Context: {}")
        self._has_signer = True
    context_ptr = nb._consume_into(
        lambda h: _lib.c2pa_context_builder_build(h),
        "Failed to build Context: {}")
self._activate(context_ptr)
```

Every failure path — settings error, retained signer, build rejection, async interrupt —
is handled by `__exit__` → `close()`, which frees iff the builder wasn't consumed. The
leak I found earlier becomes *structurally impossible* rather than patched, and the
`_consume_into` triage means a `build` pre-consume rejection is retained-then-freed-once
instead of relying on call-site ordering. (`ManagedResource` already provides
`close`/`__enter__`/`__exit__`, so the wrapper costs nothing extra. `_activate` after the
`with` keeps ownership transfer to the `Context` outside the builder's scope, mirroring
`_wrap_native_handle`'s ownership-on-success rule.)

This also gives the three consume flavors a complete, symmetric story worth stating in
the class docstring: `_consume_and_swap` (replacement for self), `_consume_no_replacement`
(status code), `_consume_into` (pointer for someone else) — all three = `_invoke_consume`
+ result check + `_raise_consume_failure`.

## R2 — One teardown implementation instead of three

`_mark_consumed`, `_release_handle`, and `_cleanup_resources` each hand-roll the same
shape: foreign-process check → CLOSED → `_safe_release()` → maybe free → null handle.
Three copies is where the next drift starts (finding 1's `finally` fix would currently
need to be applied twice). Fold them:

```python
def _teardown(self, free_handle: bool):
    if is_foreign_process(self):
        self._handle = None
        self._lifecycle_state = LifecycleState.CLOSED
        return
    self._lifecycle_state = LifecycleState.CLOSED
    try:
        self._safe_release()              # except Exception (finding 1)
    finally:
        handle, self._handle = self._handle, None
        if free_handle and handle:
            try:
                ManagedResource._free_native_ptr(handle)
            except Exception:
                logger.error("Failed to free native %s resources",
                             type(self).__name__, exc_info=True)

def _mark_consumed(self):
    self._teardown(free_handle=False)

def _release_handle(self):
    if self._lifecycle_state != LifecycleState.ACTIVE:
        self._handle = None
        self._lifecycle_state = LifecycleState.CLOSED
        return
    self._teardown(free_handle=True)
```

`_cleanup_resources` keeps its own not-already-CLOSED / `hasattr` guards and delegates
the rest to `_teardown(True)`. One place now owns the foreign-process rule, the CLOSED
ordering, and the interrupt-safe free — and finding 1's fix lands exactly once.

## R3 — Retire `_parse_operation_result_for_error`

Call-site census: `_check_ffi_operation_result` is the workhorse (29 uses);
`_parse_operation_result_for_error` has 5, and its dual behavior (result-as-error-string
vs read-slot-and-raise) is the kind of overloading the PR description already started
pruning ("removed function that did not clear previous error"). Its slot-reading mode is
now `_read_native_error()` + `_raise_typed_c2pa_error()` — the exact pair
`_raise_consume_failure` uses — and its string-parsing mode is `_raise_typed_c2pa_error`
directly. Migrating the 5 sites leaves three primitives with one job each (read, raise,
check-and-raise) plus the consume-triage built on them. Fewer names, one error-reading
discipline.

## R4 — Small cleanups (batch into one commit)

- The `except ctypes.ArgumentError: raise` clause in `_invoke_consume` is purely
  documentary (catch-and-reraise). Fine to keep for the comment's sake, but the comment
  can live on the `BaseException` clause and the clause can go — one branch fewer to
  read.
- `_release_handle`'s "normalize states" pre-ACTIVE branch and the foreign-process
  branch both collapse into R2's structure; after R2, `_release_handle` is three lines.
- With finding 2 applied, grep for remaining `_release_handle` callers: only the two
  unknown-ownership sites should survive. Any other caller is a smell — a site that
  knows ownership and should say `_mark_consumed` or rely on `close()`.
- The interrupt tests should assert the *free happened and the interrupt propagated*
  (`pytest.raises(KeyboardInterrupt)` around the close), pinning finding 1's semantics
  instead of the current suppression.

## Updated order

Finding 1 + R2 land together (the `finally` fix is written once, inside `_teardown`).
Then finding 2 (one-line branch change + test update). Then R1 (`_NativeContextBuilder`
+ `_consume_into`, deleting the recovery block). R3 and R4 as follow-up cleanup commits.

---

# Re-review at `927f846` ("fix: refactor")

## Resolved (verified branch-by-branch)

- **R2 landed**: `_teardown(free_handle)` is now the single owner of the
  foreign-process rule, CLOSED ordering, and the guarded free; `_release_handle` is a
  guard plus `_teardown(True)`; `_cleanup_resources` delegates. `_mark_consumed` is
  gone with no dangling callers (tests renamed).
- **Finding 2 landed**: the known-consumed branch uses `_teardown(free_handle=False)`
  with the rationale (guarded no-op, slot dirtying, recycled-address race) in the
  comment. `_release_handle` survives only at the two unknown-ownership sites, exactly
  as intended.
- **R1 landed**: `Context._NativeBuilder` + `_consume_into` replace the raw-pointer
  recovery block. Checked every path: pre-consume rejection → retained → freed exactly
  once by `__exit__`; consumed-then-failed → close is a no-op; success → close no-op,
  `_activate(context_ptr)` outside the `with`. The build-leak class is structurally
  gone. The three consume flavors now share `_invoke_consume` + `_raise_consume_failure`.
- **R3 landed**: `_parse_operation_result_for_error` deleted; its 5 sites migrated to
  `_check_ffi_operation_result` / `_read_native_error` + `_raise_typed_c2pa_error`.
  Side benefit: `_check_ffi_operation_result` now raises *typed* errors where it
  previously raised bare `C2paError` — compatible (subclasses are `C2paError`) and
  strictly more informative; worth one line in the PR description.
- `_safe_release` is back to `except Exception` with an accurate docstring.

## New findings

### A. MEDIUM — `_teardown` took half of finding 1: the `finally` is missing

Finding 1 had two parts: revert `_safe_release` to `Exception` (done) *and* make the
free un-skippable via `try/finally` (not done). As written, a `KeyboardInterrupt`
inside a subclass `_release()` escapes `_teardown` with the state already CLOSED and
the handle still set; every later teardown path early-returns on CLOSED, so an
**owned** handle leaks — and because `_teardown` is now the single teardown path, this
applies to every `close()`, `__del__`, and consume-failure in the codebase. One-line
shape fix:

```python
self._lifecycle_state = LifecycleState.CLOSED
try:
    self._safe_release()
finally:
    handle, self._handle = self._handle, None
    if free_handle and handle:
        try:
            ManagedResource._free_native_ptr(handle)
        except Exception:
            logger.error("Failed to free native %s resources",
                         type(self).__name__, exc_info=True)
```

The two interrupt tests were deleted in this commit rather than repointed. Reinstate
them with the corrected assertion: the handle is freed **and** the interrupt
propagates (`pytest.raises(KeyboardInterrupt)` around the close) — that pins both
halves of the intended semantics and would have caught this.

### B. MEDIUM — the `BaseException → Exception` sweep overcorrected in raw-pointer recovery blocks

The narrowing was right where the old code *suppressed or wrapped* the exception
(`_safe_release`; the signing path that wrapped everything in `C2paError`). It is wrong
where the block **frees a raw pre-activation pointer and re-raises**: Settings
`__init__`, both Reader construction sites, `Builder.from_archive`'s
`_wrap_native_handle` recovery, and the Builder construction site. Those pointers have
no owning object yet — if a `KeyboardInterrupt` lands there, `except Exception` skips
the free and nothing (not GC, not a guarded close) can ever reclaim it. The rule worth
writing into the class docstring so the next sweep doesn't reintroduce either bug:

> *catch-and-suppress must be `Exception`; catch-free-reraise on an unowned pointer
> must be `BaseException` (or `try/finally` with a consumed flag).*

Revert those five blocks to `except BaseException:` — they re-raise, so no interrupt
is ever swallowed.

Related, LOW: `_invoke_consume`'s narrowing to `Exception` is a reasonable choice
(interrupts propagate promptly; the still-ACTIVE object is later cleaned by
`close()`/GC with a guarded free), but its docstring still says "any other exception
from the call frees the handle before raising" — no longer true for interrupts. One
sentence: interrupts propagate untouched and teardown happens at the next
close/GC.

## Order

A (one-line `finally` + reinstated tests) and B (five-block revert + docstring rule)
are both small; land them in one commit and this PR is, from a memory-handling
standpoint, done.
