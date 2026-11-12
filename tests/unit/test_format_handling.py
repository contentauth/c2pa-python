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

import unittest
from c2pa import C2paError as Error, Reader
from c2pa.c2pa import _encode_format, _format_ffi_arg


class TestFormatValidation(unittest.TestCase):
    """Unit tests for _encode_format.

    The binding no longer validates the format against a supported list: the
    native library is the authority and detects the type from the bytes, so a
    given format is trimmed and passed straight through.
    """

    def test_strips_whitespace_from_query(self):
        for value in (" image/jpeg", "image/jpeg ", "\timage/jpeg\n"):
            self.assertEqual(
                _encode_format(value, "Reader"),
                b"image/jpeg")

    def test_case_normalized_to_lowercase(self):
        # MIME types are case-insensitive, so the format is lowercased before
        # being handed to the native library.
        for value in ("IMAGE/JPEG", "Image/Jpeg"):
            self.assertEqual(
                _encode_format(value, "Reader"),
                b"image/jpeg")

    def test_encodes_stripped_and_lowercased_key(self):
        self.assertEqual(
            _encode_format("  IMAGE/JPEG  ", "Reader"),
            b"image/jpeg")

    def test_production_supported_list_is_normalized(self):
        # _get_supported_mime_types strips and lowercases every entry.
        for entry in Reader.get_supported_mime_types():
            self.assertEqual(entry, entry.strip().lower())

    def test_none_autodetects(self):
        # A missing format is None (auto-detect), not the empty-bytes sentinel.
        self.assertIsNone(_encode_format(None, "Reader"))

    def test_blank_autodetects(self):
        for value in ("", "   ", "\t\n"):
            self.assertIsNone(_encode_format(value, "Reader"))

    def test_missing_format_rejected_when_autodetect_disabled(self):
        for value in (None, "", "   "):
            with self.assertRaises(Error.NotSupported):
                _encode_format(value, "Builder", allow_autodetect=False)

    def test_format_ffi_arg_maps_none_to_empty_bytes(self):
        # The native library's "detect from bytes" flag is empty bytes, not a
        # NULL c_char_p, so None must map to b"".
        self.assertEqual(_format_ffi_arg(None), b"")
        self.assertEqual(_format_ffi_arg(b"image/jpeg"), b"image/jpeg")

    def test_resolve_format_bytes(self):
        # Path form derives the format from the extension.
        self.assertEqual(
            Reader._resolve_format_bytes("photo.jpg", None), b"image/jpeg")
        # Extensionless path -> auto-detect.
        self.assertIsNone(
            Reader._resolve_format_bytes("no_extension", None))
        # Stream given: format_or_path is the format (or None for detect).
        self.assertEqual(
            Reader._resolve_format_bytes("image/jpeg", object()), b"image/jpeg")
        self.assertIsNone(
            Reader._resolve_format_bytes(None, object()))

    def test_unknown_format_passes_through(self):
        # No supported-list check: the format is encoded and handed to the
        # native library, which is the authority on validity.
        self.assertEqual(
            _encode_format("application/x-nope", "Reader"),
            b"application/x-nope")

    def test_literal_none_string_passes_through(self):
        # The string "None" is a plain string; it is trimmed, lowercased, and
        # encoded like any other, not rejected in the binding.
        self.assertEqual(_encode_format("None", "Reader"), b"none")
