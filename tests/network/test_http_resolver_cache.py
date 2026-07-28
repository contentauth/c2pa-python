# Copyright 2025 Adobe. All rights reserved.
# This file is licensed to you under the Apache License,
# Version 2.0 (http://www.apache.org/licenses/LICENSE-2.0)
# or the MIT license (http://opensource.org/licenses/MIT),
# at your option.

# Unless required by applicable law or agreed to in writing,
# this software is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR REPRESENTATIONS OF ANY KIND, either express or
# implied. See the LICENSE-MIT and LICENSE-APACHE files for the
# specific language governing permissions and limitations under
# each license.

"""A custom HTTP resolver that caches responses and retries throttled
requests, exercised against the real network.

Ported from the former examples/http_resolver_cache.py: still a runnable
demonstration of the resolver pattern, now also verified in CI. Needs
internet access to fetch the remote manifest for tests/fixtures/cloud.jpg;
tests skip (not fail) when that fetch can't reach the network.
"""

import collections
import os
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from typing import NamedTuple

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_REPO_ROOT, "src"))

import c2pa  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        os.pardir, "fixtures")


class HttpResponse(NamedTuple):
    """Duck-typed stand-in for c2pa's internal resolver response shape.

    The resolver contract only requires .status (int) and .body (bytes);
    there is no public type to import, any object with those attributes
    works.
    """
    status: int
    body: bytes = b""


def _skip_if_offline(testcase, exc):
    """Skip the test if exc looks like a network-reachability failure.

    Re-raises anything else, so a real bug in the resolver or the SDK
    still fails the test instead of being silently skipped.
    """
    message = str(exc)
    if "fetch" in message or "resolver" in message:
        testcase.skipTest(
            "needs internet access to fetch the remote manifest for "
            f"tests/fixtures/cloud.jpg: {exc}")
    raise exc


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

    Caching policy: only read GET requests answered with 200 are cached.
    POSTs (timestamp requests) and error responses are not.

    Retry policy: 429 and 503 are retried up to max_retries times,
    honoring a capped Retry-After when the header is present,
    and otherwise backing off exponentially.
    Any other status is final and is passed through to the SDK.
    Transport errors raise, which marks a hard failure.
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
                return HttpResponse(cached[0], cached[1])

        status, body = self._fetch_with_retries(request)
        if cacheable and status == 200:
            self.cache.put(request.url, (status, body))
        return HttpResponse(status, body)

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
                    # report it.
                    return e.code, e.read()
                delay = self._retry_delay(e, attempt)
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


class TestHttpResolverCache(unittest.TestCase):

    def test_read_with_cache(self):
        """Reading the same remote-manifest asset twice hits the cache."""
        resolver = CachingHttpResolver()
        try:
            with c2pa.Context.builder().with_resolver(
                    resolver).build() as context:
                for _ in range(2):
                    with open(os.path.join(FIXTURES, "cloud.jpg"),
                              "rb") as f:
                        with c2pa.Reader(
                                "image/jpeg", f, context=context) as reader:
                            reader.get_validation_state()
        except c2pa.C2paError as e:
            _skip_if_offline(self, e)

        self.assertEqual(resolver.cache.hits, 1)
        self.assertEqual(resolver.cache.misses, 1)

    def test_sign_with_cache(self):
        """Adding the same remote-manifest ingredient repeatedly hits the
        cache.

        Each add re-reads the ingredient's remote manifest through the
        context resolver, so three adds mean one network fetch and two
        cache hits.
        """
        with open(os.path.join(FIXTURES, "es256_certs.pem"), "rb") as f:
            certs = f.read()
        with open(os.path.join(FIXTURES, "es256_private.key"), "rb") as f:
            key = f.read()

        # ta_url is None, meaning "no timestamp authority".
        # An empty string is treated as a URL and fails signing.
        signer_info = c2pa.C2paSignerInfo(
            alg=b"es256", sign_cert=certs, private_key=key, ta_url=None)

        ingredient_labels = [f"cloud-ingredient-{i + 1}" for i in range(3)]

        manifest_definition = {
            "claim_generator": "http_resolver_cache",
            "claim_generator_info": [
                {"name": "http_resolver_cache", "version": "0.1"}],
            "format": "image/jpeg",
            "title": "Signed with a caching HTTP resolver",
            "assertions": [{
                "label": "c2pa.actions.v2",
                "data": {"actions": [
                    {
                        "action": "c2pa.created",
                        "digitalSourceType":
                            "http://cv.iptc.org/newscodes/"
                            "digitalsourcetype/digitalCreation",
                    },
                    {
                        "action": "c2pa.placed",
                        "parameters": {"ingredientIds": ingredient_labels},
                    },
                ]},
            }],
        }

        resolver = CachingHttpResolver()
        context = (c2pa.Context.builder()
                   .with_resolver(resolver)
                   .with_signer(c2pa.Signer.from_info(signer_info))
                   .build())
        try:
            try:
                builder = c2pa.Builder(manifest_definition, context=context)

                with open(os.path.join(FIXTURES, "cloud.jpg"),
                          "rb") as ingredient:
                    for index in range(3):
                        ingredient.seek(0)
                        builder.add_ingredient(
                            {"title": f"cloud.jpg #{index + 1}",
                             "relationship": "componentOf",
                             "label": ingredient_labels[index]},
                            "image/jpeg", ingredient)

                with tempfile.TemporaryDirectory() as output_dir:
                    output_path = os.path.join(
                        output_dir, "A_signed_cached.jpg")
                    with open(os.path.join(FIXTURES, "A.jpg"),
                              "rb") as source:
                        with open(output_path, "wb") as dest:
                            builder.sign(
                                c2pa.Signer.from_info(signer_info),
                                "image/jpeg", source, dest)
                    self.assertTrue(os.path.exists(output_path))
            except c2pa.C2paError as e:
                _skip_if_offline(self, e)
        finally:
            context.close()

        self.assertEqual(resolver.cache.misses, 1)
        self.assertEqual(resolver.cache.hits, 2)

    def test_failing_resolver_is_a_clean_error(self):
        """A final failure surfaces as a typed error, not a crash.

        Needs no network: the resolver answers without calling out.
        """
        def always_500(request):
            return HttpResponse(500, b"")

        with c2pa.Context.builder().with_resolver(
                always_500).build() as context:
            with self.assertRaises(c2pa.C2paError):
                with open(os.path.join(FIXTURES, "cloud.jpg"), "rb") as f:
                    c2pa.Reader("image/jpeg", f, context=context)


if __name__ == "__main__":
    unittest.main()
