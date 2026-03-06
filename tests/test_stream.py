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

import io
import unittest
import ctypes

from c2pa.c2pa import Stream


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



if __name__ == '__main__':
    unittest.main(warnings='ignore')
