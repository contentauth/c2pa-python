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
import json
import unittest
import c2pa.c2pa as c2pa_module
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.backends import default_backend
from unittest.mock import patch
from c2pa import C2paSigningAlg as SigningAlg, C2paSignerInfo, Signer
from c2pa.c2pa import ManagedResource


TESTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_PATH = os.getcwd()
FIXTURES_DIR = os.path.join(TESTS_DIR, "fixtures")
DEFAULT_TEST_FILE_NAME = "C.jpg"
INGREDIENT_TEST_FILE_NAME = "A.jpg"
DEFAULT_TEST_FILE = os.path.join(FIXTURES_DIR, DEFAULT_TEST_FILE_NAME)
INGREDIENT_TEST_FILE = os.path.join(FIXTURES_DIR, INGREDIENT_TEST_FILE_NAME)
ALTERNATIVE_INGREDIENT_TEST_FILE = os.path.join(FIXTURES_DIR, "cloud.jpg")


def _patch_free(test, fn):
    """Route ManagedResource._free_native_ptr to `fn` until `test` ends."""
    patcher = patch.object(
        ManagedResource, '_free_native_ptr', staticmethod(fn))
    patcher.start()
    test.addCleanup(patcher.stop)


def _fail_with_native_error(tag_bytes):
    """Build a mock FFI callable that sets a native error and returns None.
    """
    def _mock(*args):
        c2pa_module._lib.c2pa_error_set_last(tag_bytes)
        return None
    return _mock


def load_test_settings_json():
    """
    Load default (legacy) trust configuration test settings from a
    JSON config file and return its content as JSON-compatible dict.
    The return value is used to load settings (thread_local) in tests.

    Returns:
        dict: The parsed JSON content as a Python dictionary (JSON-compatible).

    Raises:
        FileNotFoundError: If trust_config_test_settings.json is not found.
        json.JSONDecodeError: If the JSON file is malformed.
    """
    # Locate the file which contains default settings for tests
    settings_path = os.path.join(TESTS_DIR, 'trust_config_test_settings.json')

    # Load the located default test settings
    with open(settings_path, 'r') as f:
        settings_data = json.load(f)

    return settings_data


def parse_native_version():
    """
    Parse the expected native SDK version.

    Reads c2pa-rs-preflight-ref.txt instead of c2pa-native-version.txt when
    C2PA_PREFLIGHT_RUN is set: that flag is set only by
    test-c2pa-rs-source-build.yml's own "Run tests" step, because the
    presence of c2pa-rs-preflight-ref.txt in the checked-out tree isn't by
    itself proof of anything -- an ordinary build.yml run on a branch that
    happens to carry that file (e.g. this PR) still downloads and installs
    the real pinned release, not the preflight ref.

    Returns:
        str: The semantic version string (e.g. "0.85.2").
    """
    repo_root = os.path.dirname(TESTS_DIR)
    if os.environ.get('C2PA_PREFLIGHT_RUN'):
        path = os.path.join(repo_root, 'c2pa-rs-preflight-ref.txt')
    else:
        path = os.path.join(repo_root, 'c2pa-native-version.txt')
    with open(path, 'r') as f:
        raw = f.read().strip()
    # Strip the "c2pa-v" / "c2pa-rc-v" prefix to get the bare semantic version.
    return raw.split('v', 1)[1] if 'v' in raw else raw


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
                        "digitalSourceType": "http://c2pa.org/digitalsourcetype/empty",
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
