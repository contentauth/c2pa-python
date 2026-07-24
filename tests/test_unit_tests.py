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

import gc
import inspect
import os
import io
import json
import re
import unittest
import ctypes
import warnings
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.backends import default_backend
import tempfile
import shutil
import ctypes
import threading

# Suppress deprecation warnings
warnings.simplefilter("ignore", category=DeprecationWarning)

from c2pa import Builder, C2paError as Error, Reader, C2paSigningAlg as SigningAlg, C2paSignerInfo, Signer, sdk_version, C2paBuilderIntent, C2paDigitalSourceType
from c2pa import Settings, Context, ContextBuilder, ContextProvider
from c2pa.c2pa import Stream, LifecycleState, ManagedResource, load_settings, create_signer, create_signer_from_info, ed25519_sign, format_embeddable
import c2pa.c2pa as c2pa_module


PROJECT_PATH = os.getcwd()
FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
DEFAULT_TEST_FILE_NAME = "C.jpg"
INGREDIENT_TEST_FILE_NAME = "A.jpg"
DEFAULT_TEST_FILE = os.path.join(FIXTURES_DIR, DEFAULT_TEST_FILE_NAME)
INGREDIENT_TEST_FILE = os.path.join(FIXTURES_DIR, INGREDIENT_TEST_FILE_NAME)
ALTERNATIVE_INGREDIENT_TEST_FILE = os.path.join(FIXTURES_DIR, "cloud.jpg")


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
    tests_dir = os.path.dirname(os.path.abspath(__file__))
    settings_path = os.path.join(tests_dir, 'trust_config_test_settings.json')

    # Load the located default test settings
    with open(settings_path, 'r') as f:
        settings_data = json.load(f)

    return settings_data


def parse_native_version():
    """
    Parse the expected native SDK version from c2pa-native-version.txt.

    Returns:
        str: The semantic version string (e.g. "0.85.2").
    """
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    version_path = os.path.join(repo_root, 'c2pa-native-version.txt')
    with open(version_path, 'r') as f:
        raw = f.read().strip()
    # Strip the "c2pa-v" prefix to get the bare semantic version.
    return raw.split('v', 1)[1] if 'v' in raw else raw


class TestC2paSdk(unittest.TestCase):
    def test_sdk_version(self):
        # This test verifies the native libraries used match the expected version.
        self.assertIn(parse_native_version(), sdk_version())


