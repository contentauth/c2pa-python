# PR #303 — adversarial review: memory, callback, and resolver handling

**Branch state reviewed:** `mathern/http-resolver-custom` at `c785450`.
**Method:** every claim below was adversarially confirmed — against the c2pa-rs FFI source at the pinned tag `c2pa-v0.90.1` (`c2pa_c_ffi/src/c_api.rs`), and where ctypes semantics decide the outcome, by running the experiment (results quoted). The exposed API is untouched by this plan, per instruction. Implementer: Opus 5.

---

## Part A — Confirmed sound. Do not "fix" these.

Each of these was attacked and held. They are listed so the implementer doesn't churn them.

**A1. The bytearray snapshot fix (`data = bytes(payload)`) is complete and correct.** Before `184790f`, `length = len(payload)` was computed on the live object and `bytes(payload)` was taken later at `memmove` time; a resolver returning a `bytearray` and shrinking it from another thread in between would have made `memmove` read `length` bytes from a shorter source — an out-of-bounds read. The current code snapshots once and derives `length` from the snapshot. The parallel fix in the signer callback (`signature = bytes(signature)`) closes the same window there. Verified: `bytes(bytearray)` produces an immutable copy.

**A2. The zero-length body invariant matches Rust exactly.** On the success path Rust skips its `free` when `body.is_null() || body_len == 0`, so a non-NULL pointer with zero length would leak; the trampoline writes `body = None` / `body_len = 0` together. On the error path (`rc != 0`) Rust frees any non-null body unconditionally — and on the trampoline's only mid-write failure (malloc returning NULL), `status` may already be written but `body` is still NULL from Rust's zero-init (`C2paHttpResponse { status: 0, body: null, body_len: 0 }` is constructed fresh per call), so nothing dangles and nothing leaks.

**A3. The allocator-matching logic is right for every shipped artifact.** Rust frees with `libc::free`; `ucrtbase`-before-`msvcrt` matches Rust MSVC targets, and `CDLL(None)` matches on Unix. Checked `build-wheel.yml`: wheels are `manylinux_2_28` x86_64/aarch64 (glibc) plus mac/Windows — no musllinux target, so there is no shipped configuration where `CDLL(None)` and the native library disagree (see B8 for the residual source-build note). The lazy-init race on `_native_malloc` is benign (idempotent assignment of equivalent objects).

**A4. The thunk keep-alive chain holds, including failure paths.** `_http_resolver_cb` is pinned on the Context before any native call can capture the raw pointer; `Context._release` deliberately does not clear it; `Reader`/`Builder` store `_context` on construction and clear it only in their own release, at which point their native Arc clone is already being dropped. If `Context.__init__` fails after the resolver was set (signer rejection, build failure), the `with self._NativeBuilder()` block frees the native builder, which owns the resolver by then (`set_http_resolver` does `Box::from_raw` — verified), so no native user of the thunk survives the exception. `_NativeHttpResolver` failure before consumption is freed by its own `with` block. No leak, no dangle, in any ordering I could construct under the documented single-owner usage rules.

**A5. No uncollectable cycles, no error-slot cross-thread confusion.** The thunk's closure chain (`Context → CFUNCTYPE → _trampoline → resolve_fn → resolver`) has no back-edge to Context unless the user creates one, and PEP 442 collects cycles through `__del__` anyway. `c2pa_error_set_last` writes a thread-local slot and the callback is synchronous, so the error is always set on exactly the thread that reads it after `rc != 0`.

**A6. Header parsing is injection-safe.** Rust builds the block from `http::HeaderMap` (names already lowercase, values cannot contain `\n` — `to_str()` filters), joins with `\n`, and always sends a valid, possibly empty, never-NULL CString. `partition(":")` keeps colons inside values. The Python side's NULL-guard is defensively redundant, which is fine.

---

## Part B — Findings. Ordered by severity; each with its adversarial confirmation and the fix Opus 5 should implement.

### B1 (High, security) — The reference resolvers are SSRF/local-file-read gadgets

The request URL a resolver receives originates from **untrusted asset content**: a remote-manifest reference embedded in whatever JPEG someone hands the application. Both `DebugHttpResolver` and `CachingHttpResolver` pass `request.url` straight to `urllib.request.urlopen`, whose default opener chain includes `FileHandler`, `FTPHandler`, and `DataHandler`. Confirmed consequences:

- A crafted asset with a `file:///etc/hostname`-style manifest URL makes the resolver read a **local file** and feed its contents into the SDK (and, for `CachingHttpResolver`, into the cache; for `DebugHttpResolver`, the URL into its log).
- `http://169.254.169.254/...` or any internal-network URL is fetched **from inside the caller's network** — the classic SSRF the built-in resolver's `core.allowed_network_hosts` exists to prevent, and which a custom resolver explicitly bypasses.
- `data:` URLs let the asset author synthesize the "fetched" bytes with no network at all.

