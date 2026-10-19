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

import inspect
import io
import unittest
import subprocess
import sys
import threading
import c2pa.c2pa as c2pa_module
from c2pa import C2paError as Error


class TestErrorPlumbing(unittest.TestCase):
    """Covers the error helpers themselves, which had no direct tests."""

    def _set_native_error(self, text):
        c2pa_module._lib.c2pa_error_set_last(text.encode('utf-8'))

    def test_every_error_tag_maps_to_its_typed_subclass(self):
        # The wire text is "Tag: message"; each tag gets its own subclass so
        # callers can catch precisely.
        tags = [
            "Assertion", "AssertionNotFound", "Decoding", "Encoding",
            "FileNotFound", "Io", "Json", "Manifest", "ManifestNotFound",
            "NotSupported", "Other", "RemoteManifest", "ResourceNotFound",
            "Signature", "Verify", "UntrackedPointer", "WrongPointerType",
        ]
        for tag in tags:
            with self.subTest(tag=tag):
                expected = getattr(Error, tag)
                with self.assertRaises(expected):
                    c2pa_module._raise_typed_c2pa_error(f"{tag}: detail")

    def test_unmapped_tag_falls_back_to_base_error(self):
        with self.assertRaises(Error) as ctx:
            c2pa_module._raise_typed_c2pa_error("Nonsense: detail")
        # Base class only: no subclass should claim an unknown tag.
        self.assertIs(type(ctx.exception), Error)

    def test_check_ffi_operation_result_raises_with_native_message(self):
        self._set_native_error("Io: disk exploded")
        with self.assertRaises(Error) as ctx:
            c2pa_module._check_ffi_operation_result(None, "fallback text")
        self.assertIn("disk exploded", str(ctx.exception))

    def test_check_ffi_operation_result_uses_fallback_when_slot_empty(self):
        # The slot is sticky and thread-local, so a fresh thread is the only
        # way to observe it unset.
        captured = []

        def run():
            try:
                c2pa_module._check_ffi_operation_result(None, "fallback text")
            except BaseException as e:      # noqa: BLE001 - reported below
                captured.append(e)

        t = threading.Thread(target=run)
        t.start()
        t.join()

        self.assertEqual(len(captured), 1, "expected a raise on failure")
        self.assertIsInstance(captured[0], Error)
        self.assertIn("fallback text", str(captured[0]))

    def test_check_ffi_operation_result_passes_success_through(self):
        self.assertEqual(
            c2pa_module._check_ffi_operation_result(42, "unused"), 42)

    def test_stream_creation_failure_reports_a_real_message(self):
        # Regression: used to raise bare Exception("...: None") instead of the
        # native error message.
        real = c2pa_module._lib.c2pa_create_stream
        c2pa_module._lib.c2pa_create_stream = lambda *a: None
        try:
            # With an error set, the message must carry it.
            self._set_native_error("Io: stream refused")
            with self.assertRaises(Error) as ctx:
                c2pa_module.Stream(io.BytesIO(b"x"))
            self.assertIn("stream refused", str(ctx.exception))

            # With the slot unset, the old code raised bare Exception.
            captured = []

            def run():
                try:
                    c2pa_module.Stream(io.BytesIO(b"x"))
                except BaseException as e:   # noqa: BLE001 - reported below
                    captured.append(e)

            t = threading.Thread(target=run)
            t.start()
            t.join()

            self.assertEqual(len(captured), 1, "expected a raise on failure")
            self.assertIsInstance(captured[0], Error, "must be typed, not bare")
            self.assertNotIn("None", str(captured[0]))
        finally:
            c2pa_module._lib.c2pa_create_stream = real

    def test_supported_mime_types_raises_instead_of_returning_empty(self):
        # Regression: `if error:` was always False, so a native failure
        # returned an empty list instead of raising. Only visible with the
        # slot unset, hence the fresh thread.
        captured = []

        def run():
            try:
                captured.append(
                    c2pa_module._get_supported_mime_types(
                        lambda count: None, None))
            except BaseException as e:      # noqa: BLE001 - reported below
                captured.append(e)

        t = threading.Thread(target=run)
        t.start()
        t.join()

        self.assertIsInstance(captured[0], Error, "failed lookup returned data")

    def test_supported_mime_types_reports_the_native_message(self):
        self._set_native_error("Io: mime lookup failed")
        with self.assertRaises(Error) as ctx:
            c2pa_module._get_supported_mime_types(lambda count: None, None)
        self.assertIn("mime lookup failed", str(ctx.exception))

    def test_reading_an_error_does_not_leave_it_readable(self):
        """An error is reportable once, by the reader that observes it.
        """
        self._set_native_error("Io: read me once")

        self.assertEqual(
            c2pa_module._read_native_error(), "Io: read me once")
        self.assertIsNone(c2pa_module._read_native_error(), "reported twice")

    def test_import_learns_no_marker_before_first_use(self):
        result = subprocess.run(
            [sys.executable, "-c",
             "import c2pa.c2pa as m\n"
             "assert m._marker_text_for.cache_info().currsize == 0, "
             "'learned at import'\n"
             "m._read_native_error()\n"
             "assert m._marker_text(), 'never learned on first use'\n"],
            capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])

    def test_the_no_error_marker_never_reaches_a_caller(self):
        """The marker is internal, not a message for users."""
        marker = c2pa_module._marker_text()

        c2pa_module._write_no_error_marker()
        self.assertIsNone(c2pa_module._read_native_error())

        c2pa_module._write_no_error_marker()
        with self.assertRaises(Error) as ctx:
            c2pa_module._check_ffi_operation_result(None, "fallback: {}")
        self.assertNotIn(marker, str(ctx.exception))

    def test_a_failure_after_a_null_read_does_not_inherit_the_old_message(self):
        """The message surviving a NULL read must not become someone's error."""
        c2pa_module._write_no_error_marker()
        c2pa_module._lib.c2pa_error_set_last(b"Io: belongs to an earlier call")

        original = c2pa_module._lib.c2pa_error
        try:
            c2pa_module._lib.c2pa_error = lambda: None
            c2pa_module._read_native_error()
        finally:
            c2pa_module._lib.c2pa_error = original

        with self.assertRaises(Error) as ctx:
            c2pa_module._check_ffi_operation_result(
                None, "Later unrelated failure: {}")

        self.assertNotIn("belongs to an earlier call", str(ctx.exception))

    def test_every_real_rejection_wording_is_classified_as_pre_consume(self):
        """Every tag arrives bare or behind the "Other: " wrapper."""
        wrapper = c2pa_module.ManagedResource._NATIVE_ERROR_WRAPPER
        classify = c2pa_module.ManagedResource._is_pre_consume_rejection

        for tag in c2pa_module.ManagedResource._PRE_CONSUME_ERROR_TAGS:
            bare = f"{tag} some detail"
            wrapped = f"{wrapper}{tag} some detail"
            self.assertTrue(classify(bare), bare)
            self.assertTrue(classify(wrapped), wrapped)

    def test_caller_text_quoting_a_tag_is_not_a_rejection(self):
        """A tag inside the message body describes the caller's input.

        Native errors quote caller-supplied strings verbatim: a JSON parse
        failure repeats the offending value, an Io failure names the path.
        Reading one of those as a pre-consume rejection hands the resource back
        as usable after native may already own and have dropped its handle.
        """
        classify = c2pa_module.ManagedResource._is_pre_consume_rejection

        forged = (
            'Json: invalid type: string "NullParameter: x", expected a '
            'sequence at line 1 column 43',
            'Json: invalid type: string "WrongPointerType: y", expected a '
            'sequence at line 1 column 46',
            "Io: cannot open /tmp/UntrackedPointer: 0xdead.jpg",
            "Other: manifest text mentions InvalidBufferSize: in passing",
        )
        for message in forged:
            self.assertFalse(
                classify(message),
                f"caller text was read as a pointer rejection: {message!r}")

    def test_a_failing_flush_does_not_strand_the_rest_of_the_queue(self):
        """One resource raising must not skip the resources queued behind it.
        """
        flushed = []

        class Recorder:
            def __init__(self, name, raises=None):
                self.name = name
                self.raises = raises

            def _maybe_flush_pending(self):
                if self.raises is not None:
                    raise self.raises
                flushed.append(self.name)

        first = Recorder("first")
        middle = Recorder("middle", raises=KeyboardInterrupt())
        last = Recorder("last")

        with self.assertLogs("c2pa", level="ERROR"):
            with c2pa_module._native_section():
                for resource in (first, middle, last):
                    c2pa_module._register_for_section_flush(resource)

        self.assertEqual(flushed, ["first", "last"])

    def test_runtime_does_not_call_error_set_last(self):
        """The marker mechanism must not depend on c2pa_error_set_last,
        so this module loads against native builds that lack it."""
        for fn in (c2pa_module.ManagedResource._invoke_consume,
                  c2pa_module._read_native_error,
                  c2pa_module._write_no_error_marker):
            self.assertNotIn(
                'c2pa_error_set_last', inspect.getsource(fn))
