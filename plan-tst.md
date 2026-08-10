# Fix segfault in `c2pa_reader_from_stream` (thread-local settings on worker threads)

## Context

A signing service segfaults intermittently, more prominent after the adobe_api native SDK
upgrade **2.67.1 → 2.69** (after 22 July). Confirmed crash site (via `kubectl exec`):

- `adobe_c2pa_api/c2pa.py:389` `_create_and_activate()` → the zero-arg `create()` closure from
  `_create_reader` (`c2pa.py:2542`) → native `_lib.c2pa_reader_from_stream(format_arg, stream_obj._stream)`.
- Reached from `Reader.__init__` (`c2pa.py:2436`) → `_extract_ingredient_manifest_title`
  (`cai_service.py:192`) during `_sign_image_file_sync_claim_v1`.
- Runs on a `concurrent.futures` **worker thread** (`colligo/base/threading.py:92`), not the main thread.

### Root cause (confirmed across all three layers)

`c2pa_reader_from_stream` is **`#[deprecated]`** in c2pa-rs. Its note: *"Use `c2pa_reader_from_context()`
with an explicit context instead of relying on **thread-local settings**."*

Call chain of the crashing (context-less) path:

- `c2pa.py` `_create_reader` → `c2pa_reader_from_stream`
  (c2pa-rs `c2pa_c_ffi/src/c_api.rs:1091`)
- → `Reader::from_stream` (c2pa-rs `sdk/src/reader.rs:264`), which does
  `let settings = crate::settings::get_thread_local_settings();`
- → reads `thread_local!(static SETTINGS ...)` (c2pa-rs `sdk/src/settings/mod.rs:45`, getter at `1016`).

