# Stale error read in a threaded environment

## The mechanism

The native error slot is a `thread_local!` `RefCell` in
`c2pa_c_ffi/src/cimpl/cimpl_error.rs`. `c2pa_error()` calls `last_message()`,
which peeks at the slot and returns a copy. Nothing clears it. A message written
by one call stays readable until some later call on the same thread overwrites
it.

That matters because not every failing native call sets an error. A call can
return NULL, or a negative status, and leave the slot holding whatever the
previous call put there. Python then reads the slot, finds a message, and
reports it as the reason this call failed. The exception type is derived from
that text too, so a caller branching on the error type branches on the wrong
one.

The Python layer handles this by writing a marker into the slot before a native
call and treating that marker as "no error of my own". `c2pa_free` of address
`0x1` is never a real handle, so it fails and stores the text
`Other: UntrackedPointer: 0x1`, which `_read_native_error` maps back to `None`.

## Where it breaks

`_read_native_error` reads the slot, then plants the marker, so each message is
reported once. Two of its paths returned before reaching the marker:

```python
error = _lib.c2pa_error()
if not error:
    return None          # slot still holds the old message
```

`c2pa_error()` renders the stored message into a fresh C string through
`to_c_string`, which returns `null_mut()` when the message contains an interior
NUL byte. The slot keeps the message; the caller sees NULL and returns `None`
without marking. The same applies to a message that decodes to empty.

## What a user sees

A worker thread in a pool, running two unrelated operations:

1. An operation fails and writes `Io: belongs to an earlier call` into the slot.
2. `_read_native_error` runs and hits the NULL branch. It returns `None`, so the
   first operation reports no native detail. The message stays in the slot.
3. A later, unrelated operation on the same thread fails without setting an
   error. It reads the slot, finds the message from step 1, and raises it.

The third operation raises `Io: belongs to an earlier call`. The thread pool is
what makes this reachable in practice: the two operations share a thread and
never share anything else.

Both tests added in `tests/test_unit_tests.py` fail against the unfixed code:

```text
AssertionError: 'belongs to an earlier call' unexpectedly found in
'Io: belongs to an earlier call' : a later failure reported a message
left by an earlier call
```

## The fix

Plant the marker on both early returns, so a message that cannot be rendered or
decoded is still consumed:

```python
error = _lib.c2pa_error()
if not error:
    _mark_sentinel_no_native_error()
    return None
```

Every path out of `_read_native_error` now leaves the slot carrying the marker,
which is what the function's docstring already described.

## Caller text forging a pointer rejection

After a consuming call fails, `_raise_consume_failure` decides who owns the
handle by looking for one of four tags in the native message. A tag names a
rejection that happened before native took ownership, so matching one means the
handle is still ours and the resource goes back into service.

The match was a substring search, and native messages quote caller-supplied
strings verbatim. A JSON parse failure repeats the offending value:

```text
Json: invalid type: string "NullParameter: injected", expected a sequence at line 1 column 50
```

That message described a bad settings value, and the classifier read it as a
pointer rejection. The resource is then restored to usable while native may
already own and have dropped its handle. An `Io:` error naming a path that
contains a tag does the same thing.

Real rejections occupy two positions and never appear mid-message: either the
tag starts the message, or it follows the one `Other:` wrapper.

```text
NullParameter: format
Other: UntrackedPointer: 0x9999
```

Stripping that wrapper and requiring the tag at the start of what remains keeps
every real rejection and rejects the forged ones.

## A second stale read, in the teardown queue

`_native_section` defers teardowns that arrive while a section is open and
flushes them when the outermost span closes. The flush loop was unguarded, so
one resource raising skipped every resource queued behind it, and the deferral
was the only remaining path to those handles' frees.

`_finish_teardown` and `_safe_release` both catch `Exception`, which leaves a
`KeyboardInterrupt` arriving during a flush able to escape and strand the queue.
Each flush now runs under its own guard, with the first exception re-raised once
the queue is drained.
