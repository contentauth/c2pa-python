# Fix cross-thread settings loss in the deprecated reader path

## Context

A signing service reports two distinct problems that an earlier revision of this document
treated as one:

1. **Confirmed, and fixed here:** readers constructed on `concurrent.futures` worker threads
   silently validate against an empty trust list, because trust configuration loaded via
   `load_settings()` never reaches those threads. The result is wrong validation output, not a
   crash.
2. **Unexplained, tracked separately:** an intermittent `Fatal Python error: Segmentation fault`,
   more prominent after the adobe_api native SDK upgrade 2.67.1 to 2.69 (after 22 July).

The earlier revision attributed the segfault to problem 1. That attribution does not survive
inspection of the Rust source — see "Ruled out as the segfault cause". The fix below addresses
problem 1 only.

Observed crash site, via `kubectl exec`:

- `adobe_c2pa_api/c2pa.py:389` `_create_and_activate()`, then the zero-arg `create()` closure from
  `_create_reader` (`c2pa.py:2542`), then native
  `_lib.c2pa_reader_from_stream(format_arg, stream_obj._stream)`.
- Reached from `Reader.__init__` (`c2pa.py:2436`), then `_extract_ingredient_manifest_title`
  (`cai_service.py:192`), during `_sign_image_file_sync_claim_v1`.
- Runs on a `concurrent.futures` worker thread (`colligo/base/threading.py:92`), not the main thread.

Line numbers in `adobe_c2pa_api/c2pa.py`, `cai_service.py`, and `colligo/` come from the original
report and were not verifiable during this review; those trees were not available. Every c2pa-rs
and upstream `c2pa-python` reference below was read directly and is current as of this revision.

## Confirmed problem: settings do not cross thread boundaries

`c2pa_reader_from_stream` is `#[deprecated]` in c2pa-rs (`c2pa_c_ffi/src/c_api.rs:1084-1088`). Its
note reads: *"Use c2pa_reader_from_context() with an explicit context instead of relying on
thread-local settings."* The body carries an inline comment saying the same thing — it inherits
thread-local settings by design and new C API usage should prefer the context entry point.

The call chain of the context-less path:

- `c2pa.py` `_create_reader`, then `c2pa_reader_from_stream` (`c_api.rs:1084`)
- then `Reader::from_stream` (`sdk/src/reader.rs:264-267`), which does
  `let settings = crate::settings::get_thread_local_settings();`
- then reads `thread_local!(static SETTINGS ...)` (`sdk/src/settings/mod.rs:45-49`), getter at
  `settings/mod.rs:1142`.

`load_settings()` routes to native `c2pa_load_settings` (`c_api.rs:518-533`), whose doc comment is
literally `/// Sets thread-local settings.`. It terminates in
`Settings::from_string` (`settings/mod.rs:638-649`), which does `SETTINGS.set(merged)` — the
calling thread's slot and nothing else.

A `concurrent.futures` worker is a different OS thread. Its `SETTINGS` is initialized from
`Settings::default()` (`settings/mod.rs:47`, default impl at `:1038-1052`) and does **not** clone
any process-global; `settings/mod.rs` contains no `OnceLock`, `RwLock`, or `lazy_static` at all.
So the trust and validation config loaded on the main thread is simply absent on the worker.

The observable effect is an empty trust list, which surfaces as an untrusted-signer validation
status. It is silent: nothing raises, and the getter degrades with `.unwrap_or_default()`
(`settings/mod.rs:1143`) rather than reporting a problem.

### Why the fix works

The context path is already fully wired and never touches the thread-local:
`Reader(..., context=ctx)`, then `_init_from_context`, then `c2pa_reader_from_context`
(`c_api.rs:1065-1069`), then `Reader::from_shared_context(&Arc<Context>)` (`reader.rs:201-208`).
Settings come from the `Arc<Context>`'s own field (`context.rs:269`), read downstream via
`context.settings()`.

`Context` is `Send + Sync` on all non-wasm targets (`context.rs:268-278`; `BoxedSigner` is
`Send + Sync` at `signer.rs:31`), so one `Arc<Context>` is genuinely shareable across threads. On
`wasm32` the cfg-gated aliases drop those bounds, but that target is single-threaded here anyway.

