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

import ctypes
import os
import unittest
from unittest.mock import MagicMock, patch

from c2pa.c2pa import ManagedResource, Stream, LifecycleState
from c2pa.lib import is_foreign_process, record_owner_pid


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
        with patch('c2pa.c2pa._lib'):
            # _free_native_ptr calls _lib.c2pa_free; patch _free_native_ptr
            # directly to avoid ctypes cast issues with the mock lib object.
            with patch.object(ManagedResource, '_free_native_ptr') as mock_free:
                obj._cleanup_resources()
        mock_free.assert_called_once_with(obj._handle)

    def test_no_stamp_calls_free(self):
        """No _owner_pid (backward-compat) must NOT suppress cleanup."""
        obj = _make_resource(pid_offset=None)
        with patch.object(ManagedResource, '_free_native_ptr') as mock_free:
            obj._cleanup_resources()
        mock_free.assert_called_once()

    def test_foreign_pid_leaves_state_unchanged(self):
        """Guard returns early; lifecycle state stays ACTIVE (not CLOSED)."""
        obj = _make_resource(pid_offset=1)
        with patch('c2pa.c2pa._lib'):
            obj._cleanup_resources()
        self.assertEqual(obj._lifecycle_state, LifecycleState.ACTIVE)

    def test_double_cleanup_is_idempotent(self):
        """Second call is a no-op after successful first cleanup."""
        obj = _make_resource(pid_offset=0)
        with patch.object(ManagedResource, '_free_native_ptr') as mock_free:
            obj._cleanup_resources()
            obj._cleanup_resources()
        mock_free.assert_called_once()

    def test_foreign_pid_skips_release(self):
        obj = _make_stream(pid_offset=1)
        with patch('c2pa.c2pa._lib') as mock_lib:
            obj.__del__()
        mock_lib.c2pa_release_stream.assert_not_called()

    def test_own_pid_releases_stream(self):
        obj = _make_stream(pid_offset=0)
        with patch('c2pa.c2pa._lib') as mock_lib:
            obj.__del__()
        mock_lib.c2pa_release_stream.assert_called_once()

    def test_no_stamp_releases_stream(self):
        obj = _make_stream(pid_offset=None)
        with patch('c2pa.c2pa._lib') as mock_lib:
            obj.__del__()
        mock_lib.c2pa_release_stream.assert_called_once()

    def test_already_closed_is_noop(self):
        obj = _make_stream(pid_offset=0)
        obj._closed = True
        with patch('c2pa.c2pa._lib') as mock_lib:
            obj.__del__()
        mock_lib.c2pa_release_stream.assert_not_called()

    def test_foreign_pid_skips_release(self):
        obj = _make_stream(pid_offset=1)
        with patch('c2pa.c2pa._lib') as mock_lib:
            obj.close()
        mock_lib.c2pa_release_stream.assert_not_called()
        self.assertTrue(obj._closed)

    def test_own_pid_releases_stream(self):
        obj = _make_stream(pid_offset=0)
        with patch('c2pa.c2pa._lib') as mock_lib:
            obj.close()
        mock_lib.c2pa_release_stream.assert_called_once()

    def test_no_stamp_releases_stream(self):
        obj = _make_stream(pid_offset=None)
        with patch('c2pa.c2pa._lib') as mock_lib:
            obj.close()
        mock_lib.c2pa_release_stream.assert_called_once()

    def test_already_closed_is_noop(self):
        obj = _make_stream(pid_offset=0)
        obj._closed = True
        with patch('c2pa.c2pa._lib') as mock_lib:
            obj.close()
        mock_lib.c2pa_release_stream.assert_not_called()

    def test_foreign_pid_close_marks_closed(self):
        """close() in forked child must set _closed=True to prevent re-entry."""
        obj = _make_stream(pid_offset=1)
        with patch('c2pa.c2pa._lib'):
            obj.close()
        self.assertTrue(obj._closed)


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


if __name__ == '__main__':
    unittest.main()
