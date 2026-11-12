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
import gzip
import bz2
import lzma
import unittest
import ctypes
import tempfile
from c2pa.c2pa import Stream
from pathlib import Path
from tests.unit._support import (
    FIXTURES_DIR,
    DEFAULT_TEST_FILE_NAME,
)


class TestIsReadableStream(unittest.TestCase):
    """ A stream is anything Stream will accept (read/write/seek/tell/flush).
    """

    def _tmp_path(self):
        return os.path.join(FIXTURES_DIR, DEFAULT_TEST_FILE_NAME)

    def test_paths_and_formats_are_not_streams(self):
        for value in (None, "", "image/jpeg", "path/to/file.jpg",
                      Path("x.jpg")):
            self.assertFalse(Stream.is_read_stream(value), repr(value))

    def test_non_stream_objects_are_not_streams(self):
        for value in (b"bytes", bytearray(b"x"), 42, object()):
            self.assertFalse(Stream.is_read_stream(value), repr(value))

    def test_object_missing_methods_is_not_a_stream(self):
        class OnlyRead:
            def read(self):
                return b""
        self.assertFalse(Stream.is_read_stream(OnlyRead()))

    def test_read_only_object_is_not_a_stream(self):
        # Has read/seek/tell but no write/flush, so not a Stream for us.
        class ReadOnly:
            def read(self):
                return b""

            def seek(self, *a):
                return 0

            def tell(self):
                return 0
        self.assertFalse(Stream.is_read_stream(ReadOnly()))

    def test_in_memory_streams_are_streams(self):
        self.assertTrue(Stream.is_read_stream(io.BytesIO(b"x")))
        self.assertTrue(Stream.is_read_stream(io.StringIO("x")))

    def test_file_handles_are_streams(self):
        path = self._tmp_path()
        for opener in (
            lambda: open(path, "rb"),
            lambda: open(path, "rb", buffering=0),
            lambda: io.BufferedReader(io.FileIO(path, "rb")),
            lambda: open(path, "r+b"),
            lambda: open(path, "r"),
        ):
            fh = opener()
            try:
                self.assertTrue(Stream.is_read_stream(fh), type(fh).__name__)
            finally:
                fh.close()

    def test_spooled_temporary_file_is_a_stream(self):
        with tempfile.SpooledTemporaryFile() as fh:
            self.assertTrue(Stream.is_read_stream(fh))

    def test_compressed_file_objects_are_streams(self):
        with tempfile.TemporaryDirectory() as tmp:
            for ext, opener in (
                ("gz", gzip.open),
                ("bz2", bz2.open),
                ("xz", lzma.open),
            ):
                p = os.path.join(tmp, f"f.{ext}")
                with opener(p, "wb") as fh:
                    fh.write(b"data")
                with opener(p, "rb") as fh:
                    self.assertTrue(Stream.is_read_stream(fh), ext)

    def test_placeholder_typed_object_with_all_methods_is_a_stream(self):
        class Duck:
            def read(self, *a):
                return b""

            def write(self, *a):
                return 0

            def seek(self, *a):
                return 0

            def tell(self):
                return 0

            def flush(self):
                pass
        self.assertTrue(Stream.is_read_stream(Duck()))


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
