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

import ast
import ctypes
import gc
import os
import re
import inspect
import io
import json
import subprocess
import sys
import textwrap
import unittest
import threading
import concurrent.futures
import time
from unittest.mock import MagicMock, patch
from c2pa import Builder, C2paError as Error, Reader, C2paSignerInfo, Signer, sdk_version  # noqa: E501
from c2pa import Context, Settings
from c2pa.c2pa import ManagedResource, Stream, LifecycleState, _native_section
import c2pa.c2pa as c2pa_module
from c2pa.lib import is_foreign_process, record_owner_pid

PROJECT_PATH = os.getcwd()
FIXTURES_FOLDER = os.path.join(os.path.dirname(__file__), "fixtures")


def _patch_free(test, fn):
    """Route ManagedResource._free_native_ptr to `fn` until `test` ends."""
    patcher = patch.object(
        ManagedResource, '_free_native_ptr', staticmethod(fn))
    patcher.start()
    test.addCleanup(patcher.stop)


class _ConcreteResource(ManagedResource):
    """Minimal concrete subclass for testing ManagedResource cleanup."""


def _make_resource(pid_offset):
    """Construct a ManagedResource-like object without triggering native init.

    pid_offset=1  → simulates a forked child (foreign PID)
    pid_offset=0  → same process (normal cleanup)
    pid_offset=None → no _owner_pid stamp (backward-compat: no protection)
    """
    obj = object.__new__(_ConcreteResource)
    obj._lifecycle_state = LifecycleState.ACTIVE
    obj._handle = ctypes.c_void_p(1)  # non-None, non-zero sentinel
    if pid_offset is not None:
        obj._owner_pid = os.getpid() + pid_offset
    return obj


def _make_stream(pid_offset):
    """Construct a Stream-like object without triggering native init."""
    obj = object.__new__(Stream)
    obj._closed = False
    obj._initialized = True
    obj._stream = MagicMock()  # non-None stream handle
    obj._close_lock = threading.Lock()
    if pid_offset is not None:
        obj._owner_pid = os.getpid() + pid_offset
    return obj


class TestManagedResourceForkGuard(unittest.TestCase):
    """Fork-safety unit tests for ManagedResource and Stream.

    Verifies that the is_foreign_process() PID guard prevents native frees
    from running in a forked child process (where native mutexes may be held
    by threads that no longer exist, causing deadlock before exec()).

    No real fork or auth credentials are required; PID mismatch is simulated
    by setting _owner_pid = os.getpid() + 1.
    """

    def test_foreign_pid_skips_free(self):
        """In a forked child (pid_offset=1), no native free should run."""
        obj = _make_resource(pid_offset=1)
        with patch('c2pa.c2pa._lib') as mock_lib:
            obj._cleanup_resources()
        mock_lib.c2pa_free.assert_not_called()

    def test_own_pid_calls_free(self):
        """In the owning process, cleanup must call c2pa_free normally."""
        obj = _make_resource(pid_offset=0)
        expected_handle = obj._handle
        with patch('c2pa.c2pa._lib'):
            with patch.object(ManagedResource, '_free_native_ptr') as mock_free:
                obj._cleanup_resources()
        mock_free.assert_called_once_with(expected_handle)

    def test_no_stamp_calls_free(self):
        """No _owner_pid (backward-compat) must NOT suppress cleanup."""
        obj = _make_resource(pid_offset=None)
        with patch.object(ManagedResource, '_free_native_ptr') as mock_free:
            obj._cleanup_resources()
        mock_free.assert_called_once()

    def test_foreign_pid_marks_closed_without_free(self):
        """A foreign child skips the native free but marks its own copy closed
        and nulls the handle, so the child cannot reuse a parent-owned handle.
        The parent holds a separate copy and frees it independently.
        """
        obj = _make_resource(pid_offset=1)
        with patch.object(ManagedResource, '_free_native_ptr') as mock_free:
            obj._cleanup_resources()
        mock_free.assert_not_called()
        self.assertEqual(obj._lifecycle_state, LifecycleState.CLOSED)
        self.assertIsNone(obj._handle)

    def test_double_cleanup_is_idempotent(self):
        """Second call is a no-op after successful first cleanup."""
        obj = _make_resource(pid_offset=0)
        with patch.object(ManagedResource, '_free_native_ptr') as mock_free:
            obj._cleanup_resources()
            obj._cleanup_resources()
        mock_free.assert_called_once()

    def test_foreign_pid_skips_release_via_del(self):
        obj = _make_stream(pid_offset=1)
        with patch('c2pa.c2pa._lib') as mock_lib:
            obj.__del__()
        mock_lib.c2pa_release_stream.assert_not_called()

    def test_own_pid_releases_stream_via_del(self):
        obj = _make_stream(pid_offset=0)
        with patch('c2pa.c2pa._lib') as mock_lib:
            obj.__del__()
        mock_lib.c2pa_release_stream.assert_called_once()

    def test_no_stamp_releases_stream_via_del(self):
        obj = _make_stream(pid_offset=None)
        with patch('c2pa.c2pa._lib') as mock_lib:
            obj.__del__()
        mock_lib.c2pa_release_stream.assert_called_once()

    def test_already_closed_is_noop_via_del(self):
        obj = _make_stream(pid_offset=0)
        obj._closed = True
        with patch('c2pa.c2pa._lib') as mock_lib:
            obj.__del__()
        mock_lib.c2pa_release_stream.assert_not_called()

    def test_foreign_pid_skips_release_via_close(self):
        obj = _make_stream(pid_offset=1)
        with patch('c2pa.c2pa._lib') as mock_lib:
            obj.close()
        mock_lib.c2pa_release_stream.assert_not_called()
        self.assertTrue(obj._closed)

    def test_own_pid_releases_stream_via_close(self):
        obj = _make_stream(pid_offset=0)
        with patch('c2pa.c2pa._lib') as mock_lib:
            obj.close()
        mock_lib.c2pa_release_stream.assert_called_once()

    def test_no_stamp_releases_stream_via_close(self):
        obj = _make_stream(pid_offset=None)
        with patch('c2pa.c2pa._lib') as mock_lib:
            obj.close()
        mock_lib.c2pa_release_stream.assert_called_once()

    def test_already_closed_is_noop_via_close(self):
        obj = _make_stream(pid_offset=0)
        obj._closed = True
        with patch('c2pa.c2pa._lib') as mock_lib:
            obj.close()
        mock_lib.c2pa_release_stream.assert_not_called()

    def test_foreign_pid_close_marks_closed(self):
        """close() in forked child must set _closed=True to prevent re-entry,
        and _initialized=False so the public properties report a closed stream."""
        obj = _make_stream(pid_offset=1)
        with patch('c2pa.c2pa._lib'):
            obj.close()
        self.assertTrue(obj._closed)
        self.assertFalse(obj._initialized)


class TestForkedChildDoesNotDeadlock(unittest.TestCase):
    """A forked child must never block on a lock the parent held at fork().

    Locking a resource for the duration of an operation means a child that
    forks while some thread holds that lock inherits it locked, with the owner
    thread gone. Anything in the child that acquires it waits forever.

    The failure mode is a hang: each operation runs on a worker thread and
    is joined with a timeout: a test that called it directly would hang the
    runner instead of failing.
    """

    _TIMEOUT = 5.0

    def _foreign_reader_with_lock_held(self, fragment_lock=False):
        """A Reader in the state a forked child inherits:
        lock held by another thread, and stamped with a PID other than this process's.
        """
        with open(DEFAULT_TEST_FILE, "rb") as asset:
            reader = Reader("image/jpeg", asset)
        holding = threading.Event()
        release = threading.Event()

        def hold_the_lock():
            held = (reader._fragment_lock if fragment_lock
                    else reader._guarded_op())
            with held:
                holding.set()
                release.wait(30)

        holder = threading.Thread(target=hold_the_lock, daemon=True)
        holder.start()
        self.assertTrue(holding.wait(self._TIMEOUT),
                        "helper thread never acquired the lock")
        self.addCleanup(holder.join, self._TIMEOUT)
        self.addCleanup(release.set)

        reader._owner_pid = os.getpid() + 1
        return reader

    def _foreign_stream_with_close_lock_held(self):
        """A Stream in the state a forked child inherits: _close_lock held by
        a thread that does not exist in the child, and a foreign owner PID.
        """
        stream = Stream(io.BytesIO(b"payload"))
        holding = threading.Event()
        release = threading.Event()

        def hold_the_lock():
            with stream._close_lock:
                holding.set()
                release.wait(30)

        holder = threading.Thread(target=hold_the_lock, daemon=True)
        holder.start()
        self.assertTrue(holding.wait(self._TIMEOUT),
                        "helper thread never acquired _close_lock")
        # Cleanups run last-registered-first, so this one runs after
        # release.set and holder.join.
        self.addCleanup(self._reclaim_foreign_stream, stream)
        self.addCleanup(holder.join, self._TIMEOUT)
        self.addCleanup(release.set)

        stream._owner_pid = os.getpid() + 1
        return stream

    def _reclaim_foreign_stream(self, stream):
        """Release a stream the foreign-process path left tracked."""
        stream._owner_pid = os.getpid()
        stream._closed = False
        stream.close()

    def test_stream_close_completes_with_close_lock_held(self):
        """close() must take the foreign-process path without acquiring
        _close_lock, which no surviving thread would release."""
        stream = self._foreign_stream_with_close_lock_held()

        outcome = self._run_with_timeout(stream.close)

        self.assertEqual(outcome, "ok")

    def _run_with_timeout(self, operation):
        """Run operation on a worker; return 'ok', the exception, or None if it
        was still running when the timeout expired."""
        result = {}

        def run():
            try:
                operation()
                result["outcome"] = "ok"
            except BaseException as e:      # noqa: BLE001 - asserted on below
                result["outcome"] = e

        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        worker.join(self._TIMEOUT)
        return result.get("outcome")

    def test_locked_read_raises_instead_of_blocking(self):
        reader = self._foreign_reader_with_lock_held()
        outcome = self._run_with_timeout(reader.json)
        self.assertIsInstance(outcome, Error)

    def test_native_call_path_raises_instead_of_blocking(self):
        reader = self._foreign_reader_with_lock_held()
        outcome = self._run_with_timeout(
            lambda: reader.resource_to_stream("any-uri", io.BytesIO()))
        self.assertIsInstance(outcome, Error)

    def test_fragment_lock_path_raises_instead_of_blocking(self):
        reader = self._foreign_reader_with_lock_held(fragment_lock=True)
        outcome = self._run_with_timeout(
            lambda: reader.with_fragment(
                "video/mp4", io.BytesIO(b""), io.BytesIO(b"")))
        self.assertIsInstance(outcome, Error)

    def test_close_still_completes(self):
        reader = self._foreign_reader_with_lock_held()
        self.assertEqual(self._run_with_timeout(reader.close), "ok")

    def test_is_valid_false_for_inherited_object(self):
        reader = self._foreign_reader_with_lock_held()
        self.assertFalse(reader.is_valid)

    def test_parent_copy_unaffected(self):
        """The child closing its copy must leave the parent's usable.

        Runs in a subprocess so that the fork happens in a single-threaded
        process. Operations that reach the network, such as reading an asset
        with a remote manifest, start background native threads that outlive
        the object that triggered them, and forking a multi-threaded process
        can lead to issues.
        """
        source = textwrap.dedent("""
            import os, sys
            from c2pa import Reader
            from c2pa.c2pa import LifecycleState

            asset_path = sys.argv[1]
            with open(asset_path, "rb") as asset:
                reader = Reader("image/jpeg", asset)
            before = reader.json()

            pid = os.fork()
            if pid == 0:
                try:
                    reader.close()
                    os._exit(0)
                except BaseException:
                    os._exit(1)
            _, status = os.waitpid(pid, 0)

            assert status >> 8 == 0, "child could not close its own copy"
            assert reader._lifecycle_state == LifecycleState.ACTIVE
            assert reader.json() == before
            reader.close()
            print("OK")
        """)

        result = subprocess.run(
            [sys.executable, "-c", source, DEFAULT_TEST_FILE],
            capture_output=True, text=True, timeout=120)

        self.assertEqual(result.returncode, 0, result.stderr[-2000:])