`load_settings()` (`c2pa.py:1419` → native `c2pa_load_settings`, `c_api.rs:522`) writes that
thread-local **only on the thread that calls it** (the main thread). A `concurrent.futures` worker
is a different OS thread, so its `SETTINGS` is a fresh `Settings::default()` — the trust/validation
config loaded on the main thread is absent there. The recent sync-CAWG-validation refactor in
`from_stream` (c2pa-rs #2120) runs validation against those default settings; a Rust panic/abort
unwinding across the `extern "C"` boundary surfaces to Python as `Fatal Python error: Segmentation fault`.

Two aggravators, both resolved by the same fix:
- **Behavior change on upgrade.** 2.67.1 bundled c2pa `0.89.0`, 2.67.4 `0.90.0`, 2.69.0 `0.90.8`
  (adobe_api `Cargo.toml:21/27`, `Cargo.lock`). The newer reader/validation path is why the crash
  became prominent post-upgrade.
- **Possible wheel↔dylib version skew** in the deployed pod (the Python package pins no native
  version; the dylib is env/build-selected, and the loaded lib is overridable at `c2pa.py:161`).

### Why the fix works

The context path is already fully wired and **never touches the thread-local**:
`Reader(..., context=ctx)` → `_init_from_context` (`c2pa.py:2583`) →
`c2pa_reader_from_context` (`c_api.rs:1069`) → `Reader::from_shared_context(&Arc<Context>)`
(`reader.rs:201`). The `Arc<Context>` carries its own settings and is explicitly safe to share
across threads. No new native binding is needed — `Settings`, `ContextBuilder`, `Context`,
`c2pa_reader_from_context`, `c2pa_builder_from_context`/`c2pa_builder_sign_context` are all already
bound in `c2pa.py`.

## Scope

**SDK-only** (sdk-python `adobe_c2pa_api/c2pa.py`). The caller (`cai_service.py` / `colligo`) is a
separate repo not accessible here; the required app-side note is documented below as guidance for
that team, but the SDK change alone stops the crash by making the default (context-less) path
thread-safe.

## The fix — route the default (context-less) path through a process-global `Context`

Stop calling the deprecated thread-local `c2pa_reader_from_stream`/
`c2pa_reader_from_manifest_data_and_stream` from the default path. Instead build a **process-global
default `Context`** once (thread-shareable `Arc` in Rust) and route every context-less `Reader`
through `_init_from_context`, so all threads use `c2pa_reader_from_context`.

### Edits in `sdk-python/src/adobe_c2pa_api/c2pa.py`

1. **Add a lazily-built, thread-safe process-global default Context.** Near the module globals, add:
   - `_default_context: Optional['Context'] = None` and a `threading.Lock`.
   - `_get_default_context()` — under the lock, if unset, build `Context()` (default `Settings`) and
     cache it; return the cached instance. Keep it module-private and never expose it for `close()`
     so its lifetime is the process. It is a `ManagedResource`; the existing `is_foreign_process`
     PID-guard (`lib.py:134`) already prevents an unsafe free in a forked child.

2. **Feed `load_settings()` into the default Context** so legacy callers keep their config on the
   worker path. In `load_settings` (`c2pa.py:1419`), after the existing `c2pa_load_settings` call
   (keep it for any main-thread thread-local consumers), also rebuild the process-global default
   Context from the same JSON: `Settings.from_json(settings_str)` → `Context(settings=...)`, stored
   under the lock. This is the bridge that carries main-thread config to worker threads via the
   thread-shareable `Arc`.

3. **Default `Reader.__init__` to the context path.** At `c2pa.py:2489`, change the dispatch so a
   context-less construction uses the default context:
   ```python
   effective_context = context if context is not None else _get_default_context()
   if effective_context is not None:
       self._init_from_context(effective_context, format_or_path, stream, manifest_data)
       return
   ```
   This removes `c2pa_reader_from_stream` from the normal path entirely. `_create_reader`
   (`c2pa.py:2529`, the deprecated calls) stays only as an explicit legacy fallback (e.g. gated
   behind an env/opt-in), or is removed once callers are migrated.

4. **Mirror for `Builder` (secondary hardening).** The context-less Builder signing path has the
   same latent thread-local dependency. Route context-less signing through
   `c2pa_builder_from_context` + `c2pa_builder_sign_context` using the same `_get_default_context()`.
   Confirm the exact Builder sign method names/lines before editing (bindings exist at
   `c2pa.py:74-75, 1028, 1040, 1045`).

### App-side note (for the caller team — not edited here)

Even with the SDK fix, the recommended long-term pattern is: build one `Context`
(`ContextBuilder().with_settings(Settings.from_json(cfg)).build()`) on startup and pass
`context=ctx` to every `Reader(...)` / `try_create(...)` / `Builder`. Stop using module-level
`load_settings()` (deprecated, thread-local). The SDK change makes the un-migrated code safe;
this note makes the intent explicit.

## Verification

1. **Repro test (new, in sdk-python tests).** On the main thread call `load_settings(cfg)` with a
   real trust config, then in a `ThreadPoolExecutor` worker build
   `Reader(fmt, stream)` over an ingredient image with an embedded manifest and read its title.
   Assert: before the fix this crashes/uses empty settings; after, it succeeds with the correct
   trust config applied. Add a second case with no `load_settings()` at all (pure default context).
2. **No-regression:** run existing sdk-python reader/builder tests; confirm `context=`-based reads,
   file-path reads, and manifest-data reads still pass.
3. **Confirm which native lib is actually loaded in the pod** to rule out/confirm skew: log
   `version()` / `_lib.c2pa_version()` (`c2pa.py:1383-1406`) at service start and immediately before
   Reader construction; compare against the wheel's expected c2pa version (2.69 ⇒ 0.90.8). If they
   differ, fix the deployment's `C2PA_LIBS_RELEASE_VERSION` / bundled dylib as a separate step.
4. **Native symbol check:** verify the deployed dylib exports `c2pa_reader_from_context` /
   `c2pa_builder_from_context` (`nm -gU libadobe_c2pa.dylib | grep from_context`) — required for the
   fix to link at runtime.

## Risks / notes

- Default-context routing changes the code path for every existing context-less caller. Keep the
  deprecated `_create_reader` path reachable behind an opt-in during rollout so behavior can be
  compared if needed.
- Process-global Context must never be `close()`d by user code; keep it module-private.
- Fork (not the observed scenario — the trace is threads) is already guarded by the PID check in
  `lib.py`; the shared `Arc<Context>` is safe across threads by design.
