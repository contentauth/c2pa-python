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
import io
import json
import unittest
import warnings
import tempfile
import shutil
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.backends import default_backend

warnings.simplefilter("ignore", category=DeprecationWarning)

from c2pa import Builder, C2paError as Error, Reader, C2paSigningAlg as SigningAlg, C2paSignerInfo, Signer
from c2pa.c2pa import read_ingredient_file, read_file, sign_file, load_settings, create_signer, create_signer_from_info

from test_common import FIXTURES_DIR, DEFAULT_TEST_FILE_NAME, INGREDIENT_TEST_FILE_NAME, DEFAULT_TEST_FILE, INGREDIENT_TEST_FILE

class TestLegacyAPI(unittest.TestCase):
    def setUp(self):
        # Filter specific deprecation warnings for legacy API tests
        warnings.filterwarnings("ignore", message="The read_file function is deprecated")
        warnings.filterwarnings("ignore", message="The sign_file function is deprecated")
        warnings.filterwarnings("ignore", message="The read_ingredient_file function is deprecated")
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

    def test_read_ingredient_file(self):
        """Test reading a C2PA ingredient from a file."""
        # Test reading ingredient from file with data_dir
        temp_data_dir = os.path.join(self.data_dir, "temp_data")
        os.makedirs(temp_data_dir, exist_ok=True)

        ingredient_json_with_dir = read_ingredient_file(self.testPath, temp_data_dir)

        # Verify some fields
        ingredient_data = json.loads(ingredient_json_with_dir)
        self.assertEqual(ingredient_data["title"], DEFAULT_TEST_FILE_NAME)
        self.assertEqual(ingredient_data["format"], "image/jpeg")
        self.assertIn("thumbnail", ingredient_data)

    def test_read_ingredient_file_who_has_no_manifest(self):
        """Test reading a C2PA ingredient from a file."""
        # Test reading ingredient from file with data_dir
        temp_data_dir = os.path.join(self.data_dir, "temp_data")
        os.makedirs(temp_data_dir, exist_ok=True)

        # Load settings first, before they need to be used
        load_settings('{"builder": { "thumbnail": {"enabled": false}}}')

        ingredient_json_with_dir = read_ingredient_file(self.testPath2, temp_data_dir)

        # Verify some fields
        ingredient_data = json.loads(ingredient_json_with_dir)
        self.assertEqual(ingredient_data["title"], INGREDIENT_TEST_FILE_NAME)
        self.assertEqual(ingredient_data["format"], "image/jpeg")
        self.assertNotIn("thumbnail", ingredient_data)

        # Reset setting
        load_settings('{"builder": { "thumbnail": {"enabled": true}}}')

    def test_compare_read_ingredient_file_with_builder_added_ingredient(self):
        """Test reading a C2PA ingredient from a file."""
        # Test reading ingredient from file with data_dir
        temp_data_dir = os.path.join(self.data_dir, "temp_data")
        os.makedirs(temp_data_dir, exist_ok=True)

        ingredient_json_with_dir = read_ingredient_file(self.testPath2, temp_data_dir)

        # Ingredient fields from read_ingredient_file
        ingredient_data = json.loads(ingredient_json_with_dir)

        # Compare with ingredient added by Builder
        builder = Builder.from_json(self.manifestDefinition)
        # Only the title is needed (filename), since title not extracted or guessed from filename
        ingredient_json = '{ "title" : "A.jpg" }'
        with open(self.testPath2, 'rb') as f:
            builder.add_ingredient(ingredient_json, "image/jpeg", f)

        with open(self.testPath2, "rb") as file:
            output = io.BytesIO(bytearray())
            builder.sign(self.signer, "image/jpeg", file, output)
            output.seek(0)

            # Get ingredient fields from signed manifest
            reader = Reader("image/jpeg", output)
            json_data = reader.json()
            manifest_data = json.loads(json_data)
            active_manifest_id = manifest_data["active_manifest"]
            active_manifest = manifest_data["manifests"][active_manifest_id]
            only_ingredient = active_manifest["ingredients"][0]

            self.assertEqual(ingredient_data["title"], only_ingredient["title"])
            self.assertEqual(ingredient_data["format"], only_ingredient["format"])
            self.assertEqual(ingredient_data["document_id"], only_ingredient["document_id"])
            self.assertEqual(ingredient_data["instance_id"], only_ingredient["instance_id"])
            self.assertEqual(ingredient_data["relationship"], only_ingredient["relationship"])

    def test_read_file(self):
        """Test reading a C2PA ingredient from a file."""
        temp_data_dir = os.path.join(self.data_dir, "temp_data")
        os.makedirs(temp_data_dir, exist_ok=True)

        # self.testPath has C2PA metadata to read
        file_json_with_dir = read_file(self.testPath, temp_data_dir)

        # Parse the JSON and verify specific fields
        file_data = json.loads(file_json_with_dir)
        expected_manifest_id = "contentauth:urn:uuid:c85a2b90-f1a0-4aa4-b17f-f938b475804e"

        # Verify some fields
        self.assertEqual(file_data["active_manifest"], expected_manifest_id)
        self.assertIn("manifests", file_data)
        self.assertIn(expected_manifest_id, file_data["manifests"])

    def test_sign_file(self):
        """Test signing a file with C2PA manifest."""
        # Set up test paths
        temp_data_dir = os.path.join(self.data_dir, "temp_data")
        os.makedirs(temp_data_dir, exist_ok=True)
        output_path = os.path.join(temp_data_dir, "signed_output.jpg")

        # Load test certificates and key
        with open(os.path.join(self.data_dir, "es256_certs.pem"), "rb") as cert_file:
            certs = cert_file.read()
        with open(os.path.join(self.data_dir, "es256_private.key"), "rb") as key_file:
            key = key_file.read()

        # Create signer info
        signer_info = C2paSignerInfo(
            alg=b"es256",
            sign_cert=certs,
            private_key=key,
            ta_url=b"http://timestamp.digicert.com"
        )

        # Create a simple manifest
        manifest = {
            "claim_generator": "python_internals_test",
            "claim_generator_info": [{
                "name": "python_internals_test",
                "version": "0.0.1",
            }],
            # Claim version has become mandatory for signing v1 claims
            "claim_version": 1,
            "format": "image/jpeg",
            "title": "Python Test Signed Image",
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

        # Convert manifest to JSON string
        manifest_json = json.dumps(manifest)

        try:
            sign_file(
                self.testPath,
                output_path,
                manifest_json,
                signer_info
            )

        finally:
            # Clean up
            if os.path.exists(output_path):
                os.remove(output_path)

    def test_sign_file_does_not_exist_errors(self):
        """Test signing a file with C2PA manifest."""
        # Set up test paths
        temp_data_dir = os.path.join(self.data_dir, "temp_data")
        os.makedirs(temp_data_dir, exist_ok=True)
        output_path = os.path.join(temp_data_dir, "signed_output.jpg")

        # Load test certificates and key
        with open(os.path.join(self.data_dir, "es256_certs.pem"), "rb") as cert_file:
            certs = cert_file.read()
        with open(os.path.join(self.data_dir, "es256_private.key"), "rb") as key_file:
            key = key_file.read()

        # Create signer info
        signer_info = C2paSignerInfo(
            alg=b"es256",
            sign_cert=certs,
            private_key=key,
            ta_url=b"http://timestamp.digicert.com"
        )

        # Create a simple manifest
        manifest = {
            "claim_generator": "python_internals_test",
            "claim_generator_info": [{
                "name": "python_internals_test",
                "version": "0.0.1",
            }],
            # Claim version has become mandatory for signing v1 claims
            "claim_version": 1,
            "format": "image/jpeg",
            "title": "Python Test Signed Image",
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

        # Convert manifest to JSON string
        manifest_json = json.dumps(manifest)

        try:
            with self.assertRaises(Error):
              sign_file(
                  "this-file-does-not-exist",
                  output_path,
                  manifest_json,
                  signer_info
              )

        finally:
            # Clean up
            if os.path.exists(output_path):
                os.remove(output_path)

    def test_builder_sign_with_ingredient_from_file(self):
        """Test Builder class operations with an ingredient added from file path."""

        builder = Builder.from_json(self.manifestDefinition)

        # Test adding ingredient from file path
        ingredient_json = '{"title": "Test Ingredient From File"}'
        # Suppress the specific deprecation warning for this test, as this is a legacy method
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            builder.add_ingredient_from_file_path(ingredient_json, "image/jpeg", self.testPath3)

        with open(self.testPath2, "rb") as file:
            output = io.BytesIO(bytearray())
            builder.sign(self.signer, "image/jpeg", file, output)
            output.seek(0)
            reader = Reader("image/jpeg", output)
            json_data = reader.json()
            manifest_data = json.loads(json_data)

            # Verify active manifest exists
            self.assertIn("active_manifest", manifest_data)
            active_manifest_id = manifest_data["active_manifest"]

            # Verify active manifest object exists
            self.assertIn("manifests", manifest_data)
            self.assertIn(active_manifest_id, manifest_data["manifests"])
            active_manifest = manifest_data["manifests"][active_manifest_id]

            # Verify ingredients array exists in active manifest
            self.assertIn("ingredients", active_manifest)
            self.assertIsInstance(active_manifest["ingredients"], list)
            self.assertTrue(len(active_manifest["ingredients"]) > 0)

            # Verify the first ingredient's title matches what we set
            first_ingredient = active_manifest["ingredients"][0]
            self.assertEqual(first_ingredient["title"], "Test Ingredient From File")

        builder.close()

    def test_builder_sign_with_ingredient_dict_from_file(self):
        """Test Builder class operations with an ingredient added from file path using a dictionary."""

        builder = Builder.from_json(self.manifestDefinition)

        # Test adding ingredient from file path with a dictionary
        ingredient_dict = {"title": "Test Ingredient From File"}
        # Suppress the specific deprecation warning for this test, as this is a legacy method
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            builder.add_ingredient_from_file_path(ingredient_dict, "image/jpeg", self.testPath3)

        with open(self.testPath2, "rb") as file:
            output = io.BytesIO(bytearray())
            builder.sign(self.signer, "image/jpeg", file, output)
            output.seek(0)
            reader = Reader("image/jpeg", output)
            json_data = reader.json()
            manifest_data = json.loads(json_data)

            # Verify active manifest exists
            self.assertIn("active_manifest", manifest_data)
            active_manifest_id = manifest_data["active_manifest"]

            # Verify active manifest object exists
            self.assertIn("manifests", manifest_data)
            self.assertIn(active_manifest_id, manifest_data["manifests"])
            active_manifest = manifest_data["manifests"][active_manifest_id]

            # Verify ingredients array exists in active manifest
            self.assertIn("ingredients", active_manifest)
            self.assertIsInstance(active_manifest["ingredients"], list)
            self.assertTrue(len(active_manifest["ingredients"]) > 0)

            # Verify the first ingredient's title matches what we set
            first_ingredient = active_manifest["ingredients"][0]
            self.assertEqual(first_ingredient["title"], "Test Ingredient From File")

        builder.close()

    def test_builder_add_ingredient_from_file_path(self):
        """Test Builder class add_ingredient_from_file_path method."""

        # Suppress the specific deprecation warning for this test, as this is a legacy method
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)

            builder = Builder.from_json(self.manifestDefinition)

            # Test adding ingredient from file path
            ingredient_json = '{"test": "ingredient_from_file_path"}'
            builder.add_ingredient_from_file_path(ingredient_json, "image/jpeg", self.testPath)

            builder.close()

    def test_builder_add_ingredient_from_file_path(self):
        """Test Builder class add_ingredient_from_file_path method."""

        # Suppress the specific deprecation warning for this test, as this is a legacy method
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)

            builder = Builder.from_json(self.manifestDefinition)

            # Test adding ingredient from file path
            ingredient_json = '{"test": "ingredient_from_file_path"}'

            with self.assertRaises(Error.FileNotFound):
                builder.add_ingredient_from_file_path(ingredient_json, "image/jpeg", "this-file-path-does-not-exist")

    def test_sign_file_using_callback_signer_overloads(self):
        """Test signing a file using the sign_file function with a Signer object."""
        # Create a temporary directory for the test
        temp_dir = tempfile.mkdtemp()

        try:
            # Create a temporary output file path
            output_path = os.path.join(temp_dir, "signed_output_callback.jpg")

            # Create signer with callback
            signer = Signer.from_callback(
                callback=self.callback_signer_es256,
                alg=SigningAlg.ES256,
                certs=self.certs.decode('utf-8'),
                tsa_url="http://timestamp.digicert.com"
            )

            # Overload that returns a JSON string
            result_json = sign_file(
                self.testPath,
                output_path,
                self.manifestDefinition,
                signer,
                False
            )

            # Verify the output file was created
            self.assertTrue(os.path.exists(output_path))

            # Verify the result is JSON
            self.assertIsInstance(result_json, str)
            self.assertGreater(len(result_json), 0)

            manifest_data = json.loads(result_json)
            self.assertIn("manifests", manifest_data)
            self.assertIn("active_manifest", manifest_data)

            output_path_bytes = os.path.join(temp_dir, "signed_output_callback_bytes.jpg")
            # Overload that returns bytes
            result_bytes = sign_file(
                self.testPath,
                output_path_bytes,
                self.manifestDefinition,
                signer,
                True
            )

            # Verify the output file was created
            self.assertTrue(os.path.exists(output_path_bytes))

            # Verify the result is bytes
            self.assertIsInstance(result_bytes, bytes)
            self.assertGreater(len(result_bytes), 0)

            # Read the signed file and verify the manifest contains expected content
            with open(output_path, "rb") as file:
                reader = Reader("image/jpeg", file)
                file_manifest_json = reader.json()
                self.assertIn("Python Test", file_manifest_json)

        finally:
            shutil.rmtree(temp_dir)

    def test_sign_file_overloads(self):
        """Test that the overloaded sign_file function works with both parameter types."""
        # Create a temporary directory for the test
        temp_dir = tempfile.mkdtemp()
        try:
            # Test with C2paSignerInfo
            output_path_1 = os.path.join(temp_dir, "signed_output_1.jpg")

            # Load test certificates and key
            with open(os.path.join(self.data_dir, "es256_certs.pem"), "rb") as cert_file:
                certs = cert_file.read()
            with open(os.path.join(self.data_dir, "es256_private.key"), "rb") as key_file:
                key = key_file.read()

            # Create signer info
            signer_info = C2paSignerInfo(
                alg=b"es256",
                sign_cert=certs,
                private_key=key,
                ta_url=b"http://timestamp.digicert.com"
            )

            # Test with C2paSignerInfo parameter - JSON return
            result_1 = sign_file(
                self.testPath,
                output_path_1,
                self.manifestDefinition,
                signer_info,
                False
            )

            self.assertIsInstance(result_1, str)
            self.assertTrue(os.path.exists(output_path_1))

            # Test with C2paSignerInfo parameter - bytes return
            output_path_1_bytes = os.path.join(temp_dir, "signed_output_1_bytes.jpg")
            result_1_bytes = sign_file(
                self.testPath,
                output_path_1_bytes,
                self.manifestDefinition,
                signer_info,
                True
            )

            self.assertIsInstance(result_1_bytes, bytes)
            self.assertTrue(os.path.exists(output_path_1_bytes))

            # Test with Signer object
            output_path_2 = os.path.join(temp_dir, "signed_output_2.jpg")

            # Create a signer from the signer info
            signer = Signer.from_info(signer_info)

            # Test with Signer parameter - JSON return
            result_2 = sign_file(
                self.testPath,
                output_path_2,
                self.manifestDefinition,
                signer,
                False
            )

            self.assertIsInstance(result_2, str)
            self.assertTrue(os.path.exists(output_path_2))

            # Test with Signer parameter - bytes return
            output_path_2_bytes = os.path.join(temp_dir, "signed_output_2_bytes.jpg")
            result_2_bytes = sign_file(
                self.testPath,
                output_path_2_bytes,
                self.manifestDefinition,
                signer,
                True
            )

            self.assertIsInstance(result_2_bytes, bytes)
            self.assertTrue(os.path.exists(output_path_2_bytes))

            # Both JSON results should be similar (same manifest structure)
            manifest_1 = json.loads(result_1)
            manifest_2 = json.loads(result_2)

            self.assertIn("manifests", manifest_1)
            self.assertIn("manifests", manifest_2)
            self.assertIn("active_manifest", manifest_1)
            self.assertIn("active_manifest", manifest_2)

            # Both bytes results should be non-empty
            self.assertGreater(len(result_1_bytes), 0)
            self.assertGreater(len(result_2_bytes), 0)

        finally:
            # Clean up the temporary directory
            shutil.rmtree(temp_dir)

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

                # Second signing operation with the same signer
                # This is to verify we don't free the signer or the callback too early
                output_path_2 = os.path.join(temp_dir, "signed_output_2.jpg")
                manifest_bytes_2 = builder.sign_file(
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



if __name__ == '__main__':
    unittest.main(warnings='ignore')
