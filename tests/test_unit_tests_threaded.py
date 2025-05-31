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
import ctypes
import threading
import concurrent.futures

from c2pa import Builder, C2paError as Error, Reader, C2paSigningAlg as SigningAlg, C2paSignerInfo, Signer, sdk_version
from c2pa.c2pa import Stream

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
        def read_metadata():
            with open(self.testPath, "rb") as file:
                reader = Reader("image/jpeg", file)
                json_data = reader.json()
                self.assertIn("C.jpg", json_data)
                return json_data

        # Create two threads
        thread1 = threading.Thread(target=read_metadata)
        thread2 = threading.Thread(target=read_metadata)

        # Start both threads
        thread1.start()
        thread2.start()

        # Wait for both threads to complete
        thread1.join()
        thread2.join()

    def test_stream_read_and_parse(self):
        def read_and_parse():
            with open(self.testPath, "rb") as file:
                reader = Reader("image/jpeg", file)
                manifest_store = json.loads(reader.json())
                title = manifest_store["manifests"][manifest_store["active_manifest"]]["title"]
                self.assertEqual(title, "C.jpg")
                return manifest_store

        # Create two threads
        thread1 = threading.Thread(target=read_and_parse)
        thread2 = threading.Thread(target=read_and_parse)

        # Start both threads
        thread1.start()
        thread2.start()

        # Wait for both threads to complete
        thread1.join()
        thread2.join()

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
            '.wav': 'audio/wav'
        }

        # Skip system files
        skip_files = {
            '.DS_Store'
        }

        def process_file(filename):
            if filename in skip_files:
                return None

            file_path = os.path.join(reading_dir, filename)
            if not os.path.isfile(file_path):
                return None

            # Get file extension and corresponding MIME type
            _, ext = os.path.splitext(filename)
            ext = ext.lower()
            if ext not in mime_types:
                return None

            mime_type = mime_types[ext]

            try:
                with open(file_path, "rb") as file:
                    reader = Reader(mime_type, file)
                    json_data = reader.json()
                    # Verify the manifest contains expected fields
                    manifest = json.loads(json_data)
                    if "manifests" not in manifest or "active_manifest" not in manifest:
                        return f"Invalid manifest structure in {filename}"
                    return None  # Success case returns None
            except Exception as e:
                return f"Failed to read metadata from {filename}: {str(e)}"

        # Create a thread pool with 6 workers
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
            # Submit all files to the thread pool
            future_to_file = {
                executor.submit(process_file, filename): filename
                for filename in os.listdir(reading_dir)
            }

            # Collect results as they complete
            errors = []
            for future in concurrent.futures.as_completed(future_to_file):
                filename = future_to_file[future]
                try:
                    error = future.result()
                    if error:
                        errors.append(error)
                except Exception as e:
                    errors.append(f"Unexpected error processing {filename}: {str(e)}")

        # If any errors occurred, fail the test with all error messages
        if errors:
            self.fail("\n".join(errors))


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

        # Define manifests
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
                {'label': 'stds.schema-org.CreativeWork',
                    'data': {
                        '@context': 'http://schema.org/',
                        '@type': 'CreativeWork',
                        'author': [
                            {'@type': 'Person',
                                'name': 'Tester'
                            }
                        ]
                    },
                    'kind': 'Json'
                }
            ]
        }

        self.manifestDefinition_1 = {
            "claim_generator": "python_test_thread1",
            "claim_generator_info": [{
                "name": "python_test_1",
                "version": "0.0.1",
            }],
            "format": "image/jpeg",
            "title": "Python Test Image 1",
            "ingredients": [],
            "assertions": [
                {'label': 'stds.schema-org.CreativeWork',
                    'data': {
                        '@context': 'http://schema.org/',
                        '@type': 'CreativeWork',
                        'author': [
                            {'@type': 'Person',
                                'name': 'Tester One'
                            }
                        ]
                    },
                    'kind': 'Json'
                }
            ]
        }

        self.manifestDefinition_2 = {
            "claim_generator": "python_test_thread2",
            "claim_generator_info": [{
                "name": "python_test_2",
                "version": "0.0.1",
            }],
            "format": "image/jpeg",
            "title": "Python Test Image 2",
            "ingredients": [],
            "assertions": [
                {'label': 'stds.schema-org.CreativeWork',
                    'data': {
                        '@context': 'http://schema.org/',
                        '@type': 'CreativeWork',
                        'author': [
                            {'@type': 'Person',
                                'name': 'Tester Two'
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
            manifest_data = builder.sign(
                self.signer, "image/jpeg", file, output)
            output.seek(0)
            reader = Reader("image/jpeg", output, manifest_data)
            json_data = reader.json()
            self.assertIn("Python Test", json_data)
            self.assertNotIn("validation_status", json_data)
            output.close()

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
                        output.seek(0)
                        reader = Reader(mime_type, output)
                        json_data = reader.json()
                        self.assertIn("Python Test", json_data)
                        self.assertNotIn("validation_status", json_data)
                        output.close()
                except Error.NotSupported:
                    continue
                except Exception as e:
                    self.fail(f"Failed to sign {filename}: {str(e)}")

    def test_parallel_manifest_writing(self):
        """Test writing different manifests to two files in parallel and verify no data mixing occurs"""
        output1 = io.BytesIO(bytearray())
        output2 = io.BytesIO(bytearray())

        def write_manifest(manifest_def, output_stream, thread_id):
            with open(self.testPath, "rb") as file:
                builder = Builder(manifest_def)
                builder.sign(self.signer, "image/jpeg", file, output_stream)
                output_stream.seek(0)
                reader = Reader("image/jpeg", output_stream)
                json_data = reader.json()
                manifest_store = json.loads(json_data)

                # Get the active manifest
                active_manifest = manifest_store["manifests"][manifest_store["active_manifest"]]

                # Verify the correct manifest was written
                expected_claim_generator = f"python_test_{thread_id}/0.0.1"
                self.assertEqual(active_manifest["claim_generator"], expected_claim_generator)
                self.assertEqual(active_manifest["title"], f"Python Test Image {thread_id}")

                # Verify the author is correct
                assertions = active_manifest["assertions"]
                for assertion in assertions:
                    if assertion["label"] == "stds.schema-org.CreativeWork":
                        author_name = assertion["data"]["author"][0]["name"]
                        self.assertEqual(author_name, f"Tester {'One' if thread_id == 1 else 'Two'}")
                        break

                return active_manifest

        # Create two threads
        thread1 = threading.Thread(
            target=write_manifest,
            args=(self.manifestDefinition_1, output1, 1)
        )
        thread2 = threading.Thread(
            target=write_manifest,
            args=(self.manifestDefinition_2, output2, 2)
        )

        # Start both threads
        thread1.start()
        thread2.start()

        # Wait for both threads to complete
        thread2.join()
        thread1.join()

        # Verify the outputs are different
        output1.seek(0)
        output2.seek(0)
        reader1 = Reader("image/jpeg", output1)
        reader2 = Reader("image/jpeg", output2)

        manifest_store1 = json.loads(reader1.json())
        manifest_store2 = json.loads(reader2.json())

        # Get the active manifests
        active_manifest1 = manifest_store1["manifests"][manifest_store1["active_manifest"]]
        active_manifest2 = manifest_store2["manifests"][manifest_store2["active_manifest"]]

        # Verify the manifests are different
        self.assertNotEqual(active_manifest1["claim_generator"], active_manifest2["claim_generator"])
        self.assertNotEqual(active_manifest1["title"], active_manifest2["title"])

        # Clean up
        output1.close()
        output2.close()


if __name__ == '__main__':
    unittest.main()
