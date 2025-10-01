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
import ctypes
import warnings
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.backends import default_backend
import tempfile
import shutil
import ctypes

# Suppress deprecation warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)

from c2pa import Builder, C2paError as Error, Reader, C2paSigningAlg as SigningAlg, C2paSignerInfo, Signer, sdk_version
from c2pa.c2pa import Stream, read_ingredient_file, read_file, sign_file, load_settings, create_signer, create_signer_from_info, ed25519_sign, format_embeddable

PROJECT_PATH = os.getcwd()
FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
DEFAULT_TEST_FILE_NAME = "C.jpg"
INGREDIENT_TEST_FILE_NAME = "A.jpg"
DEFAULT_TEST_FILE = os.path.join(FIXTURES_DIR, DEFAULT_TEST_FILE_NAME)
INGREDIENT_TEST_FILE = os.path.join(FIXTURES_DIR, INGREDIENT_TEST_FILE_NAME)
ALTERNATIVE_INGREDIENT_TEST_FILE = os.path.join(FIXTURES_DIR, "cloud.jpg")

class TestC2paSdk(unittest.TestCase):
    def test_sdk_version(self):
        self.assertIn("0.65.1", sdk_version())


class TestReader(unittest.TestCase):
    def setUp(self):
        self.data_dir = FIXTURES_DIR
        self.testPath = DEFAULT_TEST_FILE

    def test_can_retrieve_reader_supported_mimetypes(self):
        result1 = Reader.get_supported_mime_types()
        self.assertTrue(len(result1) > 0)

        # Cache hit
        result2 = Reader.get_supported_mime_types()
        self.assertTrue(len(result2) > 0)

        self.assertEqual(result1, result2)

    def test_stream_read(self):
        with open(self.testPath, "rb") as file:
            reader = Reader("image/jpeg", file)
            json_data = reader.json()
            self.assertIn(DEFAULT_TEST_FILE_NAME, json_data)

    def test_reader_detects_unsupported_mimetype_on_stream(self):
        with open(self.testPath, "rb") as file:
            with self.assertRaises(Error.NotSupported):
              Reader("mimetype/does-not-exist", file)

    def test_stream_read_and_parse(self):
        with open(self.testPath, "rb") as file:
            reader = Reader("image/jpeg", file)
            manifest_store = json.loads(reader.json())
            title = manifest_store["manifests"][manifest_store["active_manifest"]]["title"]
            self.assertEqual(title, DEFAULT_TEST_FILE_NAME)

    def test_stream_read_string_stream(self):
        with Reader(self.testPath) as reader:
            json_data = reader.json()
            self.assertIn(DEFAULT_TEST_FILE_NAME, json_data)

    def test_stream_read_string_stream_mimetype_not_supported(self):
        with self.assertRaises(Error.NotSupported):
            # xyz is actually an extension that is recognized
            # as mimetype chemical/x-xyz
            Reader(os.path.join(FIXTURES_DIR, "C.xyz"))

    def test_stream_read_string_stream_mimetype_not_recognized(self):
        with self.assertRaises(Error.NotSupported):
            Reader(os.path.join(FIXTURES_DIR, "C.test"))

    def test_stream_read_string_stream(self):
        with Reader("image/jpeg", self.testPath) as reader:
            json_data = reader.json()
            self.assertIn(DEFAULT_TEST_FILE_NAME, json_data)

    def test_reader_detects_unsupported_mimetype_on_file(self):
        with self.assertRaises(Error.NotSupported):
            Reader("mimetype/does-not-exist", self.testPath)

    def test_stream_read_filepath_as_stream_and_parse(self):
        with Reader("image/jpeg", self.testPath) as reader:
            manifest_store = json.loads(reader.json())
            title = manifest_store["manifests"][manifest_store["active_manifest"]]["title"]
            self.assertEqual(title, DEFAULT_TEST_FILE_NAME)

    def test_reader_double_close(self):
        with open(self.testPath, "rb") as file:
            reader = Reader("image/jpeg", file)
            reader.close()
            # Second close should not raise an exception
            reader.close()
            # Verify reader is closed
            with self.assertRaises(Error):
                reader.json()

    def test_reader_streams_with_nested(self):
        with open(self.testPath, "rb") as file:
            with Reader("image/jpeg", file) as reader:
                manifest_store = json.loads(reader.json())
                title = manifest_store["manifests"][manifest_store["active_manifest"]]["title"]
                self.assertEqual(title, DEFAULT_TEST_FILE_NAME)

    def test_reader_close_cleanup(self):
        with open(self.testPath, "rb") as file:
            reader = Reader("image/jpeg", file)
            # Close the reader
            reader.close()
            # Verify all resources are cleaned up
            self.assertIsNone(reader._reader)
            self.assertIsNone(reader._own_stream)
            # Verify reader is marked as closed
            self.assertTrue(reader._closed)

    def test_resource_to_stream_on_closed_reader(self):
        """Test that resource_to_stream correctly raises error on closed."""
        reader = Reader("image/jpeg", self.testPath)
        reader.close()
        with self.assertRaises(Error):
            reader.resource_to_stream("", io.BytesIO(bytearray()))

    def test_read_dng_from_stream(self):
        test_path = os.path.join(self.data_dir, "C.dng")
        with open(test_path, "rb") as file:
            file_content = file.read()

        with Reader("dng", io.BytesIO(file_content)) as reader:
            # Just run and verify there is no crash
            json.loads(reader.json())

    def test_read_dng_upper_case_from_stream(self):
        test_path = os.path.join(self.data_dir, "C.dng")
        with open(test_path, "rb") as file:
            file_content = file.read()

        with Reader("DNG", io.BytesIO(file_content)) as reader:
            # Just run and verify there is no crash
            json.loads(reader.json())

    def test_read_dng_file_from_path(self):
        test_path = os.path.join(self.data_dir, "C.dng")

        # Create reader with the file content
        with Reader(test_path) as reader:
            # Just run and verify there is no crash
            json.loads(reader.json())

    def test_read_all_files(self):
        """Test reading C2PA metadata from all files in the fixtures/files-for-reading-tests directory"""
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
            '.wav': 'audio/wav',
            '.pdf': 'application/pdf',
        }

        # Skip system files
        skip_files = {
            '.DS_Store'
        }

        for filename in os.listdir(reading_dir):
            if filename in skip_files:
                continue

            file_path = os.path.join(reading_dir, filename)
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
                    reader = Reader(mime_type, file)
                    json_data = reader.json()
                    reader.close()
                    self.assertIsInstance(json_data, str)
                    # Verify the manifest contains expected fields
                    manifest = json.loads(json_data)
                    self.assertIn("manifests", manifest)
                    self.assertIn("active_manifest", manifest)
            except Exception as e:
                self.fail(f"Failed to read metadata from {filename}: {str(e)}")

    def test_read_all_files_using_extension(self):
        """Test reading C2PA metadata from files in the fixtures/files-for-reading-tests directory"""
        reading_dir = os.path.join(self.data_dir, "files-for-reading-tests")

        # Map of file extensions to MIME types
        extensions = {
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.png': 'image/png',
        }

        # Skip system files
        skip_files = {
            '.DS_Store'
        }

        for filename in os.listdir(reading_dir):
            if filename in skip_files:
                continue

            file_path = os.path.join(reading_dir, filename)
            if not os.path.isfile(file_path):
                continue

            # Get file extension and corresponding MIME type
            _, ext = os.path.splitext(filename)
            ext = ext.lower()
            if ext not in extensions:
                continue

            try:
                with open(file_path, "rb") as file:
                    # Remove the leading dot
                    parsed_extension = ext[1:]
                    reader = Reader(parsed_extension, file)
                    json_data = reader.json()
                    reader.close()
                    self.assertIsInstance(json_data, str)
                    # Verify the manifest contains expected fields
                    manifest = json.loads(json_data)
                    self.assertIn("manifests", manifest)
                    self.assertIn("active_manifest", manifest)
            except Exception as e:
                self.fail(f"Failed to read metadata from {filename}: {str(e)}")

    def test_reader_context_manager_with_exception(self):
        """Test Reader state after exception in context manager."""
        try:
            with Reader(self.testPath) as reader:
                # Inside context - should be valid
                self.assertFalse(reader._closed)
                self.assertTrue(reader._initialized)
                self.assertIsNotNone(reader._reader)
                self.assertIsNotNone(reader._own_stream)
                self.assertIsNotNone(reader._backing_file)
                raise ValueError("Test exception")
        except ValueError:
            pass

        # After exception - should still be closed
        self.assertTrue(reader._closed)
        self.assertFalse(reader._initialized)
        self.assertIsNone(reader._reader)
        self.assertIsNone(reader._own_stream)
        self.assertIsNone(reader._backing_file)

    def test_reader_partial_initialization_states(self):
        """Test Reader behavior with partial initialization failures."""
        # Test with _reader = None but _initialized = True
        reader = Reader.__new__(Reader)
        reader._closed = False
        reader._initialized = True
        reader._reader = None
        reader._own_stream = None
        reader._backing_file = None

        with self.assertRaises(Error):
            reader._ensure_valid_state()

    def test_reader_cleanup_state_transitions(self):
        """Test Reader state during cleanup operations."""
        reader = Reader(self.testPath)

        reader._cleanup_resources()
        self.assertTrue(reader._closed)
        self.assertFalse(reader._initialized)
        self.assertIsNone(reader._reader)
        self.assertIsNone(reader._own_stream)
        self.assertIsNone(reader._backing_file)

    def test_reader_cleanup_idempotency(self):
        """Test that cleanup operations are idempotent."""
        reader = Reader(self.testPath)

        # First cleanup
        reader._cleanup_resources()
        self.assertTrue(reader._closed)

        # Second cleanup should not change state
        reader._cleanup_resources()
        self.assertTrue(reader._closed)
        self.assertFalse(reader._initialized)
        self.assertIsNone(reader._reader)
        self.assertIsNone(reader._own_stream)
        self.assertIsNone(reader._backing_file)

    def test_reader_state_with_invalid_native_pointer(self):
        """Test Reader state handling with invalid native pointer."""
        reader = Reader(self.testPath)

        # Simulate invalid native pointer
        reader._reader = 0

        # Operations should fail gracefully
        with self.assertRaises(Error):
            reader.json()

    # TODO: Unskip once fixed configuration to read data is clarified
    # def test_read_cawg_data_file(self):
    #     """Test reading C2PA metadata from C_with_CAWG_data.jpg file."""
    #     file_path = os.path.join(self.data_dir, "C_with_CAWG_data.jpg")

    #     with open(file_path, "rb") as file:
    #         reader = Reader("image/jpeg", file)
    #         json_data = reader.json()
    #         self.assertIsInstance(json_data, str)

    #         # Parse the JSON and verify specific fields
    #         manifest_data = json.loads(json_data)

    #         # Verify basic manifest structure
    #         self.assertIn("manifests", manifest_data)
    #         self.assertIn("active_manifest", manifest_data)

    #         # Get the active manifest
    #         active_manifest_id = manifest_data["active_manifest"]
    #         active_manifest = manifest_data["manifests"][active_manifest_id]

    #         # Verify manifest is not null or empty
    #         assert active_manifest is not None, "Active manifest should not be null"
    #         assert len(active_manifest) > 0, "Active manifest should not be empty"


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
                                "action": "c2pa.opened"
                            }
                        ]
                    }
                }
            ]
        }

        # Define a V2 manifest as a dictionary
        self.manifestDefinitionV2 = {
            "claim_generator": "python_test",
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
            self.assertNotIn("validation_status", json_data)
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
            self.assertNotIn("validation_status", json_data)

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
                self.assertNotIn("validation_status", json_data)

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
                self.assertNotIn("validation_status", json_data)

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
            self.assertNotIn("validation_status", json_data)
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
            self.assertNotIn("validation_status", json_data)
            output.close()

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
            self.assertNotIn("validation_status", json_data)
            output.close()

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
            self.assertNotIn("validation_status", json_data)
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
            self.assertNotIn("validation_status", json_data)
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
            self.assertNotIn("validation_status", json_data)
            output.close()

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
            self.assertNotIn("validation_status", json_data)
            archive.close()
            output.close()

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
            self.assertNotIn("validation_status", json_data)
            archive.close()
            output.close()

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
                    self.assertNotIn("validation_status", manifest_data)

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
                    self.assertNotIn("validation_status", manifest_data)

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
                        self.assertNotIn("validation_status", json_data)
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
        assert builder._builder is not None

        # Test adding ingredient
        ingredient_json = '{"test": "ingredient"}'
        with open(self.testPath, 'rb') as f:
            builder.add_ingredient(ingredient_json, "image/jpeg", f)

        builder.close()

    def test_builder_add_multiple_ingredients(self):
        builder = Builder.from_json(self.manifestDefinition)
        assert builder._builder is not None

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
            builder.add_ingredient(ingredient_json, "image/png", f)

        builder.close()

    def test_builder_add_multiple_ingredients_and_resources(self):
        builder = Builder.from_json(self.manifestDefinition)
        assert builder._builder is not None

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
            builder.add_ingredient(ingredient_json, "image/png", f)

        builder.close()

    def test_builder_add_multiple_ingredients_and_resources_interleaved(self):
        builder = Builder.from_json(self.manifestDefinition)
        assert builder._builder is not None

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
            builder.add_ingredient(ingredient_json, "image/png", f)

        builder.close()

    def test_builder_sign_with_ingredient(self):
        builder = Builder.from_json(self.manifestDefinition)
        assert builder._builder is not None

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

    def test_builder_sign_with_setting_no_thumbnail_and_ingredient(self):
        builder = Builder.from_json(self.manifestDefinition)
        assert builder._builder is not None

        # The following removes the manifest's thumbnail
        load_settings('{"builder": { "thumbnail": {"enabled": false}}}')

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

    def test_builder_sign_with_duplicate_ingredient(self):
        builder = Builder.from_json(self.manifestDefinition)
        assert builder._builder is not None

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
        assert builder._builder is not None

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

    def test_builder_sign_with_multiple_ingredient(self):
        builder = Builder.from_json(self.manifestDefinition)
        assert builder._builder is not None

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
        assert builder._builder is not None

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
        builder = Builder.from_json(self.manifestDefinition)
        load_settings(r'{"verify": { "remote_manifest_fetch": false} }')
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
          self.assertNotIn("validation_status", json_data)
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
          self.assertNotIn("validation_status", json_data)
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
          self.assertNotIn("validation_status", json_data)
          output.close()

    def test_sign_file_tmn_wip(self):
        temp_dir = tempfile.mkdtemp()
        try:
            # Create a temporary output file path
            output_path = os.path.join(temp_dir, "signed_output.jpg")

            # Use the sign_file method
            builder = Builder(self.manifestDefinition)
            builder.sign_file(
                self.testPath,
                output_path,
                self.signer
            )

            # Verify the output file was created
            self.assertTrue(os.path.exists(output_path))

            # Read the signed file and verify the manifest
            with open(output_path, "rb") as file:
                reader = Reader("image/jpeg", file)
                json_data = reader.json()
                self.assertIn("Python Test", json_data)
                self.assertNotIn("validation_status", json_data)

        finally:
            # Clean up the temporary directory
            shutil.rmtree(temp_dir)

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
                self.assertNotIn("validation_status", json_data)

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
                self.assertNotIn("validation_status", json_data)

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
                self.assertNotIn("validation_status", json_data)

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
            self.assertNotIn("validation_status", json_data)
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
                    self.assertNotIn("validation_status", json_data)

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
                self.assertNotIn("validation_status", json_data)

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
                self.assertNotIn("validation_status", json_data)

            # Verify also signed file using manifest bytes
            with Reader("mov", output_path, manifest_bytes) as reader:
                json_data = reader.json()
                self.assertIn("Python Test", json_data)
                self.assertNotIn("validation_status", json_data)

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
                self.assertNotIn("validation_status", json_data)

            # Verify also signed file using manifest bytes
            with Reader("mov", output_path, manifest_bytes) as reader:
                json_data = reader.json()
                self.assertIn("Python Test", json_data)
                self.assertNotIn("validation_status", json_data)

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
                self._signer = None

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
                                "action": "c2pa.opened",
                                "description": "Opened with Unicode: test"
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

    def test_builder_state_transitions(self):
        """Test Builder state transitions during lifecycle."""
        builder = Builder(self.manifestDefinition)

        # Initial state
        self.assertFalse(builder._closed)
        self.assertTrue(builder._initialized)
        self.assertIsNotNone(builder._builder)

        # After close
        builder.close()
        self.assertTrue(builder._closed)
        self.assertFalse(builder._initialized)
        self.assertIsNone(builder._builder)

    def test_builder_context_manager_states(self):
        """Test Builder state management in context manager."""
        with Builder(self.manifestDefinition) as builder:
            # Inside context - should be valid
            self.assertFalse(builder._closed)
            self.assertTrue(builder._initialized)
            self.assertIsNotNone(builder._builder)

            # Placeholder operation
            builder.set_no_embed()

        # After context exit - should be closed
        self.assertTrue(builder._closed)
        self.assertFalse(builder._initialized)
        self.assertIsNone(builder._builder)

    def test_builder_context_manager_with_exception(self):
        """Test Builder state after exception in context manager."""
        try:
            with Builder(self.manifestDefinition) as builder:
                # Inside context - should be valid
                self.assertFalse(builder._closed)
                self.assertTrue(builder._initialized)
                self.assertIsNotNone(builder._builder)
                raise ValueError("Test exception")
        except ValueError:
            pass

        # After exception - should still be closed
        self.assertTrue(builder._closed)
        self.assertFalse(builder._initialized)
        self.assertIsNone(builder._builder)

    def test_builder_partial_initialization_states(self):
        """Test Builder behavior with partial initialization failures."""
        # Test with _builder = None but _initialized = True
        builder = Builder.__new__(Builder)
        builder._closed = False
        builder._initialized = True
        builder._builder = None

        with self.assertRaises(Error):
            builder._ensure_valid_state()

    def test_builder_cleanup_state_transitions(self):
        """Test Builder state during cleanup operations."""
        builder = Builder(self.manifestDefinition)

        # Test _cleanup_resources method
        builder._cleanup_resources()
        self.assertTrue(builder._closed)
        self.assertFalse(builder._initialized)
        self.assertIsNone(builder._builder)

    def test_builder_cleanup_idempotency(self):
        """Test that cleanup operations are idempotent."""
        builder = Builder(self.manifestDefinition)

        # First cleanup
        builder._cleanup_resources()
        self.assertTrue(builder._closed)

        # Second cleanup should not change state
        builder._cleanup_resources()
        self.assertTrue(builder._closed)
        self.assertFalse(builder._initialized)
        self.assertIsNone(builder._builder)

    def test_builder_state_after_sign_operations(self):
        """Test Builder state after signing operations."""
        builder = Builder(self.manifestDefinition)

        with open(self.testPath, "rb") as file:
            manifest_bytes = builder.sign(self.signer, "image/jpeg", file)

        # State should still be valid after signing
        self.assertFalse(builder._closed)
        self.assertTrue(builder._initialized)
        self.assertIsNotNone(builder._builder)

        # Should be able to sign again
        with open(self.testPath, "rb") as file:
            manifest_bytes2 = builder.sign(self.signer, "image/jpeg", file)

    def test_builder_state_after_archive_operations(self):
        """Test Builder state after archive operations."""
        builder = Builder(self.manifestDefinition)

        # Test to_archive
        with io.BytesIO() as archive_stream:
            builder.to_archive(archive_stream)

        # State should still be valid
        self.assertFalse(builder._closed)
        self.assertTrue(builder._initialized)
        self.assertIsNotNone(builder._builder)

    def test_builder_state_after_double_close(self):
        """Test Builder state after double close operations."""
        builder = Builder(self.manifestDefinition)

        # First close
        builder.close()
        self.assertTrue(builder._closed)
        self.assertFalse(builder._initialized)
        self.assertIsNone(builder._builder)

        # Second close should not change state
        builder.close()
        self.assertTrue(builder._closed)
        self.assertFalse(builder._initialized)
        self.assertIsNone(builder._builder)

    def test_builder_state_with_invalid_native_pointer(self):
        """Test Builder state handling with invalid native pointer."""
        builder = Builder(self.manifestDefinition)

        # Simulate invalid native pointer
        builder._builder = 0

        # Operations should fail gracefully
        with self.assertRaises(Error):
            builder.set_no_embed()


class TestStream(unittest.TestCase):
    def setUp(self):
        self.temp_file = io.BytesIO()
        self.test_data = b"Hello, World!"
        self.temp_file.write(self.test_data)
        self.temp_file.seek(0)

    def tearDown(self):
        self.temp_file.close()

    def test_stream_initialization(self):
        stream = Stream(self.temp_file)
        self.assertTrue(stream.initialized)
        self.assertFalse(stream.closed)
        stream.close()

    def test_stream_initialization_with_invalid_object(self):
        with self.assertRaises(TypeError):
            Stream("not a file-like object")

    def test_stream_read(self):
        stream = Stream(self.temp_file)
        try:
            # Create a buffer to read into
            buffer = (ctypes.c_ubyte * 13)()
            # Read the data
            bytes_read = stream._read_cb(None, buffer, 13)
            # Verify the data
            self.assertEqual(bytes_read, 13)
            self.assertEqual(bytes(buffer[:bytes_read]), self.test_data)
        finally:
            stream.close()

    def test_stream_write(self):
        output = io.BytesIO()
        stream = Stream(output)
        try:
            # Create test data
            test_data = b"Test Write"
            buffer = (ctypes.c_ubyte * len(test_data))(*test_data)
            # Write the data
            bytes_written = stream._write_cb(None, buffer, len(test_data))
            # Verify the data
            self.assertEqual(bytes_written, len(test_data))
            output.seek(0)
            self.assertEqual(output.read(), test_data)
        finally:
            stream.close()

    def test_stream_seek(self):
        stream = Stream(self.temp_file)
        try:
            # Seek to position 7 (after "Hello, ")
            new_pos = stream._seek_cb(None, 7, 0)  # 0 = SEEK_SET
            self.assertEqual(new_pos, 7)
            # Read from new position
            buffer = (ctypes.c_ubyte * 6)()
            bytes_read = stream._read_cb(None, buffer, 6)
            self.assertEqual(bytes(buffer[:bytes_read]), b"World!")
        finally:
            stream.close()

    def test_stream_flush(self):
        output = io.BytesIO()
        stream = Stream(output)
        try:
            # Write some data
            test_data = b"Test Flush"
            buffer = (ctypes.c_ubyte * len(test_data))(*test_data)
            stream._write_cb(None, buffer, len(test_data))
            # Flush the stream
            result = stream._flush_cb(None)
            self.assertEqual(result, 0)
        finally:
            stream.close()

    def test_stream_context_manager(self):
        with Stream(self.temp_file) as stream:
            self.assertTrue(stream.initialized)
            self.assertFalse(stream.closed)
        self.assertTrue(stream.closed)

    def test_stream_double_close(self):
        stream = Stream(self.temp_file)
        stream.close()
        # Second close should not raise an exception
        stream.close()
        self.assertTrue(stream.closed)

    def test_stream_read_after_close(self):
        stream = Stream(self.temp_file)
        # Store callbacks before closing
        read_cb = stream._read_cb
        stream.close()
        buffer = (ctypes.c_ubyte * 13)()
        # Reading from closed stream should return -1
        self.assertEqual(read_cb(None, buffer, 13), -1)

    def test_stream_write_after_close(self):
        stream = Stream(self.temp_file)
        # Store callbacks before closing
        write_cb = stream._write_cb
        stream.close()
        test_data = b"Test Write"
        buffer = (ctypes.c_ubyte * len(test_data))(*test_data)
        # Writing to closed stream should return -1
        self.assertEqual(write_cb(None, buffer, len(test_data)), -1)

    def test_stream_seek_after_close(self):
        stream = Stream(self.temp_file)
        # Store callbacks before closing
        seek_cb = stream._seek_cb
        stream.close()
        # Seeking in closed stream should return -1
        self.assertEqual(seek_cb(None, 5, 0), -1)

    def test_stream_flush_after_close(self):
        stream = Stream(self.temp_file)
        # Store callbacks before closing
        flush_cb = stream._flush_cb
        stream.close()
        # Flushing closed stream should return -1
        self.assertEqual(flush_cb(None), -1)


class TestLegacyAPI(unittest.TestCase):
    def setUp(self):
        # Filter specific deprecation warnings for legacy API tests
        warnings.filterwarnings("ignore", message="The read_file function is deprecated")
        warnings.filterwarnings("ignore", message="The sign_file function is deprecated")
        warnings.filterwarnings("ignore", message="The read_ingredient_file function is deprecated")
        warnings.filterwarnings("ignore", message="The create_signer function is deprecated")
        warnings.filterwarnings("ignore", message="The create_signer_from_info function is deprecated")

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

    def test_invalid_settings_str(self):
        """Test loading a malformed settings string."""
        with self.assertRaises(Error):
            load_settings(r'{"verify": { "remote_manifest_fetch": false }')

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
                self.assertNotIn("validation_status", file_manifest_json)

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
                self.assertNotIn("validation_status", json_data)

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
                self.assertNotIn("validation_status", json_data)

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
                    self.assertNotIn("validation_status", json_data)

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
                        self.assertNotIn("validation_status", json_data)

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
    unittest.main()
