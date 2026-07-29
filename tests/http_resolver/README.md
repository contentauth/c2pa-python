# Custom HTTP resolvers

This document explains how (custom) HTTP resolvers works end to end, what the SDK does and does not do with HTTP, and the platform differences (Linux, Windows, macOS) that affect a resolver in practice.

## HTTP resolvers overview

A custom HTTP resolver lets you intercept every HTTP request the SDK makes through a `Context`, so you can add headers, cache responses, or serve responses from memory in tests.

c2pa ships no resolver types at all: there is no `HttpRequest`, `HttpResponse`, or `HttpResolver` to import from `c2pa`. `ContextBuilder.with_resolver()` (and the `Context(resolver=...)` constructor argument, also accepted by `Context.from_json`/`from_dict`) never does an `isinstance` check. It accepts either:

- any callable taking one request argument, or
- any object with a `resolve(request)` method.

The request handed to you exposes `.url` (str), `.method` (str), `.headers` (dict), and `.body` (bytes). The value you return only needs `.status` (int) and `.body` (bytes) attributes. The minimal form needs no imports at all:

```py
def my_resolver(request):
    # request.url, request.method, request.headers, request.body
    return SomeResponse(status=200, body=b"...")

context = c2pa.Context.builder().with_resolver(my_resolver).build()
reader = c2pa.Reader("image/jpeg", stream, context=context)
```

The resolver is validated immediately: something with neither shape raises `TypeError` from `with_resolver()` itself (or from the `Context` constructor on the direct path), not later at `.build()`. If a resolver object has both a `resolve()` method and is itself callable, `resolve()` wins.

