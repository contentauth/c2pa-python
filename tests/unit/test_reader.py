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
import threading
from c2pa import Builder, C2paError as Error, Reader, C2paSignerInfo, Signer
from c2pa.c2pa import LifecycleState, load_settings, _get_mime_type_from_path, _encode_format
from pathlib import Path
from tests.unit._support import (
    FIXTURES_DIR,
    DEFAULT_TEST_FILE_NAME,
    DEFAULT_TEST_FILE,
    INGREDIENT_TEST_FILE,
    load_test_settings_json,
)


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

    def test_wrong_mimetype_corrected_from_bytes_on_stream(self):
        # The binding passes the format straight through.
        # The native library detects the JPEG container and ignores the mismatched format,
        # so a valid asset still reads with a wrong (or bogus) mimetype.
        with open(self.testPath, "rb") as file:
            with Reader("mimetype/does-not-exist", file) as reader:
                self.assertIn(DEFAULT_TEST_FILE_NAME, reader.json())

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

    def test_unreadable_asset_raises_not_supported(self):
        # A plain-text file is not a recognizable asset. The binding no longer
        # rejects it up front; the native library raises NotSupported when it
        # fails to detect a container.
        with tempfile.TemporaryDirectory() as tmp:
            txt = os.path.join(tmp, "C.txt")
            with open(txt, "w") as f:
                f.write("just some plain text, not an asset\n")
            with self.assertRaises(Error.NotSupported):
                Reader(txt)

    def test_try_create_unreadable_asset_raises_not_supported(self):
        with tempfile.TemporaryDirectory() as tmp:
            txt = os.path.join(tmp, "C.txt")
            with open(txt, "w") as f:
                f.write("just some plain text, not an asset\n")
            with self.assertRaises(Error.NotSupported):
                Reader.try_create(txt)

    def test_none_format_matches_empty_string_on_stream(self):
        # None and "" both request auto-detection and read the same asset.
        with open(self.testPath, "rb") as file:
            with Reader(None, file) as reader:
                none_json = reader.json()
        with open(self.testPath, "rb") as file:
            with Reader("", file) as reader:
                empty_json = reader.json()
        self.assertEqual(none_json, empty_json)
        self.assertNotIn("None", none_json[:64])
        self.assertIn(DEFAULT_TEST_FILE_NAME, none_json)

    def test_padded_format_accepted_on_stream(self):
        with open(self.testPath, "rb") as file:
            with Reader(" image/jpeg ", file) as reader:
                self.assertIn(DEFAULT_TEST_FILE_NAME, reader.json())

    def test_try_create_none_format_matches_empty_string(self):
        with open(self.testPath, "rb") as file:
            none_reader = Reader.try_create(None, file)
        self.assertIsNotNone(none_reader)
        with open(self.testPath, "rb") as file:
            empty_reader = Reader.try_create("", file)
        self.assertIsNotNone(empty_reader)
        if none_reader is not None and empty_reader is not None:
            self.assertEqual(none_reader.json(), empty_reader.json())

    def test_bare_stream_matches_empty_and_none_format(self):
        with open(self.testPath, "rb") as file:
            with Reader(file) as reader:
                bare_json = reader.json()
        with open(self.testPath, "rb") as file:
            with Reader("", file) as reader:
                empty_json = reader.json()
        with open(self.testPath, "rb") as file:
            with Reader(None, file) as reader:
                none_json = reader.json()
        self.assertEqual(bare_json, empty_json)
        self.assertEqual(bare_json, none_json)

    def test_bare_stream_keyword_form(self):
        with open(self.testPath, "rb") as file:
            with Reader(stream=file) as reader:
                self.assertIn(DEFAULT_TEST_FILE_NAME, reader.json())

    def test_bare_stream_in_memory(self):
        with open(self.testPath, "rb") as file:
            data = file.read()
        with Reader(io.BytesIO(data)) as reader:
            self.assertIn(DEFAULT_TEST_FILE_NAME, reader.json())

    def test_try_create_bare_stream(self):
        with open(self.testPath, "rb") as file:
            reader = Reader.try_create(file)
        self.assertIsNotNone(reader)
        if reader is not None:
            self.assertIn(DEFAULT_TEST_FILE_NAME, reader.json())
            reader.close()

    def test_try_create_bare_stream_keyword(self):
        with open(self.testPath, "rb") as file:
            reader = Reader.try_create(stream=file)
        self.assertIsNotNone(reader)
        if reader is not None:
            self.assertIn(DEFAULT_TEST_FILE_NAME, reader.json())
            reader.close()

    def test_bare_stream_closed_handle_raises(self):
        # Stream.is_read_stream only checks method presence
        #  so a closed handle is accepted as a stream and fails at read time.
        file = open(self.testPath, "rb")
        file.close()
        with self.assertRaises(Error):
            Reader(file)

    def test_bare_stream_with_manifest_data_keeps_manifest(self):
        # The bare-stream shift must not swallow manifest_data.
        with open(self.testPath, "rb") as file:
            with Reader(file, manifest_data=None) as reader:
                self.assertIn(DEFAULT_TEST_FILE_NAME, reader.json())

    def test_path_string_still_opens_by_path(self):
        with Reader(self.testPath) as reader:
            self.assertIn(DEFAULT_TEST_FILE_NAME, reader.json())

    def test_path_object_still_opens_by_path(self):
        with Reader(Path(self.testPath)) as reader:
            self.assertIn(DEFAULT_TEST_FILE_NAME, reader.json())

    def test_format_plus_stream_still_means_format_and_stream(self):
        with open(self.testPath, "rb") as file:
            with Reader("image/jpeg", file) as reader:
                self.assertIn(DEFAULT_TEST_FILE_NAME, reader.json())
        with open(self.testPath, "rb") as file:
            with Reader(" image/jpeg ", file) as reader:
                self.assertIn(DEFAULT_TEST_FILE_NAME, reader.json())

    def test_format_plus_path_string_still_opens_by_path(self):
        with Reader("image/jpeg", self.testPath) as reader:
            self.assertIn(DEFAULT_TEST_FILE_NAME, reader.json())

    def test_no_args_raises_clear_error(self):
        with self.assertRaises(Error) as ctx:
            Reader()
        self.assertIn("stream", str(ctx.exception).lower())

    def test_none_first_arg_no_stream_raises_clear_error(self):
        with self.assertRaises(Error) as ctx:
            Reader(None)
        self.assertIn("stream", str(ctx.exception).lower())

    def test_text_stream_matches_existing_explicit_form(self):
        with open(self.testPath, "rb") as file:
            data = file.read()
        text = data.decode("latin-1")

        def outcome(call):
            try:
                r = call()
                out = ("ok", r.json()[:0])
                r.close()
                return out
            except Exception as e:
                return ("err", type(e).__name__)
        bare = outcome(lambda: Reader(io.StringIO(text)))
        explicit = outcome(lambda: Reader("image/jpeg", io.StringIO(text)))
        self.assertEqual(bare, explicit)

    def test_read_only_object_not_treated_as_stream(self):
        # read/seek/tell but no write/flush
        class ReadOnly:
            def read(self, *a):
                return b""

            def seek(self, *a):
                return 0

            def tell(self):
                return 0
        with self.assertRaises(Error):
            Reader(ReadOnly())

    def test_unrecognized_extension_defers_to_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            asset = os.path.join(tmp, "C.test")
            shutil.copyfile(self.testPath, asset)
            with Reader(asset) as reader:
                self.assertIn(DEFAULT_TEST_FILE_NAME, reader.json())

    def test_try_create_unrecognized_extension_defers_to_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            asset = os.path.join(tmp, "C.test")
            shutil.copyfile(self.testPath, asset)
            reader = Reader.try_create(asset)
            self.assertIsNotNone(reader)
            if reader is not None:
                with reader:
                    self.assertIn(DEFAULT_TEST_FILE_NAME, reader.json())

    def test_stream_read_string_stream(self):
        with Reader("image/jpeg", self.testPath) as reader:
            json_data = reader.json()
            self.assertIn(DEFAULT_TEST_FILE_NAME, json_data)

    def test_wrong_mimetype_corrected_from_bytes_on_file(self):
        # As with a stream: a valid asset opened by path still reads when the
        # given mimetype is wrong, because the native library corrects it from
        # the detected container.
        with Reader("mimetype/does-not-exist", self.testPath) as reader:
            self.assertIn(DEFAULT_TEST_FILE_NAME, reader.json())

    def test_read_extensionless_file_path(self):
        # Extensionless file triggers type auto-detection.
        with tempfile.TemporaryDirectory() as tmp:
            no_ext = os.path.join(tmp, "C")
            shutil.copyfile(self.testPath, no_ext)
            with Reader(no_ext) as reader:
                self.assertIn(DEFAULT_TEST_FILE_NAME, reader.json())

    def test_read_extensionless_stream_empty_format(self):
        # An empty format string on a stream triggers auto-detection.
        with open(self.testPath, "rb") as file:
            with Reader("", file) as reader:
                self.assertIn(DEFAULT_TEST_FILE_NAME, reader.json())

    def test_read_wrong_extension_corrected(self):
        # A JPEG saved with a .png extension is corrected from the bytes.
        # (Read is possible and does not fail due to wrong type).
        with tempfile.TemporaryDirectory() as tmp:
            wrong = os.path.join(tmp, "C.png")
            shutil.copyfile(self.testPath, wrong)
            with Reader(wrong) as reader:
                self.assertIn(DEFAULT_TEST_FILE_NAME, reader.json())

    def test_read_wrong_mime_corrected_on_stream(self):
        # A wrong MIME hint on a stream is corrected from the bytes.
        with open(self.testPath, "rb") as file:
            with Reader("image/png", file) as reader:
                self.assertIn(DEFAULT_TEST_FILE_NAME, reader.json())

    def test_explicit_empty_format_forces_detection(self):
        # Passing "" works even when the correct format is supported.
        with open(self.testPath, "rb") as file:
            with Reader("", file) as reader:
                manifest_store = json.loads(reader.json())
                self.assertIn("active_manifest", manifest_store)

    def test_autodetect_multiformat(self):
        fixtures = [
            os.path.join(FIXTURES_DIR, "files-for-reading-tests", "CA.jpg"),
            os.path.join(FIXTURES_DIR, "video1.mp4"),
            os.path.join(FIXTURES_DIR, "files-for-reading-tests", "pdf-file.pdf"),
            os.path.join(FIXTURES_DIR, "files-for-reading-tests", "sample1_signed.wav"),
        ]
        for path in fixtures:
            with self.subTest(path=path):
                with open(path, "rb") as file:
                    with Reader("", file) as reader:
                        self.assertIn("active_manifest", json.loads(reader.json()))

    def test_dng_extension_still_special_cased(self):
        dng_path = os.path.join(FIXTURES_DIR, "C.dng")
        with Reader(dng_path) as reader:
            self.assertIn("active_manifest", json.loads(reader.json()))

    def test_garbage_stream_empty_format_raises(self):
        # Unrecognized bytes with auto-detection raise rather than crash.
        with self.assertRaises(Error):
            Reader("", io.BytesIO(b"not an asset at all"))

    def test_empty_stream_raises(self):
        # A zero-byte stream cannot be detected and raises.
        with self.assertRaises(Error):
            Reader("", io.BytesIO(b""))

    def test_truncated_corrupt_jpeg_raises(self):
        with open(self.testPath, "rb") as file:
            data = bytearray(file.read())
        # Corrupt the body while keeping the leading JPEG magic intact.
        # This will still raise errors.
        for i in range(64, min(len(data), 4096)):
            data[i] ^= 0xFF
        with self.assertRaises(Error):
            Reader("", io.BytesIO(bytes(data)))

    def test_garbage_extensionless_file_raises(self):
        # Random bytes in an extensionless file raise.
        with tempfile.TemporaryDirectory() as tmp:
            garbage = os.path.join(tmp, "garbage")
            with open(garbage, "wb") as f:
                f.write(b"this is not a media asset")
            with self.assertRaises(Error):
                Reader(garbage)

    def test_try_create_garbage_stream_raises(self):
        with self.assertRaises(Error) as context:
            Reader.try_create("", io.BytesIO(b"not an asset at all"))
        self.assertNotIn("ManifestNotFound", str(context.exception))

    def test_try_create_extensionless_no_manifest_returns_none(self):
        unsigned = os.path.join(
            FIXTURES_DIR, "files-for-signing-tests", "earth_apollo17.jpg")
        with tempfile.TemporaryDirectory() as tmp:
            no_ext = os.path.join(tmp, "unsigned")
            shutil.copyfile(unsigned, no_ext)
            self.assertIsNone(Reader.try_create(no_ext))

    def test_sub_magic_length_stream_raises(self):
        # Fewer bytes than a full magic signature cannot be detected.
        # This will raise too.
        with self.assertRaises(Error):
            Reader("", io.BytesIO(b"\xff\xd8\xff"))

    def test_preseeked_stream_is_rewound(self):
        with open(self.testPath, "rb") as file:
            data = file.read()
        stream = io.BytesIO(data)
        stream.seek(len(data) // 2)
        with Reader("", stream) as reader:
            self.assertIn(DEFAULT_TEST_FILE_NAME, reader.json())

    def test_dng_extension_with_jpeg_bytes_corrected(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake_dng = os.path.join(tmp, "fake.dng")
            shutil.copyfile(self.testPath, fake_dng)
            with Reader(fake_dng) as reader:
                self.assertIn(DEFAULT_TEST_FILE_NAME, reader.json())

    def test_stream_read_filepath_as_stream_and_parse(self):
        with Reader("image/jpeg", self.testPath) as reader:
            manifest_store = json.loads(reader.json())
            title = manifest_store["manifests"][manifest_store["active_manifest"]]["title"]
            self.assertEqual(title, DEFAULT_TEST_FILE_NAME)

    def test_get_mime_type_from_path_dng_special_cased(self):
        self.assertEqual(_get_mime_type_from_path("photo.dng"), "image/dng")

    def test_get_mime_type_from_path_uppercase_dng(self):
        self.assertEqual(_get_mime_type_from_path("PHOTO.DNG"), "image/dng")

    def test_get_mime_type_from_path_jpeg(self):
        self.assertEqual(_get_mime_type_from_path("photo.jpg"), "image/jpeg")

    def test_get_mime_type_from_path_unknown_extension_returns_empty(self):
        # An unrecognized extension yields "" so the caller can auto-detect.
        self.assertEqual(_get_mime_type_from_path("asset.unknownext"), "")

    def test_get_mime_type_from_path_no_suffix_returns_empty(self):
        self.assertEqual(_get_mime_type_from_path("asset"), "")

    def test_get_mime_type_from_path_multi_dot_uses_final_suffix(self):
        # Only the final suffix determines the type.
        self.assertEqual(
            _get_mime_type_from_path("photo.final.jpg"), "image/jpeg")

    def test_get_mime_type_from_path_compound_extension(self):
        # mimetypes treats ".gz" as an encoding, not a type suffix,
        # the type is derived from ".tar"
        result = _get_mime_type_from_path("archive.tar.gz")
        self.assertIsInstance(result, str)
        self.assertNotIn(result, ("image/jpeg", "image/dng"))

    def test_get_mime_type_from_path_hidden_dotfile_returns_empty(self):
        # Check how we handle files without suffix (usually hidden files)
        self.assertEqual(_get_mime_type_from_path(".gitignore"), "")

    def test_get_mime_type_from_path_accepts_path_object(self):
        self.assertEqual(
            _get_mime_type_from_path(Path("dir/photo.jpg")), "image/jpeg")

    def test_encode_format_blank_autodetects(self):
        # A blank format requests auto-detection.
        self.assertIsNone(_encode_format("", "Reader"))
        self.assertIsNone(_encode_format("   ", "Reader"))

    def test_encode_format_returns_bytes(self):
        self.assertEqual(
            _encode_format("image/jpeg", "Reader"), b"image/jpeg")

    def test_encode_format_case_normalized(self):
        self.assertEqual(
            _encode_format("IMAGE/JPEG", "Reader"), b"image/jpeg")

    def test_encode_format_unknown_passes_through(self):
        # The native library decides validity.
        self.assertEqual(
            _encode_format("application/zip", "Reader"), b"application/zip")

    def test_reader_accepts_path_object(self):
        with Reader(Path(self.testPath)) as reader:
            self.assertIn(DEFAULT_TEST_FILE_NAME, reader.json())

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