No new native binding is needed. `Settings`, `Context`, `c2pa_reader_from_context`,
`c2pa_builder_from_context`, and `c2pa_builder_sign_context` are all already bound in `c2pa.py`.
Note that Rust has no `ContextBuilder` type — `c_api.rs:92` aliases
`type C2paContextBuilder = Context`. The Python `ContextBuilder` is a convenience wrapper with no
native counterpart.

## Ruled out as the segfault cause

Recorded so the next reader does not repeat this search.

**The original theory: default settings cause a Rust panic that unwinds across `extern "C"`.**
Refuted. `Store` production code (`store.rs:1-4316`, everything before the test module) contains
zero `unwrap()`, `expect()`, `panic!`, or `unreachable!`. The settings getter uses
`.unwrap_or_default()` (`settings/mod.rs:1143`) and the thread-local initializer uses
`.unwrap_or(...)` (`:47`). `Reader::from_stream` propagates with `?` (`reader.rs:267`). The FFI
macros return NULL rather than panicking (`macros.rs:316`, `:399`, `:511`), and the tracking
registry treats a poisoned mutex as an error, not a panic (`utils.rs:68`, `:103`, `:125`, `:156`).
Default settings yield an empty trust list, which is a validation status, not a fault.

**Pointer-address reuse (ABA) in the FFI tracking registry.** The registry is genuinely keyed on a
raw address (`cimpl/utils.rs:40`) and the mutex is genuinely released before the dereference
(`cimpl/macros.rs:326-330`). But reaching it requires two threads holding the same `Stream` object,
and every construction path builds its own (`c2pa.py:2510`, `:2573`, `:2600-2605`). Unreachable
without API misuse. Worth hardening with a generation counter; low priority.

**Non-atomic `Stream.close()` causing a double free.** `close()` does call
`c2pa_release_stream` before nulling `self._stream` (`c2pa.py:2079` vs `:2085`), which is the wrong
order for a lock-free guard. But `PointerRegistry::free` removes the entry inside the mutex
(`utils.rs:127`), so a concurrent second free returns `-1` rather than freeing twice. And it needs
the same shared-`Stream` precondition. A swap-then-release one-liner is still worth doing.

**Per-chunk thread spawn on the read path.** `hash_utils.rs:464` does spawn an OS thread, and the
path is reachable for a plain JPEG (`data_hash.rs:304`, called from `claim.rs:2777`). But
`MAX_HASH_BUF` is 256 MB (`hash_utils.rs:29`) and each loop iteration blocks on `rx.recv()` before
the next spawn, so a 5 MB image spawns exactly one thread and joins it before returning. The
closure captures only owned `Send` data — the stream is not captured.

**OpenSSL thread-safety.** OpenSSL is the default backend (`sdk/Cargo.toml:31`, `:177`), but
`OpenSslMutex::acquire()` coverage is complete: all FFI entry points in `c2pa_raw_crypto` plus
`certificate_trust/openssl.rs:28`. Digest is pure-Rust `sha2` (`hash_utils.rs:25`), outside
OpenSSL entirely. The worst case is a poisoned-mutex typed error.

### One latent hazard found, not implicated here

There is no `catch_unwind` at any `extern "C"` boundary in production code, `panic = "abort"` is
not set (workspace `Cargo.toml:24-27`), and the crate is built as `cdylib`
(`c2pa_c_ffi/Cargo.toml:18`). Any panic reaching the boundary therefore aborts the host process.
That is the mechanism by which a Rust-side segfault *could* occur, but no reachable panic was found
on the read path. Worth a separate hardening issue.

### The most plausible remaining segfault lead

Wheel-to-dylib version skew in the deployed pod. The Python package pins no native version, the
dylib is environment- and build-selected, and the loaded library is overridable at `c2pa.py:161`.
A wheel calling a mismatched dylib is a textbook segfault, and it fits "appeared after the
2.67.1 to 2.69 upgrade" better than any settings theory. Version history: 2.67.1 bundled c2pa
`0.89.0`, 2.67.4 `0.90.0`, 2.69.0 `0.90.8` (adobe_api `Cargo.toml:21/27`, `Cargo.lock`).

