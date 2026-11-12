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
import warnings
import tempfile
import shutil
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.backends import default_backend
from c2pa import Builder, C2paError as Error, Reader, C2paSigningAlg as SigningAlg, C2paSignerInfo, Signer
from c2pa.c2pa import create_signer, create_signer_from_info
from tests.unit._support import (
    FIXTURES_DIR,
    DEFAULT_TEST_FILE,
    INGREDIENT_TEST_FILE,
)


class TestLegacyAPI(unittest.TestCase):
    def setUp(self):
        # Filter specific deprecation warnings for legacy API tests
        warnings.filterwarnings("ignore", message="The create_signer function is deprecated")
        warnings.filterwarnings("ignore", message="The create_signer_from_info function is deprecated")
        warnings.filterwarnings("ignore", message="load_settings\\(\\) is deprecated")

        self.data_dir = FIXTURES_DIR
        self.testPath = DEFAULT_TEST_FILE
        self.testPath2 = INGREDIENT_TEST_FILE
        self.testPath3 = os.path.join(self.data_dir, "A_thumbnail.jpg")

        # Load test certificates and key
        with open(os.path.join(self.data_dir, "es256_certs.pem"), "rb") as cert_file:
            self.certs = cert_file.read()
        with open(os.path.join(self.data_dir, "es256_private.key"), "rb") as key_file:
            self.key = key_file.read()

        # Create a local ES256 signer with certs and a timestamp server
        self.signer_info = C2paSignerInfo(
            alg=b"es256",
            sign_cert=self.certs,
            private_key=self.key,
            ta_url=b"http://timestamp.digicert.com"
        )
        self.signer = Signer.from_info(self.signer_info)

        # Define a manifest as a dictionary
        self.manifestDefinition = {
            "claim_generator": "python_internals_test",
            "claim_generator_info": [{
                "name": "python_internals_test",
                "version": "0.0.1",
            }],
            "claim_version": 1,
            "format": "image/jpeg",
            "title": "Python Test Image",
            "ingredients": [],
            "assertions": [
                {
                    "label": "c2pa.actions",
                    "data": {
                        "actions": [
                            {
                                "action": "c2pa.opened"
                            }
                        ]
                    }
                }
            ]
        }

        # Create temp directory for tests
        self.temp_data_dir = os.path.join(self.data_dir, "temp_data")
        os.makedirs(self.temp_data_dir, exist_ok=True)

        # Define an example ES256 callback signer
        self.callback_signer_alg = "Es256"
        def callback_signer_es256(data: bytes) -> bytes:
            private_key = serialization.load_pem_private_key(
                self.key,
                password=None,
                backend=default_backend()
            )
            signature = private_key.sign(
                data,
                ec.ECDSA(hashes.SHA256())
            )
            return signature
        self.callback_signer_es256 = callback_signer_es256

    def tearDown(self):
        """Clean up temporary files after each test."""
        if os.path.exists(self.temp_data_dir):
            shutil.rmtree(self.temp_data_dir)

    def test_sign_file_callback_signer_reports_error(self):
        """Test signing a file using the sign_file method with a callback that reports an error."""

        temp_dir = tempfile.mkdtemp()

        try:
            output_path = os.path.join(temp_dir, "signed_output.jpg")

            # Use the sign_file method
            builder = Builder(self.manifestDefinition)

            # Define a callback that always returns None to simulate an error
            def error_callback_signer(data: bytes) -> bytes:
                # Could alternatively also raise an error
                # raise RuntimeError("Simulated signing error")
                return None

            # Create signer with error callback using create_signer function
            signer = create_signer(
                callback=error_callback_signer,
                alg=SigningAlg.ES256,
                certs=self.certs.decode('utf-8'),
                tsa_url="http://timestamp.digicert.com"
            )

            # The signing operation should fail due to the error callback
            with self.assertRaises(Error):
                builder.sign_file(
                    source_path=self.testPath,
                    dest_path=output_path,
                    signer=signer
                )

        finally:
            shutil.rmtree(temp_dir)

    def test_sign_file_callback_signer(self):
        """Test signing a file using the sign_file method."""

        temp_dir = tempfile.mkdtemp()

        try:
            output_path = os.path.join(temp_dir, "signed_output.jpg")

            # Use the sign_file method
            builder = Builder(self.manifestDefinition)

            # Create signer with callback using create_signer function
            signer = create_signer(
                callback=self.callback_signer_es256,
                alg=SigningAlg.ES256,
                certs=self.certs.decode('utf-8'),
                tsa_url="http://timestamp.digicert.com"
            )

            manifest_bytes = builder.sign_file(
                source_path=self.testPath,
                dest_path=output_path,
                signer=signer
            )

            # Verify the output file was created
            self.assertTrue(os.path.exists(output_path))

            # Verify results
            self.assertIsInstance(manifest_bytes, bytes)
            self.assertGreater(len(manifest_bytes), 0)

            # Read the signed file and verify the manifest
            with open(output_path, "rb") as file, Reader("image/jpeg", file) as reader:
                json_data = reader.json()
                # Needs trust configuration to be set up to validate as Trusted
                # self.assertNotIn("validation_status", json_data)

                # Parse the JSON and verify the signature algorithm
                manifest_data = json.loads(json_data)
                active_manifest_id = manifest_data["active_manifest"]
                active_manifest = manifest_data["manifests"][active_manifest_id]

                self.assertIn("signature_info", active_manifest)
                signature_info = active_manifest["signature_info"]
                self.assertEqual(signature_info["alg"], self.callback_signer_alg)

        finally:
            shutil.rmtree(temp_dir)

    def test_sign_file_callback_signer_managed_single(self):
        """Test signing a file using the sign_file method with context managers."""

        temp_dir = tempfile.mkdtemp()

        try:
            output_path = os.path.join(temp_dir, "signed_output_managed.jpg")

            # Create builder and signer with context managers
            with Builder(self.manifestDefinition) as builder, create_signer(
                callback=self.callback_signer_es256,
                alg=SigningAlg.ES256,
                certs=self.certs.decode('utf-8'),
                tsa_url="http://timestamp.digicert.com"
            ) as signer:

                manifest_bytes = builder.sign_file(
                    source_path=self.testPath,
                    dest_path=output_path,
                    signer=signer
                )

            # Verify results
            self.assertTrue(os.path.exists(output_path))
            self.assertIsInstance(manifest_bytes, bytes)
            self.assertGreater(len(manifest_bytes), 0)

            # Verify signed data can be read
            with open(output_path, "rb") as file:
                with Reader("image/jpeg", file) as reader:
                    json_data = reader.json()
                    self.assertIn("Python Test", json_data)
                    # Needs trust configuration to be set up to validate as Trusted
                    # self.assertNotIn("validation_status", json_data)

                    # Parse the JSON and verify the signature algorithm
                    manifest_data = json.loads(json_data)
                    active_manifest_id = manifest_data["active_manifest"]
                    active_manifest = manifest_data["manifests"][active_manifest_id]

                    # Verify the signature_info contains the correct algorithm
                    self.assertIn("signature_info", active_manifest)
                    signature_info = active_manifest["signature_info"]
                    self.assertEqual(signature_info["alg"], self.callback_signer_alg)

        finally:
            shutil.rmtree(temp_dir)

    def test_sign_file_callback_signer_managed_multiple_uses(self):
        """Test that a signer can be used multiple times with context managers."""

        temp_dir = tempfile.mkdtemp()

        try:
            # Create builder and signer with context managers
            with Builder(self.manifestDefinition) as builder, create_signer(
                callback=self.callback_signer_es256,
                alg=SigningAlg.ES256,
                certs=self.certs.decode('utf-8'),
                tsa_url="http://timestamp.digicert.com"
            ) as signer:

                # First signing operation
                output_path_1 = os.path.join(temp_dir, "signed_output_1.jpg")
                manifest_bytes_1 = builder.sign_file(
                    source_path=self.testPath,
                    dest_path=output_path_1,
                    signer=signer
                )

                # Verify first signing was successful
                self.assertTrue(os.path.exists(output_path_1))
                self.assertIsInstance(manifest_bytes_1, bytes)
                self.assertGreater(len(manifest_bytes_1), 0)

                # Second signing operation with a new builder but same signer
                # Builder is consumed by sign, so we need a fresh one.
                # This verifies we don't free the signer or the callback too early.
                builder2 = Builder(self.manifestDefinition)
                output_path_2 = os.path.join(temp_dir, "signed_output_2.jpg")
                manifest_bytes_2 = builder2.sign_file(
                    source_path=self.testPath,
                    dest_path=output_path_2,
                    signer=signer
                )

                # Verify second signing was successful
                self.assertTrue(os.path.exists(output_path_2))
                self.assertIsInstance(manifest_bytes_2, bytes)
                self.assertGreater(len(manifest_bytes_2), 0)

                # Verify both files contain valid C2PA data
                for output_path in [output_path_1, output_path_2]:
                    with open(output_path, "rb") as file, Reader("image/jpeg", file) as reader:
                        json_data = reader.json()
                        self.assertIn("Python Test", json_data)
                        # Needs trust configuration to be set up to validate as Trusted
                        # self.assertNotIn("validation_status", json_data)

                        # Parse the JSON and verify the signature algorithm
                        manifest_data = json.loads(json_data)
                        active_manifest_id = manifest_data["active_manifest"]
                        active_manifest = manifest_data["manifests"][active_manifest_id]

                        # Verify the signature_info contains the correct algorithm
                        self.assertIn("signature_info", active_manifest)
                        signature_info = active_manifest["signature_info"]
                        self.assertEqual(signature_info["alg"], self.callback_signer_alg)

        finally:
            shutil.rmtree(temp_dir)

    def test_create_signer_from_info(self):
        """Create a Signer using the create_signer_from_info function"""
        signer = create_signer_from_info(self.signer_info)
        self.assertIsNotNone(signer)