class TestReader(unittest.TestCase):
    def setUp(self):
        warnings.filterwarnings("ignore", message="load_settings\\(\\) is deprecated")
        self.data_dir = FIXTURES_DIR
        self.testPath = DEFAULT_TEST_FILE

    def test_can_retrieve_reader_supported_mimetypes(self):
        result1 = Reader.get_supported_mime_types()
        self.assertTrue(len(result1) > 0)

        # Cache hit
        result2 = Reader.get_supported_mime_types()
        self.assertTrue(len(result2) > 0)

        self.assertEqual(result1, result2)

    def test_stream_read_nothing_to_read(self):
        # The ingredient test file has no manifest
        # So if we instantiate directly, the Reader instance should throw
        with open(INGREDIENT_TEST_FILE, "rb") as file:
            with self.assertRaises(Error) as context:
                reader = Reader("image/jpeg", file)
            self.assertIn("ManifestNotFound: no JUMBF data found", str(context.exception))

    def test_try_create_reader_nothing_to_read(self):
        # The ingredient test file has no manifest
        # So if we use Reader.try_create, in this case we'll get None
        # And no error should be raised
        with open(INGREDIENT_TEST_FILE, "rb") as file:
            reader = Reader.try_create("image/jpeg", file)
            self.assertIsNone(reader)

    def test_stream_read(self):
        with open(self.testPath, "rb") as file:
            reader = Reader("image/jpeg", file)
            json_data = reader.json()
            self.assertIn(DEFAULT_TEST_FILE_NAME, json_data)

    def test_try_create_reader_from_stream(self):
        with open(self.testPath, "rb") as file:
            reader = Reader.try_create("image/jpeg", file)
            self.assertIsNotNone(reader)
            json_data = reader.json()
            self.assertIn(DEFAULT_TEST_FILE_NAME, json_data)

    def test_try_create_reader_from_stream_context_manager(self):
        with open(self.testPath, "rb") as file:
            reader = Reader.try_create("image/jpeg", file)
            self.assertIsNotNone(reader)
            # Check that a Reader returned by try_create is not None,
            # before using it in a context manager pattern (with)
            if reader is not None:
                with reader:
                    json_data = reader.json()
                    self.assertIn(DEFAULT_TEST_FILE_NAME, json_data)

    def test_stream_read_detailed(self):
        with open(self.testPath, "rb") as file:
            reader = Reader("image/jpeg", file)
            json_data = reader.detailed_json()
            self.assertIn(DEFAULT_TEST_FILE_NAME, json_data)

    def test_get_active_manifest(self):
        with open(self.testPath, "rb") as file:
            reader = Reader("image/jpeg", file)
            active_manifest = reader.get_active_manifest()

            # Check the returned manifest label/key
            expected_label = "contentauth:urn:uuid:c85a2b90-f1a0-4aa4-b17f-f938b475804e"
            self.assertEqual(active_manifest["label"], expected_label)

    def test_get_manifest(self):
        with open(self.testPath, "rb") as file:
            reader = Reader("image/jpeg", file)

            # Test getting manifest by the specific label
            label = "contentauth:urn:uuid:c85a2b90-f1a0-4aa4-b17f-f938b475804e"
            manifest = reader.get_manifest(label)
            self.assertEqual(manifest["label"], label)

            # It should be the active manifest too, so cross-check
            active_manifest = reader.get_active_manifest()
            self.assertEqual(manifest, active_manifest)

    def test_stream_get_non_active_manifest_by_label(self):
        video_path = os.path.join(FIXTURES_DIR, "video1.mp4")
        with open(video_path, "rb") as file:
            reader = Reader("video/mp4", file)

            non_active_label = "urn:uuid:54281c07-ad34-430e-bea5-112a18facf0b"
            non_active_manifest = reader.get_manifest(non_active_label)
            self.assertEqual(non_active_manifest["label"], non_active_label)

            # Verify it's not the active manifest
            # (that test case has only one other manifest that is not the active manifest)
            active_manifest = reader.get_active_manifest()
            self.assertNotEqual(non_active_manifest, active_manifest)
            self.assertNotEqual(non_active_manifest["label"], active_manifest["label"])

    def test_stream_get_non_active_manifest_by_label_not_found(self):
        video_path = os.path.join(FIXTURES_DIR, "video1.mp4")
        with open(video_path, "rb") as file:
            reader = Reader("video/mp4", file)

            # Try to get a manifest with a label that clearly doesn't exist...
            non_existing_label = "urn:uuid:clearly-not-existing"
            with self.assertRaises(KeyError):
                reader.get_manifest(non_existing_label)

    def test_stream_read_get_validation_state(self):
        with open(self.testPath, "rb") as file:
            reader = Reader("image/jpeg", file)
            validation_state = reader.get_validation_state()
            self.assertIsNotNone(validation_state)
            self.assertEqual(validation_state, "Valid")

    def test_stream_read_get_validation_state_with_trust_config(self):
        # Run in a separate thread to isolate thread-local settings
        result = {}
        exception = {}

        def read_with_trust_config():
            try:
                # Load trust configuration
                settings_dict = load_test_settings_json()

                # Apply the settings (including trust configuration)
                # Settings are thread-local, so they won't affect other tests
                # And that is why we also run the test in its own thread, so tests are isolated
                load_settings(settings_dict)

                with open(self.testPath, "rb") as file:
                    reader = Reader("image/jpeg", file)
                    validation_state = reader.get_validation_state()
                    result['validation_state'] = validation_state
            except Exception as e:
                exception['error'] = e

        # Create and start thread
        thread = threading.Thread(target=read_with_trust_config)
        thread.start()
        thread.join()

        # Check for exceptions
        if 'error' in exception:
            raise exception['error']

        # Assertions run in main thread
        self.assertIsNotNone(result.get('validation_state'))
        # With trust configuration loaded, manifest is Trusted
        self.assertEqual(result.get('validation_state'), "Trusted")

    def test_stream_read_get_validation_results(self):
        with open(self.testPath, "rb") as file:
            reader = Reader("image/jpeg", file)
            validation_results = reader.get_validation_results()

            self.assertIsNotNone(validation_results)
            self.assertIsInstance(validation_results, dict)

            self.assertIn("activeManifest", validation_results)
            active_manifest_results = validation_results["activeManifest"]
            self.assertIsInstance(active_manifest_results, dict)

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

    def test_stream_read_detailed_and_parse(self):
        with open(self.testPath, "rb") as file:
            reader = Reader("image/jpeg", file)
            manifest_store = json.loads(reader.detailed_json())
            title = manifest_store["manifests"][manifest_store["active_manifest"]]["claim"]["dc:title"]
            self.assertEqual(title, DEFAULT_TEST_FILE_NAME)

    def test_stream_read_crjson_and_parse(self):
        with open(self.testPath, "rb") as file:
            reader = Reader("image/jpeg", file)
            crjson = reader.crjson()
            self.assertTrue(crjson)
            json.loads(crjson)

    def test_stream_read_crjson_path_only(self):
        with Reader(self.testPath) as reader:
            crjson = reader.crjson()
            self.assertTrue(crjson)
            json.loads(crjson)

    def test_stream_read_string_stream_path_only(self):
        with Reader(self.testPath) as reader:
            json_data = reader.json()
            self.assertIn(DEFAULT_TEST_FILE_NAME, json_data)

    def test_try_create_from_path(self):
        test_path = os.path.join(self.data_dir, "C.dng")

        # Create reader with the file content
        reader = Reader.try_create(test_path)
        self.assertIsNotNone(reader)
        # Just run and verify there is no crash
        json.loads(reader.json())

    def test_stream_read_string_stream_mimetype_not_supported(self):
        with self.assertRaises(Error.NotSupported):
            # xyz is actually an extension that is recognized
            # as mimetype chemical/x-xyz
            Reader(os.path.join(FIXTURES_DIR, "C.xyz"))

    def test_try_create_raises_mimetype_not_supported(self):
        with self.assertRaises(Error.NotSupported):
            # xyz is actually an extension that is recognized
            # as mimetype chemical/x-xyz, but we don't support it
            Reader.try_create(os.path.join(FIXTURES_DIR, "C.xyz"))

    def test_stream_read_string_stream_mimetype_not_recognized(self):
        with self.assertRaises(Error.NotSupported):
            Reader(os.path.join(FIXTURES_DIR, "C.test"))

    def test_try_create_raises_mimetype_not_recognized(self):
        with self.assertRaises(Error.NotSupported):
            Reader.try_create(os.path.join(FIXTURES_DIR, "C.test"))

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
            self.assertIsNone(reader._handle)
            self.assertIsNone(reader._own_stream)
            # Verify reader is marked as closed
            self.assertEqual(reader._lifecycle_state, LifecycleState.CLOSED)

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

    def test_try_create_all_files(self):
        """Test reading C2PA metadata using Reader.try_create from all files in the fixtures/files-for-reading-tests directory"""
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
                    reader = Reader.try_create(mime_type, file)
                    # try_create returns None if no manifest found, otherwise a Reader
                    self.assertIsNotNone(reader, f"Expected Reader for {filename}")
                    json_data = reader.json()
                    reader.close()
                    self.assertIsInstance(json_data, str)
                    # Verify the manifest contains expected fields
                    manifest = json.loads(json_data)
                    self.assertIn("manifests", manifest)
                    self.assertIn("active_manifest", manifest)
            except Exception as e:
                self.fail(f"Failed to read metadata from {filename}: {str(e)}")

    def test_try_create_all_files_using_extension(self):
        """
        Test reading C2PA metadata using Reader.try_create
        from files in the fixtures/files-for-reading-tests directory
        """
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
                    reader = Reader.try_create(parsed_extension, file)
                    # try_create returns None if no manifest found, otherwise a Reader
                    self.assertIsNotNone(reader, f"Expected Reader for {filename}")
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

    def test_read_cached_all_files(self):
        """Test reading C2PA metadata with cache functionality from all files in the fixtures/files-for-reading-tests directory"""
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

                    # Test 1: Verify cache variables are initially None
                    self.assertIsNone(reader._manifest_json_str_cache, f"JSON cache should be None initially for {filename}")
                    self.assertIsNone(reader._manifest_data_cache, f"Manifest data cache should be None initially for {filename}")

                    # Test 2: Multiple calls to json() should return the same result and use cache
                    json_data_1 = reader.json()
                    self.assertIsNotNone(reader._manifest_json_str_cache, f"JSON cache not set after first json() call for {filename}")
                    self.assertEqual(json_data_1, reader._manifest_json_str_cache, f"JSON cache doesn't match return value for {filename}")

                    json_data_2 = reader.json()
                    self.assertEqual(json_data_1, json_data_2, f"JSON inconsistency for {filename}")
                    self.assertIsInstance(json_data_1, str)

                    # Test 3: Test methods that use the cache
                    try:
                        # Test get_active_manifest() which uses _get_cached_manifest_data()
                        active_manifest = reader.get_active_manifest()
                        self.assertIsInstance(active_manifest, dict, f"Active manifest not dict for {filename}")

                        # Test 4: Verify cache is set after calling cache-using methods
                        self.assertIsNotNone(reader._manifest_json_str_cache, f"JSON cache not set after get_active_manifest for {filename}")
                        self.assertIsNotNone(reader._manifest_data_cache, f"Manifest data cache not set after get_active_manifest for {filename}")

                        # Test 5: Multiple calls to cache-using methods should return the same result
                        active_manifest_2 = reader.get_active_manifest()
                        self.assertEqual(active_manifest, active_manifest_2, f"Active manifest cache inconsistency for {filename}")

                        # Test get_validation_state() which uses the cache
                        validation_state = reader.get_validation_state()
                        # validation_state can be None, so just check it doesn't crash

                        # Test get_validation_results() which uses the cache
                        validation_results = reader.get_validation_results()
                        # validation_results can be None, so just check it doesn't crash

                        # Test 6: Multiple calls to validation methods should return the same result
                        validation_state_2 = reader.get_validation_state()
                        self.assertEqual(validation_state, validation_state_2, f"Validation state cache inconsistency for {filename}")

                        validation_results_2 = reader.get_validation_results()
                        self.assertEqual(validation_results, validation_results_2, f"Validation results cache inconsistency for {filename}")

                    except KeyError as e:
                        # Some files might not have active manifests or validation data
                        # This is expected for some test files, so we'll skip cache testing for those
                        pass

                    # Test 7: Verify the manifest contains expected fields
                    manifest = json.loads(json_data_1)
                    self.assertIn("manifests", manifest)
                    self.assertIn("active_manifest", manifest)

                    # Test 8: Test cache clearing on close
                    reader.close()
                    self.assertIsNone(reader._manifest_json_str_cache, f"JSON cache not cleared for {filename}")
                    self.assertIsNone(reader._manifest_data_cache, f"Manifest data cache not cleared for {filename}")

            except Exception as e:
                self.fail(f"Failed to read cached metadata from {filename}: {str(e)}")

    def test_reader_context_manager_with_exception(self):
        """Test Reader state after exception in context manager."""
        try:
            with Reader(self.testPath) as reader:
                # Inside context - should be valid
                self.assertEqual(reader._lifecycle_state, LifecycleState.ACTIVE)
                self.assertIsNotNone(reader._handle)
                self.assertIsNotNone(reader._own_stream)
                self.assertIsNotNone(reader._backing_file)
                raise ValueError("Test exception")
        except ValueError:
            pass

        # After exception - should still be closed
        self.assertEqual(reader._lifecycle_state, LifecycleState.CLOSED)
        self.assertIsNone(reader._handle)
        self.assertIsNone(reader._own_stream)
        self.assertIsNone(reader._backing_file)

    def test_reader_partial_initialization_states(self):
        """Test Reader behavior with partial initialization failures."""
        # Test with _reader = None but lifecycle state = ACTIVE
        reader = Reader.__new__(Reader)
        reader._lifecycle_state = LifecycleState.ACTIVE
        reader._handle = None
        reader._own_stream = None
        reader._backing_file = None

        with self.assertRaises(Error):
            reader._ensure_valid_state()

    def test_reader_cleanup_state_transitions(self):
        """Test Reader state during cleanup operations."""
        reader = Reader(self.testPath)

        reader._cleanup_resources()
        self.assertEqual(reader._lifecycle_state, LifecycleState.CLOSED)
        self.assertIsNone(reader._handle)
        self.assertIsNone(reader._own_stream)
        self.assertIsNone(reader._backing_file)

    def test_reader_cleanup_idempotency(self):
        """Test that cleanup operations are idempotent."""
        reader = Reader(self.testPath)

        # First cleanup
        reader._cleanup_resources()
        self.assertEqual(reader._lifecycle_state, LifecycleState.CLOSED)

        # Second cleanup should not change state
        reader._cleanup_resources()
        self.assertEqual(reader._lifecycle_state, LifecycleState.CLOSED)
        self.assertIsNone(reader._handle)
        self.assertIsNone(reader._own_stream)
        self.assertIsNone(reader._backing_file)

    def test_reader_state_with_invalid_native_pointer(self):
        """Test Reader state handling with invalid native pointer."""
        reader = Reader(self.testPath)

        # Simulate invalid native pointer
        reader._handle = 0

        # Operations should fail gracefully
        with self.assertRaises(Error):
            reader.json()

    def test_reader_is_embedded(self):
        """Test the is_embedded method returns correct values for embedded and remote manifests."""

        # Test with a fixture which has an embedded manifest
        with open(self.testPath, "rb") as file:
            reader = Reader("image/jpeg", file)
            self.assertTrue(reader.is_embedded())
            reader.close()

        # Test with cloud.jpg fixture which has a remote manifest (not embedded)
        cloud_fixture_path = os.path.join(self.data_dir, "cloud.jpg")
        with Reader("image/jpeg", cloud_fixture_path) as reader:
            self.assertFalse(reader.is_embedded())

    def test_sign_and_read_is_not_embedded(self):
        """Test the is_embedded method returns correct values for remote manifests."""

        with open(os.path.join(self.data_dir, "es256_certs.pem"), "rb") as cert_file:
            certs = cert_file.read()
        with open(os.path.join(self.data_dir, "es256_private.key"), "rb") as key_file:
            key = key_file.read()

        # Create signer info and signer
        signer_info = C2paSignerInfo(
            alg=b"es256",
            sign_cert=certs,
            private_key=key,
            ta_url=b"http://timestamp.digicert.com"
        )
        signer = Signer.from_info(signer_info)

        # Define a simple manifest
        manifest_definition = {
            "claim_generator": "python_test",
            "claim_generator_info": [{
                "name": "python_test",
                "version": "0.0.1",
            }],
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

        # Create a temporary directory for the signed file
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_file_path = os.path.join(temp_dir, "signed_test_file_no_embed.jpg")

            with open(self.testPath, "rb") as file:
                builder = Builder(manifest_definition)
                # Direct the Builder not to embed the manifest into the asset
                builder.set_no_embed()


                with open(temp_file_path, "wb") as temp_file:
                    manifest_data = builder.sign(
                        signer, "image/jpeg", file, temp_file)

                with Reader("image/jpeg", temp_file_path, manifest_data) as reader:
                    self.assertFalse(reader.is_embedded())

    def test_reader_get_remote_url(self):
        """Test the get_remote_url method returns correct values for embedded and remote manifests."""

        # Test get_remote_url for file with embedded manifest (should return None)
        with open(self.testPath, "rb") as file:
            reader = Reader("image/jpeg", file)
            self.assertIsNone(reader.get_remote_url())
            reader.close()

        # Test remote manifest using cloud.jpg fixture which has a remote URL
        cloud_fixture_path = os.path.join(self.data_dir, "cloud.jpg")
        with Reader("image/jpeg", cloud_fixture_path) as reader:
            remote_url = reader.get_remote_url()
            self.assertEqual(remote_url, "https://cai-manifests.adobe.com/manifests/adobe-urn-uuid-5f37e182-3687-462e-a7fb-573462780391")
            self.assertFalse(reader.is_embedded())

    def test_stream_read_and_parse_cached(self):
        """Test reading and parsing with cache verification by repeating operations multiple times"""
        with open(self.testPath, "rb") as file:
            reader = Reader("image/jpeg", file)

            # Verify cache starts as None
            self.assertIsNone(reader._manifest_json_str_cache, "JSON cache should be None initially")
            self.assertIsNone(reader._manifest_data_cache, "Manifest data cache should be None initially")

            # First operation - should populate cache
            manifest_store_1 = json.loads(reader.json())
            title_1 = manifest_store_1["manifests"][manifest_store_1["active_manifest"]]["title"]
            self.assertEqual(title_1, DEFAULT_TEST_FILE_NAME)

            # Verify cache is populated after first json() call
            self.assertIsNotNone(reader._manifest_json_str_cache, "JSON cache should be set after first json() call")
            self.assertEqual(manifest_store_1, json.loads(reader._manifest_json_str_cache), "Cached JSON should match parsed result")

            # Repeat the same operation multiple times to verify cache usage
            for i in range(5):
                manifest_store = json.loads(reader.json())
                title = manifest_store["manifests"][manifest_store["active_manifest"]]["title"]
                self.assertEqual(title, DEFAULT_TEST_FILE_NAME, f"Title should be consistent on iteration {i+1}")

                # Verify cache is still populated and consistent
                self.assertIsNotNone(reader._manifest_json_str_cache, f"JSON cache should remain set on iteration {i+1}")
                self.assertEqual(manifest_store, json.loads(reader._manifest_json_str_cache), f"Cached JSON should match parsed result on iteration {i+1}")

            # Test methods that use the cache
            # Test get_active_manifest() which uses _get_cached_manifest_data()
            active_manifest_1 = reader.get_active_manifest()
            self.assertIsInstance(active_manifest_1, dict, "Active manifest should be a dict")

            # Verify manifest data cache is populated
            self.assertIsNotNone(reader._manifest_data_cache, "Manifest data cache should be set after get_active_manifest()")

            # Repeat get_active_manifest() multiple times to verify cache usage
            for i in range(3):
                active_manifest = reader.get_active_manifest()
                self.assertEqual(active_manifest_1, active_manifest, f"Active manifest should be consistent on iteration {i+1}")

                # Verify cache remains populated
                self.assertIsNotNone(reader._manifest_data_cache, f"Manifest data cache should remain set on iteration {i+1}")

            # Test get_validation_state() and get_validation_results() with cache
            validation_state_1 = reader.get_validation_state()
            validation_results_1 = reader.get_validation_results()

            # Repeat validation methods to verify cache usage
            for i in range(3):
                validation_state = reader.get_validation_state()
                validation_results = reader.get_validation_results()

                self.assertEqual(validation_state_1, validation_state, f"Validation state should be consistent on iteration {i+1}")
                self.assertEqual(validation_results_1, validation_results, f"Validation results should be consistent on iteration {i+1}")

            # Verify cache clearing on close
            reader.close()
            self.assertIsNone(reader._manifest_json_str_cache, "JSON cache should be cleared on close")
            self.assertIsNone(reader._manifest_data_cache, "Manifest data cache should be cleared on close")

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
            "assertions": [],
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
            "assertions": [],
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
            "assertions": [],
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
            "assertions": [],
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
            "assertions": [],
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
            "assertions": [],
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
            "assertions": [],
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
            "assertions": [],
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
            builder.add_ingredient(ingredient_json, "image/png", f)

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
            builder.add_ingredient(ingredient_json, "image/png", f)

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
            builder.add_ingredient(ingredient_json, "image/png", f)

        builder.close()

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
            builder.add_ingredient(ingredient_json, "image/png", f)

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
                                "action": "c2pa.placed",
                                "parameters": {
                                    "ingredientIds": ["ingredient-for-placed"]
                                },
                            },
                            {
                                "action": "c2pa.opened",
                                "digitalSourceType": "http://cv.iptc.org/newscodes/digitalsourcetype/digitalCreation",
                                "parameters": {
                                    "ingredientIds": ["ingredient-for-opened"]
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


class TestSettings(TestContextAPIs):

    def test_settings_default_construction(self):
        settings = Settings()
        self.assertTrue(settings.is_valid)
        settings.close()

    def test_settings_set_chaining(self):
        settings = Settings()
        result = (
            settings.set(
                "builder.thumbnail.enabled", "false"
            ).set(
                "builder.thumbnail.enabled", "true"
            )
        )
        self.assertIs(result, settings)
        settings.close()

    def test_settings_from_json(self):
        settings = Settings.from_json(
            '{"builder":{"thumbnail":'
            '{"enabled":false}}}'
        )
        self.assertTrue(settings.is_valid)
        settings.close()

    def test_settings_from_dict(self):
        settings = Settings.from_dict({
            "builder": {
                "thumbnail": {"enabled": False}
            }
        })
        self.assertTrue(settings.is_valid)
        settings.close()

    def test_settings_update_json(self):
        settings = Settings()
        result = settings.update(
            '{"builder":{"thumbnail":'
            '{"enabled":false}}}'
        )
        self.assertIs(result, settings)
        settings.close()

    def test_settings_update_dict(self):
        settings = Settings()
        result = settings.update({
            "builder": {
                "thumbnail": {"enabled": False}
            }
        })
        self.assertIs(result, settings)
        settings.close()

    def test_settings_is_valid_after_close(self):
        settings = Settings()
        settings.close()
        self.assertFalse(settings.is_valid)

    def test_settings_raises_after_close(self):
        settings = Settings()
        settings.close()
        with self.assertRaises(Error):
            settings.set(
                "builder.thumbnail.enabled", "false"
            )


class TestContext(TestContextAPIs):

    def test_context_default(self):
        context = Context()
        self.assertTrue(context.is_valid)
        self.assertFalse(context.has_signer)
        context.close()

    def test_context_from_settings(self):
        settings = Settings()
        context = Context(settings)
        self.assertTrue(context.is_valid)
        context.close()
        settings.close()

    def test_context_from_json(self):
        context = Context.from_json(
            '{"builder":{"thumbnail":'
            '{"enabled":false}}}'
        )
        self.assertTrue(context.is_valid)
        context.close()

    def test_context_from_dict(self):
        context = Context.from_dict({
            "builder": {
                "thumbnail": {"enabled": False}
            }
        })
        self.assertTrue(context.is_valid)
        context.close()

    def test_context_context_manager(self):
        with Context() as context:
            self.assertTrue(context.is_valid)

    def test_context_is_valid_after_close(self):
        context = Context()
        context.close()
        self.assertFalse(context.is_valid)


class TestContextBuilder(TestContextAPIs):

    def test_context_builder_default(self):
        context = Context.builder().build()
        self.assertTrue(context.is_valid)
        self.assertFalse(context.has_signer)
        context.close()

    def test_context_builder_with_settings(self):
        settings = Settings()
        context = Context.builder().with_settings(settings).build()
        self.assertTrue(context.is_valid)
        context.close()
        settings.close()

    def test_context_builder_with_signer(self):
        signer = self._ctx_make_signer()
        context = (
            Context.builder()
            .with_signer(signer)
            .build()
        )
        self.assertTrue(context.is_valid)
        self.assertTrue(context.has_signer)
        context.close()

    def test_context_builder_with_settings_and_signer(self):
        settings = Settings()
        signer = self._ctx_make_signer()
        context = (
            Context.builder()
            .with_settings(settings)
            .with_signer(signer)
            .build()
        )
        self.assertTrue(context.is_valid)
        self.assertTrue(context.has_signer)
        context.close()
        settings.close()

    def test_context_builder_chaining_returns_self(self):
        settings = Settings()
        context_builder = Context.builder()
        result = context_builder.with_settings(settings)
        self.assertIs(result, context_builder)
        context = context_builder.build()
        context.close()
        settings.close()

    def test_context_builder_with_settings_last_wins(self):
        """The last with_settings call determines the settings used.

        Toggles thumbnails on, off, on, off across four calls.
        The last call disables thumbnails, so the signed manifest
        should have no thumbnail.
        """
        settings_on_1 = Settings.from_dict({
            "builder": {"thumbnail": {"enabled": True}},
        })
        settings_off_1 = Settings.from_dict({
            "builder": {"thumbnail": {"enabled": False}},
        })
        settings_on_2 = Settings.from_dict({
            "builder": {"thumbnail": {"enabled": True}},
        })
        settings_off_2 = Settings.from_dict({
            "builder": {"thumbnail": {"enabled": False}},
        })
        context = (
            Context.builder()
            .with_settings(settings_on_1)
            .with_settings(settings_off_1)
            .with_settings(settings_on_2)
            .with_settings(settings_off_2)
            .build()
        )
        signer = self._ctx_make_signer()
        builder = Builder(self.test_manifest, context)
        with tempfile.TemporaryDirectory() as temp_dir:
            dest_path = os.path.join(temp_dir, "out.jpg")
            with (
                open(DEFAULT_TEST_FILE, "rb") as source_file,
                open(dest_path, "w+b") as dest_file,
            ):
                builder.sign(
                    signer, "image/jpeg", source_file, dest_file,
                )
            reader = Reader(dest_path)
            manifest = reader.get_active_manifest()
            # Last settings disabled thumbnails
            self.assertIsNone(manifest.get("thumbnail"))
            reader.close()
        builder.close()
        context.close()
        settings_on_1.close()
        settings_off_1.close()
        settings_on_2.close()
        settings_off_2.close()


class TestContextWithSigner(TestContextAPIs):

    def test_context_with_signer(self):
        signer = self._ctx_make_signer()
        context = Context(signer=signer)
        self.assertTrue(context.is_valid)
        self.assertTrue(context.has_signer)
        context.close()

    def test_context_with_settings_and_signer(self):
        settings = Settings()
        signer = self._ctx_make_signer()
        context = Context(settings, signer)
        self.assertTrue(context.is_valid)
        self.assertTrue(context.has_signer)
        context.close()
        settings.close()

    def test_consumed_signer_is_closed(self):
        signer = self._ctx_make_signer()
        context = Context(signer=signer)
        self.assertEqual(signer._lifecycle_state, LifecycleState.CLOSED)
        context.close()

    def test_consumed_signer_raises_on_use(self):
        signer = self._ctx_make_signer()
        context = Context(signer=signer)
        with self.assertRaises(Error):
            signer._ensure_valid_state()
        context.close()

    def test_context_has_signer_flag(self):
        signer = self._ctx_make_signer()
        context = Context(signer=signer)
        self.assertTrue(context.has_signer)
        context.close()

    def test_context_no_signer_flag(self):
        context = Context()
        self.assertFalse(context.has_signer)
        context.close()

    def test_context_from_json_with_signer(self):
        signer = self._ctx_make_signer()
        context = Context.from_json(
            '{"builder":{"thumbnail":'
            '{"enabled":false}}}',
            signer,
        )
        self.assertTrue(context.has_signer)
        self.assertEqual(signer._lifecycle_state, LifecycleState.CLOSED)
        context.close()


class TestReaderWithContext(TestContextAPIs):

    def test_reader_with_default_context(self):
        context = Context()
        with open(DEFAULT_TEST_FILE, "rb") as file_handle:
            reader = Reader("image/jpeg", file_handle, context=context,)
            data = reader.json()
            self.assertIsNotNone(data)
            reader.close()
        context.close()

    def test_reader_with_settings_context(self):
        settings = Settings()
        context = Context(settings)
        with open(DEFAULT_TEST_FILE, "rb") as file_handle:
            reader = Reader("image/jpeg", file_handle, context=context,)
            data = reader.json()
            self.assertIsNotNone(data)
            reader.close()
        context.close()
        settings.close()

    def test_reader_without_context(self):
        with open(DEFAULT_TEST_FILE, "rb") as file_handle:
            reader = Reader("image/jpeg", file_handle)
            data = reader.json()
            self.assertIsNotNone(data)
            reader.close()

    def test_reader_try_create_with_context(self):
        context = Context()
        reader = Reader.try_create(DEFAULT_TEST_FILE, context=context,)
        self.assertIsNotNone(reader)
        data = reader.json()
        self.assertIsNotNone(data)
        reader.close()
        context.close()

    def test_reader_try_create_no_manifest(self):
        context = Context()
        reader = Reader.try_create(INGREDIENT_TEST_FILE, context=context,)
        self.assertIsNone(reader)
        context.close()

    def test_reader_file_path_with_context(self):
        context = Context()
        reader = Reader(DEFAULT_TEST_FILE, context=context,)
        data = reader.json()
        self.assertIsNotNone(data)
        reader.close()
        context.close()

    def test_reader_format_and_path_with_ctx(self):
        context = Context()
        reader = Reader("image/jpeg", DEFAULT_TEST_FILE, context=context)
        data = reader.json()
        self.assertIsNotNone(data)
        reader.close()
        context.close()

    def test_with_fragment_on_closed_reader_raises(self):
        context = Context()
        reader = Reader(DEFAULT_TEST_FILE, context=context)
        reader.close()
        with self.assertRaises(Error):
            reader.with_fragment(
                "video/mp4",
                io.BytesIO(b"\x00" * 100),
                io.BytesIO(b"\x00" * 100),
            )
        context.close()

    def test_with_fragment_unsupported_format_raises(self):
        context = Context()
        reader = Reader(DEFAULT_TEST_FILE, context=context)
        with self.assertRaises(Error):
            reader.with_fragment(
                "text/plain",
                io.BytesIO(b"\x00" * 100),
                io.BytesIO(b"\x00" * 100),
            )
        reader.close()
        context.close()

    def test_with_fragment_with_dash_fixtures(self):
        context = Context()
        init_path = os.path.join(FIXTURES_DIR, "dashinit.mp4")
        with open(init_path, "rb") as init_fragment:
            reader = Reader("video/mp4", init_fragment, context=context)
        frag_path = os.path.join(FIXTURES_DIR, "dash1.m4s")
        with open(init_path, "rb") as init_fragment, \
             open(frag_path, "rb") as next_fragment:
            reader.with_fragment("video/mp4", init_fragment, next_fragment)
        reader.close()
        context.close()


class TestSidecarReader(TestContextAPIs):
    """Reader over a detached (sidecar) manifest with a Context"""

    def _make_detached_manifest(self):
        """Sign DEFAULT_TEST_FILE with no-embed, return (asset_bytes,
        manifest_bytes) where manifest_bytes is the "detached" sidecar
        C2PA manifest."""

        signer = self._ctx_make_signer()
        with open(DEFAULT_TEST_FILE, "rb") as f:
            asset_bytes = f.read()
        builder = Builder(self.test_manifest)
        builder.set_no_embed()
        # Output is discarded: with no-embed the asset is unchanged and the
        # manifest is returned by sign().
        manifest_bytes = builder.sign(
            signer, "image/jpeg", io.BytesIO(asset_bytes), io.BytesIO())
        builder.close()
        signer.close()
        self.assertIsInstance(manifest_bytes, bytes)
        self.assertGreater(len(manifest_bytes), 0)
        return asset_bytes, manifest_bytes

    def test_reader_with_manifest_data_and_context(self):
        asset_bytes, manifest_bytes = self._make_detached_manifest()
        context = Context()
        reader = Reader(
            "image/jpeg",
            io.BytesIO(asset_bytes),
            manifest_bytes,
            context=context,
        )
        try:
            data = reader.json()
            self.assertTrue(data)
            self.assertFalse(reader.is_embedded())
            self.assertIn("manifests", json.loads(data))
        finally:
            reader.close()
            context.close()

    def test_reader_manifest_data_context_invalid_manifest_raises(self):
        with open(DEFAULT_TEST_FILE, "rb") as f:
            asset_bytes = f.read()
        context = Context()
        reader = None
        try:
            with self.assertRaises(Error):
                reader = Reader(
                    "image/jpeg",
                    io.BytesIO(asset_bytes),
                    b"not a real manifest",
                    context=context,
                )
            # The consumed-pointer error branch must leave no usable handle.
            if reader is not None:
                self.assertEqual(
                    reader._lifecycle_state, LifecycleState.CLOSED)
                self.assertIsNone(reader._handle)
        finally:
            if reader is not None:
                reader.close()
            context.close()

    def test_reader_manifest_data_context_wrong_type_raises(self):
        with open(DEFAULT_TEST_FILE, "rb") as f:
            asset_bytes = f.read()
        context = Context()
        try:
            # Non-bytes manifest_data must raise TypeError before any native
            # reader handle is allocated (no leak on this path).
            with self.assertRaises(TypeError):
                Reader(
                    "image/jpeg",
                    io.BytesIO(asset_bytes),
                    "manifest as str, not bytes",
                    context=context,
                )
        finally:
            context.close()

    def test_reader_manifest_data_context_use_after_close_raises(self):
        asset_bytes, manifest_bytes = self._make_detached_manifest()
        context = Context()
        reader = Reader(
            "image/jpeg",
            io.BytesIO(asset_bytes),
            manifest_bytes,
            context=context,
        )
        reader.close()
        self.assertEqual(reader._lifecycle_state, LifecycleState.CLOSED)
        with self.assertRaises(Error):
            reader.json()
        # Idempotent close after use-after-close attempt.
        reader.close()
        context.close()

    def test_reader_manifest_data_context_as_context_manager(self):
        asset_bytes, manifest_bytes = self._make_detached_manifest()
        context = Context()
        with Reader(
            "image/jpeg",
            io.BytesIO(asset_bytes),
            manifest_bytes,
            context=context,
        ) as reader:
            self.assertEqual(reader._lifecycle_state, LifecycleState.ACTIVE)
            self.assertTrue(reader.json())
        self.assertEqual(reader._lifecycle_state, LifecycleState.CLOSED)
        context.close()


class TestBuilderWithContext(TestContextAPIs):

    def test_contextual_builder_with_default_context(self):
        context = Context()
        builder = Builder(self.test_manifest, context)
        self.assertIsNotNone(builder)
        builder.close()
        context.close()

    def test_contextual_builder_with_settings_context(self):
        settings = Settings.from_dict({
            "builder": {
                "thumbnail": {"enabled": False}
            }
        })
        context = Context(settings)
        builder = Builder(self.test_manifest, context)
        signer = self._ctx_make_signer()
        with tempfile.TemporaryDirectory() as temp_dir:
            dest_path = os.path.join(temp_dir, "out.jpg")
            with (
                open(DEFAULT_TEST_FILE, "rb") as source_file,
                open(dest_path, "w+b") as dest_file,
            ):
                builder.sign(
                    signer, "image/jpeg", source_file, dest_file,
                )
            reader = Reader(dest_path)
            manifest = reader.get_active_manifest()
            self.assertIsNone(
                manifest.get("thumbnail")
            )
            reader.close()
        builder.close()
        context.close()
        settings.close()

    def test_contextual_builder_from_json_with_context(self):
        context = Context()
        builder = Builder.from_json(self.test_manifest, context)
        self.assertIsNotNone(builder)
        builder.close()
        context.close()

    def test_contextual_builder_sign_context_signer(self):
        signer = self._ctx_make_signer()
        context = Context(signer=signer)
        builder = Builder(
            self.test_manifest, context=context,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            dest_path = os.path.join(temp_dir, "out.jpg")
            with (
                open(DEFAULT_TEST_FILE, "rb") as source_file,
                open(dest_path, "w+b") as dest_file,
            ):
                manifest_bytes = builder.sign(
                    "image/jpeg",
                    source_file,
                    dest_file,
                )
                self.assertIsNotNone(manifest_bytes)
                self.assertGreater(len(manifest_bytes), 0)
            reader = Reader(dest_path)
            data = reader.json()
            self.assertIsNotNone(data)
            reader.close()
        builder.close()
        context.close()

    def test_contextual_builder_sign_signer_ovverride(self):
        context_signer = self._ctx_make_signer()
        context = Context(signer=context_signer)
        builder = Builder(
            self.test_manifest, context=context,
        )
        explicit_signer = self._ctx_make_signer()
        with tempfile.TemporaryDirectory() as temp_dir:
            dest_path = os.path.join(temp_dir, "out.jpg")
            with (
                open(DEFAULT_TEST_FILE, "rb") as source_file,
                open(dest_path, "w+b") as dest_file,
            ):
                manifest_bytes = builder.sign(
                    explicit_signer,
                    "image/jpeg", source_file, dest_file,
                )
                self.assertIsNotNone(manifest_bytes)
                self.assertGreater(len(manifest_bytes), 0)
        builder.close()
        explicit_signer.close()
        context.close()

    def test_contextual_builder_sign_no_signer_raises(self):
        context = Context()
        builder = Builder(
            self.test_manifest, context=context,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            dest_path = os.path.join(temp_dir, "out.jpg")
            with (
                open(DEFAULT_TEST_FILE, "rb") as source_file,
                open(dest_path, "w+b") as dest_file,
            ):
                with self.assertRaises(Error):
                    builder.sign(
                        "image/jpeg",
                        source_file,
                        dest_file,
                    )
        builder.close()
        context.close()

    def test_sign_file_with_context_signer_no_explicit_signer(self):
        signer = self._ctx_make_signer()
        context = Context(signer=signer)
        builder = Builder(
            self.test_manifest, context=context,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            dest_path = os.path.join(temp_dir, "out.jpg")
            manifest_bytes = builder.sign_file(
                source_path=DEFAULT_TEST_FILE,
                dest_path=dest_path,
            )
            self.assertIsNotNone(manifest_bytes)
            self.assertGreater(len(manifest_bytes), 0)
            reader = Reader(dest_path)
            data = reader.json()
            self.assertIsNotNone(data)
            reader.close()
        builder.close()
        context.close()

    def test_sign_file_no_signer_raises(self):
        context = Context()
        builder = Builder(
            self.test_manifest, context=context,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            dest_path = os.path.join(temp_dir, "out.jpg")
            with self.assertRaises(Error):
                builder.sign_file(
                    source_path=DEFAULT_TEST_FILE,
                    dest_path=dest_path,
                )
        builder.close()
        context.close()

    def test_with_archive_preserves_settings(self):
        """with_archive() preserves the builder's context settings.

        Settings live on the builder's context, not in the archive.
        The archive only carries the manifest definition. This test
        proves that a builder created with no-thumbnail settings
        keeps those settings after loading an archive.
        """
        settings = Settings.from_dict({
            "builder": {
                "thumbnail": {"enabled": False}
            }
        })
        context = Context(settings)
        signer = self._ctx_make_signer()
        builder = Builder(
            self.test_manifest, context,
        )
        archive = io.BytesIO(bytearray())
        builder.to_archive(archive)

        # Context provides the no-thumbnail setting;
        # with_archive only loads the manifest definition.
        builder2 = Builder({}, context)
        builder2.with_archive(archive)
        with (
            open(DEFAULT_TEST_FILE, "rb") as source,
            io.BytesIO(bytearray()) as output,
        ):
            builder2.sign(
                signer, "image/jpeg", source, output,
            )
            output.seek(0)
            reader = Reader(
                "image/jpeg", output, context=Context(),
            )
            manifest = reader.get_active_manifest()
            self.assertIsNone(
                manifest.get("thumbnail"),
                "with_archive should preserve no-thumbnail setting",
            )
            reader.close()
        archive.close()
        builder2.close()
        signer.close()
        context.close()
        settings.close()

    def test_with_archive_replaces_definition(self):
        """with_archive() restores the original builder's
        manifest definition, even if something set on new Builder."""
        context = Context()
        signer = self._ctx_make_signer()
        original_manifest = dict(self.test_manifest)
        original_manifest["title"] = "Original Title"
        builder = Builder(original_manifest, context)
        archive = io.BytesIO(bytearray())
        builder.to_archive(archive)

        replaced_manifest = dict(self.test_manifest)
        replaced_manifest["title"] = "Replaced Title"
        builder2 = Builder(replaced_manifest, context)
        builder2.with_archive(archive)
        with (
            open(DEFAULT_TEST_FILE, "rb") as source,
            io.BytesIO(bytearray()) as output,
        ):
            builder2.sign(
                signer, "image/jpeg", source, output,
            )
            output.seek(0)
            reader = Reader(
                "image/jpeg", output, context=Context(),
            )
            json_data = reader.json()
            self.assertIn("Original Title", json_data)
            self.assertNotIn("Replaced Title", json_data)
            reader.close()
        archive.close()
        builder2.close()
        signer.close()
        context.close()

    def test_with_archive_on_closed_builder_raises(self):
        """with_archive() on a closed builder raises C2paError."""
        context = Context()
        builder = Builder(
            self.test_manifest, context=context,
        )
        archive = io.BytesIO(bytearray())
        builder.to_archive(archive)
        builder.close()
        with self.assertRaises(Error):
            builder.with_archive(archive)
        context.close()

    def test_from_archive_roundtrip(self):
        """from_archive() can't propagate contexts."""
        settings = Settings.from_dict({
            "builder": {
                "thumbnail": {"enabled": False}
            }
        })
        context = Context(settings)
        signer = self._ctx_make_signer()
        builder = Builder(
            self.test_manifest, context=context,
        )
        archive = io.BytesIO(bytearray())
        builder.to_archive(archive)

        # from_archive creates a context-free builder
        builder2 = Builder.from_archive(archive)
        with (
            open(DEFAULT_TEST_FILE, "rb") as source,
            io.BytesIO(bytearray()) as output,
        ):
            builder2.sign(
                signer, "image/jpeg", source, output,
            )
            output.seek(0)
            reader = Reader(
                "image/jpeg", output, context=Context(),
            )
            manifest = reader.get_active_manifest()
            # from_archive can't propagate contexts
            self.assertIsNotNone(
                manifest.get("thumbnail"),
                "from_archive should lose settings and generate thumbnail",
            )
            reader.close()
        archive.close()
        builder2.close()
        signer.close()
        context.close()
        settings.close()


class TestContextIntegration(TestContextAPIs):

    def test_sign_no_thumbnail_via_context(self):
        settings = Settings.from_dict({
            "builder": {
                "thumbnail": {"enabled": False}
            }
        })
        context = Context(settings)
        signer = self._ctx_make_signer()
        builder = Builder(
            self.test_manifest, context=context,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            dest_path = os.path.join(temp_dir, "out.jpg")
            with (
                open(DEFAULT_TEST_FILE, "rb") as source_file,
                open(dest_path, "w+b") as dest_file,
            ):
                builder.sign(
                    signer, "image/jpeg", source_file, dest_file,
                )
            reader = Reader(dest_path)
            manifest = reader.get_active_manifest()
            self.assertIsNone(
                manifest.get("thumbnail")
            )
            reader.close()
        builder.close()
        signer.close()
        context.close()
        settings.close()

    def test_sign_read_roundtrip(self):
        signer = self._ctx_make_signer()
        context = Context(signer=signer)
        builder = Builder(
            self.test_manifest, context=context,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            dest_path = os.path.join(temp_dir, "out.jpg")
            with (
                open(DEFAULT_TEST_FILE, "rb") as source_file,
                open(dest_path, "w+b") as dest_file,
            ):
                builder.sign(
                    "image/jpeg",
                    source_file,
                    dest_file,
                )
            reader = Reader(dest_path)
            data = reader.json()
            self.assertIsNotNone(data)
            self.assertIn("manifests", data)
            reader.close()
        builder.close()
        context.close()

    def test_shared_context_multi_builders(self):
        context = Context()
        signer1 = self._ctx_make_signer()
        signer2 = self._ctx_make_signer()

        builder1 = Builder(self.test_manifest, context)
        builder2 = Builder(self.test_manifest, context)

        with tempfile.TemporaryDirectory() as temp_dir:
            for index, (builder, signer) in enumerate(
                [(builder1, signer1), (builder2, signer2)]
            ):
                dest_path = os.path.join(
                    temp_dir, f"out{index}.jpg"
                )
                with (
                    open(
                        DEFAULT_TEST_FILE, "rb"
                    ) as source_file,
                    open(dest_path, "w+b") as dest_file,
                ):
                    manifest_bytes = builder.sign(
                        signer, "image/jpeg",
                        source_file, dest_file,
                    )
                    self.assertGreater(len(manifest_bytes), 0)

        builder1.close()
        builder2.close()
        signer1.close()
        signer2.close()
        context.close()

    def test_trusted_sign_no_thumbnail_via_context(self):
        trust_dict = load_test_settings_json()
        trust_dict.setdefault("builder", {})["thumbnail"] = {
            "enabled": False,
        }
        settings = Settings.from_dict(trust_dict)
        context = Context(settings)
        signer = self._ctx_make_signer()
        builder = Builder(
            self.test_manifest, context=context,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            dest_path = os.path.join(temp_dir, "out.jpg")
            with (
                open(DEFAULT_TEST_FILE, "rb") as source_file,
                open(dest_path, "w+b") as dest_file,
            ):
                builder.sign(
                    signer, "image/jpeg",
                    source_file, dest_file,
                )
            reader = Reader(dest_path, context=context)
            manifest = reader.get_active_manifest()
            self.assertIsNone(manifest.get("thumbnail"))
            validation_state = reader.get_validation_state()
            self.assertEqual(validation_state, "Trusted")
            reader.close()
        builder.close()
        signer.close()
        context.close()
        settings.close()

    def test_shared_trusted_context_multi_builders(self):
        trust_dict = load_test_settings_json()
        settings = Settings.from_dict(trust_dict)
        context = Context(settings)
        signer1 = self._ctx_make_signer()
        signer2 = self._ctx_make_signer()

        builder1 = Builder(
            self.test_manifest, context=context,
        )
        builder2 = Builder(
            self.test_manifest, context=context,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            for index, (builder, signer) in enumerate(
                [(builder1, signer1), (builder2, signer2)]
            ):
                dest_path = os.path.join(
                    temp_dir, f"out{index}.jpg"
                )
                with (
                    open(
                        DEFAULT_TEST_FILE, "rb"
                    ) as source_file,
                    open(dest_path, "w+b") as dest_file,
                ):
                    manifest_bytes = builder.sign(
                        signer, "image/jpeg",
                        source_file, dest_file,
                    )
                    self.assertGreater(
                        len(manifest_bytes), 0,
                    )
                reader = Reader(
                    dest_path, context=context,
                )
                validation_state = (
                    reader.get_validation_state()
                )
                self.assertEqual(
                    validation_state, "Trusted",
                )
                reader.close()

        builder1.close()
        builder2.close()
        signer1.close()
        signer2.close()
        context.close()
        settings.close()

    def test_read_validation_trusted_via_context(self):
        trust_dict = load_test_settings_json()
        settings = Settings.from_dict(trust_dict)
        context = Context(settings)
        with open(DEFAULT_TEST_FILE, "rb") as f:
            reader = Reader("image/jpeg", f, context=context)
            validation_state = (
                reader.get_validation_state()
            )
            self.assertEqual(
                validation_state, "Trusted",
            )
            reader.close()
        context.close()
        settings.close()

    def test_sign_es256_trusted_via_context(self):
        trust_dict = load_test_settings_json()
        settings = Settings.from_dict(trust_dict)
        context = Context(settings)
        signer = self._ctx_make_signer()
        builder = Builder(
            self.test_manifest, context=context,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            dest_path = os.path.join(temp_dir, "out.jpg")
            with (
                open(DEFAULT_TEST_FILE, "rb") as source,
                open(dest_path, "w+b") as dest,
            ):
                builder.sign(
                    signer, "image/jpeg", source, dest,
                )
            reader = Reader(dest_path, context=context)
            validation_state = (
                reader.get_validation_state()
            )
            self.assertEqual(
                validation_state, "Trusted",
            )
            reader.close()
        builder.close()
        signer.close()
        context.close()
        settings.close()

    def test_sign_ed25519_trusted_via_context(self):
        trust_dict = load_test_settings_json()
        settings = Settings.from_dict(trust_dict)
        context = Context(settings)
        signer = self._ctx_make_ed25519_signer()
        builder = Builder(
            self.test_manifest, context=context,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            dest_path = os.path.join(temp_dir, "out.jpg")
            with (
                open(DEFAULT_TEST_FILE, "rb") as source,
                open(dest_path, "w+b") as dest,
            ):
                builder.sign(
                    signer, "image/jpeg", source, dest,
                )
            reader = Reader(dest_path, context=context)
            validation_state = (
                reader.get_validation_state()
            )
            self.assertEqual(
                validation_state, "Trusted",
            )
            reader.close()
        builder.close()
        signer.close()
        context.close()
        settings.close()

    def test_sign_ps256_trusted_via_context(self):
        trust_dict = load_test_settings_json()
        settings = Settings.from_dict(trust_dict)
        context = Context(settings)
        signer = self._ctx_make_ps256_signer()
        builder = Builder(
            self.test_manifest, context=context,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            dest_path = os.path.join(temp_dir, "out.jpg")
            with (
                open(DEFAULT_TEST_FILE, "rb") as source,
                open(dest_path, "w+b") as dest,
            ):
                builder.sign(
                    signer, "image/jpeg", source, dest,
                )
            reader = Reader(dest_path, context=context)
            validation_state = (
                reader.get_validation_state()
            )
            self.assertEqual(
                validation_state, "Trusted",
            )
            reader.close()
        builder.close()
        signer.close()
        context.close()
        settings.close()

    def test_archive_sign_trusted_via_context(self):
        trust_dict = load_test_settings_json()
        settings = Settings.from_dict(trust_dict)
        context = Context(settings)
        signer = self._ctx_make_signer()
        builder = Builder(
            self.test_manifest, context=context,
        )
        archive = io.BytesIO(bytearray())
        builder.to_archive(archive)
        builder = Builder({}, context=context)
        builder.with_archive(archive)
        with (
            open(DEFAULT_TEST_FILE, "rb") as source,
            io.BytesIO(bytearray()) as output,
        ):
            builder.sign(
                signer, "image/jpeg", source, output,
            )
            output.seek(0)
            reader = Reader(
                "image/jpeg", output, context=context,
            )
            validation_state = (
                reader.get_validation_state()
            )
            self.assertEqual(
                validation_state, "Trusted",
            )
            reader.close()
        archive.close()
        builder.close()
        signer.close()
        context.close()
        settings.close()

    def test_archive_sign_with_ingredient_trusted_via_context(self):
        trust_dict = load_test_settings_json()
        settings = Settings.from_dict(trust_dict)
        context = Context(settings)
        signer = self._ctx_make_signer()
        builder = Builder(
            self.test_manifest, context=context,
        )
        archive = io.BytesIO(bytearray())
        builder.to_archive(archive)
        builder = Builder({}, context=context)
        builder.with_archive(archive)
        ingredient_json = '{"test": "ingredient"}'
        with open(DEFAULT_TEST_FILE, "rb") as f:
            builder.add_ingredient(
                ingredient_json, "image/jpeg", f,
            )
        with (
            open(DEFAULT_TEST_FILE, "rb") as source,
            io.BytesIO(bytearray()) as output,
        ):
            builder.sign(
                signer, "image/jpeg", source, output,
            )
            output.seek(0)
            reader = Reader(
                "image/jpeg", output, context=context,
            )
            validation_state = (
                reader.get_validation_state()
            )
            self.assertEqual(
                validation_state, "Trusted",
            )
            reader.close()
        archive.close()
        builder.close()
        signer.close()
        context.close()
        settings.close()

    def test_remote_sign_trusted_via_context(self):
        trust_dict = load_test_settings_json()
        settings = Settings.from_dict(trust_dict)
        context = Context(settings=settings)
        signer = self._ctx_make_signer()
        builder = Builder(
            self.test_manifest, context=context,
        )
        builder.set_no_embed()
        with open(DEFAULT_TEST_FILE, "rb") as source:
            with io.BytesIO() as output_buffer:
                manifest_data = builder.sign(
                    signer, "image/jpeg",
                    source, output_buffer,
                )
                output_buffer.seek(0)
                read_buffer = io.BytesIO(
                    output_buffer.getvalue()
                )
                reader = Reader(
                    "image/jpeg", read_buffer,
                    manifest_data, context=context,
                )
                validation_state = (
                    reader.get_validation_state()
                )
                self.assertEqual(
                    validation_state, "Trusted",
                )
                reader.close()
                read_buffer.close()
        builder.close()
        signer.close()
        context.close()
        settings.close()

    def test_sign_callback_signer_in_ctx(self):
        signer = self._ctx_make_callback_signer()
        context = Context(signer=signer)
        builder = Builder(
            self.test_manifest, context=context,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            dest_path = os.path.join(temp_dir, "out.jpg")
            with (
                open(DEFAULT_TEST_FILE, "rb") as source_file,
                open(dest_path, "w+b") as dest_file,
            ):
                manifest_bytes = builder.sign(
                    "image/jpeg",
                    source_file,
                    dest_file,
                )
                self.assertGreater(len(manifest_bytes), 0)
            reader = Reader(dest_path)
            data = reader.json()
            self.assertIsNotNone(data)
            reader.close()
        builder.close()
        context.close()


class TestStreamReferences(unittest.TestCase):

    def test_stream_collected_after_del(self):
        """Stream must be collected by reference counting."""
        import gc
        import weakref
        gc.collect()
        garbage_before = len(gc.garbage)

        buf = io.BytesIO(b"hello world")
        s = Stream(buf)
        ref = weakref.ref(s)
        del s

        # Trigger gc, we want to verify it's collected
        # collected now (1 gc call) means no gc cycle breaker needed
        # aka ref cycle did not happen.
        gc.collect()

        self.assertIsNone(ref(), "Stream not collected")
        self.assertEqual(len(gc.garbage), garbage_before,
                         "Stream added objects to gc.garbage")

    def test_stream_not_added_to_gc_garbage_list(self):
        """Creating and dropping many Streams must not grow gc.garbage."""
        import gc
        gc.collect()
        gc.garbage.clear()

        for _ in range(20):
            s = Stream(io.BytesIO(b"data"))
            del s

        gc.collect()
        self.assertEqual(len(gc.garbage), 0,
                         f"gc.garbage unexpectedly non-empty: {gc.garbage}")

    def test_callbacks_return_minus_one_after_stream_collected(self):
        """Callbacks must return -1 gracefully when the Stream has been GC'd."""
        import gc
        import weakref

        buf = io.BytesIO(b"test")
        s = Stream(buf)

        read_cb = s._read_cb
        seek_cb = s._seek_cb
        write_cb = s._write_cb
        flush_cb = s._flush_cb
        ref = weakref.ref(s)
        del s
        gc.collect()

        # Stream should be gone.
        self.assertIsNone(ref(), "Stream not collected before callback test")

        # All callbacks must return -1 without crashing.
        self.assertEqual(read_cb(None, None, 0), -1)
        self.assertEqual(seek_cb(None, 0, 0), -1)
        self.assertEqual(write_cb(None, None, 0), -1)
        self.assertEqual(flush_cb(None), -1)


class TestManagedResourceLifecycle(unittest.TestCase):
    """Lifecycle primitives (_activate, _swap_handle, _wrap_native_handle),
    the _owner_pid stamp that governs which process may free a handle, and
    the ownership hand-offs between Python and the native library.

    For testing: setUp records frees instead of performing them,
    so a miscount reads as memory handling issue.
    Tests releasing real handles call _use_real_frees() first to
    restore release behavior.
    """

    class _FakeHandleResource(ManagedResource):
        """Concrete subclass with no resources of its own."""

    class _CallbackHoldingResource(ManagedResource):
        """Mimics Signer: its _release() reads an attribute that _init_attrs()
        is responsible for defaulting."""

        def _release(self):
            if self._callback_cb:
                self._callback_cb = None

    class _ReleaseRecordingResource(ManagedResource):
        """Records _release() calls for test asserts."""

        def __init__(self):
            super().__init__()
            self.release_calls = 0

        def _release(self):
            self.release_calls += 1

    class _ExtenderResource(ManagedResource):
        """For testing: An extender that owns a raw handle and wraps it via
        _wrap_native_handle. It carries several attributes of its own, all
        defaulted in _init_attrs (not __init__), and _release reads them, so a
        missing attribute would surface as an AttributeError on test teardown.
        """

        def _init_attrs(self):
            super()._init_attrs()
            self.label = "extender"
            self.buffer = []
            self.released = False

        def _release(self):
            # Reads attributes _init_attrs is responsible for defaulting.
            self.buffer.append(self.label)
            self.released = True

    def setUp(self):
        self.data_dir = FIXTURES_DIR
        self.freed = []
        self._real_free = ManagedResource._free_native_ptr
        ManagedResource._free_native_ptr = staticmethod(self.freed.append)

    def tearDown(self):
        ManagedResource._free_native_ptr = self._real_free

    def _free_counts(self):
        counts = {}
        for handle in self.freed:
            counts[handle] = counts.get(handle, 0) + 1
        return counts

    def _use_real_frees(self):
        """Undo free recorder, so native handles are really freed."""
        ManagedResource._free_native_ptr = self._real_free

    def _make_signer(self):
        with open(os.path.join(self.data_dir, "es256_certs.pem"), "rb") as f:
            certs = f.read()
        with open(os.path.join(self.data_dir, "es256_private.key"), "rb") as f:
            key = f.read()
        return Signer.from_info(C2paSignerInfo(
            b"es256", certs, key, b"http://timestamp.digicert.com"))

    def test_release_failure_still_frees_handle(self):
        res = self._CallbackHoldingResource()
        # _callback_cb is never set, so _release() raises AttributeError.
        res._activate(0xBBBB)

        res.close()

        self.assertEqual(self.freed, [0xBBBB],
                         "handle leaked when _release() raised")
        self.assertIsNone(res._handle)

    def test_release_failure_is_logged(self):
        res = self._CallbackHoldingResource()
        res._activate(0xBBBB)

        with self.assertLogs('c2pa', level='ERROR') as captured:
            res.close()

        self.assertTrue(
            any('Failed to release' in line for line in captured.output),
            f"_release() failure was not logged: {captured.output}")

    def test_activate_rejects_null_handle(self):
        res = self._FakeHandleResource()

        with self.assertRaises(Error) as ctx:
            res._activate(None)

        self.assertIn("null handle", str(ctx.exception))
        self.assertEqual(res._lifecycle_state, LifecycleState.UNINITIALIZED)

    def test_activate_rejects_double_activation(self):
        res = self._FakeHandleResource()
        res._activate(0x1111)

        with self.assertRaises(Error) as ctx:
            res._activate(0x2222)

        self.assertIn("already activated", str(ctx.exception))
        # The first handle is still owned, and is freed exactly once.
        self.assertEqual(res._handle, 0x1111)
        res.close()
        self.assertEqual(self.freed, [0x1111])

    def test_activate_rejects_reactivation_after_close(self):
        res = self._FakeHandleResource()
        res._activate(0x3333)
        res.close()
        self.freed.clear()

        with self.assertRaises(Error):
            res._activate(0x4444)

        # Staying CLOSED is what prevents a second free of the handle.
        self.assertEqual(res._lifecycle_state, LifecycleState.CLOSED)
        self.assertIsNone(res._handle)
        self.assertEqual(self.freed, [])

    def test_activate_does_not_mutate_on_rejection(self):
        res = self._FakeHandleResource()
        res._activate(0x5555)

        with self.assertRaises(Error):
            res._activate(0x6666)

        self.assertEqual(res._handle, 0x5555,
                         "rejected activation replaced the handle")
        self.assertEqual(res._lifecycle_state, LifecycleState.ACTIVE)

    def test_swap_handle_does_not_free_consumed_handle(self):
        res = self._FakeHandleResource()
        res._activate(0xAAA1)

        res._swap_handle(0xAAA2)

        # The FFI already owns and frees the old pointer.
        self.assertEqual(self.freed, [])
        self.assertEqual(res._handle, 0xAAA2)

        res.close()
        self.assertEqual(self.freed, [0xAAA2])

    def test_swap_handle_requires_active_resource(self):
        uninitialized = self._FakeHandleResource()
        with self.assertRaises(Error) as ctx:
            uninitialized._swap_handle(0x1)
        self.assertIn("not active", str(ctx.exception))

        closed = self._FakeHandleResource()
        closed._activate(0x2)
        closed.close()
        with self.assertRaises(Error):
            closed._swap_handle(0x3)

    def test_swap_handle_rejects_null_replacement(self):
        res = self._FakeHandleResource()
        res._activate(0x7777)

        with self.assertRaises(Error) as ctx:
            res._swap_handle(None)

        self.assertIn("null handle", str(ctx.exception))
        self.assertEqual(res._handle, 0x7777)
        self.assertEqual(res._lifecycle_state, LifecycleState.ACTIVE)

    def test_wrap_native_handle_bypasses_init(self):
        seen = []

        class Probe(ManagedResource):
            def __init__(self):
                raise AssertionError("__init__ must be bypassed")

            def _init_attrs(self):
                super()._init_attrs()
                self._tag = 'from _init_attrs'

            def _release(self):
                seen.append(self._tag)

        obj = Probe._wrap_native_handle(0xC0DE)

        self.assertEqual(obj._tag, 'from _init_attrs')
        self.assertEqual(obj._lifecycle_state, LifecycleState.ACTIVE)
        self.assertTrue(obj.is_valid)
        self.assertTrue(hasattr(obj, '_owner_pid'))

        obj.close()
        self.assertEqual(seen, ['from _init_attrs'],
                         "_release() could not see the class's own attrs")

    def test_wrap_native_handle_rejects_null(self):
        with self.assertRaises(Error):
            self._FakeHandleResource._wrap_native_handle(None)

    def test_close_after_wrap_is_idempotent(self):
        obj = self._FakeHandleResource._wrap_native_handle(0xD00D)

        obj.close()
        obj.close()

        self.assertEqual(self.freed, [0xD00D], "handle freed more than once")

    def test_every_construction_path_records_owner_pid(self):
        pid = os.getpid()

        plain = self._FakeHandleResource()
        self.assertEqual(plain._owner_pid, pid)

        activated = self._FakeHandleResource()
        activated._activate(0xA1)
        self.assertEqual(activated._owner_pid, pid)

        wrapped = self._FakeHandleResource._wrap_native_handle(0xA2)
        self.assertEqual(wrapped._owner_pid, pid)

        # A swap keeps the original stamp:
        # the replacement handle was allocated by the same process
        # that created the object.
        wrapped._swap_handle(0xA3)
        self.assertEqual(wrapped._owner_pid, pid)

    def test_foreign_child_skips_free_for_wrapped_and_swapped(self):
        wrapped = self._FakeHandleResource._wrap_native_handle(0xC1)
        wrapped._owner_pid = os.getpid() + 1
        wrapped.close()

        swapped = self._FakeHandleResource()
        swapped._activate(0xC2)
        swapped._swap_handle(0xC3)
        swapped._owner_pid = os.getpid() + 1
        swapped.close()

        self.assertEqual(self.freed, [],
                         "forked child freed a pointer its parent still owns")
        # The child must not free a pointer the parent still owns.
        # The child does mark its own copies closed and nulls their handles,
        # which stops the child from reusing a parent-owned handle.
        self.assertEqual(wrapped._lifecycle_state, LifecycleState.CLOSED)
        self.assertIsNone(wrapped._handle)
        self.assertEqual(swapped._lifecycle_state, LifecycleState.CLOSED)
        self.assertIsNone(swapped._handle)

        # A second foreign teardown is a no-op.
        wrapped.close()
        swapped.close()
        self.assertEqual(self.freed, [])

    def test_owning_process_frees_wrapped_and_swapped_exactly_once(self):
        wrapped = self._FakeHandleResource._wrap_native_handle(0xC4)
        wrapped.close()
        wrapped.close()

        swapped = self._FakeHandleResource()
        swapped._activate(0xC5)
        swapped._swap_handle(0xC6)
        swapped.close()

        # 0xC5 was consumed by the test FFI swap.
        # Only the replacement must be freed here.
        self.assertEqual(self._free_counts(), {0xC4: 1, 0xC6: 1})

    def test_foreign_child_skips_release(self):
        foreign = self._ReleaseRecordingResource()
        foreign._activate(0xD1)
        foreign._owner_pid = os.getpid() + 1
        foreign.close()
        self.assertEqual(foreign.release_calls, 0)

        owned = self._ReleaseRecordingResource()
        owned._activate(0xD2)
        owned.close()
        self.assertEqual(owned.release_calls, 1)

    def test_consumed_resource_frees_nothing_in_either_process(self):
        owned = self._FakeHandleResource()
        owned._activate(0xE1)
        owned._teardown(free_handle=False)
        owned.close()

        foreign = self._FakeHandleResource()
        foreign._activate(0xE2)
        foreign._teardown(free_handle=False)
        foreign._owner_pid = os.getpid() + 1
        foreign.close()

        self.assertEqual(self.freed, [])

    # Consuming a handle hands the native pointer to a new owner.
    # The Python-side resources are still ours to free.
    def test_teardown_consumed_releases_python_resources(self):
        res = self._ReleaseRecordingResource()
        res._activate(0xF1)

        res._teardown(free_handle=False)

        self.assertEqual(res.release_calls, 1)
        self.assertEqual(res._lifecycle_state, LifecycleState.CLOSED)
        self.assertIsNone(res._handle)
        self.assertEqual(self.freed, [])

    def test_teardown_consumed_swallows_failing_release(self):
        res = self._CallbackHoldingResource()
        res._activate(0xF2)

        with self.assertLogs("c2pa", level="ERROR"):
            res._teardown(free_handle=False)

        self.assertEqual(res._lifecycle_state, LifecycleState.CLOSED)
        self.assertIsNone(res._handle)

    def test_teardown_consumed_in_foreign_process_skips_release(self):
        res = self._ReleaseRecordingResource()
        res._activate(0xF3)
        res._owner_pid = os.getpid() + 1

        res._teardown(free_handle=False)

        self.assertEqual(res.release_calls, 0)
        self.assertEqual(res._lifecycle_state, LifecycleState.CLOSED)
        self.assertIsNone(res._handle)

    def test_extender_wraps_handle_fully_built(self):
        obj = self._ExtenderResource._wrap_native_handle(0xE0)

        # Every attribute _init_attrs defaults is present,
        # even though __init__ never ran.
        self.assertEqual(obj.label, "extender")
        self.assertEqual(obj.buffer, [])
        self.assertFalse(obj.released)
        self.assertTrue(obj.is_valid)
        self.assertEqual(obj._owner_pid, os.getpid())

        # _release reads those attributes, so a missing one will raise here.
        obj.close()
        obj.close()

        self.assertTrue(obj.released)
        self.assertEqual(obj.buffer, ["extender"])
        self.assertEqual(self.freed, [0xE0], "wrapped handle freed once")

    def test_extender_foreign_teardown_skips_native_free(self):
        obj = self._ExtenderResource._wrap_native_handle(0xE1)
        # Stamp a foreign owner:
        # teardown runs in a process that did not create the handle,
        # so it must not free the pointer or run _release.
        obj._owner_pid = os.getpid() + 1

        obj.close()

        self.assertEqual(self.freed, [],
                         "forked child freed a handle its parent still owns")
        self.assertFalse(obj.released, "foreign teardown ran _release")
        # The child marks its own copy closed and nulls the handle:
        # the parent holds a separate copy and it stops the
        # child reusing a parent-owned handle.
        self.assertEqual(obj._lifecycle_state, LifecycleState.CLOSED)
        self.assertIsNone(obj._handle)

        # A second foreign teardown stays a no-op,
        # and any operation on the now-closed child copy fails.
        obj.close()
        self.assertEqual(self.freed, [])
        with self.assertRaises(Error):
            obj._ensure_valid_state()

    def test_signer_init_rejects_null_pointer(self):
        with self.assertRaises(Error):
            Signer(None)

    def test_builder_from_archive_wraps_handle(self):
        self._use_real_frees()
        archive = io.BytesIO()
        Builder({"claim_generator": "test", "format": "image/jpeg"}).to_archive(
            archive)

        builder = Builder.from_archive(io.BytesIO(archive.getvalue()))

        self.assertTrue(builder.is_valid)
        self.assertIsNone(builder._context)
        self.assertFalse(builder._has_context_signer)
        builder.close()
        self.assertEqual(builder._lifecycle_state, LifecycleState.CLOSED)

    def test_context_build_failure_consumes_signer(self):
        self._use_real_frees()
        signer = self._make_signer()
        real_build = c2pa_module._lib.c2pa_context_builder_build
        c2pa_module._lib.c2pa_context_builder_build = lambda ptr: None
        try:
            with self.assertRaises(Error):
                Context(signer=signer)
        finally:
            c2pa_module._lib.c2pa_context_builder_build = real_build

        self.assertIsNone(signer._handle,
                          "Signer still holds a pointer the native side freed")
        self.assertEqual(signer._lifecycle_state, LifecycleState.CLOSED)

        # Nothing left to free, so close() must be a no-op.
        freed = []
        real_free = ManagedResource._free_native_ptr
        ManagedResource._free_native_ptr = staticmethod(freed.append)
        try:
            signer.close()
        finally:
            ManagedResource._free_native_ptr = real_free
        self.assertEqual(freed, [])

    def test_context_with_signer_consumes_it_on_success(self):
        self._use_real_frees()
        signer = self._make_signer()

        context = Context(signer=signer)

        self.assertTrue(context.is_valid)
        self.assertIsNone(signer._handle)
        self.assertEqual(signer._lifecycle_state, LifecycleState.CLOSED)
        self.assertTrue(context.has_signer)
        context.close()

    def test_construction_failure_leaves_nothing_to_free(self):
        # Activation happens after the null check, so a failed construction
        # has no handle on the object that __del__ can find.
        real_new = c2pa_module._lib.c2pa_context_new
        c2pa_module._lib.c2pa_context_new = lambda: None
        try:
            with self.assertRaises(Error):
                Context()
        finally:
            c2pa_module._lib.c2pa_context_new = real_new

        real_json = c2pa_module._lib.c2pa_builder_from_json
        c2pa_module._lib.c2pa_builder_from_json = lambda j: None
        try:
            with self.assertRaises(Error):
                Builder({"claim_generator": "test"})
        finally:
            c2pa_module._lib.c2pa_builder_from_json = real_json

    def test_context_build_null_return_frees_builder(self):
        # Set a pre-consume tag in the error slot to mock a pointer rejection.
        settings = Settings()
        c2pa_module._lib.c2pa_error_set_last(
            b"UntrackedPointer: mocked pre-consume rejection")
        real_build = c2pa_module._lib.c2pa_context_builder_build
        c2pa_module._lib.c2pa_context_builder_build = lambda ptr: None
        try:
            with self.assertRaises(Error):
                Context(settings=settings)
        finally:
            c2pa_module._lib.c2pa_context_builder_build = real_build

        # One free: the un-consumed builder.
        # Settings borrows, so it is not freed here.
        self.assertEqual(len(self.freed), 1,
                         "un-consumed builder leaked on build failure")
        settings.close()

    def test_consume_no_replacement_marks_consumed_on_success(self):
        res = self._FakeHandleResource()
        res._activate(0xCAFE)

        res._consume_no_replacement(lambda h: 0, "set failed: {}")

        # Native took ownership.
        self.assertEqual(self.freed, [])
        self.assertIsNone(res._handle)
        self.assertEqual(res._lifecycle_state, LifecycleState.CLOSED)

    def test_consume_no_replacement_retains_on_pre_consume_tag(self):
        res = self._FakeHandleResource()
        res._activate(0xCAFE)
        real_read = c2pa_module._read_native_error
        c2pa_module._read_native_error = lambda: "UntrackedPointer: rejected"
        try:
            with self.assertRaises(Error):
                res._consume_no_replacement(lambda h: -1, "set failed: {}")
        finally:
            c2pa_module._read_native_error = real_read

        # Rejected before ownership transferred: handle retained.
        self.assertEqual(res._handle, 0xCAFE)
        self.assertEqual(res._lifecycle_state, LifecycleState.ACTIVE)
        self.assertEqual(self.freed, [])
        res.close()
        self.assertEqual(self.freed, [0xCAFE])

    def test_consume_no_replacement_marks_consumed_on_other_error(self):
        res = self._FakeHandleResource()
        res._activate(0xCAFE)
        real_read = c2pa_module._read_native_error
        c2pa_module._read_native_error = lambda: "OtherError: boom"
        try:
            with self.assertRaises(Error):
                res._consume_no_replacement(lambda h: -1, "set failed: {}")
        finally:
            c2pa_module._read_native_error = real_read

        # A non-tag error means native took ownership then failed and dropped
        # the value itself: mark consumed, do not free.
        self.assertEqual(self.freed, [])
        self.assertIsNone(res._handle)
        self.assertEqual(res._lifecycle_state, LifecycleState.CLOSED)


class TestManagedResourceObjects(TestContextAPIs):
    """Tests native resource handling management when managed manually.
    """

    @staticmethod
    def _ptr_addr(ptr):
        """Address a ctypes pointer points at, or None for a null pointer.

        ctypes pointers compare by identity, not by value: two pointer objects
        for the same address are unequal. Compare addresses instead.
        """
        if not ptr:
            return None
        return ctypes.cast(ptr, ctypes.c_void_p).value

    def _instrument_frees(self):
        """Record frees instead of performing them, and restore on teardown.
        """
        freed = []
        real_free = ManagedResource._free_native_ptr
        ManagedResource._free_native_ptr = staticmethod(freed.append)
        self.addCleanup(
            lambda: setattr(
                ManagedResource, '_free_native_ptr', real_free))
        return freed

    def _free_count(self, freed, handle):
        """How many times `handle` was freed, ignoring unrelated frees."""
        target = self._ptr_addr(handle)
        self.assertIsNotNone(target, "cannot count frees of a null handle")
        return sum(1 for ptr in freed if self._ptr_addr(ptr) == target)

    def _make_archive(self, manifest=None):
        archive = io.BytesIO()
        builder = Builder(manifest or self.test_manifest)
        try:
            builder.to_archive(archive)
        finally:
            builder.close()
        archive.seek(0)
        return archive

    def test_settings_activation_paths(self):
        pid = os.getpid()
        for label, factory in (
            ("Settings()", lambda: Settings()),
            ("from_json", lambda: Settings.from_json('{"version_major": 1}')),
            ("from_dict", lambda: Settings.from_dict({"version_major": 1})),
        ):
            with self.subTest(path=label):
                settings = factory()
                try:
                    self.assertTrue(settings.is_valid)
                    self.assertEqual(settings._owner_pid, pid)
                finally:
                    settings.close()

    def test_context_activation_paths(self):
        pid = os.getpid()
        settings = Settings.from_dict({"version_major": 1})
        try:
            for label, factory in (
                # No settings and no signer takes the c2pa_context_new path.
                ("Context()", lambda: Context()),
                # Anything else goes through the ContextBuilder path.
                ("Context(settings)", lambda: Context(settings)),
                ("from_dict", lambda: Context.from_dict({"version_major": 1})),
                ("builder()",
                 lambda: Context.builder().with_settings(settings).build()),
            ):
                with self.subTest(path=label):
                    context = factory()
                    try:
                        self.assertTrue(context.is_valid)
                        self.assertEqual(context._owner_pid, pid)
                    finally:
                        context.close()
        finally:
            settings.close()

    def test_reader_activation_paths(self):
        pid = os.getpid()
        context = Context()
        try:
            with open(DEFAULT_TEST_FILE, "rb") as f:
                from_stream = Reader("image/jpeg", f)
            self.addCleanup(from_stream.close)
            self.assertEqual(from_stream._owner_pid, pid)

            from_path = Reader(DEFAULT_TEST_FILE)
            self.addCleanup(from_path.close)
            self.assertEqual(from_path._owner_pid, pid)

            with open(DEFAULT_TEST_FILE, "rb") as f:
                with_context = Reader(DEFAULT_TEST_FILE, context=context)
            self.addCleanup(with_context.close)
            self.assertEqual(with_context._owner_pid, pid)

            with open(DEFAULT_TEST_FILE, "rb") as f:
                created = Reader.try_create("image/jpeg", f)
            self.addCleanup(created.close)
            self.assertEqual(created._owner_pid, pid)
        finally:
            context.close()

    def test_builder_activation_paths(self):
        pid = os.getpid()
        context = Context()
        try:
            plain = Builder(self.test_manifest)
            self.addCleanup(plain.close)
            self.assertEqual(plain._owner_pid, pid)

            from_json = Builder.from_json(self.test_manifest)
            self.addCleanup(from_json.close)
            self.assertEqual(from_json._owner_pid, pid)

            with_context = Builder(self.test_manifest, context=context)
            self.addCleanup(with_context.close)
            self.assertEqual(with_context._owner_pid, pid)

            # from_archive is the only caller of _wrap_native_handle,
            # which bypasses __init__ entirely
            wrapped = Builder.from_archive(self._make_archive())
            self.addCleanup(wrapped.close)
            self.assertEqual(wrapped._owner_pid, pid)
            self.assertIsNone(wrapped._context)
            self.assertFalse(wrapped._has_context_signer)
        finally:
            context.close()

    def test_signer_activation_paths(self):
        signer = self._ctx_make_signer()
        self.addCleanup(signer.close)
        self.assertTrue(signer.is_valid)
        self.assertEqual(signer._owner_pid, os.getpid())

        callback_signer = self._ctx_make_callback_signer()
        self.addCleanup(callback_signer.close)
        self.assertEqual(callback_signer._owner_pid, os.getpid())

    def test_builder_with_archive_swaps_the_handle(self):
        context = Context()
        self.addCleanup(context.close)
        builder = Builder(self.test_manifest, context=context)
        original_handle = builder._handle
        original_stamp = builder._owner_pid

        result = builder.with_archive(self._make_archive())

        self.assertIs(result, builder, "with_archive should return self")
        self.assertNotEqual(builder._handle, original_handle,
                            "the native handle was not replaced")
        self.assertEqual(builder._lifecycle_state, LifecycleState.ACTIVE)
        # The replacement came from this process, the stamp still applies.
        self.assertEqual(builder._owner_pid, original_stamp)
        self.assertEqual(builder._owner_pid, os.getpid())
        builder.close()

    def test_reader_with_fragment_swaps_the_handle(self):
        init_path = os.path.join(FIXTURES_DIR, "dashinit.mp4")
        fragment_path = os.path.join(FIXTURES_DIR, "dash1.m4s")
        context = Context()
        self.addCleanup(context.close)

        with open(init_path, "rb") as init:
            reader = Reader("video/mp4", init, context=context)
        self.addCleanup(reader.close)
        original_handle = reader._handle

        # The Reader consumed the first handle, so the init stream is reopened.
        with open(init_path, "rb") as init, open(fragment_path, "rb") as frag:
            result = reader.with_fragment("video/mp4", init, frag)

        self.assertIs(result, reader, "with_fragment should return self")
        self.assertNotEqual(reader._handle, original_handle,
                            "the native handle was not replaced")
        self.assertEqual(reader._lifecycle_state, LifecycleState.ACTIVE)
        self.assertEqual(reader._owner_pid, os.getpid())

    def test_swapped_builder_is_freed_exactly_once(self):
        context = Context()
        self.addCleanup(context.close)
        builder = Builder(self.test_manifest, context=context)
        original_handle = builder._handle
        archive = self._make_archive()

        # Instrument across the swap so a free of the consumed pointer is recorded.
        freed = self._instrument_frees()
        builder.with_archive(archive)
        swapped_handle = builder._handle

        self.assertEqual(self._free_count(freed, original_handle), 0,
                         "the swap freed the consumed pointer")

        builder.close()
        builder.close()

        # Only the replacement is must be freed here.
        self.assertEqual(self._free_count(freed, swapped_handle), 1)
        self.assertEqual(self._free_count(freed, original_handle), 0)

    def test_repeated_swaps_on_one_builder(self):
        # Each with_archive consumes the handle the previous one returned, so
        # a chain of swaps is where a wrong swap surfaces: keeping the
        # consumed pointer makes the next call raise UntrackedPointer from
        # the native registry.
        context = Context()
        self.addCleanup(context.close)
        builder = Builder(self.test_manifest, context=context)
        self.addCleanup(builder.close)

        seen = [builder._handle]
        for _ in range(5):
            builder.with_archive(self._make_archive())
            self.assertEqual(builder._lifecycle_state, LifecycleState.ACTIVE)
            seen.append(builder._handle)

        self.assertTrue(builder.is_valid)
        self.assertEqual(builder._owner_pid, os.getpid())

    def test_context_consumes_signer_but_not_settings(self):
        settings = Settings.from_dict({"version_major": 1})
        signer = self._ctx_make_signer()

        context = Context(settings=settings, signer=signer)
        self.addCleanup(context.close)

        # The signer pointer moved to the native context builder.
        self.assertIsNone(signer._handle)
        self.assertEqual(signer._lifecycle_state, LifecycleState.CLOSED)
        self.assertTrue(context.has_signer)

        # Settings are copied, not consumed, so the caller still owns them.
        self.assertTrue(settings.is_valid)
        self.assertEqual(settings._owner_pid, os.getpid())
        settings.close()

    def test_consumed_signer_close_frees_nothing(self):
        signer = self._ctx_make_signer()
        # Captured before the context consumes it:
        # close() nulls the handle, there is no pointer left to identify the free by.
        signer_handle = signer._handle
        context = Context(signer=signer)
        self.addCleanup(context.close)

        freed = self._instrument_frees()
        signer.close()

        self.assertEqual(self._free_count(freed, signer_handle), 0,
                         "closing a consumed Signer freed a pointer the "
                         "context now owns")

    def test_builder_with_archive_null_return_marks_consumed(self):
        builder = Builder(self.test_manifest)
        released_handle = builder._handle
        archive = self._make_archive()

        # Mimic a non-tag error: native took ownership then failed and dropped
        # the value itself, so the handle is marked consumed, not freed.
        c2pa_module._lib.c2pa_error_set_last(b"Other: mocked test error")
        real_call = c2pa_module._lib.c2pa_builder_with_archive
        c2pa_module._lib.c2pa_builder_with_archive = lambda b, s: None

        # Instrument before the failure...
        freed = self._instrument_frees()
        try:
            with self.assertRaises(Error):
                builder.with_archive(archive)
        finally:
            c2pa_module._lib.c2pa_builder_with_archive = real_call

        # Nothing left to own after failing.
        self.assertIsNone(builder._handle)
        self.assertEqual(builder._lifecycle_state, LifecycleState.CLOSED)

        # A non-tag error marks consumed: no free (a free here would be a
        # guarded no-op that dirties the error slot and races a recycled
        # address in other threads).
        self.assertEqual(self._free_count(freed, released_handle), 0,
                         "consumed handle was freed instead of marked consumed")

        # close() must not free it either.
        builder.close()
        self.assertEqual(self._free_count(freed, released_handle), 0,
                         "close() freed a handle already marked consumed")

    def test_reader_with_fragment_null_return_marks_consumed(self):
        init_path = os.path.join(FIXTURES_DIR, "dashinit.mp4")
        fragment_path = os.path.join(FIXTURES_DIR, "dash1.m4s")
        with open(init_path, "rb") as init:
            reader = Reader("video/mp4", init)
        released_handle = reader._handle

        # Mimic a non-tag error: native took ownership then failed and dropped
        # the value itself, so the handle is marked consumed, not freed.
        c2pa_module._lib.c2pa_error_set_last(b"Other: mocked test error")

        real_call = c2pa_module._lib.c2pa_reader_with_fragment
        c2pa_module._lib.c2pa_reader_with_fragment = (
            lambda r, f, s, frag: None)

        # Instrument before failure so any free would be counted.
        freed = self._instrument_frees()
        try:
            with open(init_path, "rb") as init, \
                    open(fragment_path, "rb") as frag:
                with self.assertRaises(Error):
                    reader.with_fragment("video/mp4", init, frag)
        finally:
            c2pa_module._lib.c2pa_reader_with_fragment = real_call

        self.assertIsNone(reader._handle)
        self.assertEqual(reader._lifecycle_state, LifecycleState.CLOSED)

        # A non-tag error marks consumed: no free.
        self.assertEqual(self._free_count(freed, released_handle), 0,
                         "consumed handle was freed instead of marked consumed")

        # close() must not free it either.
        reader.close()
        self.assertEqual(self._free_count(freed, released_handle), 0,
                         "close() freed a handle already marked consumed")

    def test_reader_with_fragment_ffi_raise_frees_self(self):
        # If the ctypes call itself raises, the failure runs
        # through the except BaseException branch, which frees the handle.
        # with_fragment must free exactly once and leave nothing for close().
        init_path = os.path.join(FIXTURES_DIR, "dashinit.mp4")
        fragment_path = os.path.join(FIXTURES_DIR, "dash1.m4s")
        with open(init_path, "rb") as init:
            reader = Reader("video/mp4", init)
        released_handle = reader._handle

        def _raise(*_args):
            raise RuntimeError("boom")

        real_call = c2pa_module._lib.c2pa_reader_with_fragment
        c2pa_module._lib.c2pa_reader_with_fragment = _raise

        # Instrument before the failure so the eager free is counted.
        freed = self._instrument_frees()
        try:
            with open(init_path, "rb") as init, \
                    open(fragment_path, "rb") as frag:
                with self.assertRaises(Error):
                    reader.with_fragment("video/mp4", init, frag)
        finally:
            c2pa_module._lib.c2pa_reader_with_fragment = real_call

        self.assertIsNone(reader._handle)
        self.assertEqual(reader._lifecycle_state, LifecycleState.CLOSED)

        # The error path frees the old handle.
        self.assertEqual(self._free_count(freed, released_handle), 1,
                         "error path did not free the old handle exactly once")

        # close() must not free it again.
        reader.close()
        self.assertEqual(self._free_count(freed, released_handle), 1,
                         "close() freed a handle the error path already freed")

    # Consume-and-return ownership: the native call can take the handle partway
    # through the call, so a null return does not always say on its own
    # whether the handle was consumed or not, warranting further checks/bookkeeping.

    @staticmethod
    def _is_pre_consume_rejection(error_message):
        """True if this native error means ownership never transferred."""
        if not error_message:
            return False
        return any(tag in error_message
                   for tag in ManagedResource._PRE_CONSUME_ERROR_TAGS)

    def _stale_reader_handle(self):
        """A freed, untracked pointer, captured before close() nulls it.

        Take a fresh one per call: recycled addresses become tracked again.
        """
        init_path = os.path.join(FIXTURES_DIR, "dashinit.mp4")
        with open(init_path, "rb") as init:
            victim = Reader("video/mp4", init)
        stale = ctypes.cast(victim._handle,
                            ctypes.POINTER(c2pa_module.C2paReader))
        victim.close()
        return stale

    @staticmethod
    def _untracked_reader_handle():
        """A pointer the native registry never handed out.

        Rejected like a stale handle, but not a freed address, so it cannot
        be recycled and start passing the registry lookup.
        """
        buf = ctypes.create_string_buffer(64)
        return (ctypes.cast(buf, ctypes.POINTER(c2pa_module.C2paReader)),
                buf)

    def test_with_fragment_pre_consume_rejection_keeps_handle(self):
        # Rejected before native lib took ownership,
        # so nothing was consumed and the handle is still ours.
        init_path = os.path.join(FIXTURES_DIR, "dashinit.mp4")
        fragment_path = os.path.join(FIXTURES_DIR, "dash1.m4s")
        with open(init_path, "rb") as init:
            reader = Reader("video/mp4", init)
        real_handle = reader._handle

        reader._handle = self._stale_reader_handle()
        try:
            with open(init_path, "rb") as init, \
                    open(fragment_path, "rb") as frag:
                with self.assertRaises(Error) as caught:
                    reader.with_fragment("video/mp4", init, frag)
        finally:
            reader._handle = real_handle

        self.assertIn("UntrackedPointer", str(caught.exception))
        # Ownership never transferred, so the resource stays usable.
        self.assertIsNotNone(reader._handle)
        self.assertEqual(reader._lifecycle_state, LifecycleState.ACTIVE)
        self.assertTrue(reader.json())
        reader.close()

    def test_with_fragment_pre_consume_rejection_does_not_leak(self):
        # A handle dropped on this path leaks one reader per call.
        init_path = os.path.join(FIXTURES_DIR, "dashinit.mp4")
        fragment_path = os.path.join(FIXTURES_DIR, "dash1.m4s")

        for _ in range(25):
            with open(init_path, "rb") as init:
                reader = Reader("video/mp4", init)
            real_handle = reader._handle
            reader._handle = self._stale_reader_handle()
            try:
                with open(init_path, "rb") as init, \
                        open(fragment_path, "rb") as frag:
                    with self.assertRaises(Error):
                        reader.with_fragment("video/mp4", init, frag)
            finally:
                reader._handle = real_handle
            # Still owns a working handle every time round.
            self.assertEqual(reader._lifecycle_state, LifecycleState.ACTIVE)
            self.assertTrue(reader.json())
            reader.close()

    def test_with_archive_post_consume_failure_consumes_handle(self):
        # Ownership taken, then the operation failed:
        # The handle is gone, so close() must not free it again.
        builder = Builder(json.dumps(
            {"claim_generator_info": [{"name": "test", "version": "0.1"}],
             "assertions": []}))
        consumed_handle = builder._handle

        with self.assertRaises(Error):
            builder.with_archive(io.BytesIO(b"not a valid archive"))

        self.assertIsNone(builder._handle)
        self.assertEqual(builder._lifecycle_state, LifecycleState.CLOSED)

        freed = self._instrument_frees()
        builder.close()
        self.assertEqual(self._free_count(freed, consumed_handle), 0,
                         "close() freed a handle the FFI already consumed")

    def test_with_fragment_marshalling_error_keeps_handle(self):
        # Never reaches native code, so nothing was consumed.
        init_path = os.path.join(FIXTURES_DIR, "dashinit.mp4")
        with open(init_path, "rb") as init:
            reader = Reader("video/mp4", init)
        real_handle = reader._handle

        def _bad_marshalling(*_args):
            raise ctypes.ArgumentError("wrong argument type")

        real_call = c2pa_module._lib.c2pa_reader_with_fragment
        c2pa_module._lib.c2pa_reader_with_fragment = _bad_marshalling
        try:
            with open(init_path, "rb") as init, \
                    open(init_path, "rb") as frag:
                with self.assertRaises(ctypes.ArgumentError):
                    reader.with_fragment("video/mp4", init, frag)
        finally:
            c2pa_module._lib.c2pa_reader_with_fragment = real_call

        self.assertIs(reader._handle, real_handle)
        self.assertEqual(reader._lifecycle_state, LifecycleState.ACTIVE)
        self.assertTrue(reader.json(),
                        "a marshalling failure never reached the FFI, so "
                        "the reader must still be usable")

        reader.close()

    def test_unknown_failure_drops_handle_without_freeing(self):
        # Ownership unknowable, so the handle is let go rather than freed.
        # Needs a mock: every real null return sets an error.
        init_path = os.path.join(FIXTURES_DIR, "dashinit.mp4")
        fragment_path = os.path.join(FIXTURES_DIR, "dash1.m4s")
        with open(init_path, "rb") as init:
            reader = Reader("video/mp4", init)

        consumed_handle = reader._handle
        # Simulate an error being set
        c2pa_module._lib.c2pa_error_set_last(b"Other: mocked test error")
        real_call = c2pa_module._lib.c2pa_reader_with_fragment
        c2pa_module._lib.c2pa_reader_with_fragment = (
            lambda r, f, s, frag: None)
        try:
            with open(init_path, "rb") as init, \
                    open(fragment_path, "rb") as frag:
                with self.assertRaises(Error):
                    reader.with_fragment("video/mp4", init, frag)
        finally:
            c2pa_module._lib.c2pa_reader_with_fragment = real_call

        # Unplaceable, so the handle is let go rather than freed twice.
        self.assertIsNone(reader._handle)
        self.assertEqual(reader._lifecycle_state, LifecycleState.CLOSED)

        freed = self._instrument_frees()
        reader.close()
        self.assertEqual(self._free_count(freed, consumed_handle), 0,
                         "close() freed a handle of unknown ownership")

    def test_pre_consume_rejection_is_typed(self):
        # Rejections arrive wrapped as "Other: UntrackedPointer: 0x...".
        self.assertTrue(self._is_pre_consume_rejection(
            "Other: UntrackedPointer: 0x600001234567"))
        self.assertTrue(self._is_pre_consume_rejection(
            "Other: WrongPointerType: 0x600001234567"))
        self.assertFalse(self._is_pre_consume_rejection(
            "Verify: invalid JUMBF header"))
        self.assertFalse(self._is_pre_consume_rejection(None))
        self.assertFalse(self._is_pre_consume_rejection(""))

    def test_pre_consume_tags_still_match_the_native_wording(self):
        # Classification keys on error text (the numeric code is not
        # exported), so a native rename would silently misjudge ownership.
        init_path = os.path.join(FIXTURES_DIR, "dashinit.mp4")
        fragment_path = os.path.join(FIXTURES_DIR, "dash1.m4s")
        with open(init_path, "rb") as init:
            reader = Reader("video/mp4", init)
        real_handle = reader._handle

        reader._handle = self._stale_reader_handle()
        try:
            with open(init_path, "rb") as init, \
                    open(fragment_path, "rb") as frag:
                with self.assertRaises(Error) as caught:
                    reader.with_fragment("video/mp4", init, frag)
        finally:
            reader._handle = real_handle

        message = str(caught.exception)
        self.assertTrue(
            self._is_pre_consume_rejection(message),
            f"the native rejection wording changed and no longer matches "
            f"_PRE_CONSUME_ERROR_TAGS; ownership will be misjudged: "
            f"{message!r}")
        reader.close()

    def test_stale_handle_is_actually_rejected_every_time(self):
        # A handle that stopped being rejected would quietly measure the
        # success path. Uses the never-allocated buffer: freed addresses get
        # recycled and start passing the registry lookup.
        init_path = os.path.join(FIXTURES_DIR, "dashinit.mp4")
        fragment_path = os.path.join(FIXTURES_DIR, "dash1.m4s")

        for _ in range(25):
            with open(init_path, "rb") as init:
                reader = Reader("video/mp4", init)
            real_handle = reader._handle
            bogus, _buf = self._untracked_reader_handle()
            reader._handle = bogus
            try:
                with open(init_path, "rb") as init, \
                        open(fragment_path, "rb") as frag:
                    with self.assertRaises(Error) as caught:
                        reader.with_fragment("video/mp4", init, frag)
                self.assertTrue(
                    self._is_pre_consume_rejection(
                        str(caught.exception)),
                    "the bogus handle was not rejected, so this stopped "
                    "exercising the pre-consume path")
            finally:
                reader._handle = real_handle
                reader.close()

    def test_perf_scenario_bogus_handle_is_rejected(self):
        # The perf scenarios use a plain buffer so looping does not swamp
        # the measurement. It still has to produce a real rejection.
        init_path = os.path.join(FIXTURES_DIR, "dashinit.mp4")
        fragment_path = os.path.join(FIXTURES_DIR, "dash1.m4s")
        with open(init_path, "rb") as init:
            reader = Reader("video/mp4", init)
        real_handle = reader._handle

        bogus, _buf = self._untracked_reader_handle()
        reader._handle = bogus
        try:
            with open(init_path, "rb") as init, \
                    open(fragment_path, "rb") as frag:
                with self.assertRaises(Error) as caught:
                    reader.with_fragment("video/mp4", init, frag)
        finally:
            reader._handle = real_handle

        self.assertTrue(
            self._is_pre_consume_rejection(str(caught.exception)),
            "the perf scenarios' bogus handle is no longer rejected, so "
            "with_fragment_pre_consume_rejection measures nothing")
        # Handle kept, so the reader still works and frees normally.
        self.assertEqual(reader._lifecycle_state, LifecycleState.ACTIVE)
        self.assertTrue(reader.json())
        reader.close()

    def test_every_null_return_sets_its_own_error(self):
        # Reading the slot without clearing it is only sound because every
        # null return sets an error. Check each path reports its own.
        init_path = os.path.join(FIXTURES_DIR, "dashinit.mp4")
        fragment_path = os.path.join(FIXTURES_DIR, "dash1.m4s")

        # Leave a recognisable error behind, so anything stale shows up.
        try:
            Reader("image/jpeg", io.BytesIO(b"not an image")).json()
        except Error:
            pass
        self.assertIn("NotSupported", c2pa_module._read_native_error() or "")

        # Pre-consume rejection: reports UntrackedPointer, not NotSupported.
        with open(init_path, "rb") as init:
            reader = Reader("video/mp4", init)
        real_handle = reader._handle
        reader._handle = self._stale_reader_handle()
        try:
            with open(init_path, "rb") as init, \
                    open(fragment_path, "rb") as frag:
                with self.assertRaises(Error) as caught:
                    reader.with_fragment("video/mp4", init, frag)
        finally:
            reader._handle = real_handle
        self.assertIn("UntrackedPointer", str(caught.exception))
        self.assertNotIn("NotSupported", str(caught.exception))
        reader.close()

        # Post-consume failure: reports the operation error, not the
        # UntrackedPointer left by the step above.
        builder = Builder(json.dumps(
            {"claim_generator_info": [{"name": "test", "version": "0.1"}],
             "assertions": []}))
        with self.assertRaises(Error) as caught:
            builder.with_archive(io.BytesIO(b"not a valid archive"))
        self.assertNotIn("UntrackedPointer", str(caught.exception))
        builder.close()

    def test_pre_consume_classification_holds_across_threads(self):
        # The error slot is thread-local, so concurrent calls do not mask
        # each other's errors and misjudge ownership.
        init_path = os.path.join(FIXTURES_DIR, "dashinit.mp4")
        fragment_path = os.path.join(FIXTURES_DIR, "dash1.m4s")
        init_bytes = open(init_path, "rb").read()
        frag_bytes = open(fragment_path, "rb").read()
        problems = []

        def worker():
            for _ in range(10):
                reader = Reader("video/mp4", io.BytesIO(init_bytes))
                real_handle = reader._handle
                # A never-allocated buffer, not a freed pointer: with several
                # threads churning the allocator, a freed address gets reused
                # and starts passing the registry lookup, which would end the
                # iteration in a real consume instead of a rejection.
                bogus, _buf = self._untracked_reader_handle()
                reader._handle = bogus
                try:
                    reader.with_fragment("video/mp4",
                                         io.BytesIO(init_bytes),
                                         io.BytesIO(frag_bytes))
                    problems.append("rejection did not raise")
                except Error as e:
                    if not self._is_pre_consume_rejection(str(e)):
                        problems.append(f"misclassified: {str(e)[:60]}")
                finally:
                    reader._handle = real_handle
                    if reader._lifecycle_state != LifecycleState.ACTIVE:
                        problems.append("handle dropped on a rejection")
                    reader.close()

        threads = [threading.Thread(target=worker) for _ in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(problems, [],
                         "ownership was misjudged under concurrency")

    def test_reading_the_native_error_does_not_empty_the_slot(self):
        # c2pa_error() peeks, so nothing Python can call empties the slot.
        # _consume_and_swap depends on this.
        try:
            Reader("image/jpeg", io.BytesIO(b"not an image")).json()
        except Error:
            pass

        first = c2pa_module._read_native_error()
        self.assertTrue(first, "expected a native error to have been set")

        self.assertEqual(
            c2pa_module._read_native_error(), first,
            "reading emptied the native slot; the comments in "
            "_consume_and_swap about a persistent error are now wrong")

    def test_read_native_error_returns_none_for_an_empty_message(self):
        # c2pa_error() returns an owned pointer to "" when no error is set,
        # never NULL, so the pointer cannot be the "is there an error" test.
        original = c2pa_module._lib.c2pa_error
        empty = ctypes.create_string_buffer(b"")

        try:
            c2pa_module._lib.c2pa_error = lambda: ctypes.cast(
                empty, ctypes.c_void_p).value
            self.assertIsNone(
                c2pa_module._read_native_error(),
                "an empty native message must read as None, otherwise "
                "callers' 'if error:' checks are only accidentally right")
        finally:
            c2pa_module._lib.c2pa_error = original

    def test_mocked_null_without_error_is_a_known_limitation(self):
        # A null with no error of its own is the case that breaks: the slot
        # still holds whatever came before. No native path does this, so it
        # is pinned here rather than defended in _consume_and_swap.
        init_path = os.path.join(FIXTURES_DIR, "dashinit.mp4")
        fragment_path = os.path.join(FIXTURES_DIR, "dash1.m4s")

        c2pa_module._lib.c2pa_error_set_last(
            b"UntrackedPointer: 0xdeadbeef")

        with open(init_path, "rb") as init:
            reader = Reader("video/mp4", init)

        real_call = c2pa_module._lib.c2pa_reader_with_fragment
        c2pa_module._lib.c2pa_reader_with_fragment = (
            lambda r, f, s, frag: None)
        try:
            with open(init_path, "rb") as init, \
                    open(fragment_path, "rb") as frag:
                with self.assertRaises(Error):
                    reader.with_fragment("video/mp4", init, frag)
        finally:
            c2pa_module._lib.c2pa_reader_with_fragment = real_call
            # Nothing clears the slot, so a planted tag would follow other
            # tests around and change how their failures are classified.
            c2pa_module._lib.c2pa_error_set_last(
                b"Other: cleared by test teardown")

        # The stale tag wins, so the handle is kept. Safe here (the mock
        # consumed nothing), and the reader is still usable.
        self.assertIsNotNone(reader._handle)
        self.assertEqual(reader._lifecycle_state, LifecycleState.ACTIVE)
        reader.close()

    # Backfilling a pointer minted by a direct FFI call. Builder.from_archive
    # is the only production caller of _wrap_native_handle, so these are the
    # only tests that drive the primitive as the generic entry point it is.

    def _raw_builder_handle(self):
        manifest = json.dumps(
            {"claim_generator": "raw_ffi_test", "format": "image/jpeg"}
        ).encode("utf-8")
        handle = c2pa_module._lib.c2pa_builder_from_json(manifest)
        self.assertTrue(handle, "the FFI did not return a builder pointer")
        return handle

    def test_wrap_raw_ffi_builder_pointer(self):
        builder = Builder._wrap_native_handle(self._raw_builder_handle())

        self.assertTrue(builder.is_valid)
        self.assertEqual(builder._lifecycle_state, LifecycleState.ACTIVE)
        self.assertEqual(builder._owner_pid, os.getpid())

        archive = io.BytesIO()
        builder.to_archive(archive)
        self.assertTrue(archive.getvalue())

        builder.close()
        self.assertEqual(builder._lifecycle_state, LifecycleState.CLOSED)
        self.assertIsNone(builder._handle)

    def test_wrap_raw_ffi_settings_pointer(self):
        handle = c2pa_module._lib.c2pa_settings_new()
        self.assertTrue(handle)

        settings = Settings._wrap_native_handle(handle)
        try:
            self.assertTrue(settings.is_valid)
            self.assertEqual(settings._owner_pid, os.getpid())
            settings.set("version_major", "1")
        finally:
            settings.close()

    def test_wrap_raw_ffi_context_pointer(self):
        handle = c2pa_module._lib.c2pa_context_new()
        self.assertTrue(handle)

        context = Context._wrap_native_handle(handle)
        try:
            self.assertTrue(context.is_valid)
            self.assertEqual(context._owner_pid, os.getpid())
            # Handing the wrapped pointer back to the FFI proves it is live.
            builder = Builder(self.test_manifest, context=context)
            self.assertTrue(builder.is_valid)
            builder.close()
        finally:
            context.close()

    def test_wrapped_raw_pointer_freed_exactly_once(self):
        handle = self._raw_builder_handle()
        freed = self._instrument_frees()

        builder = Builder._wrap_native_handle(handle)
        builder.close()
        builder.close()
        del builder
        gc.collect()

        self.assertEqual(self._free_count(freed, handle), 1,
                         "wrapped handle not freed exactly once")

    def test_wrap_supplies_defaults(self):
        # _init_attrs() runs on the wrap path, so an instance built around a
        # raw handle still has everything the rest of the class reads.
        builder = Builder._wrap_native_handle(self._raw_builder_handle())
        self.addCleanup(builder.close)

        self.assertIsNone(builder._context)
        self.assertFalse(builder._has_context_signer)

    def test_init_attrs_covers_what_init_sets(self):
        # Anything __init__ sets but _init_attrs() misses is absent on a
        # wrapped instance, which is the trap _init_attrs() exists to close.
        for cls in (Builder, Context, Reader, Signer):
            with self.subTest(cls=cls.__name__):
                defaulted = set(re.findall(
                    r"self\.(_[a-z][a-z0-9_]*)\s*=",
                    inspect.getsource(cls._init_attrs)))
                assigned = set(re.findall(
                    r"self\.(_[a-z][a-z0-9_]*)\s*=",
                    inspect.getsource(cls.__init__)))
                self.assertEqual(
                    assigned - defaulted, set(),
                    f"{cls.__name__}.__init__ sets attributes that "
                    f"_init_attrs() does not default")

    def test_init_attrs_overrides_chain_to_super(self):
        # A subclass of these would silently lose the parent's defaults if
        # the chain were broken.
        for cls in (Builder, Context, Reader, Signer):
            with self.subTest(cls=cls.__name__):
                self.assertIn(
                    "super()._init_attrs()",
                    inspect.getsource(cls._init_attrs),
                    f"{cls.__name__}._init_attrs() does not chain to super()")

    def test_wrap_raw_ffi_signer_pointer(self):
        # Signer._release() reads _callback_cb, so a wrap that skipped the
        # defaults would fail during cleanup rather than at the wrap.
        freed = self._instrument_frees()

        signer = Signer._wrap_native_handle(0xABCD)
        self.assertIsNone(signer._callback_cb)
        self.assertEqual(signer._owner_pid, os.getpid())

        # Cleanup swallows a failing _release(), so the error log is the only
        # way to see one.
        with self.assertNoLogs("c2pa", level="ERROR"):
            signer.close()

        self.assertEqual(freed, [0xABCD])

    def test_signer_release_clears_callback(self):
        signer = self._ctx_make_callback_signer()
        self.assertIsNotNone(signer._callback_cb)

        signer.close()

        self.assertIsNone(signer._callback_cb)

    def test_builder_release_clears_context(self):
        context = Context()
        self.addCleanup(context.close)
        builder = Builder(self.test_manifest, context=context)

        builder.close()

        self.assertIsNone(builder._context,
                          "closed Builder still pins its Context")
        # The Builder does not own the Context, so it must not close it.
        self.assertTrue(context.is_valid)

    def test_consumed_reader_closes_backing_file(self):
        # A failed with_fragment consumes the reader.
        # # Reader(path) opened the backing file itself,
        # so nothing else will ever close it.
        reader = Reader(DEFAULT_TEST_FILE)
        backing_file = reader._backing_file
        self.assertFalse(backing_file.closed)

        # Simulate an error being set
        c2pa_module._lib.c2pa_error_set_last(b"Other: mocked test error")
        real_call = c2pa_module._lib.c2pa_reader_with_fragment
        c2pa_module._lib.c2pa_reader_with_fragment = (
            lambda r, f, s, frag: None)
        try:
            with open(DEFAULT_TEST_FILE, "rb") as main, \
                    open(DEFAULT_TEST_FILE, "rb") as frag:
                with self.assertRaises(Error):
                    reader.with_fragment("image/jpeg", main, frag)
        finally:
            c2pa_module._lib.c2pa_reader_with_fragment = real_call

        self.assertTrue(backing_file.closed,
                        "consumed Reader leaked its backing file")

    def test_consumed_builder_releases_context(self):
        context = Context()
        self.addCleanup(context.close)
        builder = Builder(self.test_manifest, context=context)
        archive = self._make_archive()

        # Simulate an error being set
        c2pa_module._lib.c2pa_error_set_last(b"Other: mocked test error")
        real_call = c2pa_module._lib.c2pa_builder_with_archive
        c2pa_module._lib.c2pa_builder_with_archive = lambda b, s: None
        try:
            with self.assertRaises(Error):
                builder.with_archive(archive)
        finally:
            c2pa_module._lib.c2pa_builder_with_archive = real_call

        self.assertIsNone(builder._context,
                          "consumed Builder still pins its Context")
        self.assertTrue(context.is_valid)

    def test_context_takes_callback_before_consuming_signer(self):
        # Consuming the signer releases its callback reference,
        # so the Context has to take it first or the callback dies with the signer.
        signer = self._ctx_make_callback_signer()
        callback = signer._callback_cb
        self.assertIsNotNone(callback)

        context = Context(signer=signer)
        self.addCleanup(context.close)

        self.assertIs(context._signer_callback_cb, callback)
        self.assertIsNone(signer._callback_cb)

    def test_reader_close_closes_backing_file(self):
        # _close_streams reads the attrs _init_attrs() defaults, so this is
        # the regression guard for reading them directly.
        reader = Reader(DEFAULT_TEST_FILE)
        reader.json()
        backing_file = reader._backing_file
        self.assertIsNotNone(backing_file)

        reader.close()

        self.assertTrue(backing_file.closed, "Reader left its file open")
        self.assertIsNone(reader._backing_file)
        self.assertIsNone(reader._manifest_json_str_cache)
        self.assertIsNone(reader._manifest_data_cache)

    def test_consumed_reader_clears_caches(self):
        # Consuming marks the reader closed, so close() will not run later.
        # Anything cleanup owes the object has to happen at consume time.
        reader = Reader(DEFAULT_TEST_FILE)
        reader.json()
        self.assertIsNotNone(reader._manifest_json_str_cache)

        # Simulate an error being set
        c2pa_module._lib.c2pa_error_set_last(b"Other: mocked test error")
        real_call = c2pa_module._lib.c2pa_reader_with_fragment
        c2pa_module._lib.c2pa_reader_with_fragment = (
            lambda r, f, s, frag: None)
        try:
            with open(DEFAULT_TEST_FILE, "rb") as main, \
                    open(DEFAULT_TEST_FILE, "rb") as frag:
                with self.assertRaises(Error):
                    reader.with_fragment("image/jpeg", main, frag)
        finally:
            c2pa_module._lib.c2pa_reader_with_fragment = real_call

        self.assertIsNone(reader._manifest_json_str_cache,
                          "consumed Reader kept its manifest cache")
        self.assertIsNone(reader._manifest_data_cache)

    def test_reader_del_clears_caches(self):
        # __del__ goes through _cleanup_resources, not close(), so cache
        # clearing has to live somewhere both paths reach.
        reader = Reader(DEFAULT_TEST_FILE)
        reader.json()
        self.assertIsNotNone(reader._manifest_json_str_cache)

        # __del__ runs _cleanup_resources directly, so drive that rather than
        # dropping the reference: the assertions need the object afterwards.
        reader._cleanup_resources()

        self.assertIsNone(reader._manifest_json_str_cache,
                          "cleanup left the manifest cache alive")
        self.assertIsNone(reader._manifest_data_cache)

    def test_from_archive_frees_handle_when_wrap_fails(self):
        # The wrap raising means no Python object took ownership, so
        # from_archive still holds the handle and has to free it.
        archive = self._make_archive()  # closes a Builder; keep it off the count
        freed = self._instrument_frees()
        real_wrap = Builder._wrap_native_handle

        def _boom(*args, **kwargs):
            raise Error("wrap failed")

        Builder._wrap_native_handle = _boom
        try:
            with self.assertRaises(Error):
                Builder.from_archive(archive)
        finally:
            Builder._wrap_native_handle = real_wrap

        self.assertEqual(len(freed), 1,
                         "from_archive leaked the handle when the wrap failed")

    def test_sign_failure_chains_the_original_exception(self):
        # The wrapper re-raises as C2paError; losing __cause__ hides which
        # call actually failed.
        builder = Builder(self.test_manifest)
        signer = self._ctx_make_signer()
        self.addCleanup(signer.close)

        sentinel = RuntimeError("native call blew up")
        real_sign = c2pa_module._lib.c2pa_builder_sign

        def _boom(*args):
            raise sentinel

        c2pa_module._lib.c2pa_builder_sign = _boom
        try:
            with self.assertRaises(Error) as ctx:
                builder.sign(signer, "image/jpeg",
                             io.BytesIO(b"x"), io.BytesIO())
        finally:
            c2pa_module._lib.c2pa_builder_sign = real_sign

        self.assertIs(ctx.exception.__cause__, sentinel,
                      "signing error dropped the original exception")


class TestErrorPlumbing(unittest.TestCase):
    """Covers the error helpers themselves, which had no direct tests."""

    def _set_native_error(self, text):
        c2pa_module._lib.c2pa_error_set_last(text.encode('utf-8'))

    def test_every_error_tag_maps_to_its_typed_subclass(self):
        # The wire text is "Tag: message"; each tag gets its own subclass so
        # callers can catch precisely.
        tags = [
            "Assertion", "AssertionNotFound", "Decoding", "Encoding",
            "FileNotFound", "Io", "Json", "Manifest", "ManifestNotFound",
            "NotSupported", "Other", "RemoteManifest", "ResourceNotFound",
            "Signature", "Verify", "UntrackedPointer", "WrongPointerType",
        ]
        for tag in tags:
            with self.subTest(tag=tag):
                expected = getattr(Error, tag)
                with self.assertRaises(expected):
                    c2pa_module._raise_typed_c2pa_error(f"{tag}: detail")

    def test_unmapped_tag_falls_back_to_base_error(self):
        with self.assertRaises(Error) as ctx:
            c2pa_module._raise_typed_c2pa_error("Nonsense: detail")
        # Base class only: no subclass should claim an unknown tag.
        self.assertIs(type(ctx.exception), Error)

    def test_check_ffi_operation_result_raises_with_native_message(self):
        self._set_native_error("Io: disk exploded")
        with self.assertRaises(Error) as ctx:
            c2pa_module._check_ffi_operation_result(None, "fallback text")
        self.assertIn("disk exploded", str(ctx.exception))

    def test_check_ffi_operation_result_uses_fallback_when_slot_empty(self):
        # The slot is sticky and thread-local, so a fresh thread is the only
        # way to observe it unset.
        captured = []

        def run():
            try:
                c2pa_module._check_ffi_operation_result(None, "fallback text")
            except BaseException as e:      # noqa: BLE001 - reported below
                captured.append(e)

        t = threading.Thread(target=run)
        t.start()
        t.join()

        self.assertEqual(len(captured), 1, "expected a raise on failure")
        self.assertIsInstance(captured[0], Error)
        self.assertIn("fallback text", str(captured[0]))

    def test_check_ffi_operation_result_passes_success_through(self):
        self.assertEqual(
            c2pa_module._check_ffi_operation_result(42, "unused"), 42)

    def test_stream_creation_failure_reports_a_real_message(self):
        # Regression: used to raise bare Exception("...: None") instead of the
        # native error message.
        real = c2pa_module._lib.c2pa_create_stream
        c2pa_module._lib.c2pa_create_stream = lambda *a: None
        try:
            # With an error set, the message must carry it.
            self._set_native_error("Io: stream refused")
            with self.assertRaises(Error) as ctx:
                c2pa_module.Stream(io.BytesIO(b"x"))
            self.assertIn("stream refused", str(ctx.exception))

            # With the slot unset, the old code raised bare Exception.
            captured = []

            def run():
                try:
                    c2pa_module.Stream(io.BytesIO(b"x"))
                except BaseException as e:   # noqa: BLE001 - reported below
                    captured.append(e)

            t = threading.Thread(target=run)
            t.start()
            t.join()

            self.assertEqual(len(captured), 1, "expected a raise on failure")
            self.assertIsInstance(
                captured[0], Error,
                "stream failure must raise C2paError, not bare Exception")
            self.assertNotIn("None", str(captured[0]))
        finally:
            c2pa_module._lib.c2pa_create_stream = real

    def test_supported_mime_types_raises_instead_of_returning_empty(self):
        # Regression: `if error:` was always False, so a native failure
        # returned an empty list instead of raising. Only visible with the
        # slot unset, hence the fresh thread.
        captured = []

        def run():
            try:
                captured.append(
                    c2pa_module._get_supported_mime_types(
                        lambda count: None, None))
            except BaseException as e:      # noqa: BLE001 - reported below
                captured.append(e)

        t = threading.Thread(target=run)
        t.start()
        t.join()

        self.assertIsInstance(
            captured[0], Error,
            "a failed MIME lookup returned data instead of raising")

    def test_supported_mime_types_reports_the_native_message(self):
        self._set_native_error("Io: mime lookup failed")
        with self.assertRaises(Error) as ctx:
            c2pa_module._get_supported_mime_types(lambda count: None, None)
        self.assertIn("mime lookup failed", str(ctx.exception))


class TestErrorsStillRaiseAfterCleanup(unittest.TestCase):
    """Each surface that lost a _clear_error_state() call still reports."""

    def test_reader_on_garbage_raises(self):
        with self.assertRaises(Error):
            Reader("image/jpeg", io.BytesIO(b"not an image")).json()

    def test_signer_from_info_with_bad_certs_raises(self):
        with self.assertRaises(Error):
            c2pa_module.create_signer_from_info(C2paSignerInfo(
                alg=b"es256",
                sign_cert=b"not a certificate",
                private_key=b"not a key",
                ta_url=b"",
            ))

    def test_ed25519_sign_with_empty_data_raises(self):
        with self.assertRaises(Error):
            c2pa_module.ed25519_sign(b"", "not a key")


if __name__ == '__main__':
    unittest.main(warnings='ignore')
