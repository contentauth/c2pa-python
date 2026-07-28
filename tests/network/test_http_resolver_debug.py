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

"""Tests for DebugHttpResolver (tests/network/http_resolver.py), exercised
against the real network.

Demonstrates intercepting every HTTP request the SDK makes through a
Context. Needs internet access to fetch the remote manifest for
tests/fixtures/cloud.jpg; tests skip (not fail) when the resolver itself
observes a transport failure.
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from network_test_helpers import FIXTURES, skip_if_offline  # noqa: E402
from http_resolver import DebugHttpResolver  # noqa: E402

import c2pa  # noqa: E402


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
            skip_if_offline(self, resolver, e)

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
                skip_if_offline(self, resolver, e)
        finally:
            context.close()


if __name__ == "__main__":
    unittest.main()
