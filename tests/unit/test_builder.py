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
import tempfile
import shutil
import threading
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.backends import default_backend
from c2pa import Builder, C2paError as Error, Reader, C2paSigningAlg as SigningAlg, C2paSignerInfo, Signer, C2paBuilderIntent, C2paDigitalSourceType, Context
from c2pa.c2pa import LifecycleState, load_settings, ed25519_sign, format_embeddable, _encode_format
from tests.unit._support import (
    FIXTURES_DIR,
    DEFAULT_TEST_FILE,
    INGREDIENT_TEST_FILE,
    ALTERNATIVE_INGREDIENT_TEST_FILE,
    load_test_settings_json,
)


class TestBuilderWithSigner(unittest.TestCase):
    def setUp(self):
        # Use the fixtures_dir fixture to set up paths
        self.data_dir = FIXTURES_DIR
        self.testPath = DEFAULT_TEST_FILE
        self.testPath2 = INGREDIENT_TEST_FILE
        with open(os.path.join(self.data_dir, "es256_certs.pem"), "rb") as cert_file:
            self.certs = cert_file.read()
        with open(os.path.join(self.data_dir, "es256_private.key"), "rb") as key_file:
            self.key = key_file.read()

        # Create a local Es256 signer with certs and a timestamp server
        self.signer_info = C2paSignerInfo(
            alg=b"es256",
            sign_cert=self.certs,
            private_key=self.key,
            ta_url=b"http://timestamp.digicert.com"
        )
        self.signer = Signer.from_info(self.signer_info)

        self.testPath3 = os.path.join(self.data_dir, "A_thumbnail.jpg")
        self.testPath4 = ALTERNATIVE_INGREDIENT_TEST_FILE

        # Define a manifest as a dictionary
        self.manifestDefinition = {
            "claim_generator": "python_test",
            "claim_generator_info": [{
                "name": "python_test",
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
                                "action": "c2pa.created",
                                "digitalSourceType": "http://cv.iptc.org/newscodes/digitalsourcetype/digitalCreation"
                            }
                        ]
                    }
                }
            ]
        }

        # Define a V2 manifest as a dictionary
        self.manifestDefinitionV2 = {
            "claim_generator_info": [{
                "name": "python_test",
                "version": "0.0.1",
            }],
            # claim version 2 is the default
            # "claim_version": 2,
            "format": "image/jpeg",
            "title": "Python Test Image V2",
            "ingredients": [],
            "assertions": [
                {
                    "label": "c2pa.actions",
                    "data": {
                        "actions": [
                            {
                                "action": "c2pa.created",
                                "digitalSourceType": "http://cv.iptc.org/newscodes/digitalsourcetype/digitalCreation"
                            }
                        ]
                    }
                }
            ]
        }

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

    def _create_ingredient_archive(self, ingredient_json=None):
        """Helper: create an ingredient archive from a single ingredient."""
        if ingredient_json is None:
            ingredient_json = {"title": "photo.jpg", "relationship": "componentOf"}
        manifest = {
            "claim_generator_info": [{"name": "c2pa-test", "version": "1.0"}],
            "assertions": [
                {
                    "label": "c2pa.actions",
                    "data": {
                        "actions": [
                            {
                                "action": "c2pa.created",
                                "digitalSourceType": "http://cv.iptc.org/newscodes/digitalsourcetype/digitalCreation",
                            }
                        ]
                    },
                }
            ],
        }
        builder = Builder.from_json(manifest)
        with open(self.testPath, "rb") as f:
            builder.add_ingredient(ingredient_json, "image/jpeg", f)
        archive = io.BytesIO()
        builder.to_archive(archive)
        builder.close()
        archive.seek(0)
        return archive

    def test_can_retrieve_builder_supported_mimetypes(self):
        result1 = Builder.get_supported_mime_types()
        self.assertTrue(len(result1) > 0)

        # Cache-hit
        result2 = Builder.get_supported_mime_types()
        self.assertTrue(len(result2) > 0)

        self.assertEqual(result1, result2)

    def test_reserve_size(self):
        signer_info = C2paSignerInfo(
            alg=b"es256",
            sign_cert=self.certs,
            private_key=self.key,
            ta_url=b"http://timestamp.digicert.com"
        )
        signer = Signer.from_info(signer_info)
        signer.reserve_size()

    def _local_signer(self):
        """An es256 signer with no timestamp authority (keeps signing local).

        ta_url=None maps to a NULL pointer, which is how the native side
        spells "no TSA". An empty string is not equivalent: it is passed
        through as a real, empty URL and signing then fails.
        """
        signer_info = C2paSignerInfo(
            alg=b"es256",
            sign_cert=self.certs,
            private_key=self.key,
            ta_url=None,
        )
        signer = Signer.from_info(signer_info)
        self.addCleanup(signer.close)
        return signer

    def _active_signature_info(self, signed_bytes):
        """signature_info of the active manifest in a signed asset."""
        signed_bytes.seek(0)
        reader = Reader("image/jpeg", signed_bytes)
        try:
            manifest_store = json.loads(reader.json())
        finally:
            reader.close()
        active = manifest_store["manifests"][
            manifest_store["active_manifest"]]
        return active.get("signature_info", {})

    def test_signer_with_none_ta_url_signs_without_timestamp(self):
        """ta_url=None must reach native as NULL, meaning "no TSA".
        """
        builder = Builder(self.manifestDefinitionV2)
        dest = io.BytesIO()
        with open(self.testPath, "rb") as source:
            builder.sign(self._local_signer(), "image/jpeg", source, dest)

        signature_info = self._active_signature_info(dest)
        self.assertTrue(signature_info, "expected a signed active manifest")
        self.assertNotIn(
            "time", signature_info,
            "no timestamp authority was configured, so the signature "
            "must not carry a timestamp")

    def _sign_with_ta_url(self, ta_url):
        """Sign with ta_url as the only variable. Returns the dest buffer."""
        signer_info = C2paSignerInfo(
            alg=b"es256",
            sign_cert=self.certs,
            private_key=self.key,
            ta_url=ta_url,
        )
        signer = Signer.from_info(signer_info)
        self.addCleanup(signer.close)

        builder = Builder(self.manifestDefinitionV2)
        dest = io.BytesIO()
        with open(self.testPath, "rb") as source:
            builder.sign(signer, "image/jpeg", source, dest)
        return dest

    def test_signer_with_empty_ta_url_is_not_a_no_tsa_path(self):
        """An empty ta_url is a real (empty) URL, not "no TSA".
        Only None means "no TSA".
        """
        with self.assertRaises(Error):
            self._sign_with_ta_url(b"")

    def test_empty_ta_url_is_rejected_as_a_malformed_url(self):
        """b"" fails as a URL, which is why it cannot mean "no TSA".
        """
        malformed = [
            (b"", "empty"),
            (b"   ", "whitespace"),
            (b"not-a-url", "no scheme or host"),
        ]
        for value, why in malformed:
            with self.subTest(ta_url=value, reason=why):
                with self.assertRaises(Error):
                    self._sign_with_ta_url(value)

        # The control: same signer, same asset, only ta_url differs.
        signature_info = self._active_signature_info(
            self._sign_with_ta_url(None))
        self.assertNotIn("time", signature_info)

    def test_signer_with_ta_url_signs_with_timestamp(self):
        """Control for the None case: a real TSA does add a timestamp.
        """
        builder = Builder(self.manifestDefinitionV2)
        dest = io.BytesIO()
        with open(self.testPath, "rb") as source:
            builder.sign(self.signer, "image/jpeg", source, dest)

        signature_info = self._active_signature_info(dest)
        self.assertIn(
            "time", signature_info,
            "a timestamp authority was configured, so the signature "
            "must carry a timestamp")
        self.assertTrue(signature_info["time"])

    def test_none_and_empty_ta_url_reach_native_differently(self):
        """None must marshal to NULL, b"" to a real (empty) string.

        The native side reads a NULL ta_url as "no timestamp authority"
        and any non-NULL pointer as a URL to use, including one pointing at "".
        """
        def struct_for(ta_url):
            return C2paSignerInfo(
                alg=b"es256",
                sign_cert=self.certs,
                private_key=self.key,
                ta_url=ta_url,
            )

        # ctypes surfaces a NULL c_char_p as None and an empty one as b"".
        self.assertIsNone(struct_for(None).ta_url)
        self.assertEqual(struct_for(b"").ta_url, b"")
        # A str is encoded rather than passed through untouched.
        self.assertEqual(
            struct_for("http://timestamp.digicert.com").ta_url,
            b"http://timestamp.digicert.com")

    def test_signer_rejects_non_string_ta_url(self):
        """Only None, str and bytes are accepted."""
        with self.assertRaises(TypeError):
            C2paSignerInfo(
                alg=b"es256",
                sign_cert=self.certs,
                private_key=self.key,
                ta_url=1234,
            )

    def test_signer_creation_error_alg(self):
        signer_info = C2paSignerInfo(
            alg=b"not-an-alg",
            sign_cert=self.certs,
            private_key=self.key,
            ta_url=b"http://timestamp.digicert.com"
        )
        with self.assertRaises(Error):
          Signer.from_info(signer_info)

    def test_signer_from_callback_error_no_cert(self):
        with self.assertRaises(Error):
            Signer.from_callback(
                callback=self.callback_signer_es256,
                alg=SigningAlg.ES256,
                certs=None,
                tsa_url="http://timestamp.digicert.com"
            )

    def test_signer_from_callback_error_wrong_url(self):
        with self.assertRaises(Error):
            Signer.from_callback(
                callback=self.callback_signer_es256,
                alg=SigningAlg.ES256,
                certs=None,
                tsa_url="ftp://timestamp.digicert.com"
            )

    def test_reserve_size_on_closed_signer(self):
        signer_info = C2paSignerInfo(
            alg=b"es256",
            sign_cert=self.certs,
            private_key=self.key,
            ta_url=b"http://timestamp.digicert.com"
        )
        signer = Signer.from_info(signer_info)
        signer.close()
        # Verify signer is closed by testing that operations fail
        with self.assertRaises(Error):
            signer.reserve_size()

    def test_signer_double_close(self):
        signer_info = C2paSignerInfo(
            alg=b"es256",
            sign_cert=self.certs,
            private_key=self.key,
            ta_url=b"http://timestamp.digicert.com"
        )
        signer = Signer.from_info(signer_info)
        signer.close()
        # Second close should not raise an exception
        signer.close()

    def test_builder_detects_malformed_json(self):
        with self.assertRaises(Error):
            Builder("{this is not json}")

    def test_builder_does_not_allow_sign_after_close(self):
        with open(self.testPath, "rb") as file:
            builder = Builder(self.manifestDefinition)
            output = io.BytesIO(bytearray())
            builder.close()
            with self.assertRaises(Error):
              builder.sign(self.signer, "image/jpeg", file, output)

    def test_sign_rejects_none_format(self):
        # sign requires an explicit format; None must raise NotSupported.
        with open(self.testPath, "rb") as file:
            builder = Builder(self.manifestDefinition)
            output = io.BytesIO(bytearray())
            with self.assertRaises(Error.NotSupported):
                builder.sign(self.signer, None, file, output)

    def test_sign_accepts_padded_format(self):
        with open(self.testPath, "rb") as file:
            builder = Builder(self.manifestDefinition)
            output = io.BytesIO(bytearray())
            manifest_bytes = builder.sign(
                self.signer, " image/jpeg ", file, output)
            self.assertTrue(len(manifest_bytes) > 0)

    def test_builder_does_not_allow_archiving_after_close(self):
        with open(self.testPath, "rb") as file:
            builder = Builder(self.manifestDefinition)
            placeholder_stream = io.BytesIO(bytearray())
            builder.close()
            with self.assertRaises(Error):
              builder.to_archive(placeholder_stream)

    def test_builder_does_not_allow_changing_remote_url_after_close(self):
        with open(self.testPath, "rb") as file:
            builder = Builder(self.manifestDefinition)
            builder.close()
            with self.assertRaises(Error):
              builder.set_remote_url("a-remote-url-that-is-not-important-in-this-tests")

    def test_builder_does_not_allow_adding_resource_after_close(self):
        builder = Builder(self.manifestDefinition)
        placeholder_stream = io.BytesIO(bytearray())
        builder.close()
        with self.assertRaises(Error):
            builder.add_resource("a-remote-url-that-is-not-important-in-this-tests", placeholder_stream)

    def test_builder_add_thumbnail_resource(self):
        builder = Builder(self.manifestDefinition)
        with open(self.testPath2, "rb") as thumbnail_file:
            builder.add_resource("thumbnail", thumbnail_file)
        builder.close()

    def test_builder_double_close(self):
        builder = Builder(self.manifestDefinition)
        # First close
        builder.close()
        # Second close should not raise an exception
        builder.close()
        # Verify builder is closed
        with self.assertRaises(Error):
            builder.set_no_embed()

    def test_streams_sign_recover_bytes_only(self):
        with open(self.testPath, "rb") as file:
            builder = Builder(self.manifestDefinition)
            manifest_bytes = builder.sign(self.signer, "image/jpeg", file)
            self.assertIsNotNone(manifest_bytes)

    def test_streams_sign_with_thumbnail_resource(self):
        with open(self.testPath2, "rb") as file:
            builder = Builder(self.manifestDefinitionV2)
            output = io.BytesIO(bytearray())

            with open(self.testPath2, "rb") as thumbnail_file:
                builder.add_resource("thumbnail", thumbnail_file)

            builder.sign(self.signer, "image/jpeg", file, output)
            output.seek(0)
            reader = Reader("image/jpeg", output)
            json_data = reader.json()
            self.assertIn("Python Test", json_data)
            output.close()

    def test_streams_sign_with_es256_alg_v1_manifest(self):
        with open(self.testPath, "rb") as file:
            builder = Builder(self.manifestDefinition)
            output = io.BytesIO(bytearray())
            builder.sign(self.signer, "image/jpeg", file, output)
            output.seek(0)
            reader = Reader("image/jpeg", output)
            json_data = reader.json()
            self.assertIn("Python Test", json_data)
            self.assertIn("Valid", json_data)

            # Write buffer to file
            # output.seek(0)
            # with open('/target_path', 'wb') as f:
            #     f.write(output.getbuffer())

            output.close()

    def test_streams_sign_with_es256_alg_v1_manifest_to_existing_empty_file(self):
        test_file_name = os.path.join(self.data_dir, "temp_data", "temp_signing.jpg")
        # Ensure tmp directory exists
        os.makedirs(os.path.dirname(test_file_name), exist_ok=True)

        # Ensure the target file exists before opening it in rb+ mode
        with open(test_file_name, "wb") as f:
            pass  # Create empty file

        try:
            with open(self.testPath, "rb") as source, open(test_file_name, "w+b") as target:
                builder = Builder(self.manifestDefinition)
                builder.sign(self.signer, "image/jpeg", source, target)
                reader = Reader("image/jpeg", target)
                json_data = reader.json()
                self.assertIn("Python Test", json_data)
                self.assertIn("Valid", json_data)

        finally:
            # Clean up...

            if os.path.exists(test_file_name):
                os.remove(test_file_name)

            # Also clean up the temp directory if it's empty
            temp_dir = os.path.dirname(test_file_name)
            if os.path.exists(temp_dir) and not os.listdir(temp_dir):
                os.rmdir(temp_dir)

    def test_streams_sign_with_es256_alg_v1_manifest_to_new_dest_file(self):
        test_file_name = os.path.join(self.data_dir, "temp_data", "temp_signing.jpg")
        # Ensure tmp directory exists
        os.makedirs(os.path.dirname(test_file_name), exist_ok=True)

        # A new target/destination file should be created during the test run
        try:
            with open(self.testPath, "rb") as source, open(test_file_name, "w+b") as target:
                builder = Builder(self.manifestDefinition)
                builder.sign(self.signer, "image/jpeg", source, target)
                reader = Reader("image/jpeg", target)
                json_data = reader.json()
                self.assertIn("Python Test", json_data)
                self.assertIn("Valid", json_data)

        finally:
            # Clean up...

            if os.path.exists(test_file_name):
                os.remove(test_file_name)

            # Also clean up the temp directory if it's empty
            temp_dir = os.path.dirname(test_file_name)
            if os.path.exists(temp_dir) and not os.listdir(temp_dir):
                os.rmdir(temp_dir)

    def test_streams_sign_with_es256_alg(self):
        with open(self.testPath, "rb") as file:
            builder = Builder(self.manifestDefinition)
            output = io.BytesIO(bytearray())
            builder.sign(self.signer, "image/jpeg", file, output)
            output.seek(0)
            reader = Reader("image/jpeg", output)
            json_data = reader.json()
            self.assertIn("Python Test", json_data)
            # Needs trust configuration to be set up to validate as Trusted,
            # or validation_status on read reports `signing certificate untrusted`.
            self.assertIn("Valid", json_data)
            output.close()

    def test_streams_sign_with_es256_alg_2(self):
        with open(self.testPath2, "rb") as file:
            builder = Builder(self.manifestDefinitionV2)
            output = io.BytesIO(bytearray())
            builder.sign(self.signer, "image/jpeg", file, output)
            output.seek(0)
            reader = Reader("image/jpeg", output)
            json_data = reader.json()
            self.assertIn("Python Test", json_data)
            self.assertIn("Valid", json_data)
            output.close()

    def test_streams_sign_with_es256_alg_create_intent(self):
        """Test signing with CREATE intent and empty manifest."""

        with open(self.testPath2, "rb") as file:
            # Start with an empty manifest
            builder = Builder({})
            # Set the intent for creating new content
            builder.set_intent(
                C2paBuilderIntent.CREATE,
                C2paDigitalSourceType.DIGITAL_CREATION
            )
            output = io.BytesIO(bytearray())
            builder.sign(self.signer, "image/jpeg", file, output)
            output.seek(0)
            reader = Reader("image/jpeg", output)
            json_str = reader.json()
            # Verify the manifest was created
            self.assertIsNotNone(json_str)

            # Parse the JSON to verify the structure
            manifest_data = json.loads(json_str)
            active_manifest_label = manifest_data["active_manifest"]
            active_manifest = manifest_data["manifests"][active_manifest_label]

            # Check that assertions exist
            self.assertIn("assertions", active_manifest)
            assertions = active_manifest["assertions"]

            # Find the actions assertion
            actions_assertion = None
            for assertion in assertions:
                if assertion["label"] in ["c2pa.actions", "c2pa.actions.v2"]:
                    actions_assertion = assertion
                    break

            self.assertIsNotNone(actions_assertion)

            # Verify c2pa.created action exists and there is only one
            actions = actions_assertion["data"]["actions"]
            created_actions = [
                action for action in actions
                if action["action"] == "c2pa.created"
            ]

            self.assertEqual(len(created_actions), 1)

            # Needs trust configuration to be set up to validate as Trusted,
            # or validation_status on read reports `signing certificate untrusted`.
            self.assertEqual(manifest_data["validation_state"], "Valid")
            output.close()

    def test_streams_sign_with_es256_alg_create_intent_2(self):
        """Test signing with CREATE intent and manifestDefinitionV2."""

        with open(self.testPath2, "rb") as file:
            # Start with manifestDefinitionV2 which has predefined metadata
            builder = Builder(self.manifestDefinitionV2)
            # Set the intent for creating new content
            # If we provided a full manifest, the digital source type from the full manifest "wins"
            builder.set_intent(
                C2paBuilderIntent.CREATE,
                C2paDigitalSourceType.SCREEN_CAPTURE
            )
            output = io.BytesIO(bytearray())
            builder.sign(self.signer, "image/jpeg", file, output)
            output.seek(0)
            reader = Reader("image/jpeg", output)
            json_str = reader.json()

            # Verify the manifest was created
            self.assertIsNotNone(json_str)

            # Parse the JSON to verify the structure
            manifest_data = json.loads(json_str)
            active_manifest_label = manifest_data["active_manifest"]
            active_manifest = manifest_data["manifests"][active_manifest_label]

            # Verify title from manifestDefinitionV2 is preserved
            self.assertIn("title", active_manifest)
            self.assertEqual(active_manifest["title"], "Python Test Image V2")

            # Verify claim_generator_info is present
            self.assertIn("claim_generator_info", active_manifest)
            claim_generator_info = active_manifest["claim_generator_info"]
            self.assertIsInstance(claim_generator_info, list)
            self.assertGreater(len(claim_generator_info), 0)

            # Check for the custom claim generator info from manifestDefinitionV2
            has_python_test = any(
                gen.get("name") == "python_test" and gen.get("version") == "0.0.1"
                for gen in claim_generator_info
            )
            self.assertTrue(has_python_test, "Should have python_test claim generator")

            # Verify no ingredients for CREATE intent
            ingredients_manifest = active_manifest.get("ingredients", [])
            self.assertEqual(len(ingredients_manifest), 0, "CREATE intent should have no ingredients")

            # Check that assertions exist
            self.assertIn("assertions", active_manifest)
            assertions = active_manifest["assertions"]

            # Find the actions assertion
            actions_assertion = None
            for assertion in assertions:
                if assertion["label"] in ["c2pa.actions", "c2pa.actions.v2"]:
                    actions_assertion = assertion
                    break

            self.assertIsNotNone(actions_assertion)

            # Verify c2pa.created action exists and there is only one
            actions = actions_assertion["data"]["actions"]
            created_actions = [
                action for action in actions
                if action["action"] == "c2pa.created"
            ]

            self.assertEqual(len(created_actions), 1)

            # Verify the digitalSourceType is present in the created action
            created_action = created_actions[0]
            self.assertIn("digitalSourceType", created_action)
            self.assertIn("digitalCreation", created_action["digitalSourceType"])

            # Needs trust configuration to be set up to validate as Trusted,
            # or validation_status on read reports `signing certificate untrusted`.
            self.assertEqual(manifest_data["validation_state"], "Valid")
            output.close()

    def test_streams_sign_with_es256_alg_edit_intent(self):
        """Test signing with EDIT intent and empty manifest."""

        with open(self.testPath2, "rb") as file:
            # Start with an empty manifest
            builder = Builder({})
            # Set the intent for editing existing content
            builder.set_intent(C2paBuilderIntent.EDIT)
            output = io.BytesIO(bytearray())
            builder.sign(self.signer, "image/jpeg", file, output)
            output.seek(0)
            reader = Reader("image/jpeg", output)
            json_str = reader.json()

            # Verify the manifest was created
            self.assertIsNotNone(json_str)

            # Parse the JSON to verify the structure
            manifest_data = json.loads(json_str)
            active_manifest_label = manifest_data["active_manifest"]
            active_manifest = manifest_data["manifests"][active_manifest_label]

            # Check that ingredients exist in the active manifest
            self.assertIn("ingredients", active_manifest)
            ingredients_manifest = active_manifest["ingredients"]
            self.assertIsInstance(ingredients_manifest, list)
            self.assertEqual(len(ingredients_manifest), 1)

            # Verify the ingredient has relationship "parentOf"
            ingredient = ingredients_manifest[0]
            self.assertIn("relationship", ingredient)
            self.assertEqual(
                ingredient["relationship"],
                "parentOf"
            )

            # Check that assertions exist
            self.assertIn("assertions", active_manifest)
            assertions = active_manifest["assertions"]

            # Find the actions assertion
            actions_assertion = None
            for assertion in assertions:
                if assertion["label"] in ["c2pa.actions", "c2pa.actions.v2"]:
                    actions_assertion = assertion
                    break

            self.assertIsNotNone(actions_assertion)

            # Verify c2pa.opened action exists and there is only one
            actions = actions_assertion["data"]["actions"]
            opened_actions = [
                action for action in actions
                if action["action"] == "c2pa.opened"
            ]

            self.assertEqual(len(opened_actions), 1)

            # Verify the c2pa.opened action has the correct structure
            opened_action = opened_actions[0]
            self.assertIn("parameters", opened_action)
            self.assertIn("ingredients", opened_action["parameters"])
            ingredients = opened_action["parameters"]["ingredients"]
            self.assertIsInstance(ingredients, list)
            self.assertGreater(len(ingredients), 0)

            # Verify each ingredient has url and hash
            for ingredient in ingredients:
                self.assertIn("url", ingredient)
                self.assertIn("hash", ingredient)

            # Needs trust configuration to be set up to validate as Trusted,
            # or validation_status on read reports `signing certificate untrusted`.
            self.assertEqual(manifest_data["validation_state"], "Valid")
            output.close()

    def test_streams_sign_with_es256_alg_with_trust_config(self):
        # Run in a separate thread to isolate thread-local settings
        result = {}
        exception = {}

        def sign_and_validate_with_trust_config():
            try:
                # Load trust configuration
                settings_dict = load_test_settings_json()

                # Apply the settings (including trust configuration)
                # Settings are thread-local, so they won't affect other tests
                # And that is why we also run the test in its own thread, so tests are isolated
                load_settings(settings_dict)

                with open(self.testPath, "rb") as file:
                    builder = Builder(self.manifestDefinitionV2)
                    output = io.BytesIO(bytearray())
                    builder.sign(self.signer, "image/jpeg", file, output)
                    output.seek(0)
                    reader = Reader("image/jpeg", output)
                    json_data = reader.json()

                    # Get validation state with trust config
                    validation_state = reader.get_validation_state()

                    result['json_data'] = json_data
                    result['validation_state'] = validation_state
                    output.close()
            except Exception as e:
                exception['error'] = e

        # Create and start thread
        thread = threading.Thread(target=sign_and_validate_with_trust_config)
        thread.start()
        thread.join()

        # Check for exceptions
        if 'error' in exception:
            raise exception['error']

        # Assertions run in main thread
        self.assertIn("Python Test", result.get('json_data', ''))
        # With trust configuration loaded, validation should return "Trusted"
        self.assertIsNotNone(result.get('validation_state'))
        self.assertEqual(result.get('validation_state'), "Trusted")

    def test_sign_with_ed25519_alg(self):
        with open(os.path.join(self.data_dir, "ed25519.pub"), "rb") as cert_file:
            certs = cert_file.read()
        with open(os.path.join(self.data_dir, "ed25519.pem"), "rb") as key_file:
            key = key_file.read()

        signer_info = C2paSignerInfo(
            alg=b"ed25519",
            sign_cert=certs,
            private_key=key,
            ta_url=b"http://timestamp.digicert.com"
        )
        signer = Signer.from_info(signer_info)

        with open(self.testPath, "rb") as file:
            builder = Builder(self.manifestDefinitionV2)
            output = io.BytesIO(bytearray())
            builder.sign(signer, "image/jpeg", file, output)
            output.seek(0)
            reader = Reader("image/jpeg", output)
            json_data = reader.json()
            self.assertIn("Python Test", json_data)
            # Needs trust configuration to be set up to validate as Trusted,
            # or validation_status on read reports `signing certificate untrusted`.
            self.assertIn("Valid", json_data)
            output.close()

    def test_sign_with_ed25519_alg_with_trust_config(self):
        # Run in a separate thread to isolate thread-local settings
        result = {}
        exception = {}

        def sign_and_validate_with_trust_config():
            try:
                # Load trust configuration
                settings_dict = load_test_settings_json()

                # Apply the settings (including trust configuration)
                # Settings are thread-local, so they won't affect other tests
                # And that is why we also run the test in its own thread, so tests are isolated
                load_settings(settings_dict)

                with open(os.path.join(self.data_dir, "ed25519.pub"), "rb") as cert_file:
                    certs = cert_file.read()
                with open(os.path.join(self.data_dir, "ed25519.pem"), "rb") as key_file:
                    key = key_file.read()

                signer_info = C2paSignerInfo(
                    alg=b"ed25519",
                    sign_cert=certs,
                    private_key=key,
                    ta_url=b"http://timestamp.digicert.com"
                )
                signer = Signer.from_info(signer_info)

                with open(self.testPath, "rb") as file:
                    builder = Builder(self.manifestDefinitionV2)
                    output = io.BytesIO(bytearray())
                    builder.sign(signer, "image/jpeg", file, output)
                    output.seek(0)
                    reader = Reader("image/jpeg", output)
                    json_data = reader.json()

                    # Get validation state with trust config
                    validation_state = reader.get_validation_state()

                    result['json_data'] = json_data
                    result['validation_state'] = validation_state
                    output.close()
            except Exception as e:
                exception['error'] = e

        # Create and start thread
        thread = threading.Thread(target=sign_and_validate_with_trust_config)
        thread.start()
        thread.join()

        # Check for exceptions
        if 'error' in exception:
            raise exception['error']

        # Assertions run in main thread
        self.assertIn("Python Test", result.get('json_data', ''))
        # With trust configuration loaded, validation should return "Trusted"
        self.assertIsNotNone(result.get('validation_state'))
        self.assertEqual(result.get('validation_state'), "Trusted")

    def test_sign_with_ed25519_alg_2(self):
        with open(os.path.join(self.data_dir, "ed25519.pub"), "rb") as cert_file:
            certs = cert_file.read()
        with open(os.path.join(self.data_dir, "ed25519.pem"), "rb") as key_file:
            key = key_file.read()

        signer_info = C2paSignerInfo(
            alg=b"ed25519",
            sign_cert=certs,
            private_key=key,
            ta_url=b"http://timestamp.digicert.com"
        )
        signer = Signer.from_info(signer_info)

        with open(self.testPath2, "rb") as file:
            builder = Builder(self.manifestDefinitionV2)
            output = io.BytesIO(bytearray())
            builder.sign(signer, "image/jpeg", file, output)
            output.seek(0)
            reader = Reader("image/jpeg", output)
            json_data = reader.json()
            self.assertIn("Python Test", json_data)
            # Needs trust configuration to be set up to validate as Trusted,
            # or validation_status on read reports `signing certificate untrusted`.
            self.assertIn("Valid", json_data)
            output.close()

    def test_sign_with_ps256_alg(self):
        with open(os.path.join(self.data_dir, "ps256.pub"), "rb") as cert_file:
            certs = cert_file.read()
        with open(os.path.join(self.data_dir, "ps256.pem"), "rb") as key_file:
            key = key_file.read()

        signer_info = C2paSignerInfo(
            alg=b"ps256",
            sign_cert=certs,
            private_key=key,
            ta_url=b"http://timestamp.digicert.com"
        )
        signer = Signer.from_info(signer_info)

        with open(self.testPath, "rb") as file:
            builder = Builder(self.manifestDefinitionV2)
            output = io.BytesIO(bytearray())
            builder.sign(signer, "image/jpeg", file, output)
            output.seek(0)
            reader = Reader("image/jpeg", output)
            json_data = reader.json()
            self.assertIn("Python Test", json_data)
            # Needs trust configuration to be set up to validate as Trusted,
            # or validation_status on read reports `signing certificate untrusted`.
            self.assertIn("Valid", json_data)
            output.close()

    def test_sign_with_ps256_alg_2(self):
        with open(os.path.join(self.data_dir, "ps256.pub"), "rb") as cert_file:
            certs = cert_file.read()
        with open(os.path.join(self.data_dir, "ps256.pem"), "rb") as key_file:
            key = key_file.read()

        signer_info = C2paSignerInfo(
            alg=b"ps256",
            sign_cert=certs,
            private_key=key,
            ta_url=b"http://timestamp.digicert.com"
        )
        signer = Signer.from_info(signer_info)

        with open(self.testPath2, "rb") as file:
            builder = Builder(self.manifestDefinitionV2)
            output = io.BytesIO(bytearray())
            builder.sign(signer, "image/jpeg", file, output)
            output.seek(0)
            reader = Reader("image/jpeg", output)
            json_data = reader.json()
            self.assertIn("Python Test", json_data)
            # Needs trust configuration to be set up to validate as Trusted
            # self.assertNotIn("validation_status", json_data)
            output.close()

    def test_sign_with_ps256_alg_2_with_trust_config(self):
        # Run in a separate thread to isolate thread-local settings
        result = {}
        exception = {}

        def sign_and_validate_with_trust_config():
            try:
                # Load trust configuration
                settings_dict = load_test_settings_json()

                # Apply the settings (including trust configuration)
                # Settings are thread-local, so they won't affect other tests
                # And that is why we also run the test in its own thread, so tests are isolated
                load_settings(settings_dict)

                with open(os.path.join(self.data_dir, "ps256.pub"), "rb") as cert_file:
                    certs = cert_file.read()
                with open(os.path.join(self.data_dir, "ps256.pem"), "rb") as key_file:
                    key = key_file.read()

                signer_info = C2paSignerInfo(
                    alg=b"ps256",
                    sign_cert=certs,
                    private_key=key,
                    ta_url=b"http://timestamp.digicert.com"
                )
                signer = Signer.from_info(signer_info)

                with open(self.testPath2, "rb") as file:
                    builder = Builder(self.manifestDefinitionV2)
                    output = io.BytesIO(bytearray())
                    builder.sign(signer, "image/jpeg", file, output)
                    output.seek(0)
                    reader = Reader("image/jpeg", output)
                    json_data = reader.json()

                    # Get validation state with trust config
                    validation_state = reader.get_validation_state()

                    result['json_data'] = json_data
                    result['validation_state'] = validation_state
                    output.close()
            except Exception as e:
                exception['error'] = e

        # Create and start thread
        thread = threading.Thread(target=sign_and_validate_with_trust_config)
        thread.start()
        thread.join()

        # Check for exceptions
        if 'error' in exception:
            raise exception['error']

        # Assertions run in main thread
        self.assertIn("Python Test", result.get('json_data', ''))
        # With trust configuration loaded, validation should return "Trusted"
        self.assertIsNotNone(result.get('validation_state'))
        self.assertEqual(result.get('validation_state'), "Trusted")

    def test_archive_sign(self):
        with open(self.testPath, "rb") as file:
            builder = Builder(self.manifestDefinition)
            archive = io.BytesIO(bytearray())
            builder.to_archive(archive)
            builder = Builder.from_archive(archive)
            output = io.BytesIO(bytearray())
            builder.sign(self.signer, "image/jpeg", file, output)
            output.seek(0)
            reader = Reader("image/jpeg", output)
            json_data = reader.json()
            self.assertIn("Python Test", json_data)
            # Needs trust configuration to be set up to validate as Trusted,
            # or validation_status on read reports `signing certificate untrusted`.
            self.assertIn("Valid", json_data)
            archive.close()
            output.close()

    def test_archive_sign_with_trust_config(self):
        # Run in a separate thread to isolate thread-local settings
        result = {}
        exception = {}

        def sign_and_validate_with_trust_config():
            try:
                # Load trust configuration
                settings_dict = load_test_settings_json()

                # Apply the settings (including trust configuration)
                # Settings are thread-local, so they won't affect other tests
                # And that is why we also run the test in its own thread, so tests are isolated
                load_settings(settings_dict)

                with open(self.testPath, "rb") as file:
                    builder = Builder(self.manifestDefinition)
                    archive = io.BytesIO(bytearray())
                    builder.to_archive(archive)
                    builder = Builder.from_archive(archive)
                    output = io.BytesIO(bytearray())
                    builder.sign(self.signer, "image/jpeg", file, output)
                    output.seek(0)
                    reader = Reader("image/jpeg", output)
                    json_data = reader.json()

                    # Get validation state with trust config
                    validation_state = reader.get_validation_state()

                    result['json_data'] = json_data
                    result['validation_state'] = validation_state
                    archive.close()
                    output.close()
            except Exception as e:
                exception['error'] = e

        # Create and start thread
        thread = threading.Thread(target=sign_and_validate_with_trust_config)
        thread.start()
        thread.join()

        # Check for exceptions
        if 'error' in exception:
            raise exception['error']

        # Assertions run in main thread
        self.assertIn("Python Test", result.get('json_data', ''))
        # With trust configuration loaded, validation should return "Trusted"
        self.assertIsNotNone(result.get('validation_state'))
        self.assertEqual(result.get('validation_state'), "Trusted")

    def test_archive_sign_with_added_ingredient(self):
        with open(self.testPath, "rb") as file:
            builder = Builder(self.manifestDefinitionV2)
            archive = io.BytesIO(bytearray())
            builder.to_archive(archive)
            builder = Builder.from_archive(archive)
            output = io.BytesIO(bytearray())
            ingredient_json = '{"test": "ingredient"}'
            with open(self.testPath, 'rb') as f:
                builder.add_ingredient(ingredient_json, "image/jpeg", f)
            builder.sign(self.signer, "image/jpeg", file, output)
            output.seek(0)
            reader = Reader("image/jpeg", output)
            json_data = reader.json()
            self.assertIn("Python Test", json_data)
            # Needs trust configuration to be set up to validate as Trusted,
            # or validation_status on read reports `signing certificate untrusted`.
            self.assertIn("Valid", json_data)
            archive.close()
            output.close()

    def test_archive_sign_with_added_ingredient_with_trust_config(self):
        # Run in a separate thread to isolate thread-local settings
        result = {}
        exception = {}

        def sign_and_validate_with_trust_config():
            try:
                # Load trust configuration
                settings_dict = load_test_settings_json()

                # Apply the settings (including trust configuration)
                # Settings are thread-local, so they won't affect other tests
                # And that is why we also run the test in its own thread, so tests are isolated
                load_settings(settings_dict)

                with open(self.testPath, "rb") as file:
                    builder = Builder(self.manifestDefinitionV2)
                    archive = io.BytesIO(bytearray())
                    builder.to_archive(archive)
                    builder = Builder.from_archive(archive)
                    output = io.BytesIO(bytearray())
                    ingredient_json = '{"test": "ingredient"}'
                    with open(self.testPath, 'rb') as f:
                        builder.add_ingredient(ingredient_json, "image/jpeg", f)
                    builder.sign(self.signer, "image/jpeg", file, output)
                    output.seek(0)
                    reader = Reader("image/jpeg", output)
                    json_data = reader.json()

                    # Get validation state with trust config
                    validation_state = reader.get_validation_state()

                    result['json_data'] = json_data
                    result['validation_state'] = validation_state
                    archive.close()
                    output.close()
            except Exception as e:
                exception['error'] = e

        # Create and start thread
        thread = threading.Thread(target=sign_and_validate_with_trust_config)
        thread.start()
        thread.join()

        # Check for exceptions
        if 'error' in exception:
            raise exception['error']

        # Assertions run in main thread
        self.assertIn("Python Test", result.get('json_data', ''))
        # With trust configuration loaded, validation should return "Trusted"
        self.assertIsNotNone(result.get('validation_state'))
        self.assertEqual(result.get('validation_state'), "Trusted")

    def test_write_ingredient_archive_produces_readable_archive(self):
        manifest = {
            "claim_generator_info": [{"name": "c2pa-test", "version": "0.1.0"}],
            "assertions": [],
        }
        builder = Builder.from_json(manifest)
        ingredient_json = {
            "title": "A.jpg",
            "relationship": "componentOf",
            "instance_id": "ingredient-A",
        }
        with open(self.testPath, "rb") as f:
            builder.add_ingredient(ingredient_json, "image/jpeg", f)
        archive = io.BytesIO()
        builder.write_ingredient_archive("ingredient-A", archive)
        builder.close()
        self.assertGreater(len(archive.getvalue()), 0)
        archive.close()

    def test_add_ingredient_from_archive_roundtrip(self):
        manifest = {
            "claim_generator_info": [{"name": "c2pa-test", "version": "0.1.0"}],
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
            ],
        }
        builder = Builder.from_json(manifest)
        ingredient_json = {
            "title": "A.jpg",
            "relationship": "componentOf",
            "instance_id": "catalog:ingredient-A",
        }
        with open(self.testPath, "rb") as f:
            builder.add_ingredient(ingredient_json, "image/jpeg", f)
        archive = io.BytesIO()
        builder.write_ingredient_archive("catalog:ingredient-A", archive)
        builder.close()

        archive.seek(0)
        builder2 = Builder.from_json(manifest)
        builder2.add_ingredient_from_archive(archive)
        archive.close()

        output = io.BytesIO()
        with open(self.testPath, "rb") as f:
            builder2.sign(self.signer, "image/jpeg", f, output)
        builder2.close()

        output.seek(0)
        reader = Reader("image/jpeg", output)
        json_data = reader.json()
        self.assertIn("A.jpg", json_data)
        output.close()

    def test_add_ingredient_from_archive_preserves_instance_id(self):
        manifest = {
            "claim_generator_info": [{"name": "c2pa-test", "version": "0.1.0"}],
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
            ],
        }
        archive_builder = Builder.from_json(manifest)
        ingredient_json = {
            "title": "photo.jpg",
            "relationship": "parentOf",
            "instance_id": "my-ingredient",
        }
        with open(self.testPath, "rb") as f:
            archive_builder.add_ingredient(ingredient_json, "image/jpeg", f)
        archive = io.BytesIO()
        archive_builder.write_ingredient_archive("my-ingredient", archive)
        archive_builder.close()

        archive.seek(0)
        signing_builder = Builder.from_json(manifest)
        signing_builder.add_ingredient_from_archive(archive)
        archive.close()

        output = io.BytesIO()
        with open(self.testPath, "rb") as f:
            signing_builder.sign(self.signer, "image/jpeg", f, output)
        signing_builder.close()

        output.seek(0)
        reader = Reader("image/jpeg", output)
        json_data = reader.json()
        self.assertIn("photo.jpg", json_data)
        output.close()

    def test_add_ingredient_from_archive_preserves_instance_id_component_of(self):
        manifest = {
            "claim_generator_info": [{"name": "c2pa-test", "version": "1.0"}],
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
            ],
        }
        archive_builder = Builder.from_json(manifest)
        ingredient_json = {
            "title": "photo.jpg",
            "relationship": "componentOf",
            "instance_id": "my-ingredient",
        }
        with open(self.testPath, "rb") as f:
            archive_builder.add_ingredient(ingredient_json, "image/jpeg", f)
        archive = io.BytesIO()
        archive_builder.write_ingredient_archive("my-ingredient", archive)
        archive_builder.close()

        archive.seek(0)
        signing_builder = Builder.from_json(manifest)
        signing_builder.add_ingredient_from_archive(archive)
        archive.close()

        output = io.BytesIO()
        with open(self.testPath, "rb") as f:
            signing_builder.sign(self.signer, "image/jpeg", f, output)
        signing_builder.close()

        output.seek(0)
        reader = Reader("image/jpeg", output)
        json_data = reader.json()
        self.assertIn("photo.jpg", json_data)
        self.assertIn("componentOf", json_data)
        output.close()

    def test_add_ingredient_from_archive_preserves_instance_id_input_to(self):
        manifest = {
            "claim_generator_info": [{"name": "c2pa-test", "version": "1.0"}],
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
            ],
        }
        archive_builder = Builder.from_json(manifest)
        ingredient_json = {
            "title": "photo.jpg",
            "relationship": "inputTo",
            "instance_id": "my-ingredient",
        }
        with open(self.testPath, "rb") as f:
            archive_builder.add_ingredient(ingredient_json, "image/jpeg", f)
        archive = io.BytesIO()
        archive_builder.write_ingredient_archive("my-ingredient", archive)
        archive_builder.close()

        archive.seek(0)
        signing_builder = Builder.from_json(manifest)
        signing_builder.add_ingredient_from_archive(archive)
        archive.close()

        output = io.BytesIO()
        with open(self.testPath, "rb") as f:
            signing_builder.sign(self.signer, "image/jpeg", f, output)
        signing_builder.close()

        output.seek(0)
        reader = Reader("image/jpeg", output)
        json_data = reader.json()
        self.assertIn("photo.jpg", json_data)
        self.assertIn("inputTo", json_data)
        output.close()

    def test_add_ingredient_from_archive_roundtrip_parent_of(self):
        manifest = {
            "claim_generator_info": [{"name": "c2pa-test", "version": "1.0"}],
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
            ],
        }
        builder = Builder.from_json(manifest)
        ingredient_json = {
            "title": "A.jpg",
            "relationship": "parentOf",
            "instance_id": "catalog:ingredient-A",
        }
        with open(self.testPath, "rb") as f:
            builder.add_ingredient(ingredient_json, "image/jpeg", f)
        archive = io.BytesIO()
        builder.write_ingredient_archive("catalog:ingredient-A", archive)
        builder.close()

        archive.seek(0)
        builder2 = Builder.from_json(manifest)
        builder2.add_ingredient_from_archive(archive)
        archive.close()

        output = io.BytesIO()
        with open(self.testPath, "rb") as f:
            builder2.sign(self.signer, "image/jpeg", f, output)
        builder2.close()

        output.seek(0)
        reader = Reader("image/jpeg", output)
        json_data = reader.json()
        self.assertIn("A.jpg", json_data)
        self.assertIn("parentOf", json_data)
        output.close()

    def test_add_ingredient_from_archive_roundtrip_input_to(self):
        manifest = {
            "claim_generator_info": [{"name": "c2pa-test", "version": "1.0"}],
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
            ],
        }
        builder = Builder.from_json(manifest)
        ingredient_json = {
            "title": "A.jpg",
            "relationship": "inputTo",
            "instance_id": "catalog:ingredient-A",
        }
        with open(self.testPath, "rb") as f:
            builder.add_ingredient(ingredient_json, "image/jpeg", f)
        archive = io.BytesIO()
        builder.write_ingredient_archive("catalog:ingredient-A", archive)
        builder.close()

        archive.seek(0)
        builder2 = Builder.from_json(manifest)
        builder2.add_ingredient_from_archive(archive)
        archive.close()

        output = io.BytesIO()
        with open(self.testPath, "rb") as f:
            builder2.sign(self.signer, "image/jpeg", f, output)
        builder2.close()

        output.seek(0)
        reader = Reader("image/jpeg", output)
        json_data = reader.json()
        self.assertIn("A.jpg", json_data)
        self.assertIn("inputTo", json_data)
        output.close()

    def test_ingredient_from_archive_linked_to_opened_action(self):
        ingredient_id = "xmp:iid:archive-parent-001"
        manifest = {
            "claim_generator_info": [{"name": "c2pa-test", "version": "1.0"}],
            "assertions": [
                {
                    "label": "c2pa.actions.v2",
                    "data": {
                        "actions": [
                            {
                                "action": "c2pa.opened",
                                "parameters": {"ingredientIds": [ingredient_id]},
                            }
                        ]
                    },
                }
            ],
        }
        archive_builder = Builder.from_json(manifest)
        with open(self.testPath, "rb") as f:
            archive_builder.add_ingredient(
                {"title": "photo.jpg", "relationship": "parentOf", "instance_id": ingredient_id},
                "image/jpeg", f)
        archive = io.BytesIO()
        archive_builder.write_ingredient_archive(ingredient_id, archive)
        archive_builder.close()

        archive.seek(0)
        signing_builder = Builder.from_json(manifest)
        signing_builder.add_ingredient_from_archive(archive)
        archive.close()

        output = io.BytesIO()
        with open(self.testPath, "rb") as f:
            signing_builder.sign(self.signer, "image/jpeg", f, output)
        signing_builder.close()

        output.seek(0)
        reader = Reader("image/jpeg", output)
        json_data = reader.json()
        self.assertIn("c2pa.opened", json_data)
        self.assertIn(ingredient_id, json_data)
        output.close()

    def test_ingredient_from_archive_linked_to_placed_action(self):
        ingredient_id = "xmp:iid:archive-component-001"
        manifest = {
            "claim_generator_info": [{"name": "c2pa-test", "version": "1.0"}],
            "assertions": [
                {
                    "label": "c2pa.actions.v2",
                    "data": {
                        "actions": [
                            {
                                "action": "c2pa.placed",
                                "parameters": {"ingredientIds": [ingredient_id]},
                            }
                        ]
                    },
                }
            ],
        }
        archive_builder = Builder.from_json(manifest)
        with open(self.testPath, "rb") as f:
            archive_builder.add_ingredient(
                {"title": "photo.jpg", "relationship": "componentOf", "instance_id": ingredient_id},
                "image/jpeg", f)
        archive = io.BytesIO()
        archive_builder.write_ingredient_archive(ingredient_id, archive)
        archive_builder.close()

        archive.seek(0)
        signing_builder = Builder.from_json(manifest)
        signing_builder.add_ingredient_from_archive(archive)
        archive.close()

        output = io.BytesIO()
        with open(self.testPath, "rb") as f:
            signing_builder.sign(self.signer, "image/jpeg", f, output)
        signing_builder.close()

        output.seek(0)
        reader = Reader("image/jpeg", output)
        json_data = reader.json()
        self.assertIn("c2pa.placed", json_data)
        self.assertIn(ingredient_id, json_data)
        output.close()

    def test_ingredient_from_archive_linked_to_edited_action(self):
        ingredient_id = "xmp:iid:archive-input-001"
        manifest = {
            "claim_generator_info": [{"name": "c2pa-test", "version": "1.0"}],
            "assertions": [
                {
                    "label": "c2pa.actions.v2",
                    "data": {
                        "actions": [
                            {
                                "action": "c2pa.edited",
                                "parameters": {"ingredientIds": [ingredient_id]},
                            }
                        ]
                    },
                }
            ],
        }
        archive_builder = Builder.from_json(manifest)
        with open(self.testPath, "rb") as f:
            archive_builder.add_ingredient(
                {"title": "photo.jpg", "relationship": "inputTo", "instance_id": ingredient_id},
                "image/jpeg", f)
        archive = io.BytesIO()
        archive_builder.write_ingredient_archive(ingredient_id, archive)
        archive_builder.close()

        archive.seek(0)
        signing_builder = Builder.from_json(manifest)
        signing_builder.add_ingredient_from_archive(archive)
        archive.close()

        output = io.BytesIO()
        with open(self.testPath, "rb") as f:
            signing_builder.sign(self.signer, "image/jpeg", f, output)
        signing_builder.close()

        output.seek(0)
        reader = Reader("image/jpeg", output)
        json_data = reader.json()
        self.assertIn("c2pa.edited", json_data)
        self.assertIn(ingredient_id, json_data)
        output.close()

    def test_add_two_ingredient_archives_to_one_builder(self):
        manifest = {
            "claim_generator_info": [{"name": "c2pa-test", "version": "1.0"}],
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
            ],
        }
        archives = []
        for title, instance_id in [("A.jpg", "ingredient-A"), ("B.jpg", "ingredient-B")]:
            archive_builder = Builder.from_json(manifest)
            ingredient_json = {
                "title": title,
                "relationship": "componentOf",
                "instance_id": instance_id,
            }
            with open(self.testPath, "rb") as f:
                archive_builder.add_ingredient(ingredient_json, "image/jpeg", f)
            archive = io.BytesIO()
            archive_builder.write_ingredient_archive(instance_id, archive)
            archive_builder.close()
            archive.seek(0)
            archives.append(archive)

        signing_builder = Builder.from_json(manifest)
        for archive in archives:
            signing_builder.add_ingredient_from_archive(archive)
            archive.close()

        output = io.BytesIO()
        with open(self.testPath, "rb") as f:
            signing_builder.sign(self.signer, "image/jpeg", f, output)
        signing_builder.close()

        output.seek(0)
        reader = Reader("image/jpeg", output)
        json_data = reader.json()
        self.assertIn("A.jpg", json_data)
        self.assertIn("B.jpg", json_data)
        output.close()

    def test_write_ingredient_archive_only_contains_requested_ingredient(self):
        manifest = {
            "claim_generator_info": [{"name": "c2pa-test", "version": "1.0"}],
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
            ],
        }
        archive_builder = Builder.from_json(manifest)
        for title, instance_id in [("A.jpg", "ingredient-A"), ("B.jpg", "ingredient-B")]:
            ingredient_json = {
                "title": title,
                "relationship": "componentOf",
                "instance_id": instance_id,
            }
            with open(self.testPath, "rb") as f:
                archive_builder.add_ingredient(ingredient_json, "image/jpeg", f)
        archive = io.BytesIO()
        archive_builder.write_ingredient_archive("ingredient-A", archive)
        archive_builder.close()

        archive.seek(0)
        signing_builder = Builder.from_json(manifest)
        signing_builder.add_ingredient_from_archive(archive)
        archive.close()

        output = io.BytesIO()
        with open(self.testPath, "rb") as f:
            signing_builder.sign(self.signer, "image/jpeg", f, output)
        signing_builder.close()

        output.seek(0)
        reader = Reader("image/jpeg", output)
        json_data = reader.json()
        self.assertIn("A.jpg", json_data)
        self.assertNotIn("B.jpg", json_data)
        output.close()

    def test_write_ingredient_archive_matches_label_or_instance_id(self):
        manifest = {
            "claim_generator_info": [{"name": "c2pa-test", "version": "1.0"}],
            "assertions": [],
        }
        ingredient_json = {
            "title": "photo.jpg",
            "relationship": "componentOf",
            "label": "my-label",
            "instance_id": "my-instance-id",
        }
        builder = Builder.from_json(manifest)
        with open(self.testPath, "rb") as f:
            builder.add_ingredient(ingredient_json, "image/jpeg", f)

        by_label = io.BytesIO()
        builder.write_ingredient_archive("my-label", by_label)
        self.assertGreater(len(by_label.getvalue()), 0)
        by_label.close()

        by_instance_id = io.BytesIO()
        builder.write_ingredient_archive("my-instance-id", by_instance_id)
        self.assertGreater(len(by_instance_id.getvalue()), 0)
        by_instance_id.close()

        builder.close()

    def test_write_ingredient_archive_unknown_id_raises(self):
        manifest = {
            "claim_generator_info": [{"name": "c2pa-test", "version": "1.0"}],
            "assertions": [],
        }
        builder = Builder.from_json(manifest)
        ingredient_json = {
            "title": "photo.jpg",
            "relationship": "componentOf",
            "instance_id": "ingredient-A",
        }
        with open(self.testPath, "rb") as f:
            builder.add_ingredient(ingredient_json, "image/jpeg", f)
        with self.assertRaises(Error):
            builder.write_ingredient_archive("nonexistent-id", io.BytesIO())
        builder.close()

    def test_add_ingredient_from_archive_invalid_data_raises(self):
        manifest = {
            "claim_generator_info": [{"name": "c2pa-test", "version": "1.0"}],
            "assertions": [],
        }
        builder = Builder.from_json(manifest)
        with self.assertRaises(Error):
            builder.add_ingredient_from_archive(io.BytesIO(b"not a c2pa archive"))
        with self.assertRaises(Error):
            builder.add_ingredient_from_archive(io.BytesIO())
        builder.close()

    def test_ingredient_archive_methods_raise_on_closed_builder(self):
        manifest = {
            "claim_generator_info": [{"name": "c2pa-test", "version": "1.0"}],
            "assertions": [],
        }
        builder = Builder.from_json(manifest)
        builder.close()
        with self.assertRaises(Error):
            builder.write_ingredient_archive("ingredient-A", io.BytesIO())
        with self.assertRaises(Error):
            builder.add_ingredient_from_archive(io.BytesIO())

    def test_remote_sign(self):
        with open(self.testPath, "rb") as file:
            builder = Builder(self.manifestDefinition)
            builder.set_no_embed()
            output = io.BytesIO(bytearray())
            builder.sign(self.signer, "image/jpeg", file, output)

            output.seek(0)
            # When set_no_embed() is used, no manifest should be embedded in the file
            # So reading from the file should fail
            with self.assertRaises(Error):
                Reader("image/jpeg", output)
            output.close()

    def test_remote_sign_using_returned_bytes(self):
        with open(self.testPath, "rb") as file:
            builder = Builder(self.manifestDefinition)
            builder.set_no_embed()
            with io.BytesIO() as output_buffer:
                manifest_data = builder.sign(
                    self.signer, "image/jpeg", file, output_buffer)
                output_buffer.seek(0)
                read_buffer = io.BytesIO(output_buffer.getvalue())

                with Reader("image/jpeg", read_buffer, manifest_data) as reader:
                    manifest_data = reader.json()
                    self.assertIn("Python Test", manifest_data)

    def _detached_manifest_and_asset(self):
        with open(self.testPath, "rb") as file:
            builder = Builder(self.manifestDefinition)
            builder.set_no_embed()
            with io.BytesIO() as output_buffer:
                manifest = builder.sign(
                    self.signer, "image/jpeg", file, output_buffer)
                return manifest, output_buffer.getvalue()

    def test_bare_stream_with_real_manifest_data_is_used(self):
        manifest, asset = self._detached_manifest_and_asset()
        with Reader(io.BytesIO(asset), manifest_data=manifest) as reader:
            self.assertIn("Python Test", reader.json())

    def test_manifest_data_keyword_with_real_bytes(self):
        # manifest_data passed by keyword (not positionally) with real bytes.
        manifest, asset = self._detached_manifest_and_asset()
        with Reader(
                "image/jpeg", io.BytesIO(asset),
                manifest_data=manifest) as reader:
            self.assertIn("Python Test", reader.json())

    def test_try_create_with_manifest_data(self):
        manifest, asset = self._detached_manifest_and_asset()
        reader = Reader.try_create(
            "image/jpeg", io.BytesIO(asset), manifest)
        self.assertIsNotNone(reader)
        if reader is not None:
            self.assertIn("Python Test", reader.json())
            reader.close()

    def test_try_create_with_manifest_data_keyword(self):
        # try_create with manifest_data passed by keyword.
        manifest, asset = self._detached_manifest_and_asset()
        reader = Reader.try_create(
            "image/jpeg", io.BytesIO(asset), manifest_data=manifest)
        self.assertIsNotNone(reader)
        if reader is not None:
            self.assertIn("Python Test", reader.json())
            reader.close()

    def test_bare_stream_with_context_and_manifest(self):
        # Stream and real manifest and context together.
        manifest, asset = self._detached_manifest_and_asset()
        context = Context()
        try:
            with Reader(io.BytesIO(asset), manifest_data=manifest,
                        context=context) as reader:
                self.assertIn("Python Test", reader.json())
        finally:
            context.close()

    def test_try_create_format_plus_path_string(self):
        with tempfile.TemporaryDirectory() as tmp:
            asset = os.path.join(tmp, "signed.jpg")
            with open(self.testPath, "rb") as file, open(asset, "wb") as out:
                Builder(self.manifestDefinition).sign(
                    self.signer, "image/jpeg", file, out)
            reader = Reader.try_create("image/jpeg", asset)
            self.assertIsNotNone(reader)
            if reader is not None:
                self.assertIn("Python Test", reader.json())
                reader.close()

    def test_non_context_wrong_type_manifest_raises_typeerror(self):
        with open(self.testPath, "rb") as file:
            with self.assertRaises(TypeError):
                Reader("image/jpeg", file, "not-bytes")

    def test_remote_sign_using_returned_bytes_V2(self):
        with open(self.testPath, "rb") as file:
            builder = Builder(self.manifestDefinitionV2)
            builder.set_no_embed()
            with io.BytesIO() as output_buffer:
                manifest_data = builder.sign(
                    self.signer, "image/jpeg", file, output_buffer)
                output_buffer.seek(0)
                read_buffer = io.BytesIO(output_buffer.getvalue())

                with Reader("image/jpeg", read_buffer, manifest_data) as reader:
                    manifest_data = reader.json()
                    self.assertIn("Python Test", manifest_data)

    def test_remote_sign_using_returned_bytes_V2_with_trust_config(self):
        # Run in a separate thread to isolate thread-local settings
        result = {}
        exception = {}

        def sign_and_validate_with_trust_config():
            try:
                # Load trust configuration
                settings_dict = load_test_settings_json()

                # Apply the settings (including trust configuration)
                # Settings are thread-local, so they won't affect other tests
                # And that is why we also run the test in its own thread, so tests are isolated
                load_settings(settings_dict)

                with open(self.testPath, "rb") as file:
                    builder = Builder(self.manifestDefinitionV2)
                    builder.set_no_embed()
                    with io.BytesIO() as output_buffer:
                        manifest_data = builder.sign(
                            self.signer, "image/jpeg", file, output_buffer)
                        output_buffer.seek(0)
                        read_buffer = io.BytesIO(output_buffer.getvalue())

                        with Reader("image/jpeg", read_buffer, manifest_data) as reader:
                            json_data = reader.json()

                            # Get validation state with trust config
                            validation_state = reader.get_validation_state()

                            result['json_data'] = json_data
                            result['validation_state'] = validation_state
            except Exception as e:
                exception['error'] = e

        # Create and start thread
        thread = threading.Thread(target=sign_and_validate_with_trust_config)
        thread.start()
        thread.join()

        # Check for exceptions
        if 'error' in exception:
            raise exception['error']

        # Assertions run in main thread
        self.assertIn("Python Test", result.get('json_data', ''))
        # With trust configuration loaded, validation should return "Trusted"
        self.assertIsNotNone(result.get('validation_state'))
        self.assertEqual(result.get('validation_state'), "Trusted")

    def test_sign_all_files(self):
        """Test signing all files in both fixtures directories"""
        signing_dir = os.path.join(self.data_dir, "files-for-signing-tests")
        reading_dir = os.path.join(self.data_dir, "files-for-reading-tests")

        # Map of file extensions to MIME types
        mime_types = {
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.png': 'image/png',
            '.gif': 'image/gif',
            '.webp': 'image/webp',
            '.heic': 'image/heic',
            '.heif': 'image/heif',
            '.avif': 'image/avif',
            '.tif': 'image/tiff',
            '.tiff': 'image/tiff',
            '.mp4': 'video/mp4',
            '.avi': 'video/x-msvideo',
            '.mp3': 'audio/mpeg',
            '.m4a': 'audio/mp4',
            '.wav': 'audio/wav'
        }

        # Skip files that are known to be invalid or unsupported
        skip_files = {
            'sample3.invalid.wav',  # Invalid file
        }

        # Process both directories
        for directory in [signing_dir, reading_dir]:
            for filename in os.listdir(directory):
                if filename in skip_files:
                    continue

                file_path = os.path.join(directory, filename)
                if not os.path.isfile(file_path):
                    continue

                # Get file extension and corresponding MIME type
                _, ext = os.path.splitext(filename)
                ext = ext.lower()
                if ext not in mime_types:
                    continue

                mime_type = mime_types[ext]

                try:
                    with open(file_path, "rb") as file:
                        builder = Builder(self.manifestDefinition)
                        output = io.BytesIO(bytearray())
                        builder.sign(self.signer, mime_type, file, output)
                        builder.close()
                        output.seek(0)
                        reader = Reader(mime_type, output)
                        json_data = reader.json()
                        self.assertIn("Python Test", json_data)
                        # Needs trust configuration to be set up to validate as Trusted,
                        # or validation_status on read reports `signing certificate untrusted`.
                        self.assertIn("Valid", json_data)
                        reader.close()
                        output.close()
                except Error.NotSupported:
                    continue
                except Exception as e:
                    self.fail(f"Failed to sign {filename}: {str(e)}")

    def test_sign_all_files_V2(self):
        """Test signing all files in both fixtures directories"""
        signing_dir = os.path.join(self.data_dir, "files-for-signing-tests")
        reading_dir = os.path.join(self.data_dir, "files-for-reading-tests")

        # Map of file extensions to MIME types
        mime_types = {
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.png': 'image/png',
            '.gif': 'image/gif',
            '.webp': 'image/webp',
            '.heic': 'image/heic',
            '.heif': 'image/heif',
            '.avif': 'image/avif',
            '.tif': 'image/tiff',
            '.tiff': 'image/tiff',
            '.mp4': 'video/mp4',
            '.avi': 'video/x-msvideo',
            '.mp3': 'audio/mpeg',
            '.m4a': 'audio/mp4',
            '.wav': 'audio/wav'
        }

        # Skip files that are known to be invalid or unsupported
        skip_files = {
            'sample3.invalid.wav',  # Invalid file
        }

        # Process both directories
        for directory in [signing_dir, reading_dir]:
            for filename in os.listdir(directory):
                if filename in skip_files:
                    continue

                file_path = os.path.join(directory, filename)
                if not os.path.isfile(file_path):
                    continue

                # Get file extension and corresponding MIME type
                _, ext = os.path.splitext(filename)
                ext = ext.lower()
                if ext not in mime_types:
                    continue

                mime_type = mime_types[ext]

                try:
                    with open(file_path, "rb") as file:
                        builder = Builder(self.manifestDefinitionV2)
                        output = io.BytesIO(bytearray())
                        builder.sign(self.signer, mime_type, file, output)
                        builder.close()
                        output.seek(0)
                        reader = Reader(mime_type, output)
                        json_data = reader.json()
                        self.assertIn("Python Test", json_data)
                        # Needs trust configuration to be set up to validate as Trusted,
                        # or validation_status on read reports `signing certificate untrusted`
                        self.assertIn("Valid", json_data)
                        reader.close()
                        output.close()
                except Error.NotSupported:
                    continue
                except Exception as e:
                    self.fail(f"Failed to sign {filename}: {str(e)}")

    def test_builder_no_added_ingredient_on_closed_builder(self):
        builder = Builder(self.manifestDefinition)

        builder.close()

        with self.assertRaises(Error):
            ingredient_json = '{"test": "ingredient"}'
            with open(self.testPath, 'rb') as f:
                builder.add_ingredient(ingredient_json, "image/jpeg", f)

    def test_builder_add_ingredient(self):
        builder = Builder.from_json(self.manifestDefinition)
        assert builder._handle is not None

        # Test adding ingredient
        ingredient_json = '{"test": "ingredient"}'
        with open(self.testPath, 'rb') as f:
            builder.add_ingredient(ingredient_json, "image/jpeg", f)

        builder.close()

    def test_builder_add_ingredient_dict(self):
        builder = Builder.from_json(self.manifestDefinition)
        assert builder._handle is not None

        # Test adding ingredient with a dictionary instead of JSON string
        ingredient_dict = {"test": "ingredient"}
        with open(self.testPath, 'rb') as f:
            builder.add_ingredient(ingredient_dict, "image/jpeg", f)

        builder.close()

    def test_builder_add_multiple_ingredients(self):
        builder = Builder.from_json(self.manifestDefinition)
        assert builder._handle is not None

        # Test builder operations
        builder.set_no_embed()
        builder.set_remote_url("http://test.url")

        # Test adding ingredient
        ingredient_json = '{"test": "ingredient"}'
        with open(self.testPath, 'rb') as f:
            builder.add_ingredient(ingredient_json, "image/jpeg", f)

        # Test adding another ingredient
        ingredient_json = '{"test": "ingredient2"}'
        with open(self.testPath2, 'rb') as f:
            builder.add_ingredient(ingredient_json, "image/jpeg", f)

        builder.close()

    def test_builder_add_multiple_ingredients_2(self):
        builder = Builder.from_json(self.manifestDefinition)
        assert builder._handle is not None

        # Test builder operations
        builder.set_no_embed()
        builder.set_remote_url("http://test.url")

        # Test adding ingredient with a dictionary
        ingredient_dict = {"test": "ingredient"}
        with open(self.testPath, 'rb') as f:
            builder.add_ingredient(ingredient_dict, "image/jpeg", f)

        # Test adding another ingredient with a JSON string
        ingredient_json = '{"test": "ingredient2"}'
        with open(self.testPath2, 'rb') as f:
            builder.add_ingredient(ingredient_json, "image/jpeg", f)

        builder.close()

    def test_builder_add_multiple_ingredients_and_resources(self):
        builder = Builder.from_json(self.manifestDefinition)
        assert builder._handle is not None

        # Test builder operations
        builder.set_no_embed()
        builder.set_remote_url("http://test.url")

        # Test adding resource
        with open(self.testPath, 'rb') as f:
            builder.add_resource("test_uri_1", f)

        with open(self.testPath, 'rb') as f:
            builder.add_resource("test_uri_2", f)

        with open(self.testPath, 'rb') as f:
            builder.add_resource("test_uri_3", f)

        # Test adding ingredients
        ingredient_json = '{"test": "ingredient"}'
        with open(self.testPath, 'rb') as f:
            builder.add_ingredient(ingredient_json, "image/jpeg", f)

        ingredient_json = '{"test": "ingredient2"}'
        with open(self.testPath2, 'rb') as f:
            builder.add_ingredient(ingredient_json, "image/jpeg", f)

        builder.close()

    def test_sign_with_any_format_spelling_keeps_thumbnail(self):
        # The format reaches thumbnail generation,
        # which matches a MIME type case sensitively,
        # so an unnormalized spelling silently produces no thumbnail.
        for fmt in ("image/jpeg", "IMAGE/JPEG", "Image/Jpeg", "jpg", "JPG"):
            with self.subTest(format=fmt):
                builder = Builder(self.manifestDefinition)
                dest = io.BytesIO()
                with open(self.testPath, "rb") as source:
                    builder.sign(self.signer, fmt, source, dest)

                dest.seek(0)
                reader = Reader("image/jpeg", dest)
                manifest_store = json.loads(reader.json())
                active = manifest_store["manifests"][
                    manifest_store["active_manifest"]]

                self.assertIn(
                    "thumbnail", active,
                    f"signing with {fmt} dropped the claim thumbnail")
                thumbnail = active["thumbnail"]
                self.assertEqual(thumbnail["format"], "image/jpeg")

                # The reference must resolve to a real JPEG, not just be present.
                thumbnail_bytes = io.BytesIO()
                reader.resource_to_stream(
                    thumbnail["identifier"], thumbnail_bytes)
                data = thumbnail_bytes.getvalue()
                self.assertGreater(
                    len(data), 1000,
                    f"signing with {fmt} produced an empty claim thumbnail")
                self.assertEqual(
                    data[:3], b"\xff\xd8\xff",
                    f"signing with {fmt} produced a thumbnail that is not a JPEG")

    def test_builder_add_multiple_ingredients_and_resources_interleaved(self):
        builder = Builder.from_json(self.manifestDefinition)
        assert builder._handle is not None

        with open(self.testPath, 'rb') as f:
            builder.add_resource("test_uri_1", f)

        ingredient_json = '{"test": "ingredient"}'
        with open(self.testPath, 'rb') as f:
            builder.add_ingredient(ingredient_json, "image/jpeg", f)

        with open(self.testPath, 'rb') as f:
            builder.add_resource("test_uri_2", f)

        with open(self.testPath, 'rb') as f:
            builder.add_resource("test_uri_3", f)

        ingredient_json = '{"test": "ingredient2"}'
        with open(self.testPath2, 'rb') as f:
            builder.add_ingredient(ingredient_json, "image/jpeg", f)

        builder.close()

    def test_builder_sign_with_ingredient(self):
        builder = Builder.from_json(self.manifestDefinition)
        assert builder._handle is not None

        # Test adding ingredient
        ingredient_json = '{ "title": "Test Ingredient" }'
        with open(self.testPath3, 'rb') as f:
            builder.add_ingredient(ingredient_json, "image/jpeg", f)

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

            # Verify thumbnail for manifest is here
            self.assertIn("thumbnail", active_manifest)
            thumbnail_data = active_manifest["thumbnail"]
            self.assertIn("format", thumbnail_data)
            self.assertIn("identifier", thumbnail_data)

            # Verify ingredients array exists in active manifest
            self.assertIn("ingredients", active_manifest)
            self.assertIsInstance(active_manifest["ingredients"], list)
            self.assertTrue(len(active_manifest["ingredients"]) > 0)

            # Verify the first ingredient's title matches what we set
            first_ingredient = active_manifest["ingredients"][0]
            self.assertEqual(first_ingredient["title"], "Test Ingredient")

        builder.close()

    def test_builder_sign_with_ingredients_edit_intent(self):
        """Test signing with EDIT intent and ingredient."""
        builder = Builder.from_json({})
        assert builder._handle is not None

        # Set the intent for editing existing content
        builder.set_intent(C2paBuilderIntent.EDIT)

        # Test adding ingredient
        ingredient_json = '{ "title": "Test Ingredient" }'
        with open(self.testPath3, 'rb') as f:
            builder.add_ingredient(ingredient_json, "image/jpeg", f)

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

            # Verify ingredients array exists with exactly 2 ingredients
            self.assertIn("ingredients", active_manifest)
            ingredients_manifest = active_manifest["ingredients"]
            self.assertIsInstance(ingredients_manifest, list)
            self.assertEqual(len(ingredients_manifest), 2, "Should have exactly two ingredients")

            # Verify the first ingredient is the one we added manually with componentOf relationship
            first_ingredient = ingredients_manifest[0]
            self.assertEqual(first_ingredient["title"], "Test Ingredient")
            self.assertEqual(first_ingredient["format"], "image/jpeg")
            self.assertIn("instance_id", first_ingredient)
            self.assertIn("thumbnail", first_ingredient)
            self.assertEqual(first_ingredient["thumbnail"]["format"], "image/jpeg")
            self.assertIn("identifier", first_ingredient["thumbnail"])
            self.assertEqual(first_ingredient["relationship"], "componentOf")
            self.assertIn("label", first_ingredient)

            # Verify the second ingredient is the auto-created parent with parentOf relationship
            second_ingredient = ingredients_manifest[1]
            # Parent ingredient may not have a title field, or may have an empty one
            self.assertEqual(second_ingredient["format"], "image/jpeg")
            self.assertIn("instance_id", second_ingredient)
            self.assertIn("thumbnail", second_ingredient)
            self.assertEqual(second_ingredient["thumbnail"]["format"], "image/jpeg")
            self.assertIn("identifier", second_ingredient["thumbnail"])
            self.assertEqual(second_ingredient["relationship"], "parentOf")
            self.assertIn("label", second_ingredient)

            # Count ingredients with parentOf relationship - should be exactly one
            parent_ingredients = [
                ing for ing in ingredients_manifest
                if ing.get("relationship") == "parentOf"
            ]
            self.assertEqual(len(parent_ingredients), 1, "Should have exactly one parentOf ingredient")

            # Check that assertions exist
            self.assertIn("assertions", active_manifest)
            assertions = active_manifest["assertions"]

            # Find the actions assertion
            actions_assertion = None
            for assertion in assertions:
                if assertion["label"] in ["c2pa.actions", "c2pa.actions.v2"]:
                    actions_assertion = assertion
                    break

            self.assertIsNotNone(actions_assertion, "Should have c2pa.actions assertion")

            # Verify exactly one c2pa.opened action exists for EDIT intent
            actions = actions_assertion["data"]["actions"]
            opened_actions = [
                action for action in actions
                if action["action"] == "c2pa.opened"
            ]
            self.assertEqual(len(opened_actions), 1, "Should have exactly one c2pa.opened action")

            # Verify the c2pa.opened action has the correct structure with parameters and ingredients
            opened_action = opened_actions[0]
            self.assertIn("parameters", opened_action, "c2pa.opened action should have parameters")
            self.assertIn("ingredients", opened_action["parameters"], "parameters should have ingredients array")
            ingredients_params = opened_action["parameters"]["ingredients"]
            self.assertIsInstance(ingredients_params, list)
            self.assertGreater(len(ingredients_params), 0, "Should have at least one ingredient reference")

            # Verify each ingredient reference has url and hash
            for ingredient_ref in ingredients_params:
                self.assertIn("url", ingredient_ref, "Ingredient reference should have url")
                self.assertIn("hash", ingredient_ref, "Ingredient reference should have hash")

        builder.close()

    def test_builder_sign_with_setting_no_thumbnail_and_ingredient(self):
        # The following removes the manifest's thumbnail
        # Settings should be loaded before the builder is created
        load_settings('{"builder": { "thumbnail": {"enabled": false}}}')

        builder = Builder.from_json(self.manifestDefinition)
        assert builder._handle is not None

        # Test adding ingredient
        ingredient_json = '{ "title": "Test Ingredient" }'
        with open(self.testPath3, 'rb') as f:
            builder.add_ingredient(ingredient_json, "image/jpeg", f)

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

            # There should be no thumbnail anymore here
            self.assertNotIn("thumbnail", active_manifest)

            # Verify ingredients array exists in active manifest
            self.assertIn("ingredients", active_manifest)
            self.assertIsInstance(active_manifest["ingredients"], list)
            self.assertTrue(len(active_manifest["ingredients"]) > 0)

            # Verify the first ingredient's title matches what we set
            first_ingredient = active_manifest["ingredients"][0]
            self.assertEqual(first_ingredient["title"], "Test Ingredient")
            self.assertNotIn("thumbnail", first_ingredient)

        builder.close()

        # Settings are thread-local, so we reset to the default "true" here
        load_settings('{"builder": { "thumbnail": {"enabled": true}}}')

    def test_builder_sign_with_settingdict_no_thumbnail_and_ingredient(self):
        # The following removes the manifest's thumbnail - using dict instead of string
        load_settings({"builder": {"thumbnail": {"enabled": False}}})

        builder = Builder.from_json(self.manifestDefinition)
        assert builder._handle is not None

        # Test adding ingredient
        ingredient_json = '{ "title": "Test Ingredient" }'
        with open(self.testPath3, 'rb') as f:
            builder.add_ingredient(ingredient_json, "image/jpeg", f)

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

            # There should be no thumbnail anymore here
            self.assertNotIn("thumbnail", active_manifest)

            # Verify ingredients array exists in active manifest
            self.assertIn("ingredients", active_manifest)
            self.assertIsInstance(active_manifest["ingredients"], list)
            self.assertTrue(len(active_manifest["ingredients"]) > 0)

            # Verify the first ingredient's title matches what we set
            first_ingredient = active_manifest["ingredients"][0]
            self.assertEqual(first_ingredient["title"], "Test Ingredient")
            self.assertNotIn("thumbnail", first_ingredient)

        builder.close()

        # Settings are thread-local, so we reset to the default "true" here - using dict instead of string
        load_settings({"builder": {"thumbnail": {"enabled": True}}})

    def test_builder_sign_with_duplicate_ingredient(self):
        builder = Builder.from_json(self.manifestDefinition)
        assert builder._handle is not None

        # Test adding ingredient
        ingredient_json = '{"title": "Test Ingredient"}'
        with open(self.testPath3, 'rb') as f:
            builder.add_ingredient(ingredient_json, "image/jpeg", f)
            builder.add_ingredient(ingredient_json, "image/jpeg", f)
            builder.add_ingredient(ingredient_json, "image/jpeg", f)

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
            self.assertEqual(first_ingredient["title"], "Test Ingredient")

            # Verify subsequent labels are unique and have a double underscore with a monotonically inc. index
            second_ingredient = active_manifest["ingredients"][1]
            self.assertTrue(second_ingredient["label"].endswith("__1"))

            third_ingredient = active_manifest["ingredients"][2]
            self.assertTrue(third_ingredient["label"].endswith("__2"))

        builder.close()

    def test_builder_sign_with_ingredient_from_stream(self):
        builder = Builder.from_json(self.manifestDefinition)
        assert builder._handle is not None

        # Test adding ingredient using stream
        ingredient_json = '{"title": "Test Ingredient Stream"}'
        with open(self.testPath3, 'rb') as f:
            builder.add_ingredient_from_stream(
                ingredient_json, "image/jpeg", f)

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
            self.assertEqual(
                first_ingredient["title"],
                "Test Ingredient Stream")

        builder.close()

    def test_builder_sign_with_ingredient_dict_from_stream(self):
        builder = Builder.from_json(self.manifestDefinition)
        assert builder._handle is not None

        # Test adding ingredient using stream with a dictionary
        ingredient_dict = {"title": "Test Ingredient Stream"}
        with open(self.testPath3, 'rb') as f:
            builder.add_ingredient_from_stream(
                ingredient_dict, "image/jpeg", f)

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
            self.assertEqual(
                first_ingredient["title"],
                "Test Ingredient Stream")

        builder.close()

    def test_builder_sign_with_multiple_ingredient(self):
        builder = Builder.from_json(self.manifestDefinition)
        assert builder._handle is not None

        # Add first ingredient
        ingredient_json1 = '{"title": "Test Ingredient 1"}'
        with open(self.testPath3, 'rb') as f:
            builder.add_ingredient(ingredient_json1, "image/jpeg", f)

        # Add second ingredient
        ingredient_json2 = '{"title": "Test Ingredient 2"}'
        cloud_path = ALTERNATIVE_INGREDIENT_TEST_FILE
        with open(cloud_path, 'rb') as f:
            builder.add_ingredient(ingredient_json2, "image/jpeg", f)

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
            self.assertEqual(len(active_manifest["ingredients"]), 2)

            # Verify both ingredients exist in the array (order doesn't matter)
            ingredient_titles = [ing["title"]
                                 for ing in active_manifest["ingredients"]]
            self.assertIn("Test Ingredient 1", ingredient_titles)
            self.assertIn("Test Ingredient 2", ingredient_titles)

        builder.close()

    def test_builder_sign_with_multiple_ingredients_from_stream(self):
        builder = Builder.from_json(self.manifestDefinition)
        assert builder._handle is not None

        # Add first ingredient using stream
        ingredient_json1 = '{"title": "Test Ingredient Stream 1"}'
        with open(self.testPath3, 'rb') as f:
            builder.add_ingredient_from_stream(
                ingredient_json1, "image/jpeg", f)

        # Add second ingredient using stream
        ingredient_json2 = '{"title": "Test Ingredient Stream 2"}'
        cloud_path = ALTERNATIVE_INGREDIENT_TEST_FILE
        with open(cloud_path, 'rb') as f:
            builder.add_ingredient_from_stream(
                ingredient_json2, "image/jpeg", f)

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
            self.assertEqual(len(active_manifest["ingredients"]), 2)

            # Verify both ingredients exist in the array (order doesn't matter)
            ingredient_titles = [ing["title"]
                                 for ing in active_manifest["ingredients"]]
            self.assertIn("Test Ingredient Stream 1", ingredient_titles)
            self.assertIn("Test Ingredient Stream 2", ingredient_titles)

        builder.close()

    def test_builder_set_remote_url(self):
        """Test setting the remote url of a builder."""
        builder = Builder.from_json(self.manifestDefinition)
        builder.set_remote_url("http://this_does_not_exist/foo.jpg")

        with open(self.testPath2, "rb") as file:
            output = io.BytesIO(bytearray())
            builder.sign(self.signer, "image/jpeg", file, output)
            output.seek(0)
            d = output.read()
            self.assertIn(b'provenance="http://this_does_not_exist/foo.jpg"', d)

    def test_builder_set_remote_url_no_embed(self):
        """Test setting the remote url of a builder with no embed flag."""

        # Settings need to be loaded before the builder is created
        load_settings(r'{"verify": { "remote_manifest_fetch": false} }')

        builder = Builder.from_json(self.manifestDefinition)
        builder.set_no_embed()
        builder.set_remote_url("http://this_does_not_exist/foo.jpg")

        with open(self.testPath2, "rb") as file:
            output = io.BytesIO(bytearray())
            builder.sign(self.signer, "image/jpeg", file, output)
            output.seek(0)
            with self.assertRaises(Error) as e:
                Reader("image/jpeg", output)

        self.assertIn("http://this_does_not_exist/foo.jpg", e.exception.message)

        # Return back to default settings
        load_settings(r'{"verify": { "remote_manifest_fetch": true} }')

    def test_sign_single(self):
        """Test signing a file using the sign_file method."""
        builder = Builder(self.manifestDefinition)
        output = io.BytesIO(bytearray())

        with open(self.testPath, "rb") as file:
          builder.sign(self.signer, "image/jpeg", file, output)
          output.seek(0)

          # Read the signed file and verify the manifest
          reader = Reader("image/jpeg", output)
          json_data = reader.json()
          self.assertIn("Python Test", json_data)
          # Needs trust configuration to be set up to validate as Trusted,
          # or validation_status on read reports `signing certificate untrusted`.
          self.assertIn("Valid", json_data)
          output.close()

    def test_sign_mp4_video_file_single(self):
        builder = Builder(self.manifestDefinition)
        output = io.BytesIO(bytearray())

        with open(os.path.join(FIXTURES_DIR, "video1.mp4"), "rb") as file:
          builder.sign(self.signer, "video/mp4", file, output)
          output.seek(0)

          # Read the signed file and verify the manifest
          reader = Reader("video/mp4", output)
          json_data = reader.json()
          self.assertIn("Python Test", json_data)
          # Needs trust configuration to be set up to validate as Trusted,
          # or validation_status on read reports `signing certificate untrusted`.
          self.assertIn("Valid", json_data)
          output.close()

    def test_sign_mov_video_file_single(self):
        builder = Builder(self.manifestDefinition)
        output = io.BytesIO(bytearray())

        with open(os.path.join(FIXTURES_DIR, "C-recorded-as-mov.mov"), "rb") as file:
          builder.sign(self.signer, "mov", file, output)
          output.seek(0)

          # Read the signed file and verify the manifest
          reader = Reader("mov", output)
          json_data = reader.json()
          self.assertIn("Python Test", json_data)
          # Needs trust configuration to be set up to validate as Trusted,
          # or validation_status on read reports `signing certificate untrusted`.
          self.assertIn("Valid", json_data)
          output.close()

    def test_encode_format_builder_blank_raises(self):
        with self.assertRaises(Error.NotSupported):
            _encode_format("", "Builder", allow_autodetect=False)

    def test_sign_empty_format_raises(self):
        builder = Builder(self.manifestDefinition)
        with open(self.testPath, "rb") as file:
            output = io.BytesIO()
            with self.assertRaises(Error.NotSupported):
                builder.sign(self.signer, "", file, output)

    def test_sign_file_extensionless_source_raises(self):
        builder = Builder(self.manifestDefinition)
        with tempfile.TemporaryDirectory() as tmp:
            no_ext = os.path.join(tmp, "source")
            shutil.copyfile(self.testPath, no_ext)
            dest = os.path.join(tmp, "out.jpg")
            with self.assertRaises(Error.NotSupported):
                builder.sign_file(no_ext, dest, self.signer)

    def test_sign_file_unrecognized_extension_raises(self):
        builder = Builder(self.manifestDefinition)
        with tempfile.TemporaryDirectory() as tmp:
            weird = os.path.join(tmp, "source.unknownextension")
            shutil.copyfile(self.testPath, weird)
            dest = os.path.join(tmp, "out.jpg")
            with self.assertRaises(Error.NotSupported):
                builder.sign_file(weird, dest, self.signer)

    def test_sign_file_exceptions_preservation(self):
        builder = Builder(self.manifestDefinition)
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "source.txt")
            shutil.copyfile(self.testPath, src)
            dest = os.path.join(tmp, "out.txt")
            with self.assertRaises(Error.NotSupported):
                builder.sign_file(src, dest, self.signer)

    def test_sign_file_video(self):
        temp_dir = tempfile.mkdtemp()
        try:
            # Create a temporary output file path
            output_path = os.path.join(temp_dir, "signed_output.mp4")

            # Use the sign_file method
            builder = Builder(self.manifestDefinition)
            builder.sign_file(
                os.path.join(FIXTURES_DIR, "video1.mp4"),
                output_path,
                self.signer
            )

            # Verify the output file was created
            self.assertTrue(os.path.exists(output_path))

            # Read the signed file and verify the manifest
            with open(output_path, "rb") as file:
                reader = Reader("video/mp4", file)
                json_data = reader.json()
                self.assertIn("Python Test", json_data)
                # Needs trust configuration to be set up to validate as Trusted,
                # or validation_status on read reports `signing certificate untrusted`.
                self.assertIn("Valid", json_data)

        finally:
            # Clean up the temporary directory
            shutil.rmtree(temp_dir)

    def test_sign_file_format_manifest_bytes_embeddable(self):
        builder = Builder(self.manifestDefinition)
        output = io.BytesIO(bytearray())

        with open(self.testPath, "rb") as file:
            manifest_bytes = builder.sign(self.signer, "image/jpeg", file, output)
            res = format_embeddable("image/jpeg", manifest_bytes)
            output.seek(0)
            output.close()

    def test_builder_sign_file_callback_signer_from_callback(self):
        """Test signing a file using the sign_file method with Signer.from_callback."""

        temp_dir = tempfile.mkdtemp()
        try:

            output_path = os.path.join(temp_dir, "signed_output_from_callback.jpg")

            # Will use the sign_file method
            builder = Builder(self.manifestDefinition)

            # Create signer with callback using Signer.from_callback
            signer = Signer.from_callback(
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
                self.assertIn("Python Test", json_data)
                # Needs trust configuration to be set up to validate as Trusted,
                # or validation_status on read reports `signing certificate untrusted`.
                self.assertIn("Valid", json_data)

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

    def test_builder_sign_file_callback_signer_from_callback_V2(self):
        """Test signing a file using the sign_file method with Signer.from_callback."""

        temp_dir = tempfile.mkdtemp()
        try:

            output_path = os.path.join(temp_dir, "signed_output_from_callback.jpg")

            # Will use the sign_file method
            builder = Builder(self.manifestDefinitionV2)

            # Create signer with callback using Signer.from_callback
            signer = Signer.from_callback(
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
                self.assertIn("Python Test", json_data)
                # Needs trust configuration to be set up to validate as Trusted,
                # or validation_status on read reports `signing certificate untrusted`.
                self.assertIn("Valid", json_data)

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

    def test_builder_sign_with_native_ed25519_callback(self):
        # Load Ed25519 private key (PEM)
        ed25519_pem = os.path.join(FIXTURES_DIR, "ed25519.pem")
        with open(ed25519_pem, "r") as f:
              private_key_pem = f.read()

        # Callback here uses native function
        def ed25519_callback(data: bytes) -> bytes:
            return ed25519_sign(data, private_key_pem)

        # Load the certificate (PUB)
        ed25519_pub = os.path.join(FIXTURES_DIR, "ed25519.pub")
        with open(ed25519_pub, "r") as f:
            certs_pem = f.read()

        # Create a Signer
        # signer = create_signer(
        #     callback=ed25519_callback,
        #     alg=SigningAlg.ED25519,
        #     certs=certs_pem,
        #     tsa_url=None
        # )
        signer = Signer.from_callback(
            callback=ed25519_callback,
            alg=SigningAlg.ED25519,
            certs=certs_pem,
            tsa_url=None
        )

        with open(self.testPath, "rb") as file:
            builder = Builder(self.manifestDefinition)
            output = io.BytesIO(bytearray())
            builder.sign(signer, "image/jpeg", file, output)
            output.seek(0)
            builder.close()
            reader = Reader("image/jpeg", output)
            json_data = reader.json()
            self.assertIn("Python Test", json_data)
            # Needs trust configuration to be set up to validate as Trusted,
            # or validation_status on read reports `signing certificate untrusted`.
            self.assertIn("Valid", json_data)
            reader.close()
            output.close()

    def test_signing_manifest_v2(self):
        """Test signing and reading a V2 manifest.
        V2 manifests have a slightly different structure.
        """
        with open(self.testPath, "rb") as file:
            # Create a builder with the V2 manifest definition using context manager
            with Builder(self.manifestDefinitionV2) as builder:
                output = io.BytesIO(bytearray())

                # Sign as usual...
                builder.sign(self.signer, "image/jpeg", file, output)

                output.seek(0)

                # Read the signed file and verify the manifest using context manager
                with Reader("image/jpeg", output) as reader:
                    json_data = reader.json()

                    # Basic verification of the manifest
                    self.assertIn("Python Test Image V2", json_data)
                    # Needs trust configuration to be set up to validate as Trusted,
                    # or validation_status on read reports `signing certificate untrusted`.
                    self.assertIn("Valid", json_data)

                output.close()

    def test_builder_does_not_sign_unsupported_format(self):
        with open(self.testPath, "rb") as file:
            with Builder(self.manifestDefinitionV2) as builder:
                output = io.BytesIO(bytearray())
                with self.assertRaises(Error.NotSupported):
                    builder.sign(self.signer, "mimetype/not-supported", file, output)

    def test_sign_file_mp4_video(self):
        temp_dir = tempfile.mkdtemp()
        try:
            # Create a temporary output file path
            output_path = os.path.join(temp_dir, "signed_output.mp4")

            # Use the sign_file method
            builder = Builder(self.manifestDefinition)
            builder.sign_file(
                os.path.join(FIXTURES_DIR, "video1.mp4"),
                output_path,
                self.signer
            )

            # Verify the output file was created
            self.assertTrue(os.path.exists(output_path))

            # Read the signed file and verify the manifest
            with open(output_path, "rb") as file:
                reader = Reader("video/mp4", file)
                json_data = reader.json()
                self.assertIn("Python Test", json_data)
                # Needs trust configuration to be set up to validate as Trusted,
                # or validation_status on read reports `signing certificate untrusted`.
                self.assertIn("Valid", json_data)

        finally:
            # Clean up the temporary directory
            shutil.rmtree(temp_dir)

    def test_sign_file_mov_video(self):
        temp_dir = tempfile.mkdtemp()
        try:
            # Create a temporary output file path
            output_path = os.path.join(temp_dir, "signed-C-recorded-as-mov.mov")

            # Use the sign_file method
            builder = Builder(self.manifestDefinition)
            manifest_bytes = builder.sign_file(
                os.path.join(FIXTURES_DIR, "C-recorded-as-mov.mov"),
                output_path,
                self.signer
            )

            # Verify the output file was created
            self.assertTrue(os.path.exists(output_path))

            # Read the signed file and verify the manifest
            with open(output_path, "rb") as file:
                reader = Reader("mov", file)
                json_data = reader.json()
                self.assertIn("Python Test", json_data)
                # Needs trust configuration to be set up to validate as Trusted,
                # or validation_status on read reports `signing certificate untrusted`.
                self.assertIn("Valid", json_data)

            # Verify also signed file using manifest bytes
            with Reader("mov", output_path, manifest_bytes) as reader:
                json_data = reader.json()
                self.assertIn("Python Test", json_data)
                # Needs trust configuration to be set up to validate as Trusted,
                # or validation_status on read reports `signing certificate untrusted`.
                self.assertIn("Valid", json_data)

        finally:
            # Clean up the temporary directory
            shutil.rmtree(temp_dir)

    def test_sign_file_mov_video_V2(self):
        temp_dir = tempfile.mkdtemp()
        try:
            # Create a temporary output file path
            output_path = os.path.join(temp_dir, "signed-C-recorded-as-mov.mov")

            # Use the sign_file method
            builder = Builder(self.manifestDefinitionV2)
            manifest_bytes = builder.sign_file(
                os.path.join(FIXTURES_DIR, "C-recorded-as-mov.mov"),
                output_path,
                self.signer
            )

            # Verify the output file was created
            self.assertTrue(os.path.exists(output_path))

            # Read the signed file and verify the manifest
            with open(output_path, "rb") as file:
                reader = Reader("mov", file)
                json_data = reader.json()
                self.assertIn("Python Test", json_data)
                # Needs trust configuration to be set up to validate as Trusted,
                # or validation_status on read reports `signing certificate untrusted`.
                self.assertIn("Valid", json_data)

            # Verify also signed file using manifest bytes
            with Reader("mov", output_path, manifest_bytes) as reader:
                json_data = reader.json()
                self.assertIn("Python Test", json_data)
                # Needs trust configuration to be set up to validate as Trusted,
                # or validation_status on read reports `signing certificate untrusted`.
                self.assertIn("Valid", json_data)

        finally:
            # Clean up the temporary directory
            shutil.rmtree(temp_dir)

    def test_builder_with_invalid_signer_none(self):
        """Test Builder methods with None signer."""
        builder = Builder(self.manifestDefinition)

        with open(self.testPath, "rb") as file:
            with self.assertRaises(Error):
                builder.sign(None, "image/jpeg", file)

    def test_builder_with_invalid_signer_closed(self):
        """Test Builder methods with closed signer."""
        builder = Builder(self.manifestDefinition)

        # Create and close a signer
        closed_signer = Signer.from_info(self.signer_info)
        closed_signer.close()

        with open(self.testPath, "rb") as file:
            with self.assertRaises(Error):
                builder.sign(closed_signer, "image/jpeg", file)

    def test_builder_with_invalid_signer_object(self):
        """Test Builder methods with invalid signer object."""
        builder = Builder(self.manifestDefinition)

        # Use a mock object that looks like a signer but isn't
        class MockSigner:
            def __init__(self):
                self._handle = None

        mock_signer = MockSigner()

        with open(self.testPath, "rb") as file:
            with self.assertRaises(Error):
                builder.sign(mock_signer, "image/jpeg", file)

    def test_builder_manifest_with_unicode_characters(self):
        """Test Builder with manifest containing various Unicode characters."""
        unicode_manifest = {
            "claim_generator": "python_test_unicode_テスト",
            "claim_generator_info": [{
                "name": "python_test_unicode_テスト",
                "version": "0.0.1",
            }],
            "claim_version": 1,
            "format": "image/jpeg",
            "title": "Python Test Image with Unicode: テスト test",
            "ingredients": [],
            "assertions": [
                {
                    "label": "c2pa.actions",
                    "data": {
                        "actions": [
                            {
                                "action": "c2pa.created",
                                "description": "Unicode: test",
                                "digitalSourceType": "http://cv.iptc.org/newscodes/digitalsourcetype/digitalCreation"
                            }
                        ]
                    }
                }
            ]
        }

        builder = Builder(unicode_manifest)

        with open(self.testPath, "rb") as file:
            output = io.BytesIO(bytearray())
            builder.sign(self.signer, "image/jpeg", file, output)
            output.seek(0)
            reader = Reader("image/jpeg", output)
            json_data = reader.json()

            # Verify Unicode characters are preserved in title and description
            self.assertIn("テスト", json_data)

    def test_builder_ingredient_with_special_characters(self):
        """Test Builder with ingredient containing special characters."""
        special_char_ingredient = {
            "title": "Test Ingredient with Special Chars: テスト",
            "format": "image/jpeg",
            "description": "Special characters: !@#$%^&*()_+-=[]{}|;':\",./<>?`~"
        }

        builder = Builder(self.manifestDefinition)

        # Add ingredient with special characters
        ingredient_json = json.dumps(special_char_ingredient)
        with open(self.testPath2, "rb") as ingredient_file:
            builder.add_ingredient(ingredient_json, "image/jpeg", ingredient_file)

        with open(self.testPath, "rb") as file:
            output = io.BytesIO(bytearray())
            builder.sign(self.signer, "image/jpeg", file, output)
            output.seek(0)
            reader = Reader("image/jpeg", output)
            json_data = reader.json()
            manifest_data = json.loads(json_data)

            # Verify special characters are preserved in ingredients
            self.assertIn("ingredients", manifest_data["manifests"][manifest_data["active_manifest"]])
            ingredients = manifest_data["manifests"][manifest_data["active_manifest"]]["ingredients"]
            self.assertEqual(len(ingredients), 1)

            ingredient = ingredients[0]
            self.assertIn("テスト", ingredient["title"])
            self.assertIn("!@#$%^&*()_+-=[]{}|;':\",./<>?`~", ingredient["description"])

    def test_builder_resource_uri_with_unicode(self):
        """Test Builder with resource URI containing Unicode characters."""
        builder = Builder(self.manifestDefinition)

        # Test with resource URI containing Unicode characters
        unicode_uri = "thumbnail_テスト.jpg"
        with open(self.testPath3, "rb") as thumbnail_file:
            builder.add_resource(unicode_uri, thumbnail_file)

        with open(self.testPath, "rb") as file:
            output = io.BytesIO(bytearray())
            builder.sign(self.signer, "image/jpeg", file, output)
            output.seek(0)
            reader = Reader("image/jpeg", output)
            json_data = reader.json()

            # Verify the resource was added (exact verification depends on implementation)
            self.assertIsNotNone(json_data)

    def test_builder_initialization_failure_states(self):
        """Test Builder state after initialization failures."""
        # Test with invalid JSON
        with self.assertRaises(Error):
            builder = Builder("{invalid json}")

        # Test with None manifest
        with self.assertRaises(Error):
            builder = Builder(None)

        # Test with circular reference in JSON
        circular_obj = {}
        circular_obj['self'] = circular_obj
        with self.assertRaises(Exception) as context:
            builder = Builder(circular_obj)

    def test_construction_failure_before_native_call_is_collectable(self):
        """Builder(None) fails encoding the manifest before any FFI call.
        A half-built instance is UNINITIALIZED with no native handle.
        """
        captured = []
        real_init_attrs = Builder._init_attrs

        def recording_init_attrs(self):
            real_init_attrs(self)
            captured.append(self)

        Builder._init_attrs = recording_init_attrs
        try:
            with self.assertRaises(Error):
                Builder(None)
        finally:
            Builder._init_attrs = real_init_attrs

        self.assertEqual(len(captured), 1,
                         "_init_attrs did not run during the failed construction")
        instance = captured[0]
        self.assertEqual(instance._lifecycle_state, LifecycleState.UNINITIALIZED)
        self.assertIsNone(instance._handle)

        instance._release()

    def test_builder_state_transitions(self):
        """Test Builder state transitions during lifecycle."""
        builder = Builder(self.manifestDefinition)

        # Initial state
        self.assertEqual(builder._lifecycle_state, LifecycleState.ACTIVE)
        self.assertIsNotNone(builder._handle)

        # After close
        builder.close()
        self.assertEqual(builder._lifecycle_state, LifecycleState.CLOSED)
        self.assertIsNone(builder._handle)

    def test_builder_context_manager_states(self):
        """Test Builder state management in context manager."""
        with Builder(self.manifestDefinition) as builder:
            # Inside context - should be valid
            self.assertEqual(builder._lifecycle_state, LifecycleState.ACTIVE)
            self.assertIsNotNone(builder._handle)

            # Placeholder operation
            builder.set_no_embed()

        # After context exit - should be closed
        self.assertEqual(builder._lifecycle_state, LifecycleState.CLOSED)
        self.assertIsNone(builder._handle)

    def test_builder_context_manager_with_exception(self):
        """Test Builder state after exception in context manager."""
        try:
            with Builder(self.manifestDefinition) as builder:
                # Inside context - should be valid
                self.assertEqual(builder._lifecycle_state, LifecycleState.ACTIVE)
                self.assertIsNotNone(builder._handle)
                raise ValueError("Test exception")
        except ValueError:
            pass

        # After exception - should still be closed
        self.assertEqual(builder._lifecycle_state, LifecycleState.CLOSED)
        self.assertIsNone(builder._handle)

    def test_builder_partial_initialization_states(self):
        """Test Builder behavior with partial initialization failures."""
        # Test with _builder = None but _state = ACTIVE
        builder = Builder.__new__(Builder)
        builder._lifecycle_state = LifecycleState.ACTIVE
        builder._handle = None

        with self.assertRaises(Error):
            builder._ensure_valid_state()

    def test_builder_cleanup_state_transitions(self):
        """Test Builder state during cleanup operations."""
        builder = Builder(self.manifestDefinition)

        # Test _cleanup_resources method
        builder._cleanup_resources()
        self.assertEqual(builder._lifecycle_state, LifecycleState.CLOSED)
        self.assertIsNone(builder._handle)

    def test_builder_cleanup_idempotency(self):
        """Test that cleanup operations are idempotent."""
        builder = Builder(self.manifestDefinition)

        # First cleanup
        builder._cleanup_resources()
        self.assertEqual(builder._lifecycle_state, LifecycleState.CLOSED)

        # Second cleanup should not change state
        builder._cleanup_resources()
        self.assertEqual(builder._lifecycle_state, LifecycleState.CLOSED)
        self.assertIsNone(builder._handle)

    def test_builder_state_after_sign_operations(self):
        """Test Builder state after signing operations."""
        builder = Builder(self.manifestDefinition)

        with open(self.testPath, "rb") as file:
            manifest_bytes = builder.sign(self.signer, "image/jpeg", file)

        # Builder is consumed by sign — pointer ownership transferred to Rust
        self.assertEqual(builder._lifecycle_state, LifecycleState.CLOSED)
        self.assertIsNone(builder._handle)

    def test_builder_state_after_archive_operations(self):
        """Test Builder state after archive operations."""
        builder = Builder(self.manifestDefinition)

        # Test to_archive
        with io.BytesIO() as archive_stream:
            builder.to_archive(archive_stream)

        # State should still be valid
        self.assertEqual(builder._lifecycle_state, LifecycleState.ACTIVE)
        self.assertIsNotNone(builder._handle)

    def test_builder_state_after_double_close(self):
        """Test Builder state after double close operations."""
        builder = Builder(self.manifestDefinition)

        # First close
        builder.close()
        self.assertEqual(builder._lifecycle_state, LifecycleState.CLOSED)
        self.assertIsNone(builder._handle)

        # Second close should not change state
        builder.close()
        self.assertEqual(builder._lifecycle_state, LifecycleState.CLOSED)
        self.assertIsNone(builder._handle)

    def test_builder_state_with_invalid_native_pointer(self):
        """Test Builder state handling with invalid native pointer."""
        builder = Builder(self.manifestDefinition)

        # Simulate invalid native pointer
        builder._handle = 0

        # Operations should fail gracefully
        with self.assertRaises(Error):
            builder.set_no_embed()

    def test_builder_add_action_to_manifest_no_auto_add(self):
        # For testing, remove auto-added actions
        load_settings('{"builder":{"actions":{"auto_placed_action":{"enabled":false},"auto_opened_action":{"enabled":false},"auto_created_action":{"enabled":false}}}}')

        initial_manifest_definition = {
            "claim_generator_info": [{
                "name": "python_test",
                "version": "0.0.1",
            }],
            # claim version 2 is the default
            # "claim_version": 2,
            "format": "image/jpeg",
            "title": "Python Test Image V2",
            "assertions": [
                {
                    "label": "c2pa.actions",
                    "data": {
                        "actions": [
                            {
                                "action": "c2pa.created",
                                "digitalSourceType": "http://cv.iptc.org/newscodes/digitalsourcetype/digitalCreation"
                            }
                        ]
                    }
                }
            ]
        }
        builder = Builder.from_json(initial_manifest_definition)

        action_json = '{"action": "c2pa.color_adjustments", "parameters": {"name": "brightnesscontrast"}}'
        builder.add_action(action_json)

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

            # Verify assertions object exists in active manifest
            self.assertIn("assertions", active_manifest)
            assertions = active_manifest["assertions"]

            # Find the c2pa.actions.v2 assertion to check what we added
            actions_assertion = None
            for assertion in assertions:
                if assertion.get("label") == "c2pa.actions.v2":
                    actions_assertion = assertion
                    break

            self.assertIsNotNone(actions_assertion)
            self.assertIn("data", actions_assertion)
            assertion_data = actions_assertion["data"]
            # Verify the manifest now contains actions
            self.assertIn("actions", assertion_data)
            actions = assertion_data["actions"]
            # Verify "c2pa.color_adjustments" action exists anywhere in the actions array
            created_action_found = False
            for action in actions:
                if action.get("action") == "c2pa.color_adjustments":
                    created_action_found = True
                    break

            self.assertTrue(created_action_found)

        builder.close()

        # Reset settings
        load_settings('{"builder":{"actions":{"auto_placed_action":{"enabled":true},"auto_opened_action":{"enabled":true},"auto_created_action":{"enabled":true,"source_type":"http://cv.iptc.org/newscodes/digitalsourcetype/digitalCreation"}}}}')

    def test_builder_add_action_to_manifest_from_dict_no_auto_add(self):
        # For testing, remove auto-added actions
        load_settings('{"builder":{"actions":{"auto_placed_action":{"enabled":false},"auto_opened_action":{"enabled":false},"auto_created_action":{"enabled":false}}}}')

        initial_manifest_definition = {
            "claim_generator_info": [{
                "name": "python_test",
                "version": "0.0.1",
            }],
            # claim version 2 is the default
            # "claim_version": 2,
            "format": "image/jpeg",
            "title": "Python Test Image V2",
            "assertions": [
                {
                    "label": "c2pa.actions",
                    "data": {
                        "actions": [
                            {
                                "action": "c2pa.created",
                                "digitalSourceType": "http://cv.iptc.org/newscodes/digitalsourcetype/digitalCreation"
                            }
                        ]
                    }
                }
            ]
        }
        builder = Builder.from_json(initial_manifest_definition)

        # Using a dictionary instead of a JSON string
        action_dict = {"action": "c2pa.color_adjustments", "parameters": {"name": "brightnesscontrast"}}
        builder.add_action(action_dict)

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

            # Verify assertions object exists in active manifest
            self.assertIn("assertions", active_manifest)
            assertions = active_manifest["assertions"]

            # Find the c2pa.actions.v2 assertion to check what we added
            actions_assertion = None
            for assertion in assertions:
                if assertion.get("label") == "c2pa.actions.v2":
                    actions_assertion = assertion
                    break

            self.assertIsNotNone(actions_assertion)
            self.assertIn("data", actions_assertion)
            assertion_data = actions_assertion["data"]
            # Verify the manifest now contains actions
            self.assertIn("actions", assertion_data)
            actions = assertion_data["actions"]
            # Verify "c2pa.color_adjustments" action exists anywhere in the actions array
            created_action_found = False
            for action in actions:
                if action.get("action") == "c2pa.color_adjustments":
                    created_action_found = True
                    break

            self.assertTrue(created_action_found)

        builder.close()

        # Reset settings
        load_settings('{"builder":{"actions":{"auto_placed_action":{"enabled":true},"auto_opened_action":{"enabled":true},"auto_created_action":{"enabled":true,"source_type":"http://cv.iptc.org/newscodes/digitalsourcetype/digitalCreation"}}}}')

    def test_builder_add_action_to_manifest_with_auto_add(self):
        # For testing, force settings
        load_settings('{"builder":{"actions":{"auto_placed_action":{"enabled":true},"auto_opened_action":{"enabled":true},"auto_created_action":{"enabled":true,"source_type":"http://cv.iptc.org/newscodes/digitalsourcetype/digitalCreation"}}}}')

        initial_manifest_definition = {
            "claim_generator_info": [{
                "name": "python_test",
                "version": "0.0.1",
            }],
            # claim version 2 is the default
            # "claim_version": 2,
            "format": "image/jpeg",
            "title": "Python Test Image V2",
            "ingredients": [],
            "assertions": [
                {
                    "label": "c2pa.actions",
                    "data": {
                        "actions": [
                            {
                                "action": "c2pa.created",
                                "digitalSourceType": "http://cv.iptc.org/newscodes/digitalsourcetype/digitalCreation"
                            }
                        ]
                    }
                }
            ]
        }
        builder = Builder.from_json(initial_manifest_definition)

        action_json = '{"action": "c2pa.color_adjustments", "parameters": {"name": "brightnesscontrast"}}'
        builder.add_action(action_json)

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

            # Verify assertions object exists in active manifest
            self.assertIn("assertions", active_manifest)
            assertions = active_manifest["assertions"]

            # Find the c2pa.actions.v2 assertion to check what we added
            actions_assertion = None
            for assertion in assertions:
                if assertion.get("label") == "c2pa.actions.v2":
                    actions_assertion = assertion
                    break

            self.assertIsNotNone(actions_assertion)
            self.assertIn("data", actions_assertion)
            assertion_data = actions_assertion["data"]
            # Verify the manifest now contains actions
            self.assertIn("actions", assertion_data)
            actions = assertion_data["actions"]
            # Verify "c2pa.color_adjustments" action exists anywhere in the actions array
            created_action_found = False
            for action in actions:
                if action.get("action") == "c2pa.color_adjustments":
                    created_action_found = True
                    break

            self.assertTrue(created_action_found)

            # Verify "c2pa.created" action exists only once in the actions array
            created_count = 0
            for action in actions:
                if action.get("action") == "c2pa.created":
                    created_count += 1

            self.assertEqual(created_count, 1, "c2pa.created action should appear exactly once")

        builder.close()

        # Reset settings to default
        load_settings('{"builder":{"actions":{"auto_placed_action":{"enabled":true},"auto_opened_action":{"enabled":true},"auto_created_action":{"enabled":true,"source_type":"http://cv.iptc.org/newscodes/digitalsourcetype/digitalCreation"}}}}')

    def test_builder_minimal_manifest_add_actions_and_sign_no_auto_add(self):
        # For testing, remove auto-added actions
        load_settings('{"builder":{"actions":{"auto_placed_action":{"enabled":false},"auto_opened_action":{"enabled":false},"auto_created_action":{"enabled":false}}}}')

        initial_manifest_definition = {
            "claim_generator": "python_test",
            "claim_generator_info": [{
                "name": "python_test",
                "version": "0.0.1",
            }],
            "format": "image/jpeg",
            "title": "Python Test Image V2",
        }

        builder = Builder.from_json(initial_manifest_definition)
        builder.add_action('{ "action": "c2pa.created", "digitalSourceType": "http://cv.iptc.org/newscodes/digitalsourcetype/digitalCreation"}')

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

            # Verify assertions object exists in active manifest
            self.assertIn("assertions", active_manifest)
            assertions = active_manifest["assertions"]

            # Find the c2pa.actions.v2 assertion to look for what we added
            actions_assertion = None
            for assertion in assertions:
                if assertion.get("label") == "c2pa.actions.v2":
                    actions_assertion = assertion
                    break

            self.assertIsNotNone(actions_assertion)
            self.assertIn("data", actions_assertion)
            assertion_data = actions_assertion["data"]
            # Verify the manifest now contains actions
            self.assertIn("actions", assertion_data)
            actions = assertion_data["actions"]
            # Verify "c2pa.created" action exists anywhere in the actions array
            created_action_found = False
            for action in actions:
                if action.get("action") == "c2pa.created":
                    created_action_found = True
                    break

            self.assertTrue(created_action_found)

        builder.close()

        # Reset settings
        load_settings('{"builder":{"actions":{"auto_placed_action":{"enabled":true},"auto_opened_action":{"enabled":true},"auto_created_action":{"enabled":true,"source_type":"http://cv.iptc.org/newscodes/digitalsourcetype/digitalCreation"}}}}')

    def test_builder_minimal_manifest_add_actions_and_sign_with_auto_add(self):
        # For testing, remove auto-added actions
        load_settings('{"builder":{"actions":{"auto_placed_action":{"enabled":true},"auto_opened_action":{"enabled":true},"auto_created_action":{"enabled":true,"source_type":"http://cv.iptc.org/newscodes/digitalsourcetype/digitalCreation"}}}}')

        initial_manifest_definition = {
            "claim_generator_info": [{
                "name": "python_test",
                "version": "0.0.1",
            }],
            "format": "image/jpeg",
            "title": "Python Test Image V2",
        }

        builder = Builder.from_json(initial_manifest_definition)
        action_json = '{"action": "c2pa.color_adjustments", "parameters": {"name": "brightnesscontrast"}}'
        builder.add_action(action_json)

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

            # Verify assertions object exists in active manifest
            self.assertIn("assertions", active_manifest)
            assertions = active_manifest["assertions"]

            # Find the c2pa.actions.v2 assertion to look for what we added
            actions_assertion = None
            for assertion in assertions:
                if assertion.get("label") == "c2pa.actions.v2":
                    actions_assertion = assertion
                    break

            self.assertIsNotNone(actions_assertion)
            self.assertIn("data", actions_assertion)
            assertion_data = actions_assertion["data"]
            # Verify the manifest now contains actions
            self.assertIn("actions", assertion_data)
            actions = assertion_data["actions"]
            # Verify "c2pa.created" action exists anywhere in the actions array
            created_action_found = False
            for action in actions:
                if action.get("action") == "c2pa.created":
                    created_action_found = True
                    break

            self.assertTrue(created_action_found)

            # Verify "c2pa.color_adjustments" action also exists in the same actions array
            color_adjustments_found = False
            for action in actions:
                if action.get("action") == "c2pa.color_adjustments":
                    color_adjustments_found = True
                    break

            self.assertTrue(color_adjustments_found)

        builder.close()

        # Reset settings
        load_settings('{"builder":{"actions":{"auto_placed_action":{"enabled":true},"auto_opened_action":{"enabled":true},"auto_created_action":{"enabled":true,"source_type":"http://cv.iptc.org/newscodes/digitalsourcetype/digitalCreation"}}}}')

    def test_builder_sign_dicts_no_auto_add(self):
        # For testing, remove auto-added actions
        load_settings('{"builder":{"actions":{"auto_placed_action":{"enabled":false},"auto_opened_action":{"enabled":false},"auto_created_action":{"enabled":false}}}}')

        initial_manifest_definition = {
            "claim_generator_info": [{
                "name": "python_test",
                "version": "0.0.1",
            }],
            # claim version 2 is the default
            # "claim_version": 2,
            "format": "image/jpeg",
            "title": "Python Test Image V2",
            "assertions": [
                {
                    "label": "c2pa.actions",
                    "data": {
                        "actions": [
                            {
                                "action": "c2pa.created",
                                "digitalSourceType": "http://cv.iptc.org/newscodes/digitalsourcetype/digitalCreation"
                            }
                        ]
                    }
                }
            ]
        }
        builder = Builder.from_json(initial_manifest_definition)

        # Using a dictionary instead of a JSON string
        action_dict = {"action": "c2pa.color_adjustments", "parameters": {"name": "brightnesscontrast"}}
        builder.add_action(action_dict)

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

            # Verify assertions object exists in active manifest
            self.assertIn("assertions", active_manifest)
            assertions = active_manifest["assertions"]

            # Find the c2pa.actions.v2 assertion to check what we added
            actions_assertion = None
            for assertion in assertions:
                if assertion.get("label") == "c2pa.actions.v2":
                    actions_assertion = assertion
                    break

            self.assertIsNotNone(actions_assertion)
            self.assertIn("data", actions_assertion)
            assertion_data = actions_assertion["data"]
            # Verify the manifest now contains actions
            self.assertIn("actions", assertion_data)
            actions = assertion_data["actions"]
            # Verify "c2pa.color_adjustments" action exists anywhere in the actions array
            created_action_found = False
            for action in actions:
                if action.get("action") == "c2pa.color_adjustments":
                    created_action_found = True
                    break

            self.assertTrue(created_action_found)

        builder.close()

        # Reset settings
        load_settings('{"builder":{"actions":{"auto_placed_action":{"enabled":true},"auto_opened_action":{"enabled":true},"auto_created_action":{"enabled":true,"source_type":"http://cv.iptc.org/newscodes/digitalsourcetype/digitalCreation"}}}}')

    def test_builder_opened_action_one_ingredient_no_auto_add(self):
        """Test Builder with c2pa.opened action and one ingredient, following Adobe provenance patterns"""
        # Disable auto-added actions
        load_settings('{"builder":{"actions":{"auto_placed_action":{"enabled":false},"auto_opened_action":{"enabled":false},"auto_created_action":{"enabled":false}}}}')

        # Instance IDs for linking ingredients and actions
        # This can be any unique id so the ingredient can be uniquely identified and linked to the action
        parent_ingredient_id = "xmp:iid:a965983b-36fb-445a-aa80-a2d911dcc53c"

        manifestDefinition = {
            "claim_generator_info": [{
                "name": "Python CAI test",
                "version": "3.14.16"
            }],
            "title": "A title for the provenance test",
            "ingredients": [
                # The parent ingredient will be added through add_ingredient
                # And a properly crafted manifest json so they link
            ],
            "assertions": [
                {
                    "label": "c2pa.actions.v2",
                    "data": {
                        "actions": [
                            {
                                "action": "c2pa.opened",
                                "softwareAgent": {
                                    "name": "Opened asset",
                                },
                                "parameters": {
                                    "ingredientIds": [
                                        parent_ingredient_id
                                    ]
                                },
                                "digitalSourceType": "http://cv.iptc.org/newscodes/digitalsourcetype/compositeWithTrainedAlgorithmicMedia"
                            }
                        ]
                    }
                }
            ]
        }

        # The ingredient json for the opened action needs to match the instance_id in the manifestDefinition
        # Aka the unique parent_ingredient_id we rely on for linking
        ingredient_json = {
            "relationship": "parentOf",
            "instance_id": parent_ingredient_id
        }
        # An opened ingredient is always a parent, and there can only be exactly one parent ingredient

        # Read the input file (A.jpg will be signed)
        with open(self.testPath2, "rb") as test_file:
            file_content = test_file.read()

        builder = Builder.from_json(manifestDefinition)

        # Add C.jpg as the parent "opened" ingredient
        with open(self.testPath, 'rb') as f:
            builder.add_ingredient(ingredient_json, "image/jpeg", f)

            output_buffer = io.BytesIO(bytearray())
            builder.sign(
                self.signer,
                "image/jpeg",
                io.BytesIO(file_content),
                output_buffer)
            output_buffer.seek(0)

            # Read and verify the manifest
            reader = Reader("image/jpeg", output_buffer)
            json_data = reader.json()
            manifest_data = json.loads(json_data)

            # Verify the ingredient instance ID is present
            self.assertIn(parent_ingredient_id, json_data)

            # Verify c2pa.opened action is present
            self.assertIn("c2pa.opened", json_data)

        builder.close()

        # Make sure settings are put back to the common test defaults
        load_settings('{"builder":{"actions":{"auto_placed_action":{"enabled":false},"auto_opened_action":{"enabled":false},"auto_created_action":{"enabled":false}}}}')

    def test_builder_one_opened_one_placed_action_no_auto_add(self):
        """Test Builder with c2pa.opened action where asset is its own parent ingredient"""
        # Disable auto-added actions
        load_settings('{"builder":{"actions":{"auto_placed_action":{"enabled":false},"auto_opened_action":{"enabled":false},"auto_created_action":{"enabled":false}}}}')

        # Instance IDs for linking ingredients and actions,
        # need to be unique even if the same binary file is used, so ingredients link properly to actions
        parent_ingredient_id = "xmp:iid:a965983b-36fb-445a-aa80-a2d911dcc53c"
        placed_ingredient_id = "xmp:iid:a965983b-36fb-445a-aa80-f3f800ebe42b"

        manifestDefinition = {
            "claim_generator_info": [{
                "name": "Python CAI test",
                "version": "0.2.942"
            }],
            "title": "A title for the provenance test",
            "ingredients": [
                # The parent ingredient will be added through add_ingredient
                {
                    # Represents the bubbled up AI asset/ingredient
                    "format": "jpeg",
                    "relationship": "componentOf",
                    # Instance ID must be generated to match what is in parameters ingredientIds array
                    "instance_id": placed_ingredient_id,
                }
            ],
            "assertions": [
                {
                    "label": "c2pa.actions.v2",
                    "data": {
                        "actions": [
                            {
                                "action": "c2pa.opened",
                                "softwareAgent": {
                                    "name": "Opened asset",
                                },
                                "parameters": {
                                    "ingredientIds": [
                                        parent_ingredient_id
                                    ]
                                },
                                "digitalSourceType": "http://cv.iptc.org/newscodes/digitalsourcetype/compositeWithTrainedAlgorithmicMedia"
                            },
                            {
                                "action": "c2pa.placed",
                                "softwareAgent": {
                                    "name": "Placed asset",
                                },
                                "parameters": {
                                    "ingredientIds": [
                                        placed_ingredient_id
                                    ]
                                },
                                "digitalSourceType": "http://cv.iptc.org/newscodes/digitalsourcetype/compositeWithTrainedAlgorithmicMedia"
                            }
                        ]
                    }
                }
            ]
        }

        # The ingredient json for the opened action needs to match the instance_id in the manifestDefinition for c2pa.opened
        # So that ingredients can link together.
        ingredient_json = {
            "relationship": "parentOf",
            "when": "2025-08-07T18:01:55.934Z",
            "instance_id": parent_ingredient_id
        }

        # Read the input file (A.jpg will be signed)
        with open(self.testPath2, "rb") as test_file:
            file_content = test_file.read()

        builder = Builder.from_json(manifestDefinition)

        # An asset can be its own parent ingredient!
        # We add A.jpg as its own parent ingredient
        with open(self.testPath2, 'rb') as f:
            builder.add_ingredient(ingredient_json, "image/jpeg", f)

            output_buffer = io.BytesIO(bytearray())
            builder.sign(
                self.signer,
                "image/jpeg",
                io.BytesIO(file_content),
                output_buffer)
            output_buffer.seek(0)

            # Read and verify the manifest
            reader = Reader("image/jpeg", output_buffer)
            json_data = reader.json()
            manifest_data = json.loads(json_data)

            # Verify both ingredient instance IDs are present
            self.assertIn(parent_ingredient_id, json_data)
            self.assertIn(placed_ingredient_id, json_data)

            # Verify both actions are present
            self.assertIn("c2pa.opened", json_data)
            self.assertIn("c2pa.placed", json_data)

        builder.close()

        # Make sure settings are put back to the common test defaults
        load_settings('{"builder":{"actions":{"auto_placed_action":{"enabled":false},"auto_opened_action":{"enabled":false},"auto_created_action":{"enabled":false}}}}')

    def test_builder_opened_action_multiple_ingredient_no_auto_add(self):
        """Test Builder with c2pa.opened and c2pa.placed actions with multiple ingredients"""
        # Disable auto-added actions, as what we are doing here can confuse auto-placements
        load_settings('{"builder":{"actions":{"auto_placed_action":{"enabled":false},"auto_opened_action":{"enabled":false},"auto_created_action":{"enabled":false}}}}')

        # Instance IDs for linking ingredients and actions
        # With multiple ingredients, we need multiple different unique ids so they each link properly
        parent_ingredient_id = "xmp:iid:a965983b-36fb-445a-aa80-a2d911dcc53c"
        placed_ingredient_1_id = "xmp:iid:a965983b-36fb-445a-aa80-f3f800ebe42b"
        placed_ingredient_2_id = "xmp:iid:a965983b-36fb-445a-aa80-f2d712acd14c"

        manifestDefinition = {
            "claim_generator_info": [{
                "name": "Python CAI test",
                "version": "0.2.942"
            }],
            "title": "A title for the provenance test with multiple ingredients",
            "ingredients": [
                # More ingredients will be added using add_ingredient
                {
                    "format": "jpeg",
                    "relationship": "componentOf",
                    # Instance ID must be generated to match what is in parameters ingredientIds array
                    "instance_id": placed_ingredient_1_id,
                }
            ],
            "assertions": [
                {
                    "label": "c2pa.actions.v2",
                    "data": {
                        "actions": [
                            {
                                "action": "c2pa.opened",
                                "softwareAgent": {
                                    "name": "A parent opened asset",
                                },
                                "parameters": {
                                    "ingredientIds": [
                                        parent_ingredient_id
                                    ]
                                },
                                "digitalSourceType": "http://cv.iptc.org/newscodes/digitalsourcetype/compositeWithTrainedAlgorithmicMedia"
                            },
                            {
                                "action": "c2pa.placed",
                                "softwareAgent": {
                                    "name": "Component placed assets",
                                },
                                "parameters": {
                                    "ingredientIds": [
                                        placed_ingredient_1_id,
                                        placed_ingredient_2_id
                                    ]
                                },
                                "digitalSourceType": "http://cv.iptc.org/newscodes/digitalsourcetype/compositeWithTrainedAlgorithmicMedia"
                            }
                        ]
                    }
                }
            ]
        }

        # The ingredient json for the opened action needs to match the instance_id in the manifestDefinition,
        # so that ingredients properly link with their action
        ingredient_json_parent = {
            "relationship": "parentOf",
            "instance_id": parent_ingredient_id
        }

        # The ingredient json for the placed action needs to match the instance_id in the manifestDefinition,
        # so that ingredients properly link with their action
        ingredient_json_placed = {
            "relationship": "componentOf",
            "instance_id": placed_ingredient_2_id
        }

        # Read the input file (A.jpg will be signed)
        with open(self.testPath2, "rb") as test_file:
            file_content = test_file.read()

        builder = Builder.from_json(manifestDefinition)

        # Add C.jpg as the parent ingredient (for c2pa.opened, it's the opened asset)
        with open(self.testPath, 'rb') as f1:
            builder.add_ingredient(ingredient_json_parent, "image/jpeg", f1)

            # Add cloud.jpg as another placed ingredient (for instance, added on the opened asset)
            with open(self.testPath4, 'rb') as f2:
                builder.add_ingredient(ingredient_json_placed, "image/jpeg", f2)

                output_buffer = io.BytesIO(bytearray())
                builder.sign(
                    self.signer,
                    "image/jpeg",
                    io.BytesIO(file_content),
                    output_buffer)
                output_buffer.seek(0)

                # Read and verify the manifest
                reader = Reader("image/jpeg", output_buffer)
                json_data = reader.json()
                manifest_data = json.loads(json_data)

                # Verify all ingredient instance IDs are present
                self.assertIn(parent_ingredient_id, json_data)
                self.assertIn(placed_ingredient_1_id, json_data)
                self.assertIn(placed_ingredient_2_id, json_data)

                # Verify both actions are present
                self.assertIn("c2pa.opened", json_data)
                self.assertIn("c2pa.placed", json_data)

        builder.close()

        # Make sure settings are put back to the common test defaults
        load_settings('{"builder":{"actions":{"auto_placed_action":{"enabled":false},"auto_opened_action":{"enabled":false},"auto_created_action":{"enabled":false}}}}')

    def test_link_archive_label_on_signing_builder_placed(self):
        """Label set on the signing builder's add_ingredient links an
        ingredient archive to a c2pa.placed action."""
        load_settings('{"builder":{"actions":{"auto_placed_action":{"enabled":false},"auto_opened_action":{"enabled":false},"auto_created_action":{"enabled":false}}}}')

        archive = self._create_ingredient_archive()

        manifest = {
            "claim_generator_info": [{"name": "c2pa-test", "version": "1.0"}],
            "assertions": [
                {
                    "label": "c2pa.actions.v2",
                    "data": {
                        "actions": [
                            {
                                "action": "c2pa.created",
                                "digitalSourceType": "http://c2pa.org/digitalsourcetype/empty",
                            },
                            {
                                "action": "c2pa.placed",
                                "parameters": {
                                    "ingredientIds": ["my-ingredient"]
                                },
                            }
                        ]
                    },
                }
            ],
        }

        builder = Builder.from_json(manifest)
        builder.add_ingredient(
            {"title": "photo.jpg", "relationship": "componentOf", "label": "my-ingredient"},
            "application/c2pa",
            archive,
        )

        with open(self.testPath, "rb") as src:
            output = io.BytesIO()
            builder.sign(self.signer, "image/jpeg", src, output)
            output.seek(0)

            reader = Reader("image/jpeg", output)
            manifest_data = json.loads(reader.json())
            active = manifest_data["active_manifest"]
            assertions = manifest_data["manifests"][active]["assertions"]

            placed_action = None
            for assertion in assertions:
                if assertion.get("label") == "c2pa.actions.v2":
                    for action in assertion["data"]["actions"]:
                        if action["action"] == "c2pa.placed":
                            placed_action = action
                            break

            self.assertIsNotNone(placed_action, "c2pa.placed action not found")
            self.assertIn("parameters", placed_action)
            self.assertIn("ingredients", placed_action["parameters"])
            self.assertEqual(len(placed_action["parameters"]["ingredients"]), 1)
            self.assertIn(
                "c2pa.ingredient.v3",
                placed_action["parameters"]["ingredients"][0]["url"],
            )

            reader.close()
            output.close()
        archive.close()
        builder.close()

        load_settings('{"builder":{"actions":{"auto_placed_action":{"enabled":false},"auto_opened_action":{"enabled":false},"auto_created_action":{"enabled":false}}}}')

    def test_link_archive_label_on_signing_builder_opened(self):
        """Label set on the signing builder's add_ingredient links an
        ingredient archive to a c2pa.opened action."""
        load_settings('{"builder":{"actions":{"auto_placed_action":{"enabled":false},"auto_opened_action":{"enabled":false},"auto_created_action":{"enabled":false}}}}')

        archive = self._create_ingredient_archive(
            {"title": "photo.jpg", "relationship": "parentOf"}
        )

        manifest = {
            "claim_generator_info": [{"name": "c2pa-test", "version": "1.0"}],
            "assertions": [
                {
                    "label": "c2pa.actions.v2",
                    "data": {
                        "actions": [
                            {
                                "action": "c2pa.opened",
                                "digitalSourceType": "http://cv.iptc.org/newscodes/digitalsourcetype/digitalCreation",
                                "parameters": {
                                    "ingredientIds": ["my-ingredient"]
                                },
                            }
                        ]
                    },
                }
            ],
        }

        builder = Builder.from_json(manifest)
        builder.add_ingredient(
            {"title": "photo.jpg", "relationship": "parentOf", "label": "my-ingredient"},
            "application/c2pa",
            archive,
        )

        with open(self.testPath, "rb") as src:
            output = io.BytesIO()
            builder.sign(self.signer, "image/jpeg", src, output)
            output.seek(0)

            reader = Reader("image/jpeg", output)
            manifest_data = json.loads(reader.json())
            active = manifest_data["active_manifest"]
            assertions = manifest_data["manifests"][active]["assertions"]

            opened_action = None
            for assertion in assertions:
                if assertion.get("label") == "c2pa.actions.v2":
                    for action in assertion["data"]["actions"]:
                        if action["action"] == "c2pa.opened":
                            opened_action = action
                            break

            self.assertIsNotNone(opened_action, "c2pa.opened action not found")
            self.assertIn("parameters", opened_action)
            self.assertIn("ingredients", opened_action["parameters"])
            self.assertEqual(len(opened_action["parameters"]["ingredients"]), 1)
            self.assertIn(
                "c2pa.ingredient.v3",
                opened_action["parameters"]["ingredients"][0]["url"],
            )

            reader.close()
            output.close()
        archive.close()
        builder.close()

        load_settings('{"builder":{"actions":{"auto_placed_action":{"enabled":false},"auto_opened_action":{"enabled":false},"auto_created_action":{"enabled":false}}}}')

    def test_link_archive_two_ingredients_labels(self):
        """Two ingredient archives linked to two different actions via
        distinct labels. Verifies no cross-linking."""
        load_settings('{"builder":{"actions":{"auto_placed_action":{"enabled":false},"auto_opened_action":{"enabled":false},"auto_created_action":{"enabled":false}}}}')

        archive1 = self._create_ingredient_archive(
            {"title": "photo-placed.jpg", "relationship": "componentOf"}
        )
        archive2 = self._create_ingredient_archive(
            {"title": "photo-opened.jpg", "relationship": "parentOf"}
        )

        manifest = {
            "claim_generator_info": [{"name": "c2pa-test", "version": "1.0"}],
            "assertions": [
                {
                    "label": "c2pa.actions.v2",
                    "data": {
                        "actions": [
                            {
                                "action": "c2pa.opened",
                                "digitalSourceType": "http://cv.iptc.org/newscodes/digitalsourcetype/digitalCreation",
                                "parameters": {
                                    "ingredientIds": ["ingredient-for-opened"]
                                },
                            },
                            {
                                "action": "c2pa.placed",
                                "parameters": {
                                    "ingredientIds": ["ingredient-for-placed"]
                                },
                            },
                        ]
                    },
                }
            ],
        }

        builder = Builder.from_json(manifest)
        builder.add_ingredient(
            {"title": "photo-placed.jpg", "relationship": "componentOf", "label": "ingredient-for-placed"},
            "application/c2pa",
            archive1,
        )
        builder.add_ingredient(
            {"title": "photo-opened.jpg", "relationship": "parentOf", "label": "ingredient-for-opened"},
            "application/c2pa",
            archive2,
        )

        with open(self.testPath, "rb") as src:
            output = io.BytesIO()
            builder.sign(self.signer, "image/jpeg", src, output)
            output.seek(0)

            reader = Reader("image/jpeg", output)
            manifest_data = json.loads(reader.json())
            active = manifest_data["active_manifest"]
            assertions = manifest_data["manifests"][active]["assertions"]

            placed_action = None
            opened_action = None
            for assertion in assertions:
                if assertion.get("label") == "c2pa.actions.v2":
                    for action in assertion["data"]["actions"]:
                        if action["action"] == "c2pa.placed":
                            placed_action = action
                        if action["action"] == "c2pa.opened":
                            opened_action = action

            self.assertIsNotNone(placed_action, "c2pa.placed action not found")
            self.assertIsNotNone(opened_action, "c2pa.opened action not found")

            self.assertIn("ingredients", placed_action["parameters"])
            self.assertEqual(len(placed_action["parameters"]["ingredients"]), 1)
            placed_url = placed_action["parameters"]["ingredients"][0]["url"]

            self.assertIn("ingredients", opened_action["parameters"])
            self.assertEqual(len(opened_action["parameters"]["ingredients"]), 1)
            opened_url = opened_action["parameters"]["ingredients"][0]["url"]

            # Each action should link to a different ingredient (no cross-linking)
            self.assertNotEqual(placed_url, opened_url,
                "Each action should link to a different ingredient")

            reader.close()
            output.close()
        archive1.close()
        archive2.close()
        builder.close()

        load_settings('{"builder":{"actions":{"auto_placed_action":{"enabled":false},"auto_opened_action":{"enabled":false},"auto_created_action":{"enabled":false}}}}')

    def test_link_archive_multiple_ingredients_in_one_placed_action(self):
        """A single c2pa.placed action references two componentOf ingredients
        via ingredientIds with two labels."""
        load_settings('{"builder":{"actions":{"auto_placed_action":{"enabled":false},"auto_opened_action":{"enabled":false},"auto_created_action":{"enabled":false}}}}')

        archive1 = self._create_ingredient_archive(
            {"title": "base-layer.jpg", "relationship": "componentOf"}
        )
        archive2 = self._create_ingredient_archive(
            {"title": "overlay-layer.jpg", "relationship": "componentOf"}
        )

        manifest = {
            "claim_generator_info": [{"name": "c2pa-test", "version": "1.0"}],
            "assertions": [
                {
                    "label": "c2pa.actions.v2",
                    "data": {
                        "actions": [
                            {
                                "action": "c2pa.created",
                                "digitalSourceType": "http://c2pa.org/digitalsourcetype/empty",
                            },
                            {
                                "action": "c2pa.placed",
                                "parameters": {
                                    "ingredientIds": ["base-layer", "overlay-layer"]
                                },
                            }
                        ]
                    },
                }
            ],
        }

        builder = Builder.from_json(manifest)
        builder.add_ingredient(
            {"title": "base-layer.jpg", "relationship": "componentOf", "label": "base-layer"},
            "application/c2pa",
            archive1,
        )
        builder.add_ingredient(
            {"title": "overlay-layer.jpg", "relationship": "componentOf", "label": "overlay-layer"},
            "application/c2pa",
            archive2,
        )

        with open(self.testPath, "rb") as src:
            output = io.BytesIO()
            builder.sign(self.signer, "image/jpeg", src, output)
            output.seek(0)

            reader = Reader("image/jpeg", output)
            manifest_data = json.loads(reader.json())
            active = manifest_data["active_manifest"]
            assertions = manifest_data["manifests"][active]["assertions"]

            placed_action = None
            for assertion in assertions:
                if assertion.get("label") == "c2pa.actions.v2":
                    for action in assertion["data"]["actions"]:
                        if action["action"] == "c2pa.placed":
                            placed_action = action
                            break

            self.assertIsNotNone(placed_action, "c2pa.placed action not found")
            self.assertIn("parameters", placed_action)
            self.assertIn("ingredients", placed_action["parameters"])
            ingredients = placed_action["parameters"]["ingredients"]
            self.assertEqual(len(ingredients), 2,
                "c2pa.placed should reference both ingredients")

            url0 = ingredients[0]["url"]
            url1 = ingredients[1]["url"]
            self.assertNotEqual(url0, url1,
                "Each ingredient should have a distinct URL")

            reader.close()
            output.close()
        archive1.close()
        archive2.close()
        builder.close()

        load_settings('{"builder":{"actions":{"auto_placed_action":{"enabled":false},"auto_opened_action":{"enabled":false},"auto_created_action":{"enabled":false}}}}')

    def test_ingredient_fields_survive_archive(self):
        archive = self._create_ingredient_archive({
            "title": "tracked-asset.jpg",
            "relationship": "componentOf",
            "instance_id": "tracking:project-7:asset-42",
            "description": "A tracked ingredient",
            "informational_URI": "https://example.com/assets/42",
        })

        reader = Reader("application/c2pa", archive)
        manifest_data = json.loads(reader.json())
        active = manifest_data["active_manifest"]
        ingredients = manifest_data["manifests"][active]["ingredients"]

        self.assertGreaterEqual(len(ingredients), 1)
        ing = ingredients[0]

        self.assertEqual(ing["title"], "tracked-asset.jpg")
        self.assertIn("instance_id", ing)
        self.assertEqual(ing["instance_id"], "tracking:project-7:asset-42")

        reader.close()
        archive.close()

    def test_ingredient_fields_survive_archive_then_sign(self):
        """instance_id set on the archive ingredient persists through
        archive then sign."""
        archive = self._create_ingredient_archive({
            "title": "tracked-asset.jpg",
            "relationship": "componentOf",
            "instance_id": "tracking:project-7:asset-42",
            "description": "A tracked ingredient",
            "informational_URI": "https://example.com/assets/42",
        })

        manifest = {
            "claim_generator_info": [{"name": "c2pa-test", "version": "1.0"}],
            "assertions": [
                {
                    "label": "c2pa.actions",
                    "data": {
                        "actions": [
                            {
                                "action": "c2pa.created",
                                "digitalSourceType": "http://cv.iptc.org/newscodes/digitalsourcetype/digitalCreation",
                            }
                        ]
                    },
                }
            ],
        }

        builder = Builder.from_json(manifest)
        builder.add_ingredient(
            {"title": "tracked-asset.jpg", "relationship": "componentOf"},
            "application/c2pa",
            archive,
        )

        with open(self.testPath, "rb") as src:
            output = io.BytesIO()
            builder.sign(self.signer, "image/jpeg", src, output)
            output.seek(0)

            reader = Reader("image/jpeg", output)
            manifest_data = json.loads(reader.json())
            active = manifest_data["active_manifest"]
            ingredients = manifest_data["manifests"][active]["ingredients"]

            self.assertGreaterEqual(len(ingredients), 1)
            ing = ingredients[0]

            self.assertIn("instance_id", ing)
            self.assertEqual(ing["instance_id"], "tracking:project-7:asset-42")

            reader.close()
            output.close()
        archive.close()
        builder.close()

    def test_instance_id_as_ingredient_identifier_in_catalog(self):
        """Two ingredients with different instance_id values in one archive.
        Read the archive back and select an ingredient by instance_id."""
        manifest = {
            "claim_generator_info": [{"name": "c2pa-test", "version": "1.0"}],
            "assertions": [
                {
                    "label": "c2pa.actions",
                    "data": {
                        "actions": [
                            {
                                "action": "c2pa.created",
                                "digitalSourceType": "http://cv.iptc.org/newscodes/digitalsourcetype/digitalCreation",
                            }
                        ]
                    },
                }
            ],
        }

        builder = Builder.from_json(manifest)
        with open(self.testPath, "rb") as f:
            builder.add_ingredient(
                {"title": "photo-A.jpg", "relationship": "componentOf",
                 "instance_id": "catalog:photo-A"},
                "image/jpeg", f,
            )
        with open(self.testPath, "rb") as f:
            builder.add_ingredient(
                {"title": "photo-B.jpg", "relationship": "componentOf",
                 "instance_id": "catalog:photo-B"},
                "image/jpeg", f,
            )

        archive = io.BytesIO()
        builder.to_archive(archive)
        archive.seek(0)
        builder.close()

        reader = Reader("application/c2pa", archive)
        manifest_data = json.loads(reader.json())
        active = manifest_data["active_manifest"]
        ingredients = manifest_data["manifests"][active]["ingredients"]

        self.assertEqual(len(ingredients), 2)

        found = None
        for ing in ingredients:
            if ing.get("instance_id") == "catalog:photo-B":
                found = ing
                break

        self.assertIsNotNone(found,
            "Should find ingredient by instance_id 'catalog:photo-B' in archive")
        self.assertEqual(found["title"], "photo-B.jpg")

        reader.close()
        archive.close()
