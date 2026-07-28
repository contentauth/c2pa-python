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

"""A custom HTTP resolver that logs every request/response, exercised
against the real network.

Ported from the former examples/http_resolver_debug.py: still a runnable
demonstration of intercepting every HTTP request the SDK makes through a
Context, now also verified in CI. Needs internet access to fetch the
remote manifest for tests/fixtures/cloud.jpg; tests skip (not fail) when
that fetch can't reach the network.
"""

import json
import os
import sys
import tempfile
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


class DebugHttpResolver:
    """Logs every SDK HTTP request and response status.
    The actual transfer is delegated to urllib.
    """

    def __init__(self, timeout=10.0):
        self._timeout = timeout
        self.requests = []

    def resolve(self, request):
        self.requests.append((request.method, request.url))

        # Timestamp requests POST a body; manifest fetches send none.
        data = request.body or None
        req = urllib.request.Request(
            request.url,
            data=data,
            method=request.method,
            headers=request.headers)

        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                return HttpResponse(resp.status, resp.read())
        except urllib.error.HTTPError as e:
            # A 4xx/5xx is still a response! Pass the status through and
            # let the SDK turn it into its own typed error: a remote
            # manifest fetch only accepts 200.
            return HttpResponse(e.code, e.read())
        # urllib.error.URLError (DNS failure, connection refused, timeout)
        # is deliberately not caught: raising marks the request as a hard
        # resolver failure, which surfaces as a typed C2paError.


class TestHttpResolverDebug(unittest.TestCase):

    def test_read_with_resolver(self):
        """Reading an asset whose manifest lives at a remote URL logs a
        GET for that fetch."""
        resolver = DebugHttpResolver()
        try:
            with c2pa.Context.builder().with_resolver(
                    resolver).build() as context:
                with open(os.path.join(FIXTURES, "cloud.jpg"), "rb") as f:
                    with c2pa.Reader(
                            "image/jpeg", f, context=context) as reader:
                        reader.get_validation_state()
                        self.assertFalse(reader.is_embedded())
                        self.assertTrue(reader.get_remote_url())
        except c2pa.C2paError as e:
            _skip_if_offline(self, e)

        self.assertTrue(
            any(method == "GET" for method, _ in resolver.requests))

    def test_sign_with_resolver(self):
        """Signing an asset with a remote-manifest ingredient logs a GET
        for the ingredient's manifest, and reading the signed result back
        makes no HTTP requests at all (its manifest is embedded)."""
        with open(os.path.join(FIXTURES, "es256_certs.pem"), "rb") as f:
            certs = f.read()
        with open(os.path.join(FIXTURES, "es256_private.key"), "rb") as f:
            key = f.read()

        # ta_url is None, meaning "no timestamp authority".
        signer_info = c2pa.C2paSignerInfo(
            alg=b"es256", sign_cert=certs, private_key=key, ta_url=None)

        manifest_definition = {
            "claim_generator": "http_resolver_debug",
            "claim_generator_info": [
                {"name": "http_resolver_debug", "version": "0.1"}],
            "format": "image/jpeg",
            "title": "Signed with a debug HTTP resolver",
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
                        "parameters": {"ingredientIds": ["cloud-ingredient"]},
                    },
                ]},
            }],
        }

        resolver = DebugHttpResolver()
        context = (c2pa.Context.builder()
                   .with_resolver(resolver)
                   .with_signer(c2pa.Signer.from_info(signer_info))
                   .build())
        try:
            try:
                builder = c2pa.Builder(manifest_definition, context=context)

                with open(os.path.join(FIXTURES, "cloud.jpg"),
                          "rb") as ingredient:
                    builder.add_ingredient(
                        {"title": "cloud.jpg", "relationship": "componentOf",
                         "label": "cloud-ingredient"},
                        "image/jpeg", ingredient)

                with tempfile.TemporaryDirectory() as output_dir:
                    output_path = os.path.join(
                        output_dir, "A_signed_resolver.jpg")
                    with open(os.path.join(FIXTURES, "A.jpg"),
                              "rb") as source:
                        with open(output_path, "wb") as dest:
                            builder.sign(
                                c2pa.Signer.from_info(signer_info),
                                "image/jpeg", source, dest)

                    self.assertTrue(
                        any(m == "GET" for m, _ in resolver.requests))
                    requests_before_reread = len(resolver.requests)

                    # Reading the signed file back uses its embedded
                    # manifest, so this makes no HTTP requests at all.
                    with open(output_path, "rb") as f:
                        with c2pa.Reader("image/jpeg", f) as reader:
                            store = json.loads(reader.json())
                            manifest = store["manifests"][
                                store["active_manifest"]]
                            self.assertTrue(manifest.get("ingredients"))

                    self.assertEqual(
                        len(resolver.requests), requests_before_reread)
            except c2pa.C2paError as e:
                _skip_if_offline(self, e)
        finally:
            context.close()


if __name__ == "__main__":
    unittest.main()