The built-in Rust resolver speaks only http/https; the examples silently widen that. Since this directory is the copy-paste reference implementation, the examples are the spec — they must model the safe pattern.

**Fix:** in `http_resolver_example_impl.py`, both network-delegating resolvers reject non-`http(s)` schemes up front (parse with `urllib.parse.urlsplit`; on any other scheme, raise — a hard failure is the right semantic for "this URL should never be fetched"). Add a short "the URL is attacker-influenced" paragraph to `tests/http_resolver/README.md`'s host-filtering bullet, naming `file://` and internal-host SSRF explicitly. Add a no-network test: build a request-shaped object with a `file://` URL, call `resolve()` directly, assert it raises without touching the filesystem.

### B2 (Medium, data integrity) — Response status is silently double-truncated; a non-200 can alias to 200

Two modular reductions sit between the resolver's return value and what validation sees. Confirmed empirically on the Python side: assigning `2**35 + 200` to a `c_int` struct field **does not raise — it stores 200**. Confirmed in Rust source: `Response::builder().status(resp.status as u16)` truncates i32 → u16. Net effect: status `65736` (or `2**32 + 200`, etc.) reaches validation as a clean `200`; a negative status wraps. A malicious resolver gains nothing (it could return 200 honestly), so this is not an escalation — but a *buggy* resolver (an off-by-arithmetic on a retry counter mixed into status, a status parsed from a corrupt upstream) has its error laundered into success, which for a remote-manifest fetch means "manifest accepted" instead of "fetch failed". Silent modular arithmetic in a validation pipeline is corruption by another name.

**Fix:** in the trampoline, after the existing int/bool check: `if not 100 <= status <= 599: raise TypeError(f"resolver response .status out of range: {status}")`. The existing `BaseException` handler converts it into a typed error carrying that message. Test: resolver returning `65736` produces a `C2paError` mentioning the out-of-range value, not a success.

### B3 (Medium, contract integrity) — Falsy non-bytes bodies are silently masked to empty

`payload = result.body or b""` runs **before** the isinstance check, so `result.body = 0`, `False`, `0.0`, or `[]` all become `b""` and pass — confirmed: `0 or b""` → `b""`. The check that exists specifically to catch wrong-typed bodies has a falsy-shaped hole in it; a resolver bug returning `0` (say, a misplaced status) yields a well-formed empty 200 response instead of a diagnostic. Same family as B2: an error becomes silently valid data.

**Fix:** replace with explicit None-handling: `payload = result.body; if payload is None: payload = b""` then the existing isinstance check (which now sees `0` and raises). Test: resolver whose response has `body = 0` produces a typed error naming `int`, and `body = None` still means empty body.

### B4 (Medium, correctness/robustness) — The signer callback lags the trampoline's hardening on three counts

The resolver trampoline and the signer callback are the two Python→native callbacks in the file; the review compared them line by line. The signer's `wrapped_callback`:

1. **Catches `Exception`, not `BaseException`.** A `KeyboardInterrupt`/`SystemExit` raised inside the user's signing callback is swallowed by ctypes' own callback guard (ctypes never unwinds into native code — it reports the exception and returns the restype default, `0`). `0` is neither the `-1` error convention nor a plausible signature length; whether native code treats "0 bytes signed" as failure is left to chance, and the real cause is lost. The trampoline's `BaseException` catch exists for exactly this; mirror it.
2. **Never calls `c2pa_error_set_last`.** By the bridge's own (verified) analysis, the native error slot is thread-local and *not cleared* before callbacks — returning `-1` without setting it can surface a **stale error from an earlier call** as the signing failure's diagnosis. The trampoline sets the slot on every failure path; the signer sets it on none.
3. **Silently truncates oversized signatures.** `actual_len = min(len(signature), signed_len)` — a signature longer than the native buffer is cut and returned as if complete, guaranteeing a baffling downstream validation failure instead of a clear local error. Truncated cryptographic material is corruption, not accommodation.

**Fix:** catch `BaseException`; on every failure path call `c2pa_error_set_last` with a `"Other: Python signer callback failed: ..."` message (same sanitization as B5) before returning `-1`; and replace the `min()` with `if len(signature) > signed_len: set error slot; return -1`. Keep the existing `-1` returns for the input-validation branches but add slot messages there too. Test (unit-level, no signing round-trip needed): a callback returning an oversized `bytes` yields a typed error, not a truncated signature.

### B5 (Low, diagnostics) — Error-slot messages are NUL-truncatable and unbounded

