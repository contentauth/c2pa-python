# On custom HTTP resolvers

A custom HTTP resolver lets you intercept every HTTP request the SDK makes through a `Context`. You can use custom resolvers to add headers, cache responses, log traffic, or serve responses from memory in tests.

c2pa ships no resolver types at all — no `HttpRequest`, `HttpResponse`, or `HttpResolver` to import from `c2pa`. `with_resolver()` never does an `isinstance` check: it accepts any callable, or any object with a `resolve(request)` method. The request it receives exposes `.url`, `.method`, `.headers` (dict), and `.body` (bytes); the response it returns only needs `.status` (int) and `.body` (bytes) attributes.

The minimal form needs no imports at all:

```py
def my_resolver(request):
    # request.url, request.method, request.headers, request.body
    return SomeResponse(status=200, body=b"...")

context = c2pa.Context.builder().with_resolver(my_resolver).build()
reader = c2pa.Reader("image/jpeg", stream, context=context)
```

[`http_resolver.py`](./http_resolver.py) in this directory is a reference implementation of that shape — copy it into your own project or adapt it. It has `HttpRequest`, `HttpResponse`, an optional `HttpResolver` base class (subclassing it is not required — it just gets you a documented, type-checkable contract instead of duck typing), plus two example resolvers this test suite exercises: `CachingHttpResolver` (LRU cache with a TTL and retry/backoff for throttled requests) and `DebugHttpResolver` (logs every request/response, delegating the transfer to `urllib`). Neither example imports `c2pa` itself — only the `test_http_resolver_*.py` files do, to exercise them against real `Context`/`Reader`/`Builder` instances.

Whichever form you use, it's validated immediately: passing something with neither shape raises `TypeError` from `with_resolver()` itself, not later at `.build()`. Raising from the resolver marks the request as a hard failure. Returning a non-200 status passes that status through, and the SDK turns it into a typed `C2paError`.

Two things to note before writing one:

- A custom resolver bypasses the `core.allowed_network_hosts` setting, which only filters the built-in resolver. Host filtering becomes your responsibility.
- The SDK does not follow redirects by default. Delegating to `urllib.request` as `http_resolver.py`'s examples do gives you redirect handling for free.

## How a custom resolver works

1. **The wiring.** `ContextBuilder.with_resolver(resolver)` stores the resolver, validating it eagerly. `Context.__init__` (whether reached via the builder or `Context(resolver=...)` directly) wraps it in `Context._NativeHttpResolver` — a private nested class in `c2pa.py` that owns the native `C2paHttpResolver` handle via `c2pa_http_resolver_create`, following the same `ManagedResource` lifecycle as `Context._NativeBuilder`/`Reader`/`Builder`/`Signer`.

2. **The trampoline.** Your resolver is wrapped into a ctypes `CFUNCTYPE` callback (`_make_http_resolver_trampoline`, a module-private function in `c2pa.py`). The native side calls this callback for every HTTP request the SDK makes through that `Context` — remote manifest fetches, OCSP requests, RFC 3161 timestamp requests, and CAWG did:web resolution. The callback decodes the native `C2paHttpRequest` struct into plain Python `str`/`bytes`, calls your `resolve()`, and writes the result back into the native `C2paHttpResponse` struct.

3. **Memory and ownership handling** — the part implementers most often get wrong:
   - A non-empty response body must be allocated with the *same C runtime malloc* the native library's `free()` will use (`ucrtbase` before `msvcrt` on Windows, the process's own libc elsewhere). Mismatched allocators cause heap corruption, not a leak. You don't need to worry about this yourself — the trampoline does the allocation and copy for you from the `bytes` your resolver returns.
   - Ownership transfers to native code once that buffer is written into the response struct: native frees it on *both* the success path (after copying) and the error path. Nothing on the Python side ever frees it.
   - The zero-length trap: an empty body must leave `body`/`body_len` as `NULL`/`0` *together* — a non-NULL pointer with `body_len == 0` is never freed by native code and leaks. The trampoline handles this for you as long as your resolver returns `b""` (not some non-empty placeholder) for an empty body.
   - The callback thunk is pinned on the `Context` and deliberately *not* cleared when the `Context` closes: native `Reader`/`Builder` instances clone the underlying Arc, so your resolver can still be invoked by a native clone after `Context.close()`, for as long as that `Reader`/`Builder` is alive. Your resolver must stay valid (and thread-safe — it may be called from SDK worker threads) for that whole lifetime.
   - Exceptions cannot unwind across the ctypes/native boundary: the trampoline catches every exception your resolver raises, reports it to the native error slot, and turns it into a typed `C2paError` raised from the `Reader`/`Builder` call that triggered the fetch — never from inside your `resolve()` itself.

### The testable examples

The [`test_http_resolver_debug.py`](./test_http_resolver_debug.py) test exercises `DebugHttpResolver`: logs the method and URL of each request and the status of each response.

The [`test_http_resolver_cache.py`](./test_http_resolver_cache.py) test exercises `CachingHttpResolver`: an LRU cache with a TTL (defaults: 100 items, 120 seconds) that retries throttled requests. Only GET requests answered with 200 are cached.

Run the testable examples with:

```bash
python ./tests/network/test_http_resolver_debug.py      # needs network
python ./tests/network/test_http_resolver_cache.py      # needs network

# Or the whole directory via unittest discovery:
python -m unittest discover -s tests/network -v
```
