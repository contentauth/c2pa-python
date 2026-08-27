The process dies with SIGSEGV (exit code 139, no Python exception) when a
`Context` built from a callback signer is closed on one thread while another
thread runs a context-sign (`Builder(manifest, context=ctx)` followed by
`builder.sign(format, source, dest)`) through it.

40-120 trials:

| Variant | Result |
|---|---|
| Close during concurrent context-sign, callback signer | SIGSEGV, reproducible |
| Same race, `Context._release` patched to keep the callback reference alive | 80/80 clean |
| Same race, context's native free suppressed (release still runs) | still SIGSEGV |
| Same race, info signer (`Signer.from_info`, no Python callback) | 120/120 clean |
| Single-threaded close-then-sign | clean (errors, no crash) |
| Dropping the last `ctx` reference mid-sign (finalizer close) | 80/80 clean |

```
python3 crashes/context-close-drops-signer-callback-mid-sign/repro.py
```

Exit code 139 within a few trials. The script: build a `Context` from
`Signer.from_callback(...)`, start a thread running a context-sign, sleep
~2 ms after the sign begins, call `ctx.close()` from the main thread, join,
repeat.
