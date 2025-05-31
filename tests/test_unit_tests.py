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
# each license.import unittest

import os
import io
import json
import unittest
from unittest.mock import mock_open, patch

from c2pa import  Builder, C2paError as Error,  Reader, C2paSigningAlg as SigningAlg, C2paSignerInfo, Signer, sdk_version # load_settings_file

PROJECT_PATH = os.getcwd()

testPath = os.path.join(PROJECT_PATH, "tests", "fixtures", "C.jpg")

class TestC2paSdk(unittest.TestCase):
    def test_version(self):
        self.assertIn("0.55.0", sdk_version())


class TestReader(unittest.TestCase):
    def setUp(self):
        # Use the fixtures_dir fixture to set up paths
        self.data_dir = os.path.join(os.path.dirname(__file__), "fixtures")
        self.testPath = os.path.join(self.data_dir, "C.jpg")

    def test_stream_read(self):
        with open(self.testPath, "rb") as file:
            reader = Reader("image/jpeg", file)
            json_data = reader.json()
            self.assertIn("C.jpg", json_data)

    def test_stream_read_and_parse(self):
        with open(self.testPath, "rb") as file:
            reader = Reader("image/jpeg", file)
            manifest_store = json.loads(reader.json())
            title = manifest_store["manifests"][manifest_store["active_manifest"]]["title"]
            self.assertEqual(title, "C.jpg")

    def test_reader_bad_format(self):
        with self.assertRaises(Error.NotSupported):
            with open(self.testPath, "rb") as file:
                reader = Reader("badFormat", file)

    def test_settings_trust(self):
        #load_settings_file("tests/fixtures/settings.toml")
        with open(self.testPath, "rb") as file:
            reader = Reader("image/jpeg", file)
            json_data = reader.json()
            self.assertIn("C.jpg", json_data)

class TestBuilder(unittest.TestCase):
    def setUp(self):
        # Use the fixtures_dir fixture to set up paths
        self.data_dir = os.path.join(os.path.dirname(__file__), "fixtures")
        with open(os.path.join(self.data_dir, "es256_certs.pem"), "rb") as cert_file:
            self.certs = cert_file.read()
        with open(os.path.join(self.data_dir, "es256_private.key"), "rb") as key_file:
            self.key = key_file.read()

        # Create a local Ps256 signer with certs and a timestamp server
        self.signer_info = C2paSignerInfo(
            alg=b"es256",
            sign_cert=self.certs,
            private_key=self.key,
            ta_url=b"http://timestamp.digicert.com"
        )
        self.signer = Signer.from_info(self.signer_info)

        self.testPath = os.path.join(self.data_dir, "C.jpg")

        # Define a manifest as a dictionary
        self.manifestDefinition = {
            "claim_generator": "python_test",
            "claim_generator_info": [{
                "name": "python_test",
                "version": "0.0.1",
            }],
            "format": "image/jpeg",
            "title": "Python Test Image",
            "ingredients": [],
            "assertions": [
                {   'label': 'stds.schema-org.CreativeWork',
                    'data': {
                        '@context': 'http://schema.org/',
                        '@type': 'CreativeWork',
                        'author': [
                            {   '@type': 'Person',
                                'name': 'Gavin Peacock'
                            }
                        ]
                    },
                    'kind': 'Json'
                }
            ]
        }

    def test_streams_sign(self):
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

    def test_sign_all_files(self):
        """Test signing all files in the fixtures/files-for-signing-tests directory"""
        signing_dir = os.path.join(self.data_dir, "files-for-signing-tests")

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

        for filename in os.listdir(signing_dir):
            if filename in skip_files:
                continue

            file_path = os.path.join(signing_dir, filename)
            if not os.path.isfile(file_path):
                continue

            # Get file extension and corresponding MIME type
            _, ext = os.path.splitext(filename)
            ext = ext.lower()
            if ext not in mime_types:
                # print(f"Skipping {filename} - unsupported file type")
                continue

            mime_type = mime_types[ext]

            try:
                with open(file_path, "rb") as file:
                    builder = Builder(self.manifestDefinition)
                    output = io.BytesIO(bytearray())
                    builder.sign(self.signer, mime_type, file, output)
                    output.seek(0)
                    reader = Reader(mime_type, output)
                    json_data = reader.json()
                    self.assertIn("Python Test", json_data)
                    self.assertNotIn("validation_status", json_data)
                    output.close()
            except Error.NotSupported:
                print(f"Skipping {filename} - format not supported")
                continue
            except Exception as e:
                self.fail(f"Failed to sign {filename}: {str(e)}")

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

    def test_remote_sign(self):
        with open(self.testPath, "rb") as file:
            builder = Builder(self.manifestDefinition)
            builder.set_no_embed()
            output = io.BytesIO(bytearray())
            manifest_data = builder.sign(self.signer, "image/jpeg", file, output)
            output.seek(0)
            reader = Reader("image/jpeg", output, manifest_data)
            json_data = reader.json()
            self.assertIn("Python Test", json_data)
            self.assertNotIn("validation_status", json_data)
            output.close()

if __name__ == '__main__':
    unittest.main()