[`http_resolver_example_impl.py`](./http_resolver_example_impl.py) is an example implementation of that shape. It defines `HttpRequest`, `HttpResponse`, and an optional `HttpResolver` abstract base class (subclassing it is not required, it just gets you a documented, type-checkable contract instead of duck typing), plus three example resolvers: `DebugHttpResolver` (logs every request/response, delegates the transfer to `urllib`), `CachingHttpResolver` (TTL'd LRU cache plus retry/backoff for throttled requests), and `AlwaysFailResolver` (answers every request with a fixed status; needs no network). The module has no dependency on `c2pa` itself; only the tests import `c2pa`, to exercise the resolvers against real `Context`/`Reader`/`Builder` instances.

## Notes on runtime

The native library and the Python process must share a C runtime: buffers the HTTP resolver bridge allocates are freed on the native side with `libc::free`, so a native library built against a different C runtime (e.g. a static-musl `.so`) than the one your Python process loads will corrupt memory.

## What traffic flows through a resolver (and when)

A resolver attached to a `Context` handles **every** HTTP request the SDK makes through that `Context`. Scope and gating to keep in mind:

- The resolver is **per-Context**. `Reader` and `Builder` instances created *without* that `Context` keep using the SDK's built-in resolver. Attaching a resolver to one `Context` changes nothing anywhere else.
- `with_resolver()` can be called multiple times when creating a context to use: the last resolver set wins and will be used.
- **Settings still gate the resolver.** With `verify.remote_manifest_fetch` set to `false`, the resolver is never invoked for a remote-manifest read; the read fails instead. A resolver is not a way to re-enable disabled fetching.

## How resolution works, end to end

Conceptually the pipeline is: native code decides it needs an HTTP resource, calls back into Python, your resolver performs the transfer however it likes, then the response is copied back into native memory. Concretely:

1. **Wiring.** `Context.__init__` normalizes your resolver into a plain callable (the `resolve` bound method, or the callable itself) and wraps it in a ctypes trampoline (`C2paHttpResolverBridge._make_trampoline`). A short-lived native resolver handle is created via `c2pa_http_resolver_create` and consumed by `c2pa_context_builder_set_http_resolver`; the native context builder takes ownership, so there is nothing for you to free.
2. **Invocation.** Whenever the native library needs an HTTP resource through that context, it synchronously invokes the trampoline with a pointer to a native request struct and a pointer to a zero-initialized native response struct. The call blocks the SDK operation (`Reader(...)`, `builder.sign(...)`, `add_ingredient(...)`) that triggered it, and **there is no SDK-side timeout**. A resolver that hangs, hangs that SDK call. Timeouts are entirely your responsibility (both example resolvers pass `timeout=` to `urllib.request.urlopen`).
3. **Decode.** The trampoline copies everything out of the native request struct (URL, method, headers, body) into a plain Python object (`C2paHttpRequestData`) holding `str`/`bytes`. Because it is a copy, the request object stays valid after your `resolve()` returns; storing it (as `DebugHttpResolver` stores `(method, url)` tuples) is safe.
4. **Resolve.** Your `resolve()` runs and returns a response-shaped object, or raises.
5. **Encode.** The trampoline validates the response (`.status` must be an `int`, `.body` must be `bytes`/`bytearray`), copies a non-empty body into a buffer allocated with the C runtime `malloc`, and writes status/body/length into the native response struct. Ownership of that buffer transfers to native code, which frees it on both the success and the error path. You never allocate or free anything yourself; you only ever return `bytes`.
6. **Consume.** The native side copies the body out, frees the buffer, and hands the response to whatever validation or signing logic asked for it.

## Request semantics

- `url` is the absolute request URL.
- `method` is the HTTP verb: `GET` for manifest fetches, `POST` for timestamp requests.
- `headers` is a dict. Header names arrive **lowercased** by the native layer. Repeated headers are delivered as separate lines internally; in the dict, the **last occurrence wins**.
- `body` is `b""` when there is no body (manifest fetches); timestamp requests `POST` a body. `request.body or None` is the idiomatic way to hand it to `urllib.request.Request`, as both examples do.

## Response and error semantics

- **Status passes through.** Return the real status; do not translate. For a remote manifest fetch, only `200` is accepted; anything else surfaces to the SDK caller as a typed `C2paError`. `DebugHttpResolver` shows the right pattern for `urllib`: an `HTTPError` is still a response, so it returns `HttpResponse(e.code, e.read())` and lets the SDK produce its own error.
- **Raising marks a hard failure.** A transport-level problem (DNS failure, connection refused, timeout) is not a response; raise, and the SDK reports the request as failed. The examples deliberately do *not* catch `urllib.error.URLError` for exactly this reason.
- **Your exception does not propagate as itself.** Exceptions cannot unwind across the ctypes/native boundary. The trampoline catches everything you raise, including `BaseException` and `KeyboardInterrupt`, records its message in the native error slot, and the failure re-emerges as a typed `C2paError` raised from the `Reader`/`Builder` call that triggered the fetch. `except MyCustomError:` around `c2pa.Reader(...)` will never fire; catch `c2pa.C2paError` and read the message.
- **Shape errors are caught early.** Returning a `str` body, a `None` status, or a `bool` status is rejected inside the trampoline with a clear `TypeError` message, which then surfaces the same way (as a `C2paError`).
- An **empty body** is fine: return `b""` (as `AlwaysFailResolver` does), and the trampoline correctly leaves the native body pointer/length pair empty together.

## Lifetimes

- **The resolver outlives `Context.close()`.** Native `Reader`/`Builder` instances hold their own reference to the underlying native context, so your resolver can still be invoked after the Python `Context` is closed, for as long as any `Reader` or `Builder` created from it is alive. Do not tear down resolver resources (close a session, release a pool) on `Context.close()`; tie them to the resolvers' own lifetime instead. The SDK internally pins the callback thunk to keep this safe, so there is nothing you need to hold onto yourself.
- **No reentrancy.** Do not call c2pa APIs from inside `resolve()`. Re-entering the FFI while a call is in flight is undefined.
- **Concurrent close() is unsafe.** Do not close a `Context`/`Reader`/`Builder` from one thread while another thread still has a call in flight on that same object, including a resolver call it triggered. This is a general property of these objects, not something specific to resolvers, but resolver users are the most likely to be multi-threaded.

## What the SDK does and does not do with HTTP

The SDK delegates the *transfer* entirely; the resolver *is* the HTTP client. That means:

- **No redirects.** The SDK does not follow redirects; a `301`/`302` returned as-is is just a non-200. Delegating to `urllib.request` (as both examples do) gives you redirect handling for free. A hand-rolled resolver must implement it.
- **Host filtering is bypassed.** The `core.allowed_network_hosts` setting only filters the *built-in* resolver. A custom resolver receives every request regardless; if you need an allowlist, enforce it yourself in `resolve()` (raise or return an error status for disallowed hosts). The URL is attacker-influenced: it comes from a remote-manifest reference embedded in whatever asset someone hands the application, so a resolver that hands it straight to a general-purpose HTTP client without a scheme check is a `file://` local-file-read and internal-network SSRF gadget. Both example resolvers reject any URL whose scheme is not `http`/`https` before doing anything else, for this reason.
- **TLS is yours.** Certificate verification, trust stores, and proxy handling all belong to whatever HTTP stack your resolver uses. The SDK sees only status and bytes. This is where most of the platform-specific behavior lives; see the platform section below.
- **No Content-Length plumbing.** The resolver response carries no `Content-Length`, so remote manifests larger than 10 MB are truncated **without an error**. If you serve large manifests, be aware the failure mode downstream is a validation error, not a size error.
- **No caching, retries, or backoff.** Each needed resource is requested; policy is yours. `CachingHttpResolver` is the reference for a reasonable policy: cache only `GET`s answered with `200` (never `POST`s, since timestamp requests must not be replayed from cache, and never error responses), retry only `429`/`503` with a capped `Retry-After` or exponential backoff, and pass every other status through untouched.

## Platform differences: Linux, Windows, macOS

The trampoline itself behaves identically everywhere, but four areas differ per platform in ways that bite resolver implementers.

### 1. The C runtime and the response buffer (why you never allocate)

The response body buffer must be allocated by the **same C runtime whose `free()` the native library calls** (on the Rust side that is `libc::free`). On Linux and macOS there is effectively one C runtime per process (glibc/musl, libSystem), so "the process's own libc" is always the right allocator. **Windows is different:** a process can host several C runtimes side by side, each with its own heap. Rust's MSVC targets link the Universal CRT, so `free` there is `ucrtbase`'s, while the legacy `msvcrt.dll` is a *different* heap. Allocating from one and freeing into the other is heap corruption, not a leak, and it corrupts silently until it crashes somewhere unrelated.

The bridge handles this for you: it loads `ucrtbase` first and falls back to `msvcrt`, and does the `malloc`+copy from the `bytes` you return. The rule for implementers: **return `bytes`, never a pointer, never something you allocated with ctypes yourself.** The reason this rule exists is Windows.

### 2. TLS trust stores

The example resolvers delegate to `urllib`, so they inherit Python's `ssl` defaults, which differ by platform:

- **macOS:** python.org builds do **not** use the system Keychain. If `Install Certificates.command` was never run after installing Python, every HTTPS fetch fails with `CERTIFICATE_VERIFY_FAILED`. Workaround without reinstalling: prefix the run with `SSL_CERT_FILE=$(python -m certifi)`.
- **Linux:** OpenSSL uses the distribution's CA bundle. On a normal desktop this just works; in slim container images the `ca-certificates` package is often missing, producing the same `CERTIFICATE_VERIFY_FAILED`. Install the package or set `SSL_CERT_FILE`.
- **Windows:** Python's `ssl` loads roots from the Windows certificate store, so system-managed (including enterprise-injected) roots are honored automatically. Corporate TLS-interception proxies therefore tend to *work* on Windows and *fail* on macOS/Linux with the same code. If a fetch verifies on one machine and not another, compare trust stores before suspecting the resolver.

A resolver using a different HTTP stack has that stack's trust behavior instead. TLS trust is resolver-side, per-platform, and invisible to the SDK.

### 3. Proxies

`urllib` discovers proxies differently per platform: environment variables (`http_proxy`, `https_proxy`, `no_proxy`) everywhere, **plus** the Windows registry (Internet Settings) on Windows and the System Configuration framework (Network preferences) on macOS. On Linux, environment variables are the only source. So a resolver built on `urllib` silently follows OS-level proxy settings on Windows/macOS but ignores them on Linux, another way the same resolver code behaves differently per machine. If you need deterministic behavior, configure the proxy (or the absence of one) explicitly in your resolver rather than relying on discovery.

### 4. Process model: fork vs. spawn

Default `multiprocessing` start methods differ: historically `fork` on Linux (`forkserver` since Python 3.14), `spawn` on macOS and Windows. Under `spawn`, a child process imports fresh and never inherits a `Context`, so there is nothing to think about. Under `fork`, the child inherits the parent's memory image, including a `Context` with a resolver attached. The SDK's native handles are PID-stamped so a forked child neither uses nor frees the parent's native resources (see [`../../docs/native-resources-management.md`](../../docs/native-resources-management.md)), but your *resolver's own* state is ordinary Python and gets copied: locks are cloned in whatever state they were in, background threads do **not** survive the fork, and open sockets/sessions are shared with the parent. A resolver holding only per-call state (like both examples) forks safely; one holding live connections should be recreated in the child. This concern is Linux-only in practice.

## Examples and tests

- [`http_resolver_example_impl.py`](./http_resolver_example_impl.py): the reference shapes (`HttpRequest`, `HttpResponse`, optional `HttpResolver` ABC) and the three resolvers described above. Copy it into your project and adapt it; it does not import `c2pa`.
- [`test_http_resolver_debug.py`](./test_http_resolver_debug.py): exercises `DebugHttpResolver`, verifying that a remote-manifest read logs a `GET`, that signing with a remote-manifest ingredient fetches it through the resolver, and that re-reading the signed (embedded-manifest) output performs no HTTP at all.
- [`test_http_resolver_cache.py`](./test_http_resolver_cache.py): exercises `CachingHttpResolver` (reading twice / ingesting the same ingredient repeatedly hits the cache exactly as the hit/miss counters predict) and `AlwaysFailResolver` (a non-200 answer surfaces as a clean typed `C2paError`, with no network needed).

Both network tests need internet access to fetch the remote manifest for `tests/fixtures/cloud.jpg`, and fail without it. If your Python has no CA bundle configured, every fetch fails with `CERTIFICATE_VERIFY_FAILED` (see the TLS section above); on macOS, prefix the commands with `SSL_CERT_FILE=$(python -m certifi)`.

Run them in a CLI with the commands:

```bash
python ./tests/http_resolver/test_http_resolver_debug.py
python ./tests/http_resolver/test_http_resolver_cache.py

# Or the whole directory via unittest discovery:
python -m unittest discover -s tests/http_resolver -v
```
