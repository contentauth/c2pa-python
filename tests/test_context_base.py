# Copyright 2023 Adobe. All rights reserved.
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

import os
import unittest

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.backends import default_backend

from c2pa import C2paSigningAlg as SigningAlg, C2paSignerInfo, Signer

from test_common import FIXTURES_DIR


class TestContextAPIs(unittest.TestCase):
    """Base for context-related tests; provides test_manifest and signer helpers."""

    test_manifest = {
        "claim_generator": "c2pa_python_sdk_test/context",
        "claim_generator_info": [{
            "name": "c2pa_python_sdk_contextual_test",
            "version": "0.1.0",
        }],
        "format": "image/jpeg",
        "title": "Test Image",
        "ingredients": [],
        "assertions": [
            {
                "label": "c2pa.actions",
                "data": {
                    "actions": [{
                        "action": "c2pa.created",
                    }]
                }
            }
        ]
    }

    def _ctx_make_signer(self):
        """Create a Signer for context tests."""
        certs_path = os.path.join(
            FIXTURES_DIR, "es256_certs.pem"
        )
        key_path = os.path.join(
            FIXTURES_DIR, "es256_private.key"
        )
        with open(certs_path, "rb") as f:
            certs = f.read()
        with open(key_path, "rb") as f:
            key = f.read()
        info = C2paSignerInfo(
            alg=b"es256",
            sign_cert=certs,
            private_key=key,
            ta_url=b"http://timestamp.digicert.com",
        )
        return Signer.from_info(info)

    def _ctx_make_callback_signer(self):
        """Create a callback-based Signer for context tests."""
        certs_path = os.path.join(
            FIXTURES_DIR, "es256_certs.pem"
        )
        key_path = os.path.join(
            FIXTURES_DIR, "es256_private.key"
        )
        with open(certs_path, "rb") as f:
            certs = f.read()
        with open(key_path, "rb") as f:
            key_data = f.read()

        from cryptography.hazmat.primitives import (
            serialization,
        )
        private_key = serialization.load_pem_private_key(
            key_data, password=None,
            backend=default_backend(),
        )

        def sign_cb(data: bytes) -> bytes:
            from cryptography.hazmat.primitives.asymmetric import (  # noqa: E501
                utils as asym_utils,
            )
            sig = private_key.sign(
                data, ec.ECDSA(hashes.SHA256()),
            )
            r, s = asym_utils.decode_dss_signature(sig)
            return (
                r.to_bytes(32, byteorder='big')
                + s.to_bytes(32, byteorder='big')
            )

        return Signer.from_callback(
            sign_cb,
            SigningAlg.ES256,
            certs.decode('utf-8'),
            "http://timestamp.digicert.com",
        )

    def _ctx_make_ed25519_signer(self):
        """Create an ED25519 Signer for context tests."""
        with open(
            os.path.join(FIXTURES_DIR, "ed25519.pub"), "rb"
        ) as f:
            certs = f.read()
        with open(
            os.path.join(FIXTURES_DIR, "ed25519.pem"), "rb"
        ) as f:
            key = f.read()
        info = C2paSignerInfo(
            alg=b"ed25519",
            sign_cert=certs,
            private_key=key,
            ta_url=b"http://timestamp.digicert.com",
        )
        return Signer.from_info(info)

    def _ctx_make_ps256_signer(self):
        """Create a PS256 Signer for context tests."""
        with open(
            os.path.join(FIXTURES_DIR, "ps256.pub"), "rb"
        ) as f:
            certs = f.read()
        with open(
            os.path.join(FIXTURES_DIR, "ps256.pem"), "rb"
        ) as f:
            key = f.read()
        info = C2paSignerInfo(
            alg=b"ps256",
            sign_cert=certs,
            private_key=key,
            ta_url=b"http://timestamp.digicert.com",
        )
        return Signer.from_info(info)
