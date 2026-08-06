# Copyright 2026 Adobe. All rights reserved.
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

"""Tests for CachingHttpResolver, an HTTP resolver that caches on read.
"""

import os
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(os.path.dirname(_HERE))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(_REPO_ROOT, "src"))

FIXTURES = os.path.join(_REPO_ROOT, "tests", "fixtures")

from http_resolver_example_impl import (  # noqa: E402
    AlwaysFailResolver, CachingHttpResolver, HttpRequest)

import c2pa  # noqa: E402


class _StubFetchCachingResolver(CachingHttpResolver):
    """CachingHttpResolver with the network swapped for a canned answer,
    so the caching *decision* can be tested without a real HTTP call.
    """

    def __init__(self, status=200, body=b"payload"):
        super().__init__()
        self._canned = (status, body)
        self.fetch_count = 0

    def _fetch_with_retries(self, request):
        self.fetch_count += 1
        return self._canned


class TestCachingDecision(unittest.TestCase):
    """Tests for what CachingHttpResolver will and won't cache.
    """

    def test_opaque_encoded_get_is_never_cached(self):
        """A GET whose URL ends in a long opaque token (the shape used by
        e.g. a certificate revocation check) is fetched fresh every time,
        never served from the cache.
        """
        resolver = _StubFetchCachingResolver()
        request = HttpRequest(
            url="https://ca.example/ocsp/" + ("a" * 60),
            method="GET", headers={}, body=b"")

        resolver.resolve(request)
        resolver.resolve(request)

        self.assertEqual(resolver.fetch_count, 2)
        self.assertEqual(resolver.cache.hits, 0)

    def test_post_is_never_cached(self):
        """A request carrying a payload is never replayed from the cache."""
        resolver = _StubFetchCachingResolver()
        request = HttpRequest(
            url="https://tsa.example/timestamp", method="POST",
            headers={"content-type": "application/timestamp-query"},
            body=b"query")

        resolver.resolve(request)
        resolver.resolve(request)

        self.assertEqual(resolver.fetch_count, 2)
        self.assertEqual(resolver.cache.hits, 0)

    def test_ordinary_get_is_cached(self):
        """A plain GET the resolver can't positively rule out is treated
        as an ordinary resource fetch and cached, so the fix doesn't
        disable caching for the case it's meant to serve.
        """
        resolver = _StubFetchCachingResolver()
        request = HttpRequest(
            url="https://cdn.example/manifests/x.c2pa", method="GET",
            headers={}, body=b"")

        resolver.resolve(request)
        resolver.resolve(request)

        self.assertEqual(resolver.fetch_count, 1)
        self.assertEqual(resolver.cache.hits, 1)


class TestHttpResolverCache(unittest.TestCase):

    def test_read_with_cache(self):
        """Reading the same remote-manifest asset twice hits the cache.

        Assumption this exact-count assert depends on: one remote-manifest
        GET per read, and nothing else on this path (no OCSP, no did:web).
        If the SDK ever adds another GET here, this count shifts -- that's
        expected and worth updating, not a false alarm.
        """
        print('\n--- Reading using an HTTP resolver with a cache')
        resolver = CachingHttpResolver()
        with c2pa.Context.builder().with_resolver(
                resolver).build() as context:
            for i in range(2):
                print(f"Read #{i + 1} of cloud.jpg")
                with open(os.path.join(FIXTURES, "cloud.jpg"),
                          "rb") as f:
                    with c2pa.Reader(
                            "image/jpeg", f, context=context) as reader:
                        reader.get_validation_state()
                print(f"Cache state after read #{i + 1}: "
                      f"hits={resolver.cache.hits} "
                      f"misses={resolver.cache.misses}")

        self.assertEqual(resolver.cache.hits, 1)
        self.assertEqual(resolver.cache.misses, 1)

    def test_sign_with_cache(self):
        """Adding the same remote-manifest ingredient repeatedly hits the
        cache.

        Each add re-reads the ingredient's remote manifest through the
        context resolver, so three adds mean one network fetch and two
        cache hits.
        """
        print('\n--- Reading and signing using an HTTP resolver with a cache')
        with open(os.path.join(FIXTURES, "es256_certs.pem"), "rb") as f:
            certs = f.read()
        with open(os.path.join(FIXTURES, "es256_private.key"), "rb") as f:
            key = f.read()

        # ta_url is None, meaning "no timestamp authority".
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
            builder = c2pa.Builder(manifest_definition, context=context)

            with open(os.path.join(FIXTURES, "cloud.jpg"),
                      "rb") as ingredient:
                for index in range(3):
                    ingredient.seek(0)
                    print(f"Adding ingredient #{index + 1} of 3 "
                          f"({ingredient_labels[index]})")
                    builder.add_ingredient(
                        {"title": f"cloud.jpg #{index + 1}",
                         "relationship": "componentOf",
                         "label": ingredient_labels[index]},
                        "image/jpeg", ingredient)
                    print(f"Cache state: hits={resolver.cache.hits} "
                          f"misses={resolver.cache.misses}")

            with tempfile.TemporaryDirectory() as output_dir:
                output_path = os.path.join(
                    output_dir, "A_signed_cached.jpg")
                with open(os.path.join(FIXTURES, "A.jpg"),
                          "rb") as source:
                    with open(output_path, "wb") as dest:
                        print(f"Signing asset A.jpg -> {output_path}")
                        builder.sign(
                            c2pa.Signer.from_info(signer_info),
                            "image/jpeg", source, dest)
                self.assertTrue(os.path.exists(output_path))
        finally:
            context.close()

        print(f"Final cache state: hits={resolver.cache.hits} "
              f"misses={resolver.cache.misses} "
              f"(expected 1 miss, 2 hits, across 3 identical ingredients)")
        self.assertEqual(resolver.cache.misses, 1)
        self.assertEqual(resolver.cache.hits, 2)

    def test_failing_resolver_is_reported_as_error(self):
        """A final failure surfaces as a typed error, not a crash.
        Needs no network: the resolver answers without calling out.
        """
        with c2pa.Context.builder().with_resolver(
                AlwaysFailResolver(500)).build() as context:
            with self.assertRaises(c2pa.C2paError) as ctx:
                with open(os.path.join(FIXTURES, "cloud.jpg"), "rb") as f:
                    c2pa.Reader("image/jpeg", f, context=context)
            self.assertIn("500", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
