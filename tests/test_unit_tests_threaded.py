# Copyright 2025 Adobe. All rights reserved.
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
import threading
import concurrent.futures
import time
import asyncio
import random

from c2pa import Builder, C2paError as Error, Reader, C2paSigningAlg as SigningAlg, C2paSignerInfo, Signer, sdk_version
from c2pa.c2pa import Stream

PROJECT_PATH = os.getcwd()
FIXTURES_FOLDER = os.path.join(os.path.dirname(__file__), "fixtures")
DEFAULT_TEST_FILE = os.path.join(FIXTURES_FOLDER, "C.jpg")
INGREDIENT_TEST_FILE = os.path.join(FIXTURES_FOLDER, "A.jpg")
ALTERNATIVE_INGREDIENT_TEST_FILE = os.path.join(FIXTURES_FOLDER, "cloud.jpg")
OTHER_ALTERNATIVE_INGREDIENT_TEST_FILE = os.path.join(FIXTURES_FOLDER, "A_thumbnail.jpg")

# Note: Despite being threaded, some of the tests will take time to run,
# as they may try to push for thread contention, or simply just have a lot
# of work to do (eg. signing or reading all files in a folder).


class TestReaderWithThreads(unittest.TestCase):
    def setUp(self):
        # Use the fixtures_dir fixture to set up paths
        self.data_dir = FIXTURES_FOLDER
        self.testPath = DEFAULT_TEST_FILE

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
            '.wav': 'audio/wav',
            '.pdf': 'application/pdf',
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
                    errors.append(
                        f"Unexpected error processing {filename}: {
                            str(e)}")

        # If any errors occurred, fail the test with all error messages
        if errors:
            self.fail("\n".join(errors))


