import collections
import os
import sys
import threading
import time
import urllib.error
import urllib.request

import c2pa

# This example shows a custom HTTP resolver that caches responses and retries
# throttled requests, using nothing but the standard library.
#
# The SDK may call a resolver from worker threads, so everything here is
# thread-safe.
#
# This example needs internet access: tests/fixtures/cloud.jpg carries no
# embedded manifest, only a remote one that has to be fetched.

fixtures_dir = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "tests", "fixtures") + os.sep
output_dir = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "output") + os.sep


class TtlLruCache:
    """A small LRU cache whose entries also expire after a TTL."""

    def __init__(self, max_items=100, ttl_seconds=120.0):
        self._max_items = int(max_items)
        self._ttl = float(ttl_seconds)
        self._entries = collections.OrderedDict()  # key -> (expiry, value)
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def get(self, key):
        with self._lock:
            entry = self._entries.get(key)
            # time.monotonic, not time.time: immune to wall-clock jumps.
            if entry is not None and entry[0] > time.monotonic():
                self._entries.move_to_end(key)
                self.hits += 1
                return entry[1]
            if entry is not None:
                del self._entries[key]
            self.misses += 1
            return None

    def put(self, key, value):
        with self._lock:
            if key in self._entries:
                self._entries.move_to_end(key)
            self._entries[key] = (time.monotonic() + self._ttl, value)
            while len(self._entries) > self._max_items:
                self._entries.popitem(last=False)


class CachingHttpResolver:
    """An HTTP resolver with a response cache and bounded retries.

    Caching policy: only GET requests answered with 200 are cached. POSTs
    (timestamp requests) and error responses never are.

    Retry policy: 429 and 503 are retried up to max_retries times, honoring
    a capped Retry-After when the header is present and otherwise backing
    off exponentially. Any other status is final and is passed through to
    the SDK. Transport errors raise, which marks a hard failure.
    """

    def __init__(self, cache=None, timeout=10.0, max_retries=3,
                 backoff_seconds=0.5, max_retry_after=10.0):
        self.cache = cache if cache is not None else TtlLruCache()
        self._timeout = timeout
        self._max_retries = int(max_retries)
        self._backoff = float(backoff_seconds)
        self._max_retry_after = float(max_retry_after)

    def resolve(self, request):
        cacheable = request.method.upper() == "GET"
        if cacheable:
            cached = self.cache.get(request.url)
            if cached is not None:
                print(f"[cache] HIT  {request.url}", flush=True)
                return c2pa.HttpResponse(cached[0], cached[1])
            print(f"[cache] MISS {request.url}", flush=True)

        status, body = self._fetch_with_retries(request)
        if cacheable and status == 200:
            self.cache.put(request.url, (status, body))
        return c2pa.HttpResponse(status, body)

    def _fetch_with_retries(self, request):
        data = request.body or None
        for attempt in range(self._max_retries + 1):
            req = urllib.request.Request(
                request.url,
                data=data,
                method=request.method,
                headers=request.headers)
            try:
                with urllib.request.urlopen(
                        req, timeout=self._timeout) as resp:
                    return resp.status, resp.read()
            except urllib.error.HTTPError as e:
                retryable = e.code in (429, 503)
                if not retryable or attempt == self._max_retries:
                    # Final failure: pass the status back so the SDK can
                    # report it as a typed error. Not cached.
                    return e.code, e.read()
                delay = self._retry_delay(e, attempt)
                print(f"[http]  {e.code}, retrying in {delay:.1f}s",
                      flush=True)
                time.sleep(delay)
        raise RuntimeError("unreachable")

    def _retry_delay(self, error, attempt):
        retry_after = error.headers.get("Retry-After")
        if retry_after:
            try:
                return min(float(retry_after), self._max_retry_after)
            except ValueError:
                pass
        return self._backoff * (2 ** attempt)


def read_with_cache():
    """Read the same remote-manifest asset twice: one fetch, one cache hit."""
    print("\n--- Reading cloud.jpg twice through one cache ---")

    resolver = CachingHttpResolver()
    with c2pa.Context.builder().with_resolver(resolver).build() as context:
        for round_number in (1, 2):
            with open(fixtures_dir + "cloud.jpg", "rb") as f:
                with c2pa.Reader("image/jpeg", f, context=context) as reader:
                    print(f"  read {round_number}: "
                          f"{reader.get_validation_state()}")

    print(f"cache hits={resolver.cache.hits} misses={resolver.cache.misses}")


def sign_with_cache():
    """Add the same remote-manifest ingredient repeatedly, hitting the cache.

    Each add re-reads the ingredient's remote manifest through the context
    resolver, so three adds mean one network fetch and two cache hits.
    """
    print("\n--- Signing with the same remote ingredient added 3 times ---")

    with open(fixtures_dir + "es256_certs.pem", "rb") as f:
        certs = f.read()
    with open(fixtures_dir + "es256_private.key", "rb") as f:
        key = f.read()

    # ta_url is None, meaning "no timestamp authority". An empty string is
    # treated as a URL and fails signing.
    signer_info = c2pa.C2paSignerInfo(
        alg=b"es256", sign_cert=certs, private_key=key, ta_url=None)

    manifest_definition = {
        "claim_generator": "http_resolver_cache",
        "claim_generator_info": [
            {"name": "http_resolver_cache", "version": "0.1"}],
        "format": "image/jpeg",
        "title": "Signed with a caching HTTP resolver",
        "assertions": [],
    }

    # A fresh resolver per flow keeps the printed counts easy to follow.
    resolver = CachingHttpResolver()
    context = (c2pa.Context.builder()
               .with_resolver(resolver)
               .with_signer(c2pa.Signer.from_info(signer_info))
               .build())
    try:
        builder = c2pa.Builder(manifest_definition, context=context)

        with open(fixtures_dir + "cloud.jpg", "rb") as ingredient:
            for index in range(3):
                ingredient.seek(0)
                builder.add_ingredient(
                    {"title": f"cloud.jpg #{index + 1}"},
                    "image/jpeg", ingredient)

        os.makedirs(output_dir, exist_ok=True)
        output_path = output_dir + "A_signed_cached.jpg"
        with open(fixtures_dir + "A.jpg", "rb") as source:
            with open(output_path, "wb") as dest:
                builder.sign(
                    c2pa.Signer.from_info(signer_info),
                    "image/jpeg", source, dest)
        print(f"signed asset written to {output_path}")
    finally:
        context.close()

    print(f"cache hits={resolver.cache.hits} misses={resolver.cache.misses} "
          "(expected 2 hits, 1 miss)")


def failing_resolver_is_a_clean_error():
    """A final failure surfaces as a typed error, not a crash."""
    print("\n--- A resolver that always answers 500 ---")

    def always_500(request):
        return c2pa.HttpResponse(500, b"")

    with c2pa.Context.builder().with_resolver(always_500).build() as context:
        try:
            with open(fixtures_dir + "cloud.jpg", "rb") as f:
                c2pa.Reader("image/jpeg", f, context=context)
            print("unexpected success")
        except c2pa.C2paError as e:
            print(f"got a typed error as expected: {e}")


def main():
    try:
        read_with_cache()
        sign_with_cache()
    except c2pa.C2paError as e:
        message = str(e)
        if "fetch" in message or "resolver" in message:
            print(f"\nError: {e}")
            print("This example needs internet access to fetch the remote "
                  "manifest for tests/fixtures/cloud.jpg.")
            sys.exit(1)
        raise

    # This one needs no network: the resolver answers without calling out.
    failing_resolver_is_a_clean_error()


if __name__ == "__main__":
    main()
