## Using a custom HTTP resolver

A custom HTTP resolver lets you intercept every HTTP request the SDK makes through a `Context`. You can use custom resolvers to add headers, cache responses, log traffic, or serve responses from memory in tests.

A resolver is either an object with a `resolve(request)` method or a plain callable. It receives a request object exposing `.url`, `.method`, `.headers` (dict), and `.body` (bytes), and must return a response object exposing `.status` (int) and `.body` (bytes) — any object with those attributes works, there is no type to import:

```py
class AnHttpResolver:
    def resolve(self, request):
        # request.url, request.method, request.headers, request.body
        return SomeResponse(status=200, body=b"...")

context = c2pa.Context.builder().with_resolver(MyResolver()).build()
reader = c2pa.Reader("image/jpeg", stream, context=context)
```

Raising from the resolver marks the request as a hard failure. Returning a non-200 status passes that status through, and the SDK turns it into a typed `C2paError`.

Two things to note before writing one:

- A custom resolver bypasses the `core.allowed_network_hosts` setting, which only filters the built-in resolver. Host filtering becomes your responsibility.
- The SDK does not follow redirects by default. Delegating to `urllib.request` in the examples below gives you redirect handling for free.

Custom resolvers need a live remote manifest to demonstrate against, so their examples live as runnable tests rather than standalone scripts:

The [`tests/network/test_http_resolver_debug.py`](https://github.com/contentauth/c2pa-python/blob/main/tests/network/test_http_resolver_debug.py) test logs the method and URL of each request and the status of each response, delegating the transfer to `urllib`.

The [`tests/network/test_http_resolver_cache.py`](https://github.com/contentauth/c2pa-python/blob/main/tests/network/test_http_resolver_cache.py) test adds an LRU cache with a TTL (defaults: 100 items, 120 seconds) and retries throttled requests. Only GET requests answered with 200 are cached.

Both use `tests/fixtures/cloud.jpg`, which has no embedded manifest, only a remote one, so they need network access; each test skips (rather than fails) when it can't reach the network. Run them with:

```bash
python -m pytest tests/network/ -v
```
