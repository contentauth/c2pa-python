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
import time

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
        """Test signing all files in both fixtures directories using a thread pool"""
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

        def sign_file(filename, thread_id):
            if filename in skip_files:
                return None

            file_path = os.path.join(signing_dir, filename)
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
                    # Choose manifest based on thread number
                    manifest_def = self.manifestDefinition_2 if thread_id % 2 == 0 else self.manifestDefinition_1
                    expected_author = "Tester Two" if thread_id % 2 == 0 else "Tester One"

                    builder = Builder(manifest_def)
                    output = io.BytesIO(bytearray())
                    builder.sign(self.signer, mime_type, file, output)
                    output.seek(0)

                    # Verify the signed file
                    reader = Reader(mime_type, output)
                    json_data = reader.json()
                    manifest_store = json.loads(json_data)
                    active_manifest = manifest_store["manifests"][manifest_store["active_manifest"]]

                    # Verify the correct manifest was used
                    expected_claim_generator = f"python_test_{2 if thread_id % 2 == 0 else 1}/0.0.1"
                    self.assertEqual(active_manifest["claim_generator"], expected_claim_generator)

                    # Verify the author is correct
                    assertions = active_manifest["assertions"]
                    for assertion in assertions:
                        if assertion["label"] == "stds.schema-org.CreativeWork":
                            author_name = assertion["data"]["author"][0]["name"]
                            self.assertEqual(author_name, expected_author)
                            break

                    output.close()
                    return None  # Success case
            except Error.NotSupported:
                return None
            except Exception as e:
                return f"Failed to sign {filename} in thread {thread_id}: {str(e)}"

        # Create a thread pool with 6 workers
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
            # Get all files from both directories
            all_files = []
            for directory in [signing_dir, reading_dir]:
                all_files.extend(os.listdir(directory))

            # Submit all files to the thread pool with thread IDs
            future_to_file = {
                executor.submit(sign_file, filename, i): (filename, i)
                for i, filename in enumerate(all_files)
            }

            # Collect results as they complete
            errors = []
            for future in concurrent.futures.as_completed(future_to_file):
                filename, thread_id = future_to_file[future]
                try:
                    error = future.result()
                    if error:
                        errors.append(error)
                except Exception as e:
                    errors.append(f"Unexpected error processing {filename} in thread {thread_id}: {str(e)}")

        # If any errors occurred, fail the test with all error messages
        if errors:
            self.fail("\n".join(errors))

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

    def test_parallel_sign_all_files_interleaved(self):
        """Test signing all files using a thread pool of 3 threads, cycling through all three manifest definitions"""
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

        # Thread synchronization
        thread_counter = 0
        thread_counter_lock = threading.Lock()
        thread_execution_order = []
        thread_order_lock = threading.Lock()

        def sign_file(filename, thread_id):
            nonlocal thread_counter

            if filename in skip_files:
                return None

            file_path = os.path.join(signing_dir, filename)
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
                    # Choose manifest based on thread number
                    if thread_id % 3 == 0:
                        manifest_def = self.manifestDefinition
                        expected_author = "Tester"
                        expected_thread = ""
                    elif thread_id % 3 == 1:
                        manifest_def = self.manifestDefinition_1
                        expected_author = "Tester One"
                        expected_thread = "1"
                    else:  # thread_id % 3 == 2
                        manifest_def = self.manifestDefinition_2
                        expected_author = "Tester Two"
                        expected_thread = "2"

                    # Record thread execution order
                    with thread_counter_lock:
                        current_count = thread_counter
                        thread_counter += 1
                        with thread_order_lock:
                            thread_execution_order.append((current_count, thread_id))

                    # Add a small delay to encourage interleaving
                    time.sleep(0.01)

                    builder = Builder(manifest_def)
                    output = io.BytesIO(bytearray())
                    builder.sign(self.signer, mime_type, file, output)
                    output.seek(0)

                    # Verify the signed file
                    reader = Reader(mime_type, output)
                    json_data = reader.json()
                    manifest_store = json.loads(json_data)
                    active_manifest = manifest_store["manifests"][manifest_store["active_manifest"]]

                    # Verify the correct manifest was used
                    if thread_id % 3 == 0:
                        expected_claim_generator = "python_test/0.0.1"
                    else:
                        expected_claim_generator = f"python_test_{expected_thread}/0.0.1"

                    self.assertEqual(active_manifest["claim_generator"], expected_claim_generator)

                    # Verify the author is correct
                    assertions = active_manifest["assertions"]
                    for assertion in assertions:
                        if assertion["label"] == "stds.schema-org.CreativeWork":
                            author_name = assertion["data"]["author"][0]["name"]
                            self.assertEqual(author_name, expected_author)
                            break

                    output.close()
                    return None  # Success case
            except Error.NotSupported:
                return None
            except Exception as e:
                return f"Failed to sign {filename} in thread {thread_id}: {str(e)}"

        # Create a thread pool with 3 workers
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            # Get all files from both directories
            all_files = []
            for directory in [signing_dir, reading_dir]:
                all_files.extend(os.listdir(directory))

            # Submit all files to the thread pool with thread IDs
            future_to_file = {
                executor.submit(sign_file, filename, i): (filename, i)
                for i, filename in enumerate(all_files)
            }

            # Collect results as they complete
            errors = []
            for future in concurrent.futures.as_completed(future_to_file):
                filename, thread_id = future_to_file[future]
                try:
                    error = future.result()
                    if error:
                        errors.append(error)
                except Exception as e:
                    errors.append(f"Unexpected error processing {filename} in thread {thread_id}: {str(e)}")

        # Verify thread interleaving
        # Check that we don't have long sequences of the same thread
        max_same_thread_sequence = 3  # Maximum allowed consecutive executions of the same thread
        current_sequence = 1
        current_thread = thread_execution_order[0][1] if thread_execution_order else None

        for i in range(1, len(thread_execution_order)):
            if thread_execution_order[i][1] == current_thread:
                current_sequence += 1
                if current_sequence > max_same_thread_sequence:
                    self.fail(f"Thread {current_thread} executed {current_sequence} times in sequence, indicating poor interleaving")
            else:
                current_sequence = 1
                current_thread = thread_execution_order[i][1]

        # If any errors occurred, fail the test with all error messages
        if errors:
            self.fail("\n".join(errors))


if __name__ == '__main__':
    unittest.main()