See "Diagnosing the segfault" for how to confirm.

## Scope

SDK-only (`sdk-python/src/adobe_c2pa_api/c2pa.py`; upstream equivalent
`c2pa-python/src/c2pa/c2pa.py`). The caller (`cai_service.py` / `colligo`) is a separate repo not
accessible here. The app-side note below is guidance for that team; the SDK change alone fixes the
settings loss for un-migrated callers.

## The fix: route the default path through a process-global Context, without a lock

Stop calling the deprecated thread-local `c2pa_reader_from_stream` and
`c2pa_reader_from_manifest_data_and_stream` from the default path. Build a process-global default
`Context` — a thread-shareable `Arc` on the Rust side — and route every context-less `Reader`
through `_init_from_context`, so all threads use `c2pa_reader_from_context`.

No `threading.Lock` is required, and none should be added. `c2pa.py` and `lib.py` currently contain
no synchronization primitives at all: no `import threading`, no `Lock`, no `RLock`, no
`threading.local`, no `contextvars`. The only cross-cutting safety machinery is fork/PID guarding
(`lib.py:304-326`), which does nothing for threads. Adding a lock would set a new precedent, and it
would carry real risk: `__del__` (`c2pa.py:604`) can fire on any thread at any bytecode boundary,
so a non-reentrant lock spanning the create and close paths invites self-deadlock.

Three properties make the lock unnecessary:

- **Eager construction.** Building the default `Context` at module scope means CPython's import
  lock already serializes it. Laziness is the only reason a lock would be needed, and
  `c2pa_context_new` is cheap enough not to warrant deferring.
- **Rebind, never mutate.** `load_settings()` must not rebuild the global in place. It binds the
  module-level name to a newly built `Context`. Name rebinding is a single atomic bytecode under
  the GIL, so a concurrent reader sees either the old object or the new one, never a torn one. The
  old `Context` is left to reference counting and must not be closed, since another thread may be
  mid-call on it.
- **Reads are already atomic.** `_init_from_context` only reads `context.is_valid` and
  `context.execution_context` (`c2pa.py:2588`, `:2612`). The Python `Context` wrapper holds no
  shared buffer and no per-call mutable state; its only hazard is a close-versus-use race, which
  cannot arise for an object that is never closed.

### Edits in `sdk-python/src/adobe_c2pa_api/c2pa.py`

Upstream line references are to `c2pa-python/src/c2pa/c2pa.py`.

1. **Add an eagerly built module-global default Context.** At the end of the `Context` class block
   (upstream around `:1780`), add `_default_context = Context()` and a `_get_default_context()`
   accessor that returns it. No lock, no lazy initialization. Keep it module-private and never
   expose it for `close()`, so its lifetime is the process. It is a `ManagedResource`, and the
   existing `is_foreign_process` PID guard (`lib.py:311`) already prevents an unsafe free in a
   forked child.

2. **Have `load_settings()` rebind the default Context.** In `load_settings` (upstream `:1419`),
   keep the existing `c2pa_load_settings` call at `:1460` so any main-thread thread-local consumers
   still work, then rebind the global from the same JSON:

   ```python
   global _default_context
   _default_context = Context.from_json(settings_str)   # a new object, not a mutation
   ```

   Reuse `Context.from_json` (`:1732`) as-is: it builds a `Settings`, constructs the `Context`, and
   closes the temporary `Settings` in a `finally`, so the resulting `Context` does not depend on it
   surviving. This is the bridge that carries main-thread configuration to worker threads.

3. **Default `Reader.__init__` to the context path.** At the dispatch (upstream `:2489`):

   ```python
   effective_context = context if context is not None else _get_default_context()
   if effective_context is not None:
       self._init_from_context(effective_context, format_or_path, stream, manifest_data)
       return
   ```

   `_init_from_context` (`:2583`) already handles all three asset shapes — positional path
   (`:2599`), `(format, path)` (`:2602`), and stream (`:2605`) — plus `manifest_data`
   (`:2615-2632`), so no new branches are needed.

   While here, fix a behavioral asymmetry: the context path calls bare `open()` outside the `try:`
   at `:2607`, so a missing file raises `FileNotFoundError`, whereas `_init_from_file` converts it
   to `C2paError.Io(...)` (`:2578-2581`). Bring the `open()` inside the `try`, or reuse
   `_init_from_file`'s conversion.

