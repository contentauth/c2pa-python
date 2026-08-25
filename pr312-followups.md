# c2pa-python pull request 312: additional fixes

Sentinel in the native thread-local error slot. Scratch note, not for the
repository.

The change is correct as written. Three items, the first of which quietly
disables the diagnostic the sentinel exists to provide.

---

## 1. Match on a substring, not on exact equality

**The problem.** The comparison is

```python
if error == ManagedResource._NO_NATIVE_ERROR.decode('utf-8'):
```

`c2pa_error_set_last` does not store the string verbatim. It runs it through
`Error::from` and then `CimplError::from`, and its own documentation states that
a missing or invalid error type is replaced with `Other` and the message includes
the original string. The sentinel already carries an `Other: ` prefix, so it may
round-trip unchanged, or it may come back re-prefixed or otherwise normalised.

**Why it matters, and why it is easy to miss.** The failure is silent rather than
dangerous. If the comparison never matches, control falls through to the final
branch, which now performs the identical `_teardown(free_handle=False)`. Same
action, no crash, all tests that check behaviour still pass.

What is lost is the distinct log line. That log line is the entire reason for
planting a sentinel rather than simply clearing the slot: it separates "the
native side reported nothing" from "the native side reported a real error", and
it is the only field evidence available for how often the ambiguous case occurs.
Losing it costs nothing today and costs the whole diagnostic tomorrow.

**Fix.** Match on the distinctive part only:

```python
_NO_NATIVE_ERROR_MARKER = "c2pa-python-no-native-error"
...
if _NO_NATIVE_ERROR_MARKER in error:
```

**And pin the round-trip in a test regardless**, since it is a property of the
native side that can change without notice:

```python
def test_sentinel_round_trips_through_native_error_slot(self):
    c2pa_module._lib.c2pa_error_set_last(ManagedResource._NO_NATIVE_ERROR)
    self.assertIn(_NO_NATIVE_ERROR_MARKER, c2pa_module._read_native_error())
```

That test fails loudly if the normalisation ever changes, which is exactly the
kind of upstream invariant worth pinning rather than assuming.

## 2. Restore the ordering rationale that was deleted

The removed paragraph explained that `c2pa_free` on a handle the registry no
longer tracks returns minus one and overwrites the slot with its own
untracked-pointer message, so the error must be read before any free or the
substitute carries a pre-consume tag and inverts the retain decision.

That constraint is still true, and the current code still depends on it. The
replacement text explains the sentinel but says nothing about why the read comes
first. A later edit that moves the read after a free would reintroduce the
inversion with no warning anywhere in the file.

One sentence is enough:

> The read must precede any free: `c2pa_free` on an untracked handle overwrites
> the slot with its own untracked-pointer message, which carries a pre-consume
> tag and would invert the decision below.

## 3. Confirm the changed test is green for the right reason

`test_context_build_null_return_frees_builder` loses its explicit
`c2pa_error_set_last(b"UntrackedPointer: ...")` line. That test needs the
retained branch to fire, which needs a pre-consume tag present at the moment the
failure is read.

With the sentinel now planted inside `_invoke_consume`, a mock that merely
returns `None` leaves the sentinel in place, the sentinel branch fires,
`_teardown(free_handle=False)` runs, and no free happens. The assertion should
then fail.

Presumably the mock is now built with `_fail_with_native_error(b"UntrackedPointer: ...")`,
which restores the tag from inside the call rather than before it. Worth
confirming that is what landed, because a test that passes for the wrong reason
here is worse than one that fails: it would be asserting the retained branch
while actually exercising the consumed one.

---

## What already holds

The sentinel is planted immediately before `ffi_call`, inside `_invoke_consume`,
with nothing between them, on the thread that makes the call. That is the correct
placement and the thread-local slot means it cannot disturb any other worker.

`_setup_function(_lib.c2pa_error_set_last, [ctypes.c_char_p], ctypes.c_int)`
supplies the explicit argument and return types, which was the one open check.
The return value itself needs no guard: minus one is returned only for a null
pointer, so any non-null sentinel returns zero.

Changing the final fallback from `_release_handle()` to
`_teardown(free_handle=False)` removes the guarded free from the ambiguous path
entirely. That is the more important half of this pull request, and it holds even
if the sentinel comparison in item 1 never matches.
