# SIGSEGV: Context.close() drops the signer callback while a context-sign is calling it

## Symptom

The process dies with SIGSEGV (exit code 139, no Python exception) when a
`Context` built from a callback signer is closed on one thread while another
thread runs a context-sign (`Builder(manifest, context=ctx)` followed by
`builder.sign(format, source, dest)`) through it.

Reproduced on commit `aac1f3b`, macOS arm64, Python 3.13. 5 out of 5 runs of
the multi-thread form crash; the minimal single-worker form crashes at close
delays of 0 to 10 ms after the sign enters (`repro.py`).

faulthandler places the faulting thread inside the native sign call:

```
Current thread (most recent call first):
  File "src/c2pa/c2pa.py", line 4032 in _sign_internal   # c2pa_builder_sign_context
  File "src/c2pa/c2pa.py", line 4110 in _sign_common
  File "src/c2pa/c2pa.py", line 4186 in sign
```

The full capture is in `faulthandler-output.txt`.

## Root cause

`Context.__init__` pins the consumed signer's ctypes callback so it outlives
the `Signer` object:

```python
self._signer_callback_cb = signer._callback_cb   # c2pa.py:1893
```

`Context._release()` is the only thing that later drops that pin:

```python
def _release(self):
    """Release Context-specific resources."""
    self._signer_callback_cb = None              # c2pa.py:1911 area
```

`Builder._sign_internal`'s context-sign branch wraps `self._native_call()`
around `c2pa_builder_sign_context` but takes no guard on the Context. A
concurrent `ctx.close()` therefore runs `_teardown` -> `_safe_release` ->
`_release()` while the native signer is invoking the pinned callback. Dropping
the last Python reference deallocates the ctypes trampoline, and the native
side's next invocation jumps through freed memory.

The native `Arc<Context>` inside the Builder keeps the Rust context alive, so
the pointer lifetimes on the Rust side are sound; the freed object is the
Python-owned callback trampoline.

## Evidence for the mechanism

Each variant run 40-120 trials:

| Variant | Result |
|---|---|
| Close during concurrent context-sign, callback signer | SIGSEGV, reproducible |
| Same race, `Context._release` patched to keep the callback reference alive | 80/80 clean |
| Same race, context's native free suppressed (release still runs) | still SIGSEGV |
| Same race, info signer (`Signer.from_info`, no Python callback) | 120/120 clean |
| Single-threaded close-then-sign | clean (errors, no crash) |
| Dropping the last `ctx` reference mid-sign (finalizer close) | 80/80 clean |

The pin-the-callback patch removing the crash while the suppress-the-free
patch does not isolates the trampoline drop, not the native handle free, as
the faulting object. The info-signer run shows the race window itself is
otherwise survivable.

The finalizer variant does not crash because `__del__` can only run once the
signing thread's `Builder` no longer references the Context; an explicit
`close()` has no such ordering.

## Reproduction

```
python3 crashes/context-close-drops-signer-callback-mid-sign/repro.py
```

Exit code 139 within a few trials. The script: build a `Context` from
`Signer.from_callback(...)`, start a thread running a context-sign, sleep
~2 ms after the sign begins, call `ctx.close()` from the main thread, join,
repeat.

## Direction for a fix

The callback must stay alive until no native call can invoke it. Options that
fit the existing design:

- Give the context-sign branch a `context._native_call()` guard (the Builder
  already holds `self._context`), so `close()` defers its teardown the same
  way `signer.close()` defers during a borrowed sign. The deferral machinery
  in `_teardown`/`_native_call` already exists.
- Alternatively, keep `_signer_callback_cb` out of `_release()` and let it die
  with the Python `Context` object; the cost is the callback living as long
  as the object rather than until `close()`.

The first option also covers any other Context state a future native call
might reach mid-close.

## Both context-sign entry points are affected

The crash reproduces through `Builder.sign(format, source, dest)` and through
`Builder.sign_file(source, dest)` when the Builder was constructed from a
context whose signer is a callback signer. Both reach
`c2pa_builder_sign_context` with no guard on the Context. `sign_file` with an
explicit signer and correct argument order (`sign_file(source, dest, signer)`)
is unaffected, as is any explicit-signer sign, because those hold
`signer._native_call()`.