4. **Mirror the dispatch for `Builder`.** The context-less Builder signing path has the same latent
   thread-local dependency. Apply the same change at `Builder.__init__` (upstream `:3350`, dispatch
   at `:3378-3380`) routing to `_init_from_context` (`:3382`), which uses
   `c2pa_builder_from_context` (`:3394`) and `c2pa_builder_sign_context` (`:3741`).
   `Builder._release` (`:3407-3410`) already documents that it does not close a borrowed `Context`,
   which is correct for a shared global.

5. **Keep the legacy path reachable during rollout.** `_create_reader` (`:2529`) stays behind an
   environment opt-in so the old and new behavior can be compared, and is removed once callers are
   migrated.

### App-side note, for the caller team

Even with the SDK fix, the recommended long-term pattern is to build one `Context`
(`ContextBuilder().with_settings(Settings.from_json(cfg)).build()`) at startup and pass
`context=ctx` to every `Reader(...)`, `try_create(...)`, and `Builder`. Stop using module-level
`load_settings()`; it is deprecated and thread-local, and the SDK's own deprecation text warns
against mixing it with the Context APIs. The SDK change makes un-migrated code safe; this note
makes the intent explicit.

## Verification

1. **Cross-thread settings test (new, in sdk-python tests).** On the main thread call
   `load_settings(cfg)` with a real trust config, then in a `ThreadPoolExecutor` worker build
   `Reader(fmt, stream)` over an ingredient image with an embedded manifest and read its title and
   validation status. Before the fix the worker reports an untrusted signer; after, it reports the
   configured trust state. Add a second case with no `load_settings()` at all, exercising the pure
   default context.
2. **Rebind-under-load test.** Run N threads constructing `Reader`s in a loop while the main thread
   calls `load_settings()` repeatedly. Assert no crash and that every `Reader` observes either the
   old or the new configuration — never a partially applied one.
3. **No regression.** Run the existing sdk-python reader and builder suites. Confirm
   `context=`-based reads, file-path reads, and manifest-data reads still pass, and that the
   file-not-found error type is now consistent across both paths.

## Diagnosing the segfault (separate track)

This cannot be settled by reading source. Ordered cheapest-discriminating-first:

1. **Get a core dump or backtrace.** Which thread the faulting program counter is on, and which
   library it is in, settles this in one shot. Everything else is guesswork until this exists.
2. **Confirm which native library the pod actually loads.** Log `version()` and
   `_lib.c2pa_version()` (`c2pa.py:1383-1406`) at service start and immediately before `Reader`
   construction, and compare against the wheel's expected c2pa version (2.69 implies 0.90.8). Also
   verify the deployed dylib exports the context entry points:
   `nm -gU libc2pa_c.dylib | grep from_context`. This is both the cheapest check and the most
   plausible cause.
3. **Instrument `Stream` thread identity.** Record `threading.get_ident()` alongside the existing
   `self._stream_id` (`c2pa.py:1826`) in `__init__` and `close()`, and assert they match. If they
   always match, the ABA and double-free theories are dead empirically, not just on inspection.
4. **Run under `MallocScribble=1 MallocPreScribble=1`** on macOS, or ASAN. If this is memory
   corruption, that converts an intermittent crash into a near-deterministic one.

Do not treat the segfault as fixed on the strength of the settings change. The two are unrelated
until a backtrace says otherwise.

## Risks and notes

- Default-context routing changes the code path for every existing context-less caller. Keeping
  `_create_reader` behind an opt-in during rollout allows a direct comparison.
- The process-global `Context` must never be closed by user code. Keep it module-private, and do
  not close the previous instance when `load_settings()` rebinds — another thread may hold it.
- Fork is already guarded by the PID check in `lib.py`; note that guard does nothing for threads.
  The shared `Arc<Context>` is safe across threads by design.