class TestBuilderWithThreads(unittest.TestCase):
    def setUp(self):
        # Use the fixtures_dir fixture to set up paths
        self.data_dir = FIXTURES_FOLDER
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

        self.testPath = DEFAULT_TEST_FILE
        self.testPath2 = INGREDIENT_TEST_FILE
        self.testPath3 = OTHER_ALTERNATIVE_INGREDIENT_TEST_FILE
        self.testPath4 = ALTERNATIVE_INGREDIENT_TEST_FILE

        # For that test manifest, we use a placeholder assertion with content
        # varying depending on thread/manifest, to check for data scrambling.
        # The used assertion is custom, and not part of the C2PA standard.
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
                    'label': 'com.unit.test',
                    'data': {
                        'author': [
                            {
                                'name': 'Tester'
                            }
                        ]
                    },
                    'kind': 'Json'
                }
            ]
        }

        # For that test manifest, we use a placeholder assertion with content
        # varying depending on thread/manifest, to check for data scrambling.
        # The used assertion is custom, and not part of the C2PA standard.
        self.manifestDefinition_1 = {
            "claim_generator": "python_test_thread1",
            "claim_generator_info": [{
                "name": "python_test_1",
                "version": "0.0.1",
            }],
            "claim_version": 1,
            "format": "image/jpeg",
            "title": "Python Test Image 1",
            "ingredients": [],
            "assertions": [
                {
                    'label': 'com.unit.test',
                    'data': {
                        'author': [
                            {
                                'name': 'Tester One'
                            }
                        ]
                    },
                    'kind': 'Json'
                }
            ]
        }

        # For that test manifest, we use a placeholder assertion with content
        # varying depending on thread/manifest, to check for data scrambling.
        # The used assertion is custom, and not part of the C2PA standard.
        self.manifestDefinition_2 = {
            "claim_generator": "python_test_thread2",
            "claim_generator_info": [{
                "name": "python_test_2",
                "version": "0.0.1",
            }],
            "claim_version": 1,
            "format": "image/jpeg",
            "title": "Python Test Image 2",
            "ingredients": [],
            "assertions": [
                {
                    'label': 'com.unit.test',
                    'data': {
                        'author': [
                            {
                                'name': 'Tester Two'
                            }
                        ]
                    },
                    'kind': 'Json'
                }
            ]
        }

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
                    expected_claim_generator = f"python_test_{
                        2 if thread_id % 2 == 0 else 1}/0.0.1"
                    self.assertEqual(
                        active_manifest["claim_generator"],
                        expected_claim_generator)

                    # Verify the author is correct
                    assertions = active_manifest["assertions"]
                    for assertion in assertions:
                        if assertion["label"] == "com.unit.test":
                            author_name = assertion["data"]["author"][0]["name"]
                            self.assertEqual(author_name, expected_author)
                            break

                    output.close()
                    return None  # Success case
            except Error.NotSupported:
                return None
            except Exception as e:
                return f"Failed to sign {
                    filename} in thread {thread_id}: {str(e)}"

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
                    errors.append(f"Unexpected error processing {
                                  filename} in thread {thread_id}: {str(e)}")

        # If any errors occurred, fail the test with all error messages
        if errors:
            self.fail("\n".join(errors))

    def test_sign_all_files_async(self):
        """Test signing all files using asyncio with a pool of workers"""
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

        async def async_sign_file(filename, thread_id):
            """Async version of file signing operation"""
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
                    expected_claim_generator = f"python_test_{
                        2 if thread_id % 2 == 0 else 1}/0.0.1"
                    self.assertEqual(
                        active_manifest["claim_generator"],
                        expected_claim_generator)

                    # Verify the author is correct
                    assertions = active_manifest["assertions"]
                    for assertion in assertions:
                        if assertion["label"] == "com.unit.test":
                            author_name = assertion["data"]["author"][0]["name"]
                            self.assertEqual(author_name, expected_author)
                            break

                    output.close()
                    return None  # Success case
            except Error.NotSupported:
                return None
            except Exception as e:
                return f"Failed to sign {
                    filename} in thread {thread_id}: {str(e)}"

        async def run_async_tests():
            # Get all files from both directories
            all_files = []
            for directory in [signing_dir, reading_dir]:
                all_files.extend(os.listdir(directory))

            # Create tasks for all files
            tasks = []
            for i, filename in enumerate(all_files):
                task = asyncio.create_task(async_sign_file(filename, i))
                tasks.append(task)

            # Wait for all tasks to complete and collect results
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Process results
            errors = []
            for result in results:
                if isinstance(result, Exception):
                    errors.append(str(result))
                elif result:  # Non-None result indicates an error
                    errors.append(result)

            # If any errors occurred, fail the test with all error messages
            if errors:
                self.fail("\n".join(errors))

        # Run the async tests
        asyncio.run(run_async_tests())

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
                self.assertEqual(
                    active_manifest["claim_generator"],
                    expected_claim_generator)
                self.assertEqual(
                    active_manifest["title"],
                    f"Python Test Image {thread_id}")

                # Verify the author is correct
                assertions = active_manifest["assertions"]
                for assertion in assertions:
                    if assertion["label"] == "com.unit.test":
                        author_name = assertion["data"]["author"][0]["name"]
                        self.assertEqual(
                            author_name, f"Tester {
                                'One' if thread_id == 1 else 'Two'}")
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
        self.assertNotEqual(
            active_manifest1["claim_generator"],
            active_manifest2["claim_generator"])
        self.assertNotEqual(
            active_manifest1["title"],
            active_manifest2["title"])

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
                            thread_execution_order.append(
                                (current_count, thread_id))

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
                        expected_claim_generator = f"python_test_{
                            expected_thread}/0.0.1"

                    self.assertEqual(
                        active_manifest["claim_generator"],
                        expected_claim_generator)

                    # Verify the author is correct
                    assertions = active_manifest["assertions"]
                    for assertion in assertions:
                        if assertion["label"] == "com.unit.test":
                            author_name = assertion["data"]["author"][0]["name"]
                            self.assertEqual(author_name, expected_author)
                            break

                    output.close()
                    return None  # Success case
            except Error.NotSupported:
                return None
            except Exception as e:
                return f"Failed to sign {
                    filename} in thread {thread_id}: {str(e)}"

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
                    errors.append(f"Unexpected error processing {
                                  filename} in thread {thread_id}: {str(e)}")

        # Verify thread interleaving
        # Check that we don't have long sequences of the same thread
        # Maximum allowed consecutive executions of the same thread
        max_same_thread_sequence = 3
        current_sequence = 1
        current_thread = thread_execution_order[0][1] if thread_execution_order else None

        for i in range(1, len(thread_execution_order)):
            if thread_execution_order[i][1] == current_thread:
                current_sequence += 1
                if current_sequence > max_same_thread_sequence:
                    self.fail(f"Thread {current_thread} executed {
                              current_sequence} times in sequence, indicating poor interleaving")
            else:
                current_sequence = 1
                current_thread = thread_execution_order[i][1]

        # If any errors occurred, fail the test with all error messages
        if errors:
            self.fail("\n".join(errors))

    def test_concurrent_read_after_write(self):
        """Test reading from a file after writing is complete"""
        output = io.BytesIO(bytearray())
        write_complete = threading.Event()
        write_errors = []
        read_errors = []

        def write_manifest():
            try:
                with open(self.testPath, "rb") as file:
                    builder = Builder(self.manifestDefinition_1)
                    builder.sign(self.signer, "image/jpeg", file, output)
                    output.seek(0)
                    write_complete.set()
            except Exception as e:
                write_errors.append(f"Write error: {str(e)}")
                write_complete.set()

        def read_manifest():
            try:
                # Wait for write to complete before reading
                write_complete.wait()

                # Read after write is complete
                output.seek(0)
                reader = Reader("image/jpeg", output)
                json_data = reader.json()
                manifest_store = json.loads(json_data)
                active_manifest = manifest_store["manifests"][manifest_store["active_manifest"]]

                # Verify final manifest
                self.assertEqual(
                    active_manifest["claim_generator"],
                    "python_test_1/0.0.1")
                self.assertEqual(
                    active_manifest["title"],
                    "Python Test Image 1")

                # Verify the author is correct
                assertions = active_manifest["assertions"]
                for assertion in assertions:
                    if assertion["label"] == "com.unit.test":
                        author_name = assertion["data"]["author"][0]["name"]
                        self.assertEqual(author_name, "Tester One")
                        break

            except Exception as e:
                read_errors.append(f"Read error: {str(e)}")

        # Start both threads
        write_thread = threading.Thread(target=write_manifest)
        read_thread = threading.Thread(target=read_manifest)

        read_thread.start()
        write_thread.start()

        # Wait for both threads to complete
        write_thread.join()
        read_thread.join()

        # Clean up
        output.close()

        # Check for errors
        if write_errors:
            self.fail("\n".join(write_errors))
        if read_errors:
            self.fail("\n".join(read_errors))

    def test_concurrent_read_write_multiple_readers(self):
        """Test multiple readers reading from a file after writing is complete"""
        output = io.BytesIO(bytearray())
        write_complete = threading.Event()
        write_errors = []
        read_errors = []
        reader_count = 3
        active_readers = 0
        readers_lock = threading.Lock()
        stream_lock = threading.Lock()  # Lock for stream access

        def write_manifest():
            try:
                with open(self.testPath, "rb") as file:
                    builder = Builder(self.manifestDefinition_1)
                    builder.sign(self.signer, "image/jpeg", file, output)
                    output.seek(0)  # Reset stream position after write
                    write_complete.set()
            except Exception as e:
                write_errors.append(f"Write error: {str(e)}")
                write_complete.set()

        def read_manifest(reader_id):
            nonlocal active_readers
            try:
                with readers_lock:
                    active_readers += 1

                # Wait for write to complete before reading
                write_complete.wait()

                # Read after write is complete
                with stream_lock:  # Ensure exclusive access to stream
                    output.seek(0)  # Reset stream position before read
                    reader = Reader("image/jpeg", output)
                    json_data = reader.json()
                    manifest_store = json.loads(json_data)
                    active_manifest = manifest_store["manifests"][manifest_store["active_manifest"]]

                # Verify final manifest
                self.assertEqual(
                    active_manifest["claim_generator"],
                    "python_test_1/0.0.1")
                self.assertEqual(
                    active_manifest["title"],
                    "Python Test Image 1")

                # Verify the author is correct
                assertions = active_manifest["assertions"]
                for assertion in assertions:
                    if assertion["label"] == "com.unit.test":
                        author_name = assertion["data"]["author"][0]["name"]
                        self.assertEqual(author_name, "Tester One")
                        break

            except Exception as e:
                read_errors.append(f"Reader {reader_id} error: {str(e)}")
            finally:
                with readers_lock:
                    active_readers -= 1

        # Start the write thread
        write_thread = threading.Thread(target=write_manifest)
        write_thread.start()

        # Start multiple read threads
        read_threads = []
        for i in range(reader_count):
            thread = threading.Thread(target=read_manifest, args=(i,))
            read_threads.append(thread)
            thread.start()

        # Wait for write to complete
        write_thread.join()

        # Wait for all readers to complete
        for thread in read_threads:
            thread.join()

        # Clean up
        output.close()

        # Check for errors
        if write_errors:
            self.fail("\n".join(write_errors))
        if read_errors:
            self.fail("\n".join(read_errors))

        # Verify all readers completed
        self.assertEqual(active_readers, 0, "Not all readers completed")

    def test_resource_contention_read(self):
        """Test multiple threads trying to access the same file simultaneously"""
        output = io.BytesIO(bytearray())
        read_complete = threading.Event()
        read_errors = []
        reader_count = 5  # Number of concurrent readers
        active_readers = 0
        readers_lock = threading.Lock()
        stream_lock = threading.Lock()  # Lock for stream access

        # First write some data to read
        with open(self.testPath, "rb") as file:
            builder = Builder(self.manifestDefinition_1)
            builder.sign(self.signer, "image/jpeg", file, output)
            output.seek(0)

        def read_manifest(reader_id):
            nonlocal active_readers
            try:
                with readers_lock:
                    active_readers += 1

                # Read the manifest
                with stream_lock:  # Ensure exclusive access to stream
                    output.seek(0)  # Reset stream position before read
                    reader = Reader("image/jpeg", output)
                    json_data = reader.json()
                    manifest_store = json.loads(json_data)
                    active_manifest = manifest_store["manifests"][manifest_store["active_manifest"]]

                # Verify manifest data
                self.assertEqual(
                    active_manifest["claim_generator"],
                    "python_test_1/0.0.1")
                self.assertEqual(
                    active_manifest["title"],
                    "Python Test Image 1")

                # Verify the author is correct
                assertions = active_manifest["assertions"]
                for assertion in assertions:
                    if assertion["label"] == "com.unit.test":
                        author_name = assertion["data"]["author"][0]["name"]
                        self.assertEqual(author_name, "Tester One")
                        break

                # Add a small delay to increase contention
                time.sleep(0.01)

            except Exception as e:
                read_errors.append(f"Reader {reader_id} error: {str(e)}")
            finally:
                with readers_lock:
                    active_readers -= 1
                    if active_readers == 0:
                        read_complete.set()

        # Create and start all threads
        read_threads = []
        for i in range(reader_count):
            thread = threading.Thread(target=read_manifest, args=(i,))
            read_threads.append(thread)
            thread.start()  # Start each thread immediately after creation

        # Wait for all readers to complete
        for thread in read_threads:
            thread.join()

        # Clean up
        output.close()

        # Check for errors
        if read_errors:
            self.fail("\n".join(read_errors))

        # Verify all readers completed
        self.assertEqual(active_readers, 0, "Not all readers completed")

    def test_resource_contention_read_parallel(self):
        """Test multiple threads starting simultaneously to read the same file"""
        output = io.BytesIO(bytearray())
        read_errors = []
        reader_count = 5  # Number of concurrent readers
        active_readers = 0
        readers_lock = threading.Lock()
        stream_lock = threading.Lock()  # Lock for stream access
        # Barrier to synchronize thread starts
        start_barrier = threading.Barrier(reader_count)
        start_times = []  # Track when each thread starts reading
        start_times_lock = threading.Lock()

        # First write some data to read
        with open(self.testPath, "rb") as file:
            builder = Builder(self.manifestDefinition_1)
            builder.sign(self.signer, "image/jpeg", file, output)
            output.seek(0)

        def read_manifest(reader_id):
            nonlocal active_readers
            try:
                with readers_lock:
                    active_readers += 1

                # Wait for all threads to be ready
                start_barrier.wait()

                # Record start time
                with start_times_lock:
                    start_times.append(time.time())

                # Read the manifest
                with stream_lock:  # Ensure exclusive access to stream
                    output.seek(0)  # Reset stream position before read
                    reader = Reader("image/jpeg", output)
                    json_data = reader.json()
                    manifest_store = json.loads(json_data)
                    active_manifest = manifest_store["manifests"][manifest_store["active_manifest"]]

                # Verify manifest data
                self.assertEqual(
                    active_manifest["claim_generator"],
                    "python_test_1/0.0.1")
                self.assertEqual(
                    active_manifest["title"],
                    "Python Test Image 1")

                # Verify the author is correct
                assertions = active_manifest["assertions"]
                for assertion in assertions:
                    if assertion["label"] == "com.unit.test":
                        author_name = assertion["data"]["author"][0]["name"]
                        self.assertEqual(author_name, "Tester One")
                        break

            except Exception as e:
                read_errors.append(f"Reader {reader_id} error: {str(e)}")
            finally:
                with readers_lock:
                    active_readers -= 1

        # Create all threads first
        read_threads = []
        for i in range(reader_count):
            thread = threading.Thread(target=read_manifest, args=(i,))
            read_threads.append(thread)

        # Start all threads at once
        for thread in read_threads:
            thread.start()

        # Wait for all readers to complete
        for thread in read_threads:
            thread.join()

        # Clean up
        output.close()

        # Check for errors
        if read_errors:
            self.fail("\n".join(read_errors))

        # Verify all readers completed
        self.assertEqual(active_readers, 0, "Not all readers completed")

    def test_archive_sign_threaded(self):
        """Test archive signing with multiple threads in parallel"""
        archive1 = io.BytesIO(bytearray())
        archive2 = io.BytesIO(bytearray())
        output1 = io.BytesIO(bytearray())
        output2 = io.BytesIO(bytearray())
        sign_errors = []
        sign_complete = threading.Event()

        def archive_sign(
                archive_stream,
                output_stream,
                manifest_def,
                thread_id):
            try:
                with open(self.testPath, "rb") as file:
                    # Create and save archive
                    builder = Builder(manifest_def)
                    builder.to_archive(archive_stream)
                    archive_stream.seek(0)

                    # Load from archive and sign
                    builder = Builder.from_archive(archive_stream)
                    builder.sign(
                        self.signer, "image/jpeg", file, output_stream)
                    output_stream.seek(0)

                    # Verify the signed file
                    reader = Reader("image/jpeg", output_stream)
                    json_data = reader.json()
                    manifest_store = json.loads(json_data)
                    active_manifest = manifest_store["manifests"][manifest_store["active_manifest"]]

                    # Verify the correct manifest was used
                    if thread_id == 1:
                        expected_claim_generator = "python_test_1/0.0.1"
                        expected_author = "Tester One"
                    else:
                        expected_claim_generator = "python_test_2/0.0.1"
                        expected_author = "Tester Two"

                    self.assertEqual(
                        active_manifest["claim_generator"],
                        expected_claim_generator)

                    # Verify the author is correct
                    assertions = active_manifest["assertions"]
                    for assertion in assertions:
                        if assertion["label"] == "com.unit.test":
                            author_name = assertion["data"]["author"][0]["name"]
                            self.assertEqual(author_name, expected_author)
                            break

            except Exception as e:
                sign_errors.append(f"Thread {thread_id} error: {str(e)}")
            finally:
                sign_complete.set()

        # Create and start two threads for concurrent archive signing
        thread1 = threading.Thread(
            target=archive_sign,
            args=(archive1, output1, self.manifestDefinition_1, 1)
        )
        thread2 = threading.Thread(
            target=archive_sign,
            args=(archive2, output2, self.manifestDefinition_2, 2)
        )

        # Start both threads
        thread1.start()
        thread2.start()

        # Wait for both threads to complete
        thread1.join()
        thread2.join()

        # Check for errors
        if sign_errors:
            self.fail("\n".join(sign_errors))

        # Verify the outputs are different before closing
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
        self.assertNotEqual(
            active_manifest1["claim_generator"],
            active_manifest2["claim_generator"])
        self.assertNotEqual(
            active_manifest1["title"],
            active_manifest2["title"])

        # Clean up after verification
        archive1.close()
        archive2.close()
        output1.close()
        output2.close()

    def test_sign_all_files_twice(self):
        """Test signing the same file twice with different manifests using a thread pool of size 2"""
        output1 = io.BytesIO(bytearray())
        output2 = io.BytesIO(bytearray())
        sign_errors = []
        thread_results = {}
        thread_lock = threading.Lock()

        def sign_file(output_stream, manifest_def, thread_id):
            try:
                with open(self.testPath, "rb") as file:
                    # Sign the file
                    builder = Builder(manifest_def)
                    builder.sign(
                        self.signer, "image/jpeg", file, output_stream)
                    output_stream.seek(0)

                    # Verify the signed file
                    reader = Reader("image/jpeg", output_stream)
                    json_data = reader.json()
                    manifest_store = json.loads(json_data)
                    active_manifest = manifest_store["manifests"][manifest_store["active_manifest"]]

                    # Verify the correct manifest was used
                    if thread_id == 1:
                        expected_claim_generator = "python_test_1/0.0.1"
                        expected_author = "Tester One"
                    else:
                        expected_claim_generator = "python_test_2/0.0.1"
                        expected_author = "Tester Two"

                    # Store results for final verification
                    with thread_lock:
                        thread_results[thread_id] = {
                            'manifest': active_manifest
                        }

                    # Verify manifest data
                    self.assertEqual(
                        active_manifest["claim_generator"],
                        expected_claim_generator)

                    # Verify the author is correct
                    assertions = active_manifest["assertions"]
                    for assertion in assertions:
                        if assertion["label"] == "com.unit.test":
                            author_name = assertion["data"]["author"][0]["name"]
                            self.assertEqual(author_name, expected_author)
                            break

                    return None  # Success case

            except Exception as e:
                return f"Thread {thread_id} error: {str(e)}"

        # Create a thread pool with 2 workers
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            # Submit both signing tasks
            future1 = executor.submit(
                sign_file, output1, self.manifestDefinition_1, 1)
            future2 = executor.submit(
                sign_file, output2, self.manifestDefinition_2, 2)

            # Collect results
            for future in concurrent.futures.as_completed([future1, future2]):
                error = future.result()
                if error:
                    sign_errors.append(error)

        # Check for errors
        if sign_errors:
            self.fail("\n".join(sign_errors))

        # Verify thread results
        self.assertEqual(
            len(thread_results),
            2,
            "Both threads should have completed")

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
        self.assertNotEqual(
            active_manifest1["claim_generator"],
            active_manifest2["claim_generator"])
        self.assertNotEqual(
            active_manifest1["title"],
            active_manifest2["title"])

        # Verify both outputs have valid signatures
        self.assertNotIn("validation_status", manifest_store1)
        self.assertNotIn("validation_status", manifest_store2)

        # Clean up
        output1.close()
        output2.close()

    def test_concurrent_read_after_write_async(self):
        """Test reading from a file after writing is complete using asyncio"""
        output = io.BytesIO(bytearray())
        write_complete = asyncio.Event()
        write_errors = []
        read_errors = []
        write_success = False

        async def write_manifest():
            nonlocal write_success
            try:
                with open(self.testPath, "rb") as file:
                    builder = Builder(self.manifestDefinition_1)
                    builder.sign(self.signer, "image/jpeg", file, output)
                    output.seek(0)
                    write_success = True
                    write_complete.set()
            except Exception as e:
                write_errors.append(f"Write error: {str(e)}")
                write_complete.set()

        async def read_manifest():
            try:
                # Wait for write to complete before reading
                await write_complete.wait()

                # Verify write was successful
                if not write_success:
                    raise Exception(
                        "Write operation did not complete successfully")

                # Verify output is not empty
                output_size = len(output.getvalue())
                self.assertGreater(
                    output_size, 0, "Output should not be empty after write")

                # Read after write is complete
                output.seek(0)
                reader = Reader("image/jpeg", output)
                json_data = reader.json()
                manifest_store = json.loads(json_data)

                # Verify manifest store structure
                self.assertIn(
                    "manifests",
                    manifest_store,
                    "Manifest store should contain 'manifests'")
                self.assertIn(
                    "active_manifest",
                    manifest_store,
                    "Manifest store should contain 'active_manifest'")

                active_manifest = manifest_store["manifests"][manifest_store["active_manifest"]]

                # Verify final manifest
                self.assertEqual(
                    active_manifest["claim_generator"],
                    "python_test_1/0.0.1")
                self.assertEqual(
                    active_manifest["title"],
                    "Python Test Image 1")

                # Verify the author is correct
                assertions = active_manifest["assertions"]
                author_found = False
                for assertion in assertions:
                    if assertion["label"] == "com.unit.test":
                        author_name = assertion["data"]["author"][0]["name"]
                        self.assertEqual(author_name, "Tester One")
                        author_found = True
                        break
                self.assertTrue(author_found,
                                "Author assertion not found in manifest")

                # Verify no validation errors
                self.assertNotIn(
                    "validation_status",
                    manifest_store,
                    "Manifest should not have validation errors")

            except Exception as e:
                read_errors.append(f"Read error: {str(e)}")

        async def run_async_tests():
            # Create and run write task first
            write_task = asyncio.create_task(write_manifest())
            await write_task  # Wait for write to complete

            # Only start read task after write is complete
            read_task = asyncio.create_task(read_manifest())
            await read_task  # Wait for read to complete

        # Run the async tests
        asyncio.run(run_async_tests())

        # Clean up
        output.close()

        # Check for errors
        if write_errors:
            self.fail("\n".join(write_errors))
        if read_errors:
            self.fail("\n".join(read_errors))

    def test_resource_contention_read_parallel_async(self):
        """Test multiple async tasks reading the same file concurrently"""
        output = io.BytesIO(bytearray())
        read_errors = []
        reader_count = 5  # Number of concurrent readers
        active_readers = 0
        readers_lock = asyncio.Lock()  # Lock for reader count
        stream_lock = asyncio.Lock()  # Lock for stream access
        # Barrier to synchronize task starts
        start_barrier = asyncio.Barrier(reader_count)

        # First write some data to read
        with open(self.testPath, "rb") as file:
            builder = Builder(self.manifestDefinition_1)
            builder.sign(self.signer, "image/jpeg", file, output)
            output.seek(0)

        async def read_manifest(reader_id):
            nonlocal active_readers
            try:
                async with readers_lock:
                    active_readers += 1

                # Wait for all tasks to be ready
                await start_barrier.wait()

                # Read the manifest
                async with stream_lock:  # Ensure exclusive access to stream
                    output.seek(0)  # Reset stream position before read
                    reader = Reader("image/jpeg", output)
                    json_data = reader.json()
                    manifest_store = json.loads(json_data)
                    active_manifest = manifest_store["manifests"][manifest_store["active_manifest"]]

                # Verify manifest data
                self.assertEqual(
                    active_manifest["claim_generator"],
                    "python_test_1/0.0.1")
                self.assertEqual(
                    active_manifest["title"],
                    "Python Test Image 1")

                # Verify the author is correct
                assertions = active_manifest["assertions"]
                for assertion in assertions:
                    if assertion["label"] == "com.unit.test":
                        author_name = assertion["data"]["author"][0]["name"]
                        self.assertEqual(author_name, "Tester One")
                        break

            except Exception as e:
                read_errors.append(f"Reader {reader_id} error: {str(e)}")
            finally:
                async with readers_lock:
                    active_readers -= 1

        async def run_async_tests():
            # Create all tasks first
            tasks = []
            for i in range(reader_count):
                task = asyncio.create_task(read_manifest(i))
                tasks.append(task)

            # Wait for all tasks to complete
            await asyncio.gather(*tasks)

        # Run the async tests
        asyncio.run(run_async_tests())

        # Clean up
        output.close()

        # Check for errors
        if read_errors:
            self.fail("\n".join(read_errors))

        # Verify all readers completed
        self.assertEqual(active_readers, 0, "Not all readers completed")

    def test_builder_sign_with_multiple_ingredients_from_stream(self):
        """Test Builder class operations with multiple ingredients using streams."""
        # Test creating builder from JSON
        builder = Builder.from_json(self.manifestDefinition)
        assert builder._builder is not None

        # Thread synchronization
        add_errors = []
        add_lock = threading.Lock()
        completed_threads = 0
        completion_lock = threading.Lock()

        def add_ingredient_from_stream(ingredient_json, file_path, thread_id):
            nonlocal completed_threads
            try:
                with open(file_path, 'rb') as f:
                    builder.add_ingredient_from_stream(
                        ingredient_json, "image/jpeg", f)
                with add_lock:
                    add_errors.append(None)  # Success case
            except Exception as e:
                with add_lock:
                    add_errors.append(f"Thread {thread_id} error: {str(e)}")
            finally:
                with completion_lock:
                    completed_threads += 1

        # Create and start two threads for parallel ingredient addition
        thread1 = threading.Thread(
            target=add_ingredient_from_stream,
            args=('{"title": "Test Ingredient Stream 1"}', self.testPath3, 1)
        )
        thread2 = threading.Thread(
            target=add_ingredient_from_stream,
            args=('{"title": "Test Ingredient Stream 2"}', self.testPath4, 2)
        )

        # Start both threads
        thread1.start()
        thread2.start()

        # Wait for both threads to complete
        thread1.join()
        thread2.join()

        # Check for errors during ingredient addition
        if any(error for error in add_errors if error is not None):
            self.fail(
                "\n".join(
                    error for error in add_errors if error is not None))

        # Verify both ingredients were added successfully
        self.assertEqual(
            completed_threads,
            2,
            "Both threads should have completed")
        self.assertEqual(
            len(add_errors),
            2,
            "Both threads should have completed without errors")

        # Now sign the manifest with the added ingredients
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

    def test_builder_sign_with_same_ingredient_multiple_times(self):
        """Test Builder class operations with the same ingredient added multiple times from different threads."""
        # Test creating builder from JSON
        builder = Builder.from_json(self.manifestDefinition)
        assert builder._builder is not None

        # Thread synchronization
        add_errors = []
        add_lock = threading.Lock()
        completed_threads = 0
        completion_lock = threading.Lock()

        def add_ingredient(ingredient_json, thread_id):
            nonlocal completed_threads
            try:
                with open(self.testPath3, 'rb') as f:
                    builder.add_ingredient(ingredient_json, "image/jpeg", f)
                with add_lock:
                    add_errors.append(None)  # Success case
            except Exception as e:
                with add_lock:
                    add_errors.append(f"Thread {thread_id} error: {str(e)}")
            finally:
                with completion_lock:
                    completed_threads += 1

        # Create and start 5 threads for parallel ingredient addition
        threads = []
        for i in range(1, 6):
            # Create unique manifest JSON for each thread
            ingredient_json = json.dumps({
                "title": f"Test Ingredient Thread {i}"
            })

            thread = threading.Thread(
                target=add_ingredient,
                args=(ingredient_json, i)
            )
            threads.append(thread)
            thread.start()

        # Wait for all threads to complete
        for thread in threads:
            thread.join()

        # Check for errors during ingredient addition
        if any(error for error in add_errors if error is not None):
            self.fail(
                "\n".join(
                    error for error in add_errors if error is not None))

        # Verify all ingredients were added successfully
        self.assertEqual(
            completed_threads,
            5,
            "All 5 threads should have completed")
        self.assertEqual(
            len(add_errors),
            5,
            "All 5 threads should have completed without errors")

        # Now sign the manifest with the added ingredients
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
            self.assertEqual(len(active_manifest["ingredients"]), 5)

            # Verify all ingredients exist in the array with correct thread IDs
            # and unique metadata
            ingredient_titles = [ing["title"]
                                 for ing in active_manifest["ingredients"]]

            # Check that we have 5 unique titles
            self.assertEqual(len(set(ingredient_titles)), 5,
                             "Should have 5 unique ingredient titles")

            # Verify each thread's ingredient exists with correct metadata
            for i in range(1, 6):
                # Find ingredients with this thread ID
                thread_ingredients = [ing for ing in active_manifest["ingredients"]
                                      if ing["title"] == f"Test Ingredient Thread {i}"]
                self.assertEqual(
                    len(thread_ingredients),
                    1,
                    f"Should find exactly one ingredient for thread {i}")

        builder.close()

    def test_builder_sign_with_multiple_ingredient_random_many_threads(self):
        """Test Builder class operations with 12 threads, each adding 3 specific ingredients and signing a file."""
        # Number of threads to use in the test
        TOTAL_THREADS_USED = 12

        # Define the specific files to use as ingredients
        # THose files should be valid to use as ingredient
        ingredient_files = [
            os.path.join(self.data_dir, "A_thumbnail.jpg"),
            os.path.join(self.data_dir, "C.jpg"),
            os.path.join(self.data_dir, "cloud.jpg")
        ]

        # Thread synchronization
        thread_results = {}
        completed_threads = 0
        thread_lock = threading.Lock()  # Lock for thread-safe access to shared data

        def thread_work(thread_id):
            nonlocal completed_threads
            try:
                # Create a new builder for this thread
                builder = Builder.from_json(self.manifestDefinition)

                # Add each ingredient
                for i, file_path in enumerate(ingredient_files, 1):
                    ingredient_json = json.dumps({
                        "title": f"Thread {thread_id} Ingredient {i} - {os.path.basename(file_path)}"
                    })

                    with open(file_path, 'rb') as f:
                        builder.add_ingredient(ingredient_json, "image/jpeg", f)

                # Use A.jpg as the file to sign
                sign_file_path = os.path.join(self.data_dir, "A.jpg")

                # Sign the file
                with open(sign_file_path, "rb") as file:
                    output = io.BytesIO()
                    builder.sign(self.signer, "image/jpeg", file, output)

                    # Ensure all data is written
                    output.flush()

                    # Get the complete data
                    output_data = output.getvalue()

                    # Create a new BytesIO with the complete data
                    input_stream = io.BytesIO(output_data)

                    # Now read and verify the signed manifest
                    reader = Reader("image/jpeg", input_stream)
                    json_data = reader.json()
                    manifest_data = json.loads(json_data)

                    # Store results for verification
                    with thread_lock:
                        thread_results[thread_id] = {
                            'manifest': manifest_data,
                            'ingredient_files': [os.path.basename(f) for f in ingredient_files],
                            'sign_file': os.path.basename(sign_file_path),
                            'manifest_hash': hash(json.dumps(manifest_data, sort_keys=True))  # Add hash for comparison
                        }

                    # Clean up streams
                    output.close()
                    input_stream.close()

                builder.close()

            except Exception as e:
                with thread_lock:
                    thread_results[thread_id] = {
                        'error': str(e)
                    }
            finally:
                with thread_lock:
                    completed_threads += 1

        # Create and start threads
        threads = []
        for i in range(1, TOTAL_THREADS_USED + 1):
            thread = threading.Thread(target=thread_work, args=(i,))
            threads.append(thread)
            thread.start()

        # Wait for all threads to complete
        for thread in threads:
            thread.join()

        # Verify all threads completed
        self.assertEqual(completed_threads, TOTAL_THREADS_USED, f"All {TOTAL_THREADS_USED} threads should have completed")
        self.assertEqual(
            len(thread_results),
            TOTAL_THREADS_USED,
            f"Should have results from all {TOTAL_THREADS_USED} threads")

        # Collect all manifest hashes for comparison
        manifest_hashes = set()
        thread_manifest_data = {}

        # Verify results for each thread
        for thread_id in range(1, TOTAL_THREADS_USED + 1):
            result = thread_results[thread_id]

            # Check if thread encountered an error
            if 'error' in result:
                self.fail(f"Thread {thread_id} failed with error: {result['error']}")

            manifest_data = result['manifest']
            ingredient_files = result['ingredient_files']
            manifest_hash = result['manifest_hash']

            # Store manifest data for cross-thread comparison
            thread_manifest_data[thread_id] = manifest_data
            manifest_hashes.add(manifest_hash)

            # Verify active manifest exists
            self.assertIn("active_manifest", manifest_data)
            active_manifest_id = manifest_data["active_manifest"]

            # Verify active manifest object exists
            self.assertIn("manifests", manifest_data)
            self.assertIn(active_manifest_id, manifest_data["manifests"])
            active_manifest = manifest_data["manifests"][active_manifest_id]

            # Verify ingredients array exists and has correct length
            self.assertIn("ingredients", active_manifest)
            self.assertIsInstance(active_manifest["ingredients"], list)
            self.assertEqual(len(active_manifest["ingredients"]), 3)

            # Verify all ingredients exist with correct thread ID and file names
            ingredient_titles = [ing["title"] for ing in active_manifest["ingredients"]]
            for i, file_name in enumerate(ingredient_files, 1):
                expected_title = f"Thread {thread_id} Ingredient {i} - {file_name}"
                self.assertIn(expected_title, ingredient_titles, f"Thread {thread_id} should have ingredient with title {expected_title}")

            # Verify no cross-thread contamination in ingredient titles
            for other_thread_id in range(1, TOTAL_THREADS_USED + 1):
                if other_thread_id != thread_id:
                    for title in ingredient_titles:
                        # Check for exact thread ID pattern to avoid false positives
                        self.assertNotIn(
                            f"Thread {other_thread_id} Ingredient",
                            title,
                            f"Thread {thread_id}'s manifest contains ingredient data from thread {other_thread_id}")

        # Verify all manifests are unique (no data scrambling between threads)
        self.assertEqual(
            len(manifest_hashes),
            TOTAL_THREADS_USED,
            "Each thread should have a unique manifest (no data scrambling)")

        # Additional verification: Compare manifest structures between threads
        for thread_id in range(1, TOTAL_THREADS_USED + 1):
            current_manifest = thread_manifest_data[thread_id]

            # Verify manifest structure is consistent
            self.assertIn("active_manifest", current_manifest)
            self.assertIn("manifests", current_manifest)

            # Verify no cross-thread contamination in manifest data
            for other_thread_id in range(1, TOTAL_THREADS_USED + 1):
                if other_thread_id != thread_id:
                    other_manifest = thread_manifest_data[other_thread_id]
                    self.assertNotEqual(
                        current_manifest["active_manifest"],
                        other_manifest["active_manifest"],
                        f"Thread {thread_id} and {other_thread_id} share the same active manifest ID")

if __name__ == '__main__':
    unittest.main()