class TestReaderWithFragmentConcurrency(unittest.TestCase):
    """with_fragment's native call and its stream-ownership transfer
    must not interleave with another with_fragment on the same Reader.
    """

    def setUp(self):
        self.init_path = os.path.join(FIXTURES_FOLDER, "dashinit.mp4")
        self.fragment_path = os.path.join(FIXTURES_FOLDER, "dash1.m4s")
        with open(self.init_path, "rb") as f:
            self.init_bytes = f.read()
        with open(self.fragment_path, "rb") as f:
            self.fragment_bytes = f.read()

    def _advance(self, reader):
        reader.with_fragment(
            "video/mp4",
            io.BytesIO(self.init_bytes),
            io.BytesIO(self.fragment_bytes))

    def test_close_during_with_fragment_does_not_double_close_stream(self):
        with open(self.init_path, "rb") as init:
            reader = Reader("video/mp4", init)

        entered_gap = threading.Event()
        release_gap = threading.Event()

        real_consume_and_swap = reader._consume_and_swap

        def gated_consume_and_swap(ffi_call, error_message):
            real_consume_and_swap(ffi_call, error_message)
            # Pauses in with_fragment's window before it reassigns _own_stream/_fragment_streams.
            entered_gap.set()
            release_gap.wait(5)

        reader._consume_and_swap = gated_consume_and_swap

        result = {}

        def run_with_fragment():
            try:
                with open(self.init_path, "rb") as init, \
                        open(self.fragment_path, "rb") as frag:
                    reader.with_fragment("video/mp4", init, frag)
                result["outcome"] = "ok"
            except BaseException as e:      # noqa: BLE001 - asserted below
                result["outcome"] = e

        worker = threading.Thread(target=run_with_fragment, daemon=True)
        worker.start()
        self.assertTrue(entered_gap.wait(5), "gap never reached")

        # close() must win the race, and with_fragment must not hang,
        # crash, or succeed without signalling.
        reader.close()
        release_gap.set()
        worker.join(5)
        self.assertIsInstance(result.get("outcome"), Error, "must raise, not hang")

        # with_fragment must not resurrect these fields on a reader close() already tore down.
        self.assertEqual(
            (reader._own_stream, reader._fragment_streams), (None, []))

class TestHelpers(unittest.TestCase):

    def test_record_and_detect_own_pid(self):
        obj = MagicMock()
        record_owner_pid(obj)
        self.assertFalse(is_foreign_process(obj))

    def test_detect_foreign_pid(self):
        obj = MagicMock()
        obj._owner_pid = os.getpid() + 1
        self.assertTrue(is_foreign_process(obj))

    def test_no_stamp_not_foreign(self):
        obj = MagicMock(spec=[])  # no _owner_pid attribute
        self.assertFalse(is_foreign_process(obj))
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
        self.test_path = DEFAULT_TEST_FILE

    def test_stream_read(self):
        def read_metadata():
            with open(self.test_path, "rb") as file:
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
            with open(self.test_path, "rb") as file:
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
                        f"Unexpected error processing {filename}: {str(e)}")

        # If any errors occurred, fail the test with all error messages
        if errors:
            self.fail("\n".join(errors))

    def test_read_cached_all_files(self):
        """Test reading C2PA metadata with cache functionality from all files in the fixtures/files-for-reading-tests directory using multithreading"""
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

        def process_file_with_cache(filename):
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

                    # Test 1: Verify cache variables are initially None
                    if reader._manifest_json_str_cache is not None:
                        return f"JSON cache should be None initially for {filename}"
                    if reader._manifest_data_cache is not None:
                        return f"Manifest data cache should be None initially for {filename}"

                    # Test 2: Multiple calls to json() should return the same result and use cache
                    json_data_1 = reader.json()
                    if reader._manifest_json_str_cache is None:
                        return f"JSON cache not set after first json() call for {filename}"
                    if json_data_1 != reader._manifest_json_str_cache:
                        return f"JSON cache doesn't match return value for {filename}"

                    json_data_2 = reader.json()
                    if json_data_1 != json_data_2:
                        return f"JSON inconsistency for {filename}"
                    if not isinstance(json_data_1, str):
                        return f"JSON data is not a string for {filename}"

                    # Test 3: Test methods that use the cache
                    try:
                        # Test get_active_manifest() which uses _get_cached_manifest_data()
                        active_manifest = reader.get_active_manifest()
                        if not isinstance(active_manifest, dict):
                            return f"Active manifest not dict for {filename}"

                        # Test 4: Verify cache is set after calling cache-using methods
                        if reader._manifest_json_str_cache is None:
                            return f"JSON cache not set after get_active_manifest for {filename}"
                        if reader._manifest_data_cache is None:
                            return f"Manifest data cache not set after get_active_manifest for {filename}"

                        # Test 5: Multiple calls to cache-using methods should return the same result
                        active_manifest_2 = reader.get_active_manifest()
                        if active_manifest != active_manifest_2:
                            return f"Active manifest cache inconsistency for {filename}"

                        # Test get_validation_state() which uses the cache
                        validation_state = reader.get_validation_state()
                        # validation_state can be None, so just check it doesn't crash

                        # Test get_validation_results() which uses the cache
                        validation_results = reader.get_validation_results()
                        # validation_results can be None, so just check it doesn't crash

                        # Test 6: Multiple calls to validation methods should return the same result
                        validation_state_2 = reader.get_validation_state()
                        if validation_state != validation_state_2:
                            return f"Validation state cache inconsistency for {filename}"

                        validation_results_2 = reader.get_validation_results()
                        if validation_results != validation_results_2:
                            return f"Validation results cache inconsistency for {filename}"

                    except KeyError:
                        # Some files might not have active manifests or validation data
                        # This is expected for some test files, so we'll skip cache testing for those
                        pass

                    # Test 7: Verify the manifest contains expected fields
                    manifest = json.loads(json_data_1)
                    if "manifests" not in manifest:
                        return f"Missing 'manifests' key in {filename}"
                    if "active_manifest" not in manifest:
                        return f"Missing 'active_manifest' key in {filename}"

                    # Test 8: Test cache clearing on close
                    reader.close()
                    if reader._manifest_json_str_cache is not None:
                        return f"JSON cache not cleared for {filename}"
                    if reader._manifest_data_cache is not None:
                        return f"Manifest data cache not cleared for {filename}"

                    return None  # Success case returns None

            except Exception as e:
                return f"Failed to read cached metadata from {filename}: {str(e)}"

        # Create a thread pool with 6 workers
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
            # Submit all files to the thread pool
            future_to_file = {
                executor.submit(process_file_with_cache, filename): filename
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
                        f"Unexpected error processing {filename}: {str(e)}")

        # If any errors occurred, fail the test with all error messages
        if errors:
            self.fail("\n".join(errors))


class TestContextualReaderWithThreads(unittest.TestCase):
    def setUp(self):
        self.data_dir = FIXTURES_FOLDER
        self.test_path = DEFAULT_TEST_FILE

    def test_stream_read(self):
        def read_metadata():
            ctx = Context()
            with open(self.test_path, "rb") as file:
                reader = Reader("image/jpeg", file, context=ctx)
                json_data = reader.json()
                self.assertIn("C.jpg", json_data)
                return json_data

        thread1 = threading.Thread(target=read_metadata)
        thread2 = threading.Thread(target=read_metadata)
        thread1.start()
        thread2.start()
        thread1.join()
        thread2.join()

    def test_stream_read_and_parse(self):
        def read_and_parse():
            ctx = Context()
            with open(self.test_path, "rb") as file:
                reader = Reader("image/jpeg", file, context=ctx)
                manifest_store = json.loads(reader.json())
                title = manifest_store["manifests"][manifest_store["active_manifest"]]["title"]
                self.assertEqual(title, "C.jpg")
                return manifest_store

        thread1 = threading.Thread(target=read_and_parse)
        thread2 = threading.Thread(target=read_and_parse)
        thread1.start()
        thread2.start()
        thread1.join()
        thread2.join()

    def test_read_all_files(self):
        """Test reading C2PA metadata from all files using context APIs."""
        reading_dir = os.path.join(self.data_dir, "files-for-reading-tests")
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
        skip_files = {'.DS_Store'}

        def process_file(filename):
            if filename in skip_files:
                return None
            file_path = os.path.join(reading_dir, filename)
            if not os.path.isfile(file_path):
                return None
            _, ext = os.path.splitext(filename)
            ext = ext.lower()
            if ext not in mime_types:
                return None
            mime_type = mime_types[ext]
            try:
                ctx = Context()
                with open(file_path, "rb") as file:
                    reader = Reader(mime_type, file, context=ctx)
                    json_data = reader.json()
                    manifest = json.loads(json_data)
                    if "manifests" not in manifest or "active_manifest" not in manifest:
                        return f"Invalid manifest structure in {filename}"
                    return None
            except Exception as e:
                return f"Failed to read metadata from {filename}: {str(e)}"

        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
            future_to_file = {
                executor.submit(process_file, filename): filename
                for filename in os.listdir(reading_dir)
            }
            errors = []
            for future in concurrent.futures.as_completed(future_to_file):
                filename = future_to_file[future]
                try:
                    error = future.result()
                    if error:
                        errors.append(error)
                except Exception as e:
                    errors.append(f"Unexpected error processing {filename}: {str(e)}")
        if errors:
            self.fail("\n".join(errors))

    def test_read_cached_all_files(self):
        """Test reading C2PA metadata with cache using context APIs."""
        reading_dir = os.path.join(self.data_dir, "files-for-reading-tests")
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
        skip_files = {'.DS_Store'}

        def process_file_with_cache(filename):
            if filename in skip_files:
                return None
            file_path = os.path.join(reading_dir, filename)
            if not os.path.isfile(file_path):
                return None
            _, ext = os.path.splitext(filename)
            ext = ext.lower()
            if ext not in mime_types:
                return None
            mime_type = mime_types[ext]
            try:
                ctx = Context()
                with open(file_path, "rb") as file:
                    reader = Reader(mime_type, file, context=ctx)
                    if reader._manifest_json_str_cache is not None:
                        return f"JSON cache should be None initially for {filename}"
                    if reader._manifest_data_cache is not None:
                        return f"Manifest data cache should be None initially for {filename}"
                    json_data_1 = reader.json()
                    if reader._manifest_json_str_cache is None:
                        return f"JSON cache not set after first json() call for {filename}"
                    if json_data_1 != reader._manifest_json_str_cache:
                        return f"JSON cache doesn't match return value for {filename}"
                    json_data_2 = reader.json()
                    if json_data_1 != json_data_2:
                        return f"JSON inconsistency for {filename}"
                    if not isinstance(json_data_1, str):
                        return f"JSON data is not a string for {filename}"
                    try:
                        active_manifest = reader.get_active_manifest()
                        if not isinstance(active_manifest, dict):
                            return f"Active manifest not dict for {filename}"
                        if reader._manifest_json_str_cache is None:
                            return f"JSON cache not set after get_active_manifest for {filename}"
                        if reader._manifest_data_cache is None:
                            return f"Manifest data cache not set after get_active_manifest for {filename}"
                        active_manifest_2 = reader.get_active_manifest()
                        if active_manifest != active_manifest_2:
                            return f"Active manifest cache inconsistency for {filename}"
                        validation_state = reader.get_validation_state()
                        validation_results = reader.get_validation_results()
                        validation_state_2 = reader.get_validation_state()
                        if validation_state != validation_state_2:
                            return f"Validation state cache inconsistency for {filename}"
                        validation_results_2 = reader.get_validation_results()
                        if validation_results != validation_results_2:
                            return f"Validation results cache inconsistency for {filename}"
                    except KeyError:
                        pass
                    manifest = json.loads(json_data_1)
                    if "manifests" not in manifest:
                        return f"Missing 'manifests' key in {filename}"
                    if "active_manifest" not in manifest:
                        return f"Missing 'active_manifest' key in {filename}"
                    reader.close()
                    if reader._manifest_json_str_cache is not None:
                        return f"JSON cache not cleared for {filename}"
                    if reader._manifest_data_cache is not None:
                        return f"Manifest data cache not cleared for {filename}"
                    return None
            except Exception as e:
                return f"Failed to read cached metadata from {filename}: {str(e)}"

        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
            future_to_file = {
                executor.submit(process_file_with_cache, filename): filename
                for filename in os.listdir(reading_dir)
            }
            errors = []
            for future in concurrent.futures.as_completed(future_to_file):
                filename = future_to_file[future]
                try:
                    error = future.result()
                    if error:
                        errors.append(error)
                except Exception as e:
                    errors.append(f"Unexpected error processing {filename}: {str(e)}")
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

        # Create a local Es256 signer with certs and no timestamp server.
        self.signer_info = C2paSignerInfo(
            alg=b"es256",
            sign_cert=self.certs,
            private_key=self.key,
            ta_url=None
        )
        self.signer = Signer.from_info(self.signer_info)

        self.test_path = DEFAULT_TEST_FILE
        self.test_path2 = INGREDIENT_TEST_FILE
        self.test_path3 = OTHER_ALTERNATIVE_INGREDIENT_TEST_FILE
        self.test_path4 = ALTERNATIVE_INGREDIENT_TEST_FILE

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
                    expected_claim_generator = f"python_test_{2 if thread_id % 2 == 0 else 1}/0.0.1"
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
            with open(self.test_path, "rb") as file:
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
                            author_name, f"Tester {'One' if thread_id == 1 else 'Two'}")
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
                        expected_claim_generator = f"python_test_{expected_thread}/0.0.1"

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
        # Maximum allowed consecutive executions of the same thread
        max_same_thread_sequence = 3
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

    def test_concurrent_read_after_write(self):
        """Test reading from a file after writing is complete"""
        output = io.BytesIO(bytearray())
        write_complete = threading.Event()
        write_errors = []
        read_errors = []

        def write_manifest():
            try:
                with open(self.test_path, "rb") as file:
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
                with open(self.test_path, "rb") as file:
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
        with open(self.test_path, "rb") as file:
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
        with open(self.test_path, "rb") as file:
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
                with open(self.test_path, "rb") as file:
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
                with open(self.test_path, "rb") as file:
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

        # Clean up
        output1.close()
        output2.close()

    def test_builder_sign_with_multiple_ingredient_random_many_threads(self):
        """Test Builder class operations with 12 threads, each adding 3 specific ingredients and signing a file."""
        # Number of threads to use in the test
        TOTAL_THREADS_USED = 12

        # Define the specific files to use as ingredients
        # Those files should be valid to use as ingredient
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