`"Other: Python HTTP resolver failed: {}".format(e).encode("utf-8", "replace")` — confirmed empirically that a `bytes` argument with an embedded NUL passes through `c_char_p` fine and the C side simply stops at the NUL. Exception text is partly attacker-influenceable (server-supplied strings inside `URLError`/`HTTPError` messages), so a hostile upstream can blank out the diagnostic tail. Separately, nothing caps the size: a pathological exception message makes Rust build an equally pathological `CString`. Neither is memory-unsafe (that's the point of the confirmation); both degrade the one artifact you need when debugging a resolver in production.

**Fix:** one tiny helper used by both callbacks (B4 makes the signer need it too): take `str(e)`, replace `"\x00"` with `"\\x00"`, truncate to ~1 KB with an ellipsis marker, then encode. The `"Other: "` prefix is already fixed-position, so error-type spoofing via a crafted message (`"Signature: ..."`) is not possible — confirmed against Rust's first-colon parse; keep the prefix exactly as is.

### B6 (Low, hardening) — The `rc=0`-with-partial-response hazard is one careless edit away

The trampoline's safety story depends on a structural invariant nobody wrote down: **no fallible statement may sit between the first write into the response struct and `return 0`.** Today that's true (status write → body write → return). If a future edit inserts anything that can raise after `response.status = status`, the `BaseException` handler returns `-1` and Rust's error path cleans up correctly (frees a body if one was written) — that part is safe. The nastier variant is an edit that makes the *ctypes guard itself* the returner (an exception the handler can't run for, e.g. during interpreter teardown): ctypes returns the restype default `0`, and Rust reads a half-written struct as success. Can't be triggered today; cheap to fence off forever.

**Fix:** a loud comment at the write site stating the invariant, and — the actually load-bearing part — reorder so `response.status` is written **last**, after the body fields. Then any hypothetical partial state is "body set, status still 0", which Rust's `Response::builder().status(0)` rejects as an invalid status code rather than accepting. Zero-cost, converts the worst theoretical outcome from silent-success to clean failure.

### B7 (Low, optional hardening) — Reentrancy is documented UB; it could be a clean error instead

"Do not call c2pa APIs from inside the resolver" is currently enforced by hoping. A thread-local `_in_native_callback` flag set around the `resolve_fn` invocation (and the signer callback body), checked by `_ensure_valid_state` / the few module-level entry points, converts a re-entrant call into an immediate `C2paError("c2pa APIs must not be called from inside a resolver/signer callback")` on the exact offending line. Cost: one thread-local read on the hot path. Recommended, but genuinely optional — decline it if the entry-point audit gets invasive.

### B8 (Notes; docstring-only, no renames — API surface stays as instructed)

- The ctypes structs `C2paHttpRequest` / `C2paHttpResponse` / `C2paHttpResolver` carry docstrings saying they're "useful if planning to write custom HTTP resolvers." They aren't — resolver authors never touch ctypes; these are trampoline internals. Since the exposed API must not change, fix only the docstrings (e.g. "Internal ctypes mirror of the native struct; resolver authors interact with the decoded `C2paHttpRequestData` instead").
- Source builds on musl (Alpine) are the one configuration where `CDLL(None)` could disagree with the native library's allocator if someone produces a static-musl `.so`. Not reachable via shipped wheels (A3); one sentence in the build docs ("native artifact and Python must share a C runtime") closes it.
- Concurrent `close()` while another thread is mid-operation on the same object is a pre-existing, class-wide use-after-free hazard of `ManagedResource` (no in-flight guard exists), not introduced by this PR; the resolver merely adds the thunk to what dangles. Out of scope here — but the resolver docs' thread-safety note should say "do not close objects that another thread is still using" explicitly, since resolver users are the most likely to be multi-threaded.

---

## Part C — Test additions (all no-network, deterministic)

1. B1: `file://` URL → both example resolvers raise; nothing read from disk (assert via a path that would exist).
2. B2: status `65736` and status `-1` → typed `C2paError`, message names the value.
3. B3: body `0` → typed error naming `int`; body `None` → succeeds as empty.
4. B4: signer callback returning oversized signature → typed error, no truncation; signer callback raising `KeyboardInterrupt` → `-1` path with slot message (invoke `wrapped_callback` directly with ctypes buffers).
5. Regression for A1: resolver returns a `bytearray` and mutates it from a timer thread immediately after `resolve()` returns; signed/validated result must be built from the snapshot (deterministic version: mutate in a subclass's `__buffer__`-free wrapper before returning is enough to prove the copy point — keep it simple: assert the trampoline's copy equals the pre-mutation content by round-tripping through `AlwaysFailResolver`-style in-memory serving).
6. B5: resolver raising `Exception("boom\x00hidden")` → resulting `C2paError` message contains `boom` and the escaped marker, not a truncation at the NUL.

## Part D — Implementation order

B1 (examples + README + test) → B2/B3 together (same function, same test file) → B5 helper → B4 signer (uses the helper) → B6 reorder+comment → B7 if clean → B8 docstrings. Each step is independently landable; nothing here touches the exposed API, the FFI signatures, or the lifecycle machinery verified in Part A.
