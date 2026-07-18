# PR #294 — Finishing plan: native-handle lifecycle extension surface

**Goal:** take #294 from WIP to mergeable and reviewer-proof. The code is
mechanically sound; the work left is *committing to the extension contract* and
writing it down where it can be enforced. No functional rewrite required.

---

## Decision to record first: the extension model

Downstream libraries should be able to wrap their own FFI pointers in the
managed lifecycle, **without** the project promising a stable public API.

Chosen: **single-underscore, subclass-facing (protected).** Keep the names as
they are (`_activate`, `_swap_handle`, `_mark_consumed`, `_wrap_native_handle`,
`_init_attrs`).

Why this level and not the alternatives — state this in the PR so it isn't
re-litigated in review:

- **Not public (no underscore).** A bare name is an implicit stability promise.
  The seam is still evolving; we don't want to guarantee it.
- **Not dunder (`__name`).** Double underscore triggers per-class name
  mangling, which breaks subclassing — the exact capability this PR exists to
  enable. It's the one "more private" option that defeats the purpose.
- **Single underscore is the idiom for "reachable, unsupported, subclass-
  friendly."** Python privacy is convention, not enforcement: a downstream lib
  *can* call these, and that's intended. The underscore communicates "no
  stability guarantee," nothing more.

Consequence that drives the rest of the plan: because the underscore does not
enforce anything, **the docstrings are the contract.** They must carry the
invariants as if the methods were public, because for the people who reach them
they effectively are.

---

## Work items

### 1. Make the docstrings the contract (primary work)
Each exposed primitive states its ownership transfer explicitly:
- `_activate(handle)` — takes ownership; frees on close; only from
  `UNINITIALIZED`; rejects null and double-activation.
- `_swap_handle(new_handle)` — **the caller guarantees the callee already
  consumed and freed the old pointer.** Requires `ACTIVE`; rejects null.
- `_mark_consumed()` — the native pointer is now owned elsewhere; this releases
  only *Python-side* resources and marks `CLOSED` without freeing the pointer.
- `_wrap_native_handle(handle)` — ownership transfers **only on successful
  return**; if it raises, the caller still owns the pointer and must free it.

### 2. Nail the `_wrap_native_handle` initialization invariant
It bypasses `__init__` entirely and runs only `_init_attrs()`. Add one explicit
line to the docstring:

> Everything an instance needs besides the native handle must be set in
> `_init_attrs()`, not `__init__` — `_wrap_native_handle` never runs `__init__`.

Live proof this matters: `Reader.__init__` sets `self._context = context`
*after* `_init_attrs()`, so a Reader built via `_wrap_native_handle` would get
`_context = None`. Fine for `Builder.from_archive` (no context by design), but a
footgun for any external extender who puts setup in `__init__`.

### 3. Legibility on the consume-and-return null path
In `with_fragment` and `with_archive`, the null branch relies on
`_check_ffi_operation_result` raising *before* control reaches `_swap_handle`.
It is safe today, but reads as "mark consumed, then a check that happens to
raise." Make the intent explicit:

```python
new_ptr = _lib.c2pa_..._with_...(self._handle, ...)
if not new_ptr:
    # callee consumed the old handle and returned nothing to own
    self._mark_consumed()
    _check_ffi_operation_result(new_ptr, "...")  # raises here
self._swap_handle(new_ptr)
```

Moving the check inside the `if not new_ptr:` block makes the control flow say
what it means. No behavior change.

### 4. `super().__init__()` audit (cheap)
Every `_activate` caller depends on `self._lifecycle_state` already existing
(set by `ManagedResource.__init__`). Context / Reader / Builder / Signer visibly
call `super().__init__()`. Confirm `Settings.__init__` does too. If the existing
tests pass, it already does — this is a five-second eyeball, not a suspected bug.

### 5. Tests: cover the *external-extender* path
The added lifecycle / integration / cross-thread tests cover the built-in types.
Add the case the PR actually unlocks:
- A minimal subclass that owns a raw handle and reaches the lifecycle via
  `_wrap_native_handle` + `_init_attrs`, asserting the instance is fully built
  (no missing attributes) and frees exactly once.
- The same wrapped instance under the fork guard: a foreign-process teardown
  skips the native free (owner-PID stamped through the wrap path).

---

## Explicit non-goals (pre-empt scope-creep review comments)
- **Not** renaming anything to public. The access level is the decision, not an
  oversight.
- **Not** adding fork guards to *operation* paths (`with_fragment` etc.). The
  PID guard's contract is teardown-safety in a forked child, not operation-
  safety. Operating on a handle in a forked child is caller error and out of
  scope.

---

## Review-defense notes (the "why", pre-answered)

- **Why underscore, not public?** See the extension-model decision above:
  reachable but unsupported is exactly the intent.
- **Why does `_mark_consumed()` now run `_release()`?** Previously the consume
  paths leaked Python-side resources (callback refs, streams, caches) until GC.
  Releasing on consume is a fix, not a regression. It cannot double-release:
  `_cleanup_resources` skips when the state is already `CLOSED`.
- **Why is the signer callback copied onto the Context before the signer is
  consumed?** The native signer holds a pointer to the Python callback.
  `_mark_consumed() -> _release()` clears the signer's callback ref, so the
  Context must capture its own reference *first*, or the first invocation of the
  consumed signer's callback would be a use-after-free. The ordering is the
  whole reason it's safe; the inline comment explaining it must stay.