class TestContextualBuilderWithThreads(TestBuilderWithThreads):
    """Same as TestBuilderWithThreads but using only the context APIs (Context, Builder/Reader with context=ctx)."""

    def test_sign_all_files(self):
        """Test signing all files using a thread pool with Context"""
        signing_dir = os.path.join(self.data_dir, "files-for-signing-tests")
        reading_dir = os.path.join(self.data_dir, "files-for-reading-tests")
        mime_types = {
            '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png',
            '.gif': 'image/gif', '.webp': 'image/webp', '.heic': 'image/heic',
            '.heif': 'image/heif', '.avif': 'image/avif', '.tif': 'image/tiff',
            '.tiff': 'image/tiff', '.mp4': 'video/mp4', '.avi': 'video/x-msvideo',
            '.mp3': 'audio/mpeg', '.m4a': 'audio/mp4', '.wav': 'audio/wav'
        }
        skip_files = {'sample3.invalid.wav'}

        def sign_file(filename, thread_id):
            if filename in skip_files:
                return None
            file_path = os.path.join(signing_dir, filename)
            if not os.path.isfile(file_path):
                return None
            _, ext = os.path.splitext(filename)
            ext = ext.lower()
            if ext not in mime_types:
                return None
            mime_type = mime_types[ext]
            try:
                with open(file_path, "rb") as file:
                    manifest_def = self.manifestDefinition_2 if thread_id % 2 == 0 else self.manifestDefinition_1
                    expected_author = "Tester Two" if thread_id % 2 == 0 else "Tester One"
                    ctx = Context()
                    builder = Builder(manifest_def, ctx)
                    output = io.BytesIO(bytearray())
                    builder.sign(self.signer, mime_type, file, output)
                    output.seek(0)
                    read_ctx = Context()
                    reader = Reader(mime_type, output, context=read_ctx)
                    json_data = reader.json()
                    manifest_store = json.loads(json_data)
                    active_manifest = manifest_store["manifests"][manifest_store["active_manifest"]]
                    expected_claim_generator = f"python_test_{2 if thread_id % 2 == 0 else 1}/0.0.1"
                    self.assertEqual(active_manifest["claim_generator"], expected_claim_generator)
                    for assertion in active_manifest["assertions"]:
                        if assertion["label"] == "com.unit.test":
                            self.assertEqual(assertion["data"]["author"][0]["name"], expected_author)
                            break
                    output.close()
                    return None
            except Error.NotSupported:
                return None
            except Exception as e:
                return f"Failed to sign {filename} in thread {thread_id}: {str(e)}"

        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
            all_files = []
            for directory in [signing_dir, reading_dir]:
                all_files.extend(os.listdir(directory))
            future_to_file = {
                executor.submit(sign_file, filename, i): (filename, i)
                for i, filename in enumerate(all_files)
            }
            errors = []
            for future in concurrent.futures.as_completed(future_to_file):
                filename, thread_id = future_to_file[future]
                try:
                    error = future.result()
                    if error:
                        errors.append(error)
                except Exception as e:
                    errors.append(f"Unexpected error processing {filename} in thread {thread_id}: {str(e)}")
            if errors:
                self.fail("\n".join(errors))

    def test_parallel_manifest_writing(self):
        """Test writing different manifests in parallel using context APIs"""
        output1 = io.BytesIO(bytearray())
        output2 = io.BytesIO(bytearray())

        def write_manifest(manifest_def, output_stream, thread_id):
            ctx = Context()
            with open(self.test_path, "rb") as file:
                builder = Builder(manifest_def, ctx)
                builder.sign(self.signer, "image/jpeg", file, output_stream)
                output_stream.seek(0)
                read_ctx = Context()
                reader = Reader("image/jpeg", output_stream, context=read_ctx)
                json_data = reader.json()
                manifest_store = json.loads(json_data)
                active_manifest = manifest_store["manifests"][manifest_store["active_manifest"]]
                self.assertEqual(active_manifest["claim_generator"], f"python_test_{thread_id}/0.0.1")
                self.assertEqual(active_manifest["title"], f"Python Test Image {thread_id}")
                for assertion in active_manifest["assertions"]:
                    if assertion["label"] == "com.unit.test":
                        self.assertEqual(assertion["data"]["author"][0]["name"], f"Tester {'One' if thread_id == 1 else 'Two'}")
                        break
                return active_manifest

        thread1 = threading.Thread(target=write_manifest, args=(self.manifestDefinition_1, output1, 1))
        thread2 = threading.Thread(target=write_manifest, args=(self.manifestDefinition_2, output2, 2))
        thread1.start()
        thread2.start()
        thread2.join()
        thread1.join()
        output1.seek(0)
        output2.seek(0)
        read_ctx1 = Context()
        read_ctx2 = Context()
        reader1 = Reader("image/jpeg", output1, context=read_ctx1)
        reader2 = Reader("image/jpeg", output2, context=read_ctx2)
        manifest_store1 = json.loads(reader1.json())
        manifest_store2 = json.loads(reader2.json())
        active_manifest1 = manifest_store1["manifests"][manifest_store1["active_manifest"]]
        active_manifest2 = manifest_store2["manifests"][manifest_store2["active_manifest"]]
        self.assertNotEqual(active_manifest1["claim_generator"], active_manifest2["claim_generator"])
        self.assertNotEqual(active_manifest1["title"], active_manifest2["title"])
        output1.close()
        output2.close()

    def test_parallel_sign_all_files_interleaved(self):
        """Test signing all files with context APIs, thread pool cycling through manifest definitions"""
        signing_dir = os.path.join(self.data_dir, "files-for-signing-tests")
        reading_dir = os.path.join(self.data_dir, "files-for-reading-tests")
        mime_types = {
            '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png',
            '.gif': 'image/gif', '.webp': 'image/webp', '.heic': 'image/heic',
            '.heif': 'image/heif', '.avif': 'image/avif', '.tif': 'image/tiff',
            '.tiff': 'image/tiff', '.mp4': 'video/mp4', '.avi': 'video/x-msvideo',
            '.mp3': 'audio/mpeg', '.m4a': 'audio/mp4', '.wav': 'audio/wav'
        }
        skip_files = {'sample3.invalid.wav'}
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
            _, ext = os.path.splitext(filename)
            ext = ext.lower()
            if ext not in mime_types:
                return None
            mime_type = mime_types[ext]
            try:
                with open(file_path, "rb") as file:
                    if thread_id % 3 == 0:
                        manifest_def = self.manifestDefinition
                        expected_author = "Tester"
                        expected_thread = ""
                    elif thread_id % 3 == 1:
                        manifest_def = self.manifestDefinition_1
                        expected_author = "Tester One"
                        expected_thread = "1"
                    else:
                        manifest_def = self.manifestDefinition_2
                        expected_author = "Tester Two"
                        expected_thread = "2"
                    with thread_counter_lock:
                        current_count = thread_counter
                        thread_counter += 1
                        with thread_order_lock:
                            thread_execution_order.append((current_count, thread_id))
                    time.sleep(0.01)
                    ctx = Context()
                    builder = Builder(manifest_def, ctx)
                    output = io.BytesIO(bytearray())
                    builder.sign(self.signer, mime_type, file, output)
                    output.seek(0)
                    read_ctx = Context()
                    reader = Reader(mime_type, output, context=read_ctx)
                    json_data = reader.json()
                    manifest_store = json.loads(json_data)
                    active_manifest = manifest_store["manifests"][manifest_store["active_manifest"]]
                    expected_claim_generator = "python_test/0.0.1" if thread_id % 3 == 0 else f"python_test_{expected_thread}/0.0.1"
                    self.assertEqual(active_manifest["claim_generator"], expected_claim_generator)
                    for assertion in active_manifest["assertions"]:
                        if assertion["label"] == "com.unit.test":
                            self.assertEqual(assertion["data"]["author"][0]["name"], expected_author)
                            break
                    output.close()
                    return None
            except Error.NotSupported:
                return None
            except Exception as e:
                return f"Failed to sign {filename} in thread {thread_id}: {str(e)}"

        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            all_files = []
            for directory in [signing_dir, reading_dir]:
                all_files.extend(os.listdir(directory))
            future_to_file = {executor.submit(sign_file, filename, i): (filename, i) for i, filename in enumerate(all_files)}
            errors = []
            for future in concurrent.futures.as_completed(future_to_file):
                filename, thread_id = future_to_file[future]
                try:
                    error = future.result()
                    if error:
                        errors.append(error)
                except Exception as e:
                    errors.append(f"Unexpected error processing {filename} in thread {thread_id}: {str(e)}")
        max_same_thread_sequence = 3
        current_sequence = 1
        current_thread = thread_execution_order[0][1] if thread_execution_order else None
        for i in range(1, len(thread_execution_order)):
            if thread_execution_order[i][1] == current_thread:
                current_sequence += 1
                if current_sequence > max_same_thread_sequence:
                    self.fail(f"Thread {current_thread} executed {current_sequence} times in sequence")
            else:
                current_sequence = 1
                current_thread = thread_execution_order[i][1]
        if errors:
            self.fail("\n".join(errors))

    def test_concurrent_read_after_write(self):
        """Test reading from a file after writing is complete, using context APIs"""
        output = io.BytesIO(bytearray())
        write_complete = threading.Event()
        write_errors = []
        read_errors = []

        def write_manifest():
            try:
                ctx = Context()
                with open(self.test_path, "rb") as file:
                    builder = Builder(self.manifestDefinition_1, ctx)
                    builder.sign(self.signer, "image/jpeg", file, output)
                    output.seek(0)
                    write_complete.set()
            except Exception as e:
                write_errors.append(f"Write error: {str(e)}")
                write_complete.set()

        def read_manifest():
            try:
                write_complete.wait()
                output.seek(0)
                read_ctx = Context()
                reader = Reader("image/jpeg", output, context=read_ctx)
                json_data = reader.json()
                manifest_store = json.loads(json_data)
                active_manifest = manifest_store["manifests"][manifest_store["active_manifest"]]
                self.assertEqual(active_manifest["claim_generator"], "python_test_1/0.0.1")
                self.assertEqual(active_manifest["title"], "Python Test Image 1")
                for assertion in active_manifest["assertions"]:
                    if assertion["label"] == "com.unit.test":
                        self.assertEqual(assertion["data"]["author"][0]["name"], "Tester One")
                        break
            except Exception as e:
                read_errors.append(f"Read error: {str(e)}")

        read_thread = threading.Thread(target=read_manifest)
        write_thread = threading.Thread(target=write_manifest)
        read_thread.start()
        write_thread.start()
        write_thread.join()
        read_thread.join()
        output.close()
        if write_errors:
            self.fail("\n".join(write_errors))
        if read_errors:
            self.fail("\n".join(read_errors))

    def test_concurrent_read_write_multiple_readers(self):
        """Test multiple readers reading after write, using context APIs"""
        output = io.BytesIO(bytearray())
        write_complete = threading.Event()
        write_errors = []
        read_errors = []
        reader_count = 3
        active_readers = 0
        readers_lock = threading.Lock()
        stream_lock = threading.Lock()

        def write_manifest():
            try:
                ctx = Context()
                with open(self.test_path, "rb") as file:
                    builder = Builder(self.manifestDefinition_1, ctx)
                    builder.sign(self.signer, "image/jpeg", file, output)
                    output.seek(0)
                    write_complete.set()
            except Exception as e:
                write_errors.append(f"Write error: {str(e)}")
                write_complete.set()

        def read_manifest(reader_id):
            nonlocal active_readers
            try:
                with readers_lock:
                    active_readers += 1
                write_complete.wait()
                with stream_lock:
                    output.seek(0)
                    read_ctx = Context()
                    reader = Reader("image/jpeg", output, context=read_ctx)
                    json_data = reader.json()
                    manifest_store = json.loads(json_data)
                    active_manifest = manifest_store["manifests"][manifest_store["active_manifest"]]
                self.assertEqual(active_manifest["claim_generator"], "python_test_1/0.0.1")
                self.assertEqual(active_manifest["title"], "Python Test Image 1")
                for assertion in active_manifest["assertions"]:
                    if assertion["label"] == "com.unit.test":
                        self.assertEqual(assertion["data"]["author"][0]["name"], "Tester One")
                        break
            except Exception as e:
                read_errors.append(f"Reader {reader_id} error: {str(e)}")
            finally:
                with readers_lock:
                    active_readers -= 1

        write_thread = threading.Thread(target=write_manifest)
        write_thread.start()
        read_threads = [threading.Thread(target=read_manifest, args=(i,)) for i in range(reader_count)]
        for t in read_threads:
            t.start()
        write_thread.join()
        for t in read_threads:
            t.join()
        output.close()
        if write_errors:
            self.fail("\n".join(write_errors))
        if read_errors:
            self.fail("\n".join(read_errors))
        self.assertEqual(active_readers, 0)

    def test_resource_contention_read(self):
        """Test multiple threads reading the same file with context APIs"""
        output = io.BytesIO(bytearray())
        read_errors = []
        reader_count = 5
        active_readers = 0
        readers_lock = threading.Lock()
        stream_lock = threading.Lock()

        ctx = Context()
        with open(self.test_path, "rb") as file:
            builder = Builder(self.manifestDefinition_1, ctx)
            builder.sign(self.signer, "image/jpeg", file, output)
            output.seek(0)

        def read_manifest(reader_id):
            nonlocal active_readers
            try:
                with readers_lock:
                    active_readers += 1
                with stream_lock:
                    output.seek(0)
                    read_ctx = Context()
                    reader = Reader("image/jpeg", output, context=read_ctx)
                    json_data = reader.json()
                    manifest_store = json.loads(json_data)
                    active_manifest = manifest_store["manifests"][manifest_store["active_manifest"]]
                self.assertEqual(active_manifest["claim_generator"], "python_test_1/0.0.1")
                self.assertEqual(active_manifest["title"], "Python Test Image 1")
                for assertion in active_manifest["assertions"]:
                    if assertion["label"] == "com.unit.test":
                        self.assertEqual(assertion["data"]["author"][0]["name"], "Tester One")
                        break
                time.sleep(0.01)
            except Exception as e:
                read_errors.append(f"Reader {reader_id} error: {str(e)}")
            finally:
                with readers_lock:
                    active_readers -= 1

        read_threads = [threading.Thread(target=read_manifest, args=(i,)) for i in range(reader_count)]
        for t in read_threads:
            t.start()
        for t in read_threads:
            t.join()
        output.close()
        if read_errors:
            self.fail("\n".join(read_errors))
        self.assertEqual(active_readers, 0)

    def test_resource_contention_read_parallel(self):
        """Test multiple threads starting simultaneously to read with context APIs"""
        output = io.BytesIO(bytearray())
        read_errors = []
        reader_count = 5
        active_readers = 0
        readers_lock = threading.Lock()
        stream_lock = threading.Lock()
        start_barrier = threading.Barrier(reader_count)

        ctx = Context()
        with open(self.test_path, "rb") as file:
            builder = Builder(self.manifestDefinition_1, ctx)
            builder.sign(self.signer, "image/jpeg", file, output)
            output.seek(0)

        def read_manifest(reader_id):
            nonlocal active_readers
            try:
                with readers_lock:
                    active_readers += 1
                start_barrier.wait()
                with stream_lock:
                    output.seek(0)
                    read_ctx = Context()
                    reader = Reader("image/jpeg", output, context=read_ctx)
                    json_data = reader.json()
                    manifest_store = json.loads(json_data)
                    active_manifest = manifest_store["manifests"][manifest_store["active_manifest"]]
                self.assertEqual(active_manifest["claim_generator"], "python_test_1/0.0.1")
                self.assertEqual(active_manifest["title"], "Python Test Image 1")
                for assertion in active_manifest["assertions"]:
                    if assertion["label"] == "com.unit.test":
                        self.assertEqual(assertion["data"]["author"][0]["name"], "Tester One")
                        break
            except Exception as e:
                read_errors.append(f"Reader {reader_id} error: {str(e)}")
            finally:
                with readers_lock:
                    active_readers -= 1

        read_threads = [threading.Thread(target=read_manifest, args=(i,)) for i in range(reader_count)]
        for t in read_threads:
            t.start()
        for t in read_threads:
            t.join()
        output.close()
        if read_errors:
            self.fail("\n".join(read_errors))
        self.assertEqual(active_readers, 0)

    def test_sign_all_files_twice(self):
        """Test signing the same file twice with different manifests using context APIs"""
        output1 = io.BytesIO(bytearray())
        output2 = io.BytesIO(bytearray())
        sign_errors = []
        thread_results = {}
        thread_lock = threading.Lock()

        def sign_file(output_stream, manifest_def, thread_id):
            try:
                ctx = Context()
                with open(self.test_path, "rb") as file:
                    builder = Builder(manifest_def, ctx)
                    builder.sign(self.signer, "image/jpeg", file, output_stream)
                    output_stream.seek(0)
                    read_ctx = Context()
                    reader = Reader("image/jpeg", output_stream, context=read_ctx)
                    json_data = reader.json()
                    manifest_store = json.loads(json_data)
                    active_manifest = manifest_store["manifests"][manifest_store["active_manifest"]]
                    if thread_id == 1:
                        expected_claim_generator = "python_test_1/0.0.1"
                        expected_author = "Tester One"
                    else:
                        expected_claim_generator = "python_test_2/0.0.1"
                        expected_author = "Tester Two"
                    with thread_lock:
                        thread_results[thread_id] = {'manifest': active_manifest}
                    self.assertEqual(active_manifest["claim_generator"], expected_claim_generator)
                    for assertion in active_manifest["assertions"]:
                        if assertion["label"] == "com.unit.test":
                            self.assertEqual(assertion["data"]["author"][0]["name"], expected_author)
                            break
                    return None
            except Exception as e:
                return f"Thread {thread_id} error: {str(e)}"

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            future1 = executor.submit(sign_file, output1, self.manifestDefinition_1, 1)
            future2 = executor.submit(sign_file, output2, self.manifestDefinition_2, 2)
            for future in concurrent.futures.as_completed([future1, future2]):
                error = future.result()
                if error:
                    sign_errors.append(error)
        if sign_errors:
            self.fail("\n".join(sign_errors))
        self.assertEqual(len(thread_results), 2)
        output1.seek(0)
        output2.seek(0)
        read_ctx1 = Context()
        read_ctx2 = Context()
        reader1 = Reader("image/jpeg", output1, context=read_ctx1)
        reader2 = Reader("image/jpeg", output2, context=read_ctx2)
        manifest_store1 = json.loads(reader1.json())
        manifest_store2 = json.loads(reader2.json())
        active_manifest1 = manifest_store1["manifests"][manifest_store1["active_manifest"]]
        active_manifest2 = manifest_store2["manifests"][manifest_store2["active_manifest"]]
        self.assertNotEqual(active_manifest1["claim_generator"], active_manifest2["claim_generator"])
        self.assertNotEqual(active_manifest1["title"], active_manifest2["title"])
        output1.close()
        output2.close()

    def test_builder_sign_with_multiple_ingredient_random_many_threads(self):
        """Test Builder with 12 threads adding ingredients and signing using context APIs"""
        TOTAL_THREADS_USED = 12
        ingredient_files = [
            os.path.join(self.data_dir, "A_thumbnail.jpg"),
            os.path.join(self.data_dir, "C.jpg"),
            os.path.join(self.data_dir, "cloud.jpg")
        ]
        thread_results = {}
        completed_threads = 0
        thread_lock = threading.Lock()

        def thread_work(thread_id):
            nonlocal completed_threads
            try:
                ctx = Context()
                builder = Builder.from_json(self.manifestDefinition, context=ctx)
                for i, file_path in enumerate(ingredient_files, 1):
                    ingredient_json = json.dumps({"title": f"Thread {thread_id} Ingredient {i} - {os.path.basename(file_path)}"})
                    with open(file_path, 'rb') as f:
                        builder.add_ingredient(ingredient_json, "image/jpeg", f)
                sign_file_path = os.path.join(self.data_dir, "A.jpg")
                with open(sign_file_path, "rb") as file:
                    output = io.BytesIO()
                    builder.sign(self.signer, "image/jpeg", file, output)
                    output.flush()
                    output_data = output.getvalue()
                    input_stream = io.BytesIO(output_data)
                    read_ctx = Context()
                    reader = Reader("image/jpeg", input_stream, context=read_ctx)
                    json_data = reader.json()
                    manifest_data = json.loads(json_data)
                    with thread_lock:
                        thread_results[thread_id] = {
                            'manifest': manifest_data,
                            'ingredient_files': [os.path.basename(f) for f in ingredient_files],
                            'sign_file': os.path.basename(sign_file_path),
                            'manifest_hash': hash(json.dumps(manifest_data, sort_keys=True))
                        }
                    output.close()
                    input_stream.close()
                builder.close()
            except Exception as e:
                with thread_lock:
                    thread_results[thread_id] = {'error': str(e)}
            finally:
                with thread_lock:
                    completed_threads += 1

        threads = [threading.Thread(target=thread_work, args=(i,)) for i in range(1, TOTAL_THREADS_USED + 1)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(completed_threads, TOTAL_THREADS_USED)
        self.assertEqual(len(thread_results), TOTAL_THREADS_USED)
        manifest_hashes = set()
        thread_manifest_data = {}
        for thread_id in range(1, TOTAL_THREADS_USED + 1):
            result = thread_results[thread_id]
            if 'error' in result:
                self.fail(f"Thread {thread_id} failed with error: {result['error']}")
            manifest_data = result['manifest']
            ingredient_files_basename = result['ingredient_files']
            manifest_hash = result['manifest_hash']
            thread_manifest_data[thread_id] = manifest_data
            manifest_hashes.add(manifest_hash)
            self.assertIn("active_manifest", manifest_data)
            active_manifest_id = manifest_data["active_manifest"]
            self.assertIn("manifests", manifest_data)
            self.assertIn(active_manifest_id, manifest_data["manifests"])
            active_manifest = manifest_data["manifests"][active_manifest_id]
            self.assertIn("ingredients", active_manifest)
            self.assertEqual(len(active_manifest["ingredients"]), 3)
            ingredient_titles = [ing["title"] for ing in active_manifest["ingredients"]]
            for i, file_name in enumerate(ingredient_files_basename, 1):
                self.assertIn(f"Thread {thread_id} Ingredient {i} - {file_name}", ingredient_titles)
            for other_thread_id in range(1, TOTAL_THREADS_USED + 1):
                if other_thread_id != thread_id:
                    for title in ingredient_titles:
                        self.assertNotIn(f"Thread {other_thread_id} Ingredient", title)
        self.assertEqual(len(manifest_hashes), TOTAL_THREADS_USED)
        for thread_id in range(1, TOTAL_THREADS_USED + 1):
            current_manifest = thread_manifest_data[thread_id]
            self.assertIn("active_manifest", current_manifest)
            self.assertIn("manifests", current_manifest)
            for other_thread_id in range(1, TOTAL_THREADS_USED + 1):
                if other_thread_id != thread_id:
                    self.assertNotEqual(current_manifest["active_manifest"], thread_manifest_data[other_thread_id]["active_manifest"])


class TestWithFragmentReentrancy(unittest.TestCase):
    """with_fragment drives caller-supplied stream callbacks, so it must not
    hold a lock a callback-spawned thread would wait on.
    """

    def test_reentrant_call_is_refused_rather_than_blocked(self):
        init_path = os.path.join(FIXTURES_FOLDER, "dashinit.mp4")
        fragment_path = os.path.join(FIXTURES_FOLDER, "dash1.m4s")
        with open(init_path, "rb") as handle:
            init_bytes = handle.read()
        with open(fragment_path, "rb") as handle:
            fragment_bytes = handle.read()

        reader = Reader("video/mp4", io.BytesIO(init_bytes))
        state = {"fired": False, "result": None, "hung": None}

        class ReentrantStream(io.BytesIO):
            """Re-enters the API from another thread, from inside a callback,
            and waits for it: the shape that deadlocks a lock held across the
            native call.
            """

            def _reenter_once(self):
                if state["fired"]:
                    return
                state["fired"] = True

                def second_call():
                    try:
                        reader.with_fragment(
                            "video/mp4",
                            io.BytesIO(init_bytes),
                            io.BytesIO(fragment_bytes))
                        state["result"] = "completed"
                    except Error as e:
                        state["result"] = e

                thread = threading.Thread(target=second_call, daemon=True)
                thread.start()
                thread.join(10)
                state["hung"] = thread.is_alive()

            def read(self, size=-1):
                self._reenter_once()
                return super().read(size)

            def seek(self, offset, whence=0):
                self._reenter_once()
                return super().seek(offset, whence)

        reader.with_fragment("video/mp4",
                             ReentrantStream(init_bytes),
                             io.BytesIO(fragment_bytes))

        self.assertFalse(state["hung"], "re-entrant call blocked")
        self.assertIsInstance(state["result"], Error, "must refuse, not interleave")

class TestStreamCloseReentrancy(unittest.TestCase):
    """close() clears the callback references inside _close_lock, which can run
    a finalizer at that bytecode boundary, and __del__ takes the same lock.
    """

    def test_close_can_be_reentered_on_the_same_thread(self):
        stream = Stream(io.BytesIO(b"payload"))
        finished = threading.Event()

        def hold_then_reenter():
            with stream._close_lock:
                # A finalizer running here re-takes the lock this thread holds.
                stream.close()
            finished.set()

        worker = threading.Thread(target=hold_then_reenter, daemon=True)
        worker.start()

        self.assertTrue(finished.wait(10), "re-entrant close() blocked")


class TestConsumeReservationWindow(unittest.TestCase):
    """The consume reservation must outlast ownership classification.

    The reservation is a mutating in-flight mark. The lifecycle state stays
    ACTIVE. _read_native_error() is a native call that releases the GIL, so a
    reservation released before the error is classified would let another
    thread use a handle native may already own.
    """

    def test_no_thread_sees_a_consumed_handle_as_valid(self):
        resource = Settings()

        reading = threading.Event()
        may_finish = threading.Event()
        seen_valid = []

        real_read = c2pa_module._read_native_error

        def gated_read():
            # Stand in for the GIL release inside the real native call.
            reading.set()
            may_finish.wait(10)
            # No pre-consume tag: native took ownership and then failed.
            return "Other: operation failed after taking ownership"

        def observer():
            if not reading.wait(10):
                return
            # The consuming call is mid-classification at this point.
            seen_valid.append(resource.is_valid)
            may_finish.set()

        watcher = threading.Thread(target=observer, daemon=True)
        watcher.start()

        c2pa_module._read_native_error = gated_read
        try:
            with self.assertRaises(Error):
                resource._consume_no_replacement(lambda h: 1, "consume: {}")
        finally:
            c2pa_module._read_native_error = real_read
            may_finish.set()
            watcher.join(10)

        self.assertFalse(seen_valid[0], "consumed handle seen valid")


class TestLocking(unittest.TestCase):
    """Tests for the locks that guard native resources:
    - the per-object operation lock that serializes native calls against teardown,
    - the fragment lock,
    - cross-thread creation/closing/releasing.

    Every join here is bounded:
    A deadlock must fail the test when timing out, not hang the suite.
    """

    JOIN_TIMEOUT = 30

    @classmethod
    def setUpClass(cls):
        cls.data_dir = FIXTURES_FOLDER
        with open(DEFAULT_TEST_FILE, 'rb') as handle:
            cls.image_bytes = handle.read()
        with open(os.path.join(FIXTURES_FOLDER,
                               "es256_certs.pem"), 'rb') as handle:
            cls.certs = handle.read()
        with open(os.path.join(FIXTURES_FOLDER,
                               "es256_private.key"), 'rb') as handle:
            cls.private_key = handle.read()

    def setUp(self):
        # Flush pending finalizers through the real free first.
        gc.collect()
        self.freed = []
        self._real_free = ManagedResource._free_native_ptr
        # Registered first so it runs last, after every patch has unwound.
        self.addCleanup(self._assert_free_hook_restored)
        _patch_free(self, self.freed.append)

    def _assert_free_hook_restored(self):
        self.assertIs(
            ManagedResource._free_native_ptr, self._real_free,
            "{} leaked a _free_native_ptr patch".format(self.id()))

    def _join_all(self, threads, what):
        for thread in threads:
            thread.join(self.JOIN_TIMEOUT)
        stuck = [t for t in threads if t.is_alive()]
        self.assertEqual(
            stuck, [],
            "{} did not finish within {}s: deadlock".format(
                what, self.JOIN_TIMEOUT))

    def _run_isolated(self, body, timeout=180):
        """Run body in a subprocess and return it,
        so that crashes can be caught and do not crash the suite itself.
        """
        source = textwrap.dedent(body)
        return subprocess.run(
            [sys.executable, "-c", source],
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            capture_output=True,
            timeout=timeout,
        )

    def _free_counts(self):
        counts = {}
        for handle in self.freed:
            counts[handle] = counts.get(handle, 0) + 1
        return counts

    def test_cross_thread_create_and_close_frees_exactly_once(self):
        count = 300

        def create(index):
            res = _ConcreteResource()
            res._activate(0x10000 + index)
            return res

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            created = list(pool.map(create, range(count)))

        # Created on worker threads, closed on the main thread.
        for res in created:
            res.close()

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            made_on_main = []
            for index in range(count):
                res = _ConcreteResource()
                res._activate(0x20000 + index)
                made_on_main.append(res)
            # Created on the main thread, closed on worker threads.
            list(pool.map(lambda r: r.close(), made_on_main))

        expected = {0x10000 + i: 1 for i in range(count)}
        expected.update({0x20000 + i: 1 for i in range(count)})
        # Restrict to this test's handles: resources dropped by other tests in
        # the class can be collected at any point and land in self.freed.
        counts = {handle: value
                  for handle, value in self._free_counts().items()
                  if handle in expected}
        self.assertEqual(counts, expected)

    def test_third_thread_gc_of_dropped_reference_frees_exactly_once(self):
        def make_and_drop(index):
            res = _ConcreteResource()
            res._activate(0x30000 + index)
            # Reference dies here; __del__ may run on this thread or later.
            return index

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(make_and_drop, range(200)))

        gc.collect()

        # Count only this test's handles
        counts = {handle: count
                  for handle, count in self._free_counts().items()
                  if 0x30000 <= handle < 0x30000 + 200}
        self.assertEqual(counts, dict.fromkeys(range(0x30000, 0x30000 + 200), 1))

    def test_close_queued_inside_a_lock_hold_is_not_orphaned(self):
        resource = _ConcreteResource()
        resource._activate(0x60001)

        real_lock = resource._op_lock
        closed = threading.Event()
        join_timeout = self.JOIN_TIMEOUT

        class GatedLock:
            def acquire(self, blocking=True, timeout=-1):
                if timeout == -1:
                    return real_lock.acquire(blocking)
                return real_lock.acquire(blocking, timeout)

            def release(self):
                return real_lock.release()

            def __enter__(self):
                real_lock.acquire()
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                if not closed.is_set():
                    worker = threading.Thread(
                        target=lambda: (resource.close(), closed.set()),
                        daemon=True)
                    worker.start()
                    worker.join(join_timeout)
                real_lock.release()
                return False

        resource._op_lock = GatedLock()
        try:
            with resource._guarded_op():
                pass
        finally:
            resource._op_lock = real_lock

        self.assertTrue(closed.is_set(), "close() was never injected")
        self.assertEqual(self._free_counts().get(0x60001), 1, "orphaned")

    def test_closed_reader_never_serves_cached_manifest(self):
        reader = Reader("image/jpeg", io.BytesIO(self.image_bytes))
        reader.get_active_manifest()

        parked = threading.Event()
        go = threading.Event()
        real_release = reader._release

        def gated_release():
            parked.set()
            go.wait(self.JOIN_TIMEOUT)
            real_release()

        reader._release = gated_release
        closer = threading.Thread(target=reader.close, daemon=True)
        closer.start()
        self.assertTrue(parked.wait(self.JOIN_TIMEOUT))

        served = []

        def read():
            try:
                served.append(reader.get_active_manifest())
            except Error as e:
                served.append(e)

        reader_thread = threading.Thread(target=read, daemon=True)
        reader_thread.start()
        reader_thread.join(1)
        go.set()
        self._join_all([closer, reader_thread], "close and read")

        self.assertIsInstance(served[0], Error, "closed Reader served cache")

    def test_release_may_wait_on_a_thread_that_takes_the_op_lock(self):
        class Polled(_ConcreteResource):
            def __init__(self):
                super().__init__()
                self.go = threading.Event()
                self.worker = None

            def _shutdown_path(self):
                self.go.wait(TestLocking.JOIN_TIMEOUT)
                try:
                    with self._guarded_op():
                        pass
                except Error:
                    pass

            def _release(self):
                self.go.set()
                self.worker.join()

        resource = Polled()
        resource._activate(0x52000)
        resource.worker = threading.Thread(
            target=resource._shutdown_path, daemon=True)
        resource.worker.start()

        closer = threading.Thread(target=resource.close, daemon=True)
        closer.start()
        closer.join(5)
        if closer.is_alive():
            resource.worker = threading.Thread(target=lambda: None)
        self.assertFalse(closer.is_alive(), "close() blocked")

    def test_settings_relayed_across_threads_stays_usable(self):
        _patch_free(self, self._real_free)

        manifest = {
            "claim_generator": "threaded_stamp_test",
            "format": "image/jpeg",
            "assertions": [],
        }
        settings = Settings()
        results = []
        errors = []

        def build_context_and_builder():
            try:
                context = Context(settings=settings)
                builder = Builder(manifest, context=context)
                results.append(builder.is_valid)
                builder.close()
                context.close()
            except Exception as exc:
                errors.append(exc)

        # Each thread owns the Settings for its turn.
        for _ in range(8):
            thread = threading.Thread(target=build_context_and_builder)
            thread.start()
            thread.join()

        settings.close()

        self.assertEqual(results, [True] * 8, errors)

    def test_json_racing_finalizer_does_not_crash(self):
        """Readers used on one thread while others are collected.
        """
        result = self._run_isolated("""
            import sys, io, gc, random, threading, time
            sys.path.insert(0, "src")
            from c2pa import Reader

            data = open("tests/fixtures/C.jpg", "rb").read()
            stop = threading.Event()
            pool, lock = [], threading.Lock()

            def worker():
                while not stop.is_set():
                    choice = random.random()
                    try:
                        if choice < 0.40:
                            reader = Reader("image/jpeg", io.BytesIO(data))
                            with lock:
                                pool.append(reader)
                        elif choice < 0.75:
                            with lock:
                                snapshot = list(pool)
                            if snapshot:
                                reader = random.choice(snapshot)
                                reader._manifest_json_str_cache = None
                                reader.json()
                        elif choice < 0.90:
                            with lock:
                                reader = pool.pop(0) if pool else None
                            if reader:
                                reader.close()
                        else:
                            with lock:
                                if len(pool) > 20:
                                    del pool[0:5]
                            gc.collect()
                    except Exception:
                        pass

            threads = [threading.Thread(target=worker) for _ in range(12)]
            for thread in threads:
                thread.start()
            deadline = time.time() + 10
            while time.time() < deadline:
                time.sleep(0.05)
            stop.set()
            for thread in threads:
                thread.join(30)
        """)
        self.assertEqual(result.returncode, 0, result.stderr.decode()[-800:])

    def test_stream_callback_blocking_on_other_thread_does_not_deadlock(self):
        """A stream callback that blocks on another thread
        which touches the same object.

        A lock held across construction deadlocks here, whether it is global
        or per-object.
        """
        data = self.image_bytes
        target = Reader("image/jpeg", io.BytesIO(data))
        errors = []

        class BlockingStream(io.BytesIO):
            def readinto(self, buffer):
                def use():
                    try:
                        target._manifest_json_str_cache = None
                        target.json()
                    except Exception:
                        pass

                helper = threading.Thread(target=use)
                helper.start()
                helper.join(10)
                if helper.is_alive():
                    errors.append("helper stuck inside stream callback")
                return super().readinto(buffer)

        def body():
            try:
                for _ in range(5):
                    Reader("image/jpeg", BlockingStream(data))
            except Exception as exc:
                errors.append(repr(exc))

        thread = threading.Thread(target=body)
        thread.start()
        self._join_all([thread], "callback blocking on another thread")
        self.assertEqual(errors, [])
        target.close()

    def test_no_nested_op_locks(self):
        """No code path may hold two resources' operation locks at once.
        With only one lock ever held, no cycle can form here.
        """
        data = self.image_bytes
        held = threading.local()
        violations = []
        real_lock = ManagedResource._guarded_op
        real_live_op_lock = ManagedResource._live_op_lock

        def make_tracking(real):
            def tracking(resource, **kw):
                lock = real(resource, **kw)
                depth = getattr(held, 'stack', None)
                if depth is None:
                    depth = held.stack = []

                class Tracked:
                    def __enter__(self):
                        others = [r for r in depth if r is not resource]
                        if others:
                            violations.append(
                                "{} while holding {}".format(
                                    type(resource).__name__,
                                    [type(o).__name__ for o in others]))
                        depth.append(resource)
                        return lock.__enter__()

                    def __exit__(self, *exc):
                        depth.pop()
                        return lock.__exit__(*exc)

                return Tracked()
            return tracking

        ManagedResource._guarded_op = make_tracking(real_lock)
        ManagedResource._live_op_lock = make_tracking(real_live_op_lock)
        try:
            reader = Reader("image/jpeg", io.BytesIO(data))
            reader.json()
            reader.detailed_json()
            reader.is_embedded()
            reader.get_remote_url()
            reader.close()
        finally:
            ManagedResource._guarded_op = real_lock
            ManagedResource._live_op_lock = real_live_op_lock

        self.assertEqual(violations, [], "nested op locks")

    def test_native_section_deferred_free_is_thread_local(self):
        """Two threads each with their own open native-error section: one
        thread's section closing must not flush a free deferred inside
        the other thread's still-open section.
        """
        freed = self._counted_free()
        resource = _ConcreteResource()
        resource._activate(0x1001)

        thread_ready = threading.Event()
        release_thread = threading.Event()

        def worker():
            with _native_section():
                resource.close()
                thread_ready.set()
                release_thread.wait(self.JOIN_TIMEOUT)
            # Flush happens here, on the worker thread, once its own
            # section closes.

        thread = threading.Thread(target=worker)
        thread.start()
        try:
            self.assertTrue(thread_ready.wait(self.JOIN_TIMEOUT))

            # A section opened and closed entirely on this (main) thread,
            # while the worker's section is still open on its own thread.
            with _native_section():
                pass

            self.assertEqual(freed, [], "other thread's section flushed")
        finally:
            release_thread.set()
        self._join_all([thread], "native-section worker")

        self.assertEqual(freed, [0x1001], "own section never flushed")

    def _counted_free(self):
        """Patch _free_native_ptr to count frees; returns the list."""
        freed = []
        real = ManagedResource._free_native_ptr

        def counting(ptr):
            freed.append(ptr)
            return real(ptr)

        _patch_free(self, counting)
        return freed

    def _thumbnail_uri(self, reader):
        manifests = json.loads(reader.json()).get("manifests", {})
        for manifest in manifests.values():
            thumbnail = manifest.get("thumbnail")
            if thumbnail and thumbnail.get("identifier"):
                return thumbnail["identifier"]
        self.skipTest("fixture has no thumbnail resource to stream")

    def test_close_inside_callback_defers_free(self):
        """A close() from inside a stream callback must not free the handle
        the native call is still using."""
        freed = self._counted_free()
        reader = Reader("image/jpeg", io.BytesIO(self.image_bytes))
        uri = self._thumbnail_uri(reader)
        during = []

        class Closer(io.BytesIO):
            def write(self, buffer):
                reader.close()
                during.append(len(freed))
                return super().write(buffer)

        try:
            reader.resource_to_stream(uri, Closer())
        except Error:
            pass

        self.assertEqual(during, [0], "handle was freed mid-call")
        self.assertEqual(len(freed), 1)

    def test_with_fragment_closes_main_stream_when_second_stream_fails(self):
        """Streams in with_fragment on failure must not get into a broken state"""
        opened = []
        real_init = Stream.__init__

        def tracking_init(wrapper, source):
            if opened:
                raise ValueError("fragment stream could not be built")
            real_init(wrapper, source)
            opened.append(wrapper)

        reader = Reader("image/jpeg", io.BytesIO(self.image_bytes))
        self.addCleanup(reader.close)

        with patch.object(Stream, '__init__', tracking_init):
            with self.assertRaises(ValueError):
                reader.with_fragment(
                    "video/mp4",
                    io.BytesIO(self.image_bytes),
                    io.BytesIO(self.image_bytes))

        self.assertTrue(opened[0].closed, "main stream left open")

    def test_use_after_deferred_close_is_rejected(self):
        """Deferring must not leave the resource usable:
        the free is pending, so the handle is about to go away."""
        reader = Reader("image/jpeg", io.BytesIO(self.image_bytes))
        uri = self._thumbnail_uri(reader)
        states = []

        class Closer(io.BytesIO):
            def write(self, buffer):
                reader.close()
                states.append(reader._lifecycle_state)
                try:
                    reader.json()
                    states.append("json succeeded")
                except Error:
                    states.append("json rejected")
                return super().write(buffer)

        try:
            reader.resource_to_stream(uri, Closer())
        except Error:
            pass

        self.assertEqual(states[1], "json rejected")

    def test_release_raising_during_deferred_teardown_does_not_leak(self):
        """The deferred free survives a failing _release:
        the handle must still be freed."""
        freed = self._counted_free()
        reader = Reader("image/jpeg", io.BytesIO(self.image_bytes))
        uri = self._thumbnail_uri(reader)

        def boom(self):
            raise RuntimeError("release failure")

        class Closer(io.BytesIO):
            def write(self, buffer):
                reader.close()
                return super().write(buffer)

        with patch.object(Reader, '_release', boom):
            try:
                reader.resource_to_stream(uri, Closer())
            except Error:
                pass

        self.assertEqual(len(freed), 1, "handle leaked")

    def test_concurrent_closes_during_callback_free_once(self):
        """Many threads closing while one native call is in flight
        must produce exactly one free (avoid double-frees,
        or freeing something the object wouldn't own)."""
        freed = self._counted_free()
        reader = Reader("image/jpeg", io.BytesIO(self.image_bytes))
        uri = self._thumbnail_uri(reader)
        started = threading.Event()
        closers = []
        during = []

        class Slow(io.BytesIO):
            def write(self, buffer):
                started.set()
                time.sleep(0.3)
                during.append(len(freed))
                return super().write(buffer)

        def closer():
            started.wait(self.JOIN_TIMEOUT)
            reader.close()

        for _ in range(8):
            thread = threading.Thread(target=closer)
            closers.append(thread)
            thread.start()
        try:
            reader.resource_to_stream(uri, Slow())
        except Error:
            pass
        self._join_all(closers, "concurrent closers")

        self.assertEqual(during[:1], [0], "handle was freed mid-call")
        self.assertEqual(len(freed), 1)

    def _borrow_resource(self):
        """An ACTIVE resource with no native handle behind it."""
        res = _ConcreteResource()
        res._lifecycle_state = LifecycleState.ACTIVE
        res._handle = ctypes.c_void_p(1)
        return res

    def _park(self, res, enter):
        """Hold `enter(res)` open on another thread.
        Returns (thread, release)."""
        inside = threading.Event()
        release = threading.Event()

        def holder():
            with enter(res):
                inside.set()
                release.wait(self.JOIN_TIMEOUT)

        thread = threading.Thread(target=holder, daemon=True)
        thread.start()
        self.assertTrue(inside.wait(self.JOIN_TIMEOUT),
                        "holder never entered its native call")
        return thread, release

    def test_is_valid_false_during_exclusive_guarded_op(self):
        res = self._borrow_resource()
        thread, release = self._park(
            res, lambda r: r._guarded_op(exclusive=True))
        try:
            self.assertFalse(res.is_valid)
        finally:
            release.set()
            self._join_all([thread], "exclusive guarded holder")
        self.assertTrue(res.is_valid)

    def test_reservation_matrix(self):
        """Readers share, writers exclude everyone.

        In flight: the two reservation kinds (a _guarded_op holds the lock,
        so a second caller blocks on it rather than being refused).
        """
        def consume(r):
            r._consume_no_replacement(lambda h: 0, "unused: {}")

        def entered(cm):
            def run(r):
                with cm(r):
                    pass
            return run

        in_flight = {
            "shared": lambda r: r._native_call(),
            "exclusive": lambda r: r._exclusive_native_call(),
        }
        attempts = {
            "shared": entered(lambda r: r._native_call()),
            "exclusive": entered(lambda r: r._exclusive_native_call()),
            "guarded": entered(lambda r: r._guarded_op()),
            "guarded_exclusive": entered(
                lambda r: r._guarded_op(exclusive=True)),
            "consume": consume,
        }
        admitted = {("shared", "shared"), ("shared", "guarded")}

        wrong = []
        for held_name, held in in_flight.items():
            for new_name, attempt in attempts.items():
                res = self._borrow_resource()
                thread, release = self._park(res, held)
                try:
                    try:
                        attempt(res)
                        got = True
                    except Error:
                        got = False
                finally:
                    release.set()
                    self._join_all([thread], "holder")
                want = (held_name, new_name) in admitted
                if got != want:
                    wrong.append("{} in flight, {} {}".format(
                        held_name, new_name,
                        "admitted" if got else "refused"))

        self.assertEqual(wrong, [])

    def test_settings_update_refused_during_settings_borrow(self):
        """Settings.update/set take &mut.
        Context construction borrows the same Settings as &.
        The mutation must be refused.
        """
        settings = Settings()
        lib = c2pa_module._lib
        real_set_settings = lib.c2pa_context_builder_set_settings
        parked = threading.Event()
        release = threading.Event()

        def gated_set_settings(builder, handle):
            parked.set()
            release.wait(self.JOIN_TIMEOUT)
            return real_set_settings(builder, handle)

        built = []
        lib.c2pa_context_builder_set_settings = gated_set_settings
        thread = threading.Thread(
            target=lambda: built.append(Context(settings=settings)),
            daemon=True)
        try:
            thread.start()
            parked.wait(self.JOIN_TIMEOUT)
            with self.assertRaises(Error):
                settings.update({"builder": {"thumbnail": {"enabled": False}}})
            with self.assertRaises(Error):
                settings.set("builder.thumbnail.enabled", "false")
        finally:
            release.set()
            self._join_all([thread], "Context construction")
            lib.c2pa_context_builder_set_settings = real_set_settings
            for context in built:
                context.close()
            settings.close()

    def test_deferred_consume_is_not_upgraded_to_free(self):
        """A deferred consuming teardown must not be overwritten by a later
        free intent arriving while the same call is still in flight.

        Scenario: a Signer shared across concurrent signs: sign borrows
        the handle (holding the in-flight guard) while Context.__init__
        consumes it.
        """
        freed = self._counted_free()
        reader = Reader("image/jpeg", io.BytesIO(self.image_bytes))

        with reader._native_call():
            # The consuming call: native took ownership, so nothing here frees.
            reader._teardown(free_handle=False)

            # A free intent arriving behind it, past a stale state check.
            reader._teardown(free_handle=True)

        self.assertEqual(freed, [], "freed a consumed handle")

    def test_concurrent_close_runs_release_once(self):
        """Two racing close() calls on one instance must run _release()
        exactly once.

        The native free is already single (the handle is nulled after the
        first teardown), so a free-counting test cannot see this: it is
        What must not run twice is _release(), the Python-side
        stream/cache cleanup a subclass overrides. _teardown() has to be
        idempotent under its own lock.

        Gate _teardown so the first close() pauses on entry, before taking
        the lock; the second then runs a full teardown (release + free +
        mark closed); the first resumes and must find the resource already
        released and do nothing.
        """
        join_timeout = self.JOIN_TIMEOUT
        orig_teardown = ManagedResource._teardown

        reader = Reader("image/jpeg", io.BytesIO(self.image_bytes))
        release_calls = []
        orig_release = reader._release

        def counting_release(_orig=orig_release, _calls=release_calls):
            _calls.append(1)
            _orig()

        reader._release = counting_release

        call_count = {"n": 0}
        count_lock = threading.Lock()
        first_arrived = threading.Event()
        release_first = threading.Event()

        def gated_teardown(self, free_handle, _target=reader,
                           _timeout=join_timeout):
            if self is _target:
                with count_lock:
                    call_count["n"] += 1
                    is_first = call_count["n"] == 1
                if is_first:
                    first_arrived.set()
                    release_first.wait(_timeout)
            return orig_teardown(self, free_handle)

        with patch.object(ManagedResource, '_teardown', gated_teardown):
            t1 = threading.Thread(target=reader.close)
            t1.start()
            self.assertTrue(first_arrived.wait(join_timeout))

            t2 = threading.Thread(target=reader.close)
            t2.start()
            t2.join(join_timeout)

            release_first.set()
            self._join_all([t1], "paused close() resuming")

        self.assertEqual(len(release_calls), 1, "_release() not idempotent")

    def test_sign_raising_native_call_closes_builder(self):
        freed = self._counted_free()
        signer = Signer.from_info(C2paSignerInfo(
            alg=b"es256", sign_cert=self.certs,
            private_key=self.private_key, ta_url=None))
        self.addCleanup(signer.close)
        builder = Builder({"claim_generator": "python_test",
                           "format": "image/jpeg", "assertions": []})
        real_sign = c2pa_module._lib.c2pa_builder_sign

        def raising(*args):
            raise RuntimeError("native sign raised")

        c2pa_module._lib.c2pa_builder_sign = raising
        try:
            with self.assertRaises(Error):
                builder.sign(signer, "image/jpeg",
                             io.BytesIO(self.image_bytes), io.BytesIO())
        finally:
            c2pa_module._lib.c2pa_builder_sign = real_sign
        self.assertEqual(len([f for f in freed if f]), 1)

    def test_every_callback_running_method_is_guarded(self):
        """Every method that hands a Stream to the native lib must be guarded,
        except the construction paths.
        """
        source = inspect.getsource(sys.modules[Reader.__module__])
        lines = source.split("\n")
        class_a = {
            ("Reader", "_create_reader"),
            ("Reader", "_init_from_context"),
            ("Builder", "from_archive"),
        }
        stream_use = re.compile(
            r"(_stream|stream_obj|source_stream|dest_stream|main_obj"
            r"|frag_obj)\._stream")

        bodies = {}
        current_class = current_method = None
        start = None
        for index, line in enumerate(lines):
            if re.match(r"^class ", line):
                current_class = line.split("(")[0].replace(
                    "class ", "").strip(":")
            if re.match(r"^def ", line):
                current_class = None
            match = re.match(r"^    def (\w+)", line)
            if match:
                if current_class and current_method and start is not None:
                    bodies[(current_class, current_method)] = "\n".join(
                        lines[start:index])
                current_method = match.group(1)
                start = index
        if current_class and current_method and start is not None:
            bodies[(current_class, current_method)] = "\n".join(lines[start:])

        unguarded = []
        checked = 0
        for key, body in bodies.items():
            if not stream_use.search(body):
                continue
            checked += 1
            if key in class_a:
                continue
            if ("_native_call()" not in body
                    and "_exclusive_native_call()" not in body
                    and "_consume_and_swap(" not in body):
                unguarded.append("{}.{}".format(*key))

        self.assertGreater(checked, 0, "coverage scan found no methods")
        self.assertEqual(unguarded, [])

    def test_every_borrowed_handle_is_guarded(self):
        """When a method hands a second object's handle to the native library,
        that object needs its own _native_call() guard.

        This can happen in callbacks, where you can't express whose handle
        is the one needing attention.
        """
        module = sys.modules[Reader.__module__]
        tree = ast.parse(inspect.getsource(module))

        # Attributes that carry a native handle out of an object.
        handle_attrs = {"_handle", "execution_context"}

        def guarded_names(node):
            """Names X guarded at this node, by either form:
            `with X._native_call():`, or `with _context_guard(X):` for a
            caller-supplied ContextProvider, which enters X._native_call()
            when X offers it.
            """
            found = set()
            calls = []
            for item in getattr(node, "items", []):
                expr = item.context_expr
                if isinstance(expr, ast.IfExp):
                    calls.extend([expr.body, expr.orelse])
                else:
                    calls.append(expr)
            for call in calls:
                if not isinstance(call, ast.Call):
                    continue
                if (isinstance(call.func, ast.Attribute)
                        and call.func.attr == "_native_call"
                        and isinstance(call.func.value, ast.Name)):
                    found.add(call.func.value.id)
                elif (isinstance(call.func, ast.Name)
                        and call.func.id == "_context_guard"
                        and call.args
                        and isinstance(call.args[0], ast.Name)):
                    found.add(call.args[0].id)
            return found

        def borrowed_in_call(call):
            """Names X whose handle this _lib.* call receives, X not self."""
            if not (isinstance(call.func, ast.Attribute)
                    and isinstance(call.func.value, ast.Name)
                    and call.func.value.id == "_lib"):
                return set()
            names = set()
            for arg in ast.walk(call):
                if (isinstance(arg, ast.Attribute)
                        and arg.attr in handle_attrs
                        and isinstance(arg.value, ast.Name)
                        and arg.value.id != "self"):
                    names.add(arg.value.id)
            return names

        def locally_owned(method):
            """A resource created inside the method never escapes to another
            thread, so nothing can close it mid-call and it needs no guard.
            """
            owned = set()
            for node in ast.walk(method):
                # `with self._NativeContextBuilder() as context_builder:` / `x = Foo()`
                if isinstance(node, (ast.With, ast.AsyncWith)):
                    for item in node.items:
                        if (isinstance(item.context_expr, ast.Call)
                                and isinstance(item.optional_vars, ast.Name)):
                            owned.add(item.optional_vars.id)
                elif isinstance(node, ast.Assign):
                    if isinstance(node.value, ast.Call):
                        for target in node.targets:
                            if isinstance(target, ast.Name):
                                owned.add(target.id)
            return owned

        unguarded = []
        checked = 0

        for cls in ast.walk(tree):
            if not isinstance(cls, ast.ClassDef):
                continue
            for method in cls.body:
                if not isinstance(method, (ast.FunctionDef,
                                           ast.AsyncFunctionDef)):
                    continue
                owned = locally_owned(method)

                # Walk the body tracking which guards are open, so a borrowed
                # handle is only accepted when its own guard encloses the use.
                def visit(node, active):
                    nonlocal checked
                    if isinstance(node, (ast.With, ast.AsyncWith)):
                        active = active | guarded_names(node)
                    if isinstance(node, ast.Call):
                        for name in borrowed_in_call(node) - owned:
                            checked += 1
                            if name not in active:
                                unguarded.append(
                                    "{}.{} passes {}._handle to native "
                                    "without {}._native_call()".format(
                                        cls.name, method.name, name, name))
                    for child in ast.iter_child_nodes(node):
                        visit(child, active)

                visit(method, frozenset())

        self.assertGreater(checked, 0, "scan found nothing")
        self.assertEqual(unguarded, [], "unguarded: " + ", ".join(unguarded))

    # FFI functions that take their receiver (first argument) as &mut.
    MUTATING_FFI = frozenset({
        "c2pa_settings_set_value",
        "c2pa_settings_update_from_string",
        "c2pa_context_builder_set_settings",
        "c2pa_builder_set_intent",
        "c2pa_builder_set_no_embed",
        "c2pa_builder_set_remote_url",
        "c2pa_builder_add_action",
        "c2pa_builder_add_resource",
        "c2pa_builder_add_ingredient_from_stream",
        "c2pa_builder_add_ingredient_from_archive",
        "c2pa_builder_sign",
        "c2pa_builder_sign_context",
    })

    def test_every_mutating_ffi_call_is_exclusive(self):
        """A native call taking its receiver as &mut must run under an
        exclusive guard on that receiver.
        """
        tree = ast.parse(inspect.getsource(sys.modules[Reader.__module__]))

        def exclusive_names(node):
            found = set()
            for item in getattr(node, "items", []):
                call = item.context_expr
                if not (isinstance(call, ast.Call)
                        and isinstance(call.func, ast.Attribute)
                        and isinstance(call.func.value, ast.Name)):
                    continue
                attr = call.func.attr
                exclusive_kw = any(
                    kw.arg == "exclusive"
                    and isinstance(kw.value, ast.Constant)
                    and kw.value.value is True
                    for kw in call.keywords)
                if (attr == "_exclusive_native_call"
                        or (attr == "_guarded_op" and exclusive_kw)):
                    found.add(call.func.value.id)
            return found

        def receiver(call):
            if call.args:
                first = call.args[0]
                if (isinstance(first, ast.Attribute)
                        and first.attr == "_handle"
                        and isinstance(first.value, ast.Name)):
                    return first.value.id
            return None

        seen = set()
        unguarded = []

        def visit(node, active, where):
            if isinstance(node, (ast.With, ast.AsyncWith)):
                active = active | exclusive_names(node)
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "_lib"
                    and node.func.attr in self.MUTATING_FFI):
                seen.add(node.func.attr)
                name = receiver(node)
                if name is None or name not in active:
                    unguarded.append("{} calls {} without an exclusive "
                                     "guard on {}".format(
                                         where, node.func.attr, name))
            for child in ast.iter_child_nodes(node):
                visit(child, active, where)

        for cls in ast.walk(tree):
            if isinstance(cls, ast.ClassDef):
                for method in cls.body:
                    if isinstance(method, (ast.FunctionDef,
                                           ast.AsyncFunctionDef)):
                        visit(method, frozenset(),
                              "{}.{}".format(cls.name, method.name))

        # Positive control: verify call seen.
        self.assertEqual(seen, set(self.MUTATING_FFI))
        self.assertEqual(unguarded, [], ", ".join(unguarded))

    def test_no_native_call_under_a_shared_guarded_op(self):
        """A Reader's direct native calls run under a reservation, so they do
        not serialize on one Reader. The manifest-field getters still share
        the op lock through _get_cached_manifest_data.
        """
        tree = ast.parse(inspect.getsource(sys.modules[Reader.__module__]))

        def is_shared_guarded_op(node):
            for item in node.items:
                call = item.context_expr
                if (isinstance(call, ast.Call)
                        and isinstance(call.func, ast.Attribute)
                        and call.func.attr == "_guarded_op"
                        and not any(kw.arg == "exclusive"
                                    for kw in call.keywords)):
                    return True
            return False

        found = set()

        def visit(node, shared, where):
            if isinstance(node, ast.With) and is_shared_guarded_op(node):
                shared = True
            if (shared and isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "_lib"):
                found.add((where, node.func.attr))
            for child in ast.iter_child_nodes(node):
                visit(child, shared, where)

        for cls in ast.walk(tree):
            if isinstance(cls, ast.ClassDef):
                for method in cls.body:
                    if isinstance(method, ast.FunctionDef):
                        visit(method, False,
                              "{}.{}".format(cls.name, method.name))

        self.assertEqual(
            sorted(f for f in found if f[0].startswith("Reader.")), [])

    def _callback_signer_source(self):
        """Shared subprocess preamble: an ES256 callback signer."""
        return """
            import io, os, sys, threading, time
            from c2pa import (Builder, Context, Signer,
                              C2paSigningAlg as SigningAlg)
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric import ec

            data_dir = sys.argv[1]
            certs = open(os.path.join(data_dir,
                                      "es256_certs.pem"), "rb").read().decode()
            key_path = os.path.join(data_dir, "es256_private.key")
            key = open(key_path, "rb").read()
            img = open(os.path.join(data_dir, "C.jpg"), "rb").read()
            manifest = {"claim_generator_info":
                        [{"name": "test", "version": "0.1"}],
                        "assertions": []}
            private_key = serialization.load_pem_private_key(
                key, password=None)

            def sign_callback(data):
                return private_key.sign(data, ec.ECDSA(hashes.SHA256()))

            def make_context():
                return Context(signer=Signer.from_callback(
                    sign_callback, SigningAlg.ES256, certs,
                    "http://timestamp.digicert.com"))
"""

    def test_context_close_during_context_sign_does_not_crash(self):
        """Closing a Context must not free the signer callback mid-sign.

        Context.__init__ pins the consumed signer's ctypes callback so it
        outlives the Signer object, and Context._release() drops that pin.
        Without an in-flight guard on the Context, a close() on another thread
        runs _release() while c2pa_builder_sign_context is calling through the
        trampoline, and the process dies with SIGSEGV.

        Runs in a subprocess: the failure mode is a segfault, which would take
        the test runner down with it otherwise.
        """
        source = textwrap.dedent(self._callback_signer_source() + """
            for trial in range(60):
                ctx = make_context()
                entered = threading.Event()

                def worker():
                    try:
                        builder = Builder(dict(manifest), context=ctx)
                        entered.set()
                        builder.sign("image/jpeg", io.BytesIO(img),
                                     io.BytesIO())
                        builder.close()
                    except Exception:
                        # A closed context may be rejected;
                        # only a crash is a failure here.
                        entered.set()

                t = threading.Thread(target=worker)
                t.start()
                entered.wait(5)
                time.sleep(0.002)
                ctx.close()
                t.join(20)
            print("OK")
        """)

        result = subprocess.run(
            [sys.executable, "-c", source, self.data_dir],
            capture_output=True, text=True, timeout=300)

        self.assertEqual(result.returncode, 0, result.stderr[-2000:])
        self.assertIn("OK", result.stdout)

    def test_section_drain_error_does_not_mask_the_body_error(self):
        """The body's exception is what the caller asked for, so it wins."""

        class FlushRaises:
            _pending_teardown = True

            def _maybe_flush_pending(self):
                raise RuntimeError("flush failed")

        class BodyError(Exception):
            pass

        with self.assertLogs('c2pa', level='ERROR') as logs:
            with self.assertRaises(BodyError):
                with _native_section():
                    c2pa_module._register_for_section_flush(FlushRaises())
                    raise BodyError("the error the caller cares about")

        self.assertTrue(any("flush failed" in line for line in logs.output))

    def test_context_sign_after_close_raises_rather_than_skipping_signer(self):
        """Signing through a closed Context must raise, not silently succeed.

        Context._release() has already dropped the pinned callback, so the
        native side signs without ever invoking it: the call returns a
        manifest of the same size while the caller's signing callback runs
        zero times. Refusing the call is what makes that visible.

        Runs in a subprocess because the callback signer needs the
        cryptography package, which this module does not otherwise import.
        """
        source = textwrap.dedent(self._callback_signer_source() + """
            calls = []

            def counting_callback(data):
                calls.append(1)
                return private_key.sign(data, ec.ECDSA(hashes.SHA256()))

            signer = Signer.from_callback(
                counting_callback, SigningAlg.ES256, certs,
                "http://timestamp.digicert.com")
            ctx = Context(signer=signer)
            builder = Builder(dict(manifest), context=ctx)
            ctx.close()

            try:
                builder.sign("image/jpeg", io.BytesIO(img), io.BytesIO())
                print("SIGNED_WITH_CALLS", len(calls))
            except Exception as exc:
                print("RAISED", type(exc).__name__, len(calls))
        """)

        result = subprocess.run(
            [sys.executable, "-c", source, self.data_dir],
            capture_output=True, text=True, timeout=300)

        self.assertIn("RAISED", result.stdout, result.stderr[-2000:])

    def test_close_during_concurrent_sign_does_not_crash(self):
        """A Signer shared across threads must not be freed mid-sign.

        Builder.sign borrows the signer's handle for the duration of the
        native call. Without a guard on the signer itself, a close() on
        another thread frees that handle while c2pa_builder_sign is using
        it, and the process dies with SIGSEGV instead of raising.

        Rotates a shared signer while other threads sign with it. Runs in a
        subprocess: the failure mode is a segfault, which would take the
        test runner down with it otherwise.
        """
        source = textwrap.dedent("""
            import io, os, sys, threading
            from c2pa import (Builder, Signer, C2paSignerInfo,
                              C2paSigningAlg as SigningAlg)

            data_dir = sys.argv[1]
            certs = open(os.path.join(data_dir, "es256_certs.pem"), "rb").read()
            key = open(os.path.join(data_dir, "es256_private.key"), "rb").read()
            img = open(os.path.join(data_dir, "C.jpg"), "rb").read()
            manifest = {"claim_generator_info":
                        [{"name": "test", "version": "0.1"}],
                        "assertions": []}

            def make():
                return Signer.from_info(C2paSignerInfo(
                    SigningAlg.ES256, certs, key, None))

            box = {"signer": make(), "stop": False}

            def rotate():
                while not box["stop"]:
                    old = box["signer"]
                    try:
                        box["signer"] = make()
                        old.close()
                    except Exception:
                        pass

            def sign():
                for _ in range(120):
                    if box["stop"]:
                        return
                    try:
                        b = Builder(manifest)
                        b.sign(box["signer"], "image/jpeg",
                               io.BytesIO(img), io.BytesIO())
                        b.close()
                    except Exception:
                        # A closed signer may be rejected;
                        # only a crash is a failure here.
                        pass

            rot = threading.Thread(target=rotate, daemon=True)
            rot.start()
            threads = [threading.Thread(target=sign) for _ in range(8)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            box["stop"] = True
            rot.join(timeout=5)
            print("OK")
        """)

        result = subprocess.run(
            [sys.executable, "-c", source, self.data_dir],
            capture_output=True, text=True, timeout=300)

        self.assertEqual(result.returncode, 0, result.stderr[-2000:])
        self.assertIn("OK", result.stdout)


class TestSwapConsumeExclusion(unittest.TestCase):
    """with_archive, with_fragment must be rejected during other in-flight calls.
    """

    _MANIFEST = {
        "claim_generator": "c2pa_python_test",
        "claim_generator_info": [{
            "name": "c2pa_python_test",
            "version": "0.1.0",
        }],
        "format": "image/jpeg",
        "title": "Python Test",
        "ingredients": [],
        "assertions": [],
    }

    def _archive_bytes(self):
        builder = Builder(self._MANIFEST)
        try:
            archive = io.BytesIO()
            builder.to_archive(archive)
            archive.seek(0)
            return archive
        finally:
            builder.close()

    def test_refused_sign_leaves_builder_usable(self):
        with open(os.path.join(FIXTURES_FOLDER, "es256_certs.pem"), "rb") as f:
            certs = f.read()
        with open(os.path.join(FIXTURES_FOLDER, "es256_private.key"), "rb") as f:
            key = f.read()
        with open(os.path.join(FIXTURES_FOLDER, "A.jpg"), "rb") as f:
            image = f.read()
        signer = Signer.from_info(C2paSignerInfo(b"es256", certs, key, None))
        self.addCleanup(signer.close)
        manifest = dict(self._MANIFEST, assertions=[{
            "label": "c2pa.actions",
            "data": {"actions": [{
                "action": "c2pa.created",
                "digitalSourceType": "http://cv.iptc.org/newscodes/"
                                     "digitalsourcetype/digitalCreation",
            }]},
        }])
        builder = Builder(manifest)
        self.addCleanup(builder.close)
        inside = threading.Event()
        release = threading.Event()

        class SlowStream(io.BytesIO):
            def readinto(self, buffer):
                inside.set()
                release.wait(10)
                return super().readinto(buffer)

        worker = threading.Thread(
            target=lambda: builder.add_resource("thumb", SlowStream(image)),
            daemon=True)
        worker.start()
        try:
            inside.wait(10)
            with self.assertRaises(Error):
                builder.sign(signer, "image/jpeg",
                             io.BytesIO(image), io.BytesIO())
        finally:
            release.set()
            worker.join(10)
        output = io.BytesIO()
        builder.sign(signer, "image/jpeg", io.BytesIO(image), output)
        self.assertGreater(len(output.getvalue()), 0)

    def test_with_fragment_rejected_when_native_in_progress(self):
        init_path = os.path.join(FIXTURES_FOLDER, "dashinit.mp4")
        fragment_path = os.path.join(FIXTURES_FOLDER, "dash1.m4s")
        with open(init_path, "rb") as f:
            init_bytes = f.read()
        with open(fragment_path, "rb") as f:
            fragment_bytes = f.read()

        reader = Reader("video/mp4", io.BytesIO(init_bytes))
        try:
            with reader._native_call():
                with self.assertRaises(Error) as raised:
                    reader.with_fragment(
                        "video/mp4",
                        io.BytesIO(init_bytes),
                        io.BytesIO(fragment_bytes))
            self.assertIn("in use", str(raised.exception))

            # The refusal must leave the reader untouched: the swap still
            # works once the borrow is gone.
            reader.with_fragment(
                "video/mp4",
                io.BytesIO(init_bytes),
                io.BytesIO(fragment_bytes))
            reader.json()
        finally:
            reader.close()

    def test_close_during_with_archive_defers_and_frees(self):
        archive_bytes = self._archive_bytes().getvalue()
        builder = Builder(self._MANIFEST)

        inside = threading.Event()
        release = threading.Event()

        class BlockingArchive(io.BytesIO):
            def read(self, *args):
                inside.set()
                release.wait(10)
                return super().read(*args)

            def seek(self, *args):
                inside.set()
                release.wait(10)
                return super().seek(*args)

        outcome = {}

        def consume():
            try:
                builder.with_archive(BlockingArchive(archive_bytes))
                outcome["result"] = "ok"
            except Exception as e:  # noqa: BLE001 - asserted below
                outcome["result"] = e

        worker = threading.Thread(target=consume, daemon=True)
        worker.start()
        try:
            self.assertTrue(inside.wait(10), "callback never reached")
            # Defers: the swap is counted in flight.
            builder.close()
        finally:
            release.set()
            worker.join(10)

        # The deferred teardown freed the replacement handle: closed for
        # good, nothing left to free, exactly one release.
        self.assertTrue(builder._released)

if __name__ == '__main__':
    unittest.main()
