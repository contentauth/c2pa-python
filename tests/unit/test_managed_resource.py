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

import gc
import inspect
import os
import io
import json
import re
import unittest
import ctypes
import threading
import c2pa.c2pa as c2pa_module
from unittest.mock import patch
from c2pa import Builder, C2paError as Error, Reader, C2paSignerInfo, Signer, Settings, Context
from c2pa.c2pa import LifecycleState, ManagedResource, format_embeddable
from tests.unit._support import (
    FIXTURES_DIR,
    DEFAULT_TEST_FILE_NAME,
    DEFAULT_TEST_FILE,
    _patch_free,
    _fail_with_native_error,
    TestContextAPIs,
)


class TestManagedResourceLifecycle(unittest.TestCase):
    """Lifecycle primitives (_activate, _consume_and_swap, _wrap_native_handle),
    the _owner_pid stamp that governs which process may free a handle, and
    the ownership hand-offs between Python and the native library.

    For testing: setUp records frees instead of performing them,
    so a miscount reads as memory handling issue.
    Tests releasing real handles call _use_real_frees() first to
    restore release behavior.
    """

    class _FakeHandleResource(ManagedResource):
        """Concrete subclass with no resources of its own."""

    class _CallbackHoldingResource(ManagedResource):
        """Mimics Signer: its _release() reads an attribute that _init_attrs()
        is responsible for defaulting."""

        def _release(self):
            if self._callback_cb:
                self._callback_cb = None

    class _ReleaseRecordingResource(ManagedResource):
        """Records _release() calls for test asserts."""

        def __init__(self):
            super().__init__()
            self.release_calls = 0

        def _release(self):
            self.release_calls += 1

    class _ExtenderResource(ManagedResource):
        """For testing: An extender that owns a raw handle and wraps it via
        _wrap_native_handle. It carries several attributes of its own, all
        defaulted in _init_attrs (not __init__), and _release reads them, so a
        missing attribute would surface as an AttributeError on test teardown.
        """

        def _init_attrs(self):
            super()._init_attrs()
            self.label = "extender"
            self.buffer = []
            self.released = False

        def _release(self):
            # Reads attributes _init_attrs is responsible for defaulting.
            self.buffer.append(self.label)
            self.released = True

    def setUp(self):
        self.data_dir = FIXTURES_DIR
        self.freed = []
        self._real_free = ManagedResource._free_native_ptr
        # Registered first so it runs last, after every patch has unwound.
        self.addCleanup(self._assert_free_hook_restored)
        _patch_free(self, self.freed.append)

    def _assert_free_hook_restored(self):
        self.assertIs(
            ManagedResource._free_native_ptr, self._real_free,
            "{} leaked a _free_native_ptr patch".format(self.id()))

    def _free_counts(self):
        counts = {}
        for handle in self.freed:
            counts[handle] = counts.get(handle, 0) + 1
        return counts

    def _use_real_frees(self):
        """Undo free recorder, so native handles are really freed."""
        _patch_free(self, self._real_free)

    def _make_signer(self):
        with open(os.path.join(self.data_dir, "es256_certs.pem"), "rb") as f:
            certs = f.read()
        with open(os.path.join(self.data_dir, "es256_private.key"), "rb") as f:
            key = f.read()
        return Signer.from_info(C2paSignerInfo(
            b"es256", certs, key, b"http://timestamp.digicert.com"))

    def test_release_failure_still_frees_handle(self):
        res = self._CallbackHoldingResource()
        # _callback_cb is never set, so _release() raises AttributeError.
        res._activate(0xBBBB)

        res.close()

        self.assertEqual(self.freed, [0xBBBB],
                         "handle leaked when _release() raised")
        self.assertIsNone(res._handle)

    def test_release_failure_is_logged(self):
        res = self._CallbackHoldingResource()
        res._activate(0xBBBB)

        with self.assertLogs('c2pa', level='ERROR') as captured:
            res.close()

        self.assertTrue(
            any('Failed to release' in line for line in captured.output),
            f"_release() failure was not logged: {captured.output}")

    def test_activate_rejects_null_handle(self):
        res = self._FakeHandleResource()

        with self.assertRaises(Error) as ctx:
            res._activate(None)

        self.assertIn("null handle", str(ctx.exception))
        self.assertEqual(res._lifecycle_state, LifecycleState.UNINITIALIZED)

    def test_activate_rejects_double_activation(self):
        res = self._FakeHandleResource()
        res._activate(0x1111)

        with self.assertRaises(Error) as ctx:
            res._activate(0x2222)

        self.assertIn("already activated", str(ctx.exception))
        # The first handle is still owned, and is freed exactly once.
        self.assertEqual(res._handle, 0x1111)
        res.close()
        self.assertEqual(self.freed, [0x1111])

    def test_activate_rejects_reactivation_after_close(self):
        res = self._FakeHandleResource()
        res._activate(0x3333)
        res.close()
        self.freed.clear()

        with self.assertRaises(Error):
            res._activate(0x4444)

        # Staying CLOSED is what prevents a second free of the handle.
        self.assertEqual(res._lifecycle_state, LifecycleState.CLOSED)
        self.assertIsNone(res._handle)
        self.assertEqual(self.freed, [])

    def test_activate_does_not_mutate_on_rejection(self):
        res = self._FakeHandleResource()
        res._activate(0x5555)

        with self.assertRaises(Error):
            res._activate(0x6666)

        self.assertEqual(res._handle, 0x5555,
                         "rejected activation replaced the handle")
        self.assertEqual(res._lifecycle_state, LifecycleState.ACTIVE)

    def test_consume_and_swap_requires_active_resource(self):
        uninitialized = self._FakeHandleResource()
        with self.assertRaises(Error):
            uninitialized._consume_and_swap(lambda h: 0x1, "swap: {}")

        closed = self._FakeHandleResource()
        closed._activate(0x2)
        closed.close()
        self.freed.clear()
        with self.assertRaises(Error):
            closed._consume_and_swap(lambda h: 0x3, "swap: {}")
        self.assertEqual(self.freed, [])

    def test_wrap_native_handle_bypasses_init(self):
        seen = []

        class Probe(ManagedResource):
            def __init__(self):
                raise AssertionError("__init__ must be bypassed")

            def _init_attrs(self):
                super()._init_attrs()
                self._tag = 'from _init_attrs'

            def _release(self):
                seen.append(self._tag)

        obj = Probe._wrap_native_handle(0xC0DE)

        self.assertEqual(obj._tag, 'from _init_attrs')
        self.assertEqual(obj._lifecycle_state, LifecycleState.ACTIVE)
        self.assertTrue(obj.is_valid)
        self.assertTrue(hasattr(obj, '_owner_pid'))

        obj.close()
        self.assertEqual(seen, ['from _init_attrs'],
                         "_release() could not see the class's own attrs")

    def test_wrap_native_handle_rejects_null(self):
        with self.assertRaises(Error):
            self._FakeHandleResource._wrap_native_handle(None)

    def test_close_after_wrap_is_idempotent(self):
        obj = self._FakeHandleResource._wrap_native_handle(0xD00D)

        obj.close()
        obj.close()

        self.assertEqual(self.freed, [0xD00D], "handle freed more than once")

    def test_every_construction_path_records_owner_pid(self):
        pid = os.getpid()

        plain = self._FakeHandleResource()
        self.assertEqual(plain._owner_pid, pid)

        activated = self._FakeHandleResource()
        activated._activate(0xA1)
        self.assertEqual(activated._owner_pid, pid)

        wrapped = self._FakeHandleResource._wrap_native_handle(0xA2)
        self.assertEqual(wrapped._owner_pid, pid)

        # A swap keeps the original stamp:
        # the replacement handle was allocated by the same process
        # that created the object.
        wrapped._consume_and_swap(lambda h: 0xA3, "swap: {}")
        self.assertEqual(wrapped._owner_pid, pid)

    def test_foreign_child_skips_free_for_wrapped_and_swapped(self):
        wrapped = self._FakeHandleResource._wrap_native_handle(0xC1)
        wrapped._owner_pid = os.getpid() + 1
        wrapped.close()

        swapped = self._FakeHandleResource()
        swapped._activate(0xC2)
        swapped._consume_and_swap(lambda h: 0xC3, "swap: {}")
        swapped._owner_pid = os.getpid() + 1
        swapped.close()

        self.assertEqual(self.freed, [],
                         "forked child freed a pointer its parent still owns")
        # The child must not free a pointer the parent still owns.
        # The child does mark its own copies closed and nulls their handles,
        # which stops the child from reusing a parent-owned handle.
        self.assertEqual(wrapped._lifecycle_state, LifecycleState.CLOSED)
        self.assertIsNone(wrapped._handle)
        self.assertEqual(swapped._lifecycle_state, LifecycleState.CLOSED)
        self.assertIsNone(swapped._handle)

        # A second foreign teardown is a no-op.
        wrapped.close()
        swapped.close()
        self.assertEqual(self.freed, [])

    def test_owning_process_frees_wrapped_and_swapped_exactly_once(self):
        wrapped = self._FakeHandleResource._wrap_native_handle(0xC4)
        wrapped.close()
        wrapped.close()

        swapped = self._FakeHandleResource()
        swapped._activate(0xC5)
        swapped._consume_and_swap(lambda h: 0xC6, "swap: {}")
        swapped.close()

        # 0xC5 was consumed by the test FFI swap.
        # Only the replacement must be freed here.
        self.assertEqual(self._free_counts(), {0xC4: 1, 0xC6: 1})

    def test_foreign_child_skips_release(self):
        foreign = self._ReleaseRecordingResource()
        foreign._activate(0xD1)
        foreign._owner_pid = os.getpid() + 1
        foreign.close()
        self.assertEqual(foreign.release_calls, 0)

        owned = self._ReleaseRecordingResource()
        owned._activate(0xD2)
        owned.close()
        self.assertEqual(owned.release_calls, 1)

    def test_consumed_resource_frees_nothing_in_either_process(self):
        owned = self._FakeHandleResource()
        owned._activate(0xE1)
        owned._teardown(free_handle=False)
        owned.close()

        foreign = self._FakeHandleResource()
        foreign._activate(0xE2)
        foreign._teardown(free_handle=False)
        foreign._owner_pid = os.getpid() + 1
        foreign.close()

        self.assertEqual(self.freed, [])

    # Consuming a handle hands the native pointer to a new owner.
    # The Python-side resources are still ours to free.
    def test_teardown_consumed_releases_python_resources(self):
        res = self._ReleaseRecordingResource()
        res._activate(0xF1)

        res._teardown(free_handle=False)

        self.assertEqual(res.release_calls, 1)
        self.assertEqual(res._lifecycle_state, LifecycleState.CLOSED)
        self.assertIsNone(res._handle)
        self.assertEqual(self.freed, [])

    def test_teardown_consumed_swallows_failing_release(self):
        res = self._CallbackHoldingResource()
        res._activate(0xF2)

        with self.assertLogs("c2pa", level="ERROR"):
            res._teardown(free_handle=False)

        self.assertEqual(res._lifecycle_state, LifecycleState.CLOSED)
        self.assertIsNone(res._handle)

    def test_teardown_consumed_in_foreign_process_skips_release(self):
        res = self._ReleaseRecordingResource()
        res._activate(0xF3)
        res._owner_pid = os.getpid() + 1

        res._teardown(free_handle=False)

        self.assertEqual(res.release_calls, 0)
        self.assertEqual(res._lifecycle_state, LifecycleState.CLOSED)
        self.assertIsNone(res._handle)

    def test_extender_wraps_handle_fully_built(self):
        obj = self._ExtenderResource._wrap_native_handle(0xE0)

        # Every attribute _init_attrs defaults is present,
        # even though __init__ never ran.
        self.assertEqual(obj.label, "extender")
        self.assertEqual(obj.buffer, [])
        self.assertFalse(obj.released)
        self.assertTrue(obj.is_valid)
        self.assertEqual(obj._owner_pid, os.getpid())

        # _release reads those attributes, so a missing one will raise here.
        obj.close()
        obj.close()

        self.assertTrue(obj.released)
        self.assertEqual(obj.buffer, ["extender"])
        self.assertEqual(self.freed, [0xE0], "wrapped handle freed once")

    def test_extender_foreign_teardown_skips_native_free(self):
        obj = self._ExtenderResource._wrap_native_handle(0xE1)
        # Stamp a foreign owner:
        # teardown runs in a process that did not create the handle,
        # so it must not free the pointer or run _release.
        obj._owner_pid = os.getpid() + 1

        obj.close()

        self.assertEqual(self.freed, [],
                         "forked child freed a handle its parent still owns")
        self.assertFalse(obj.released, "foreign teardown ran _release")
        # The child marks its own copy closed and nulls the handle:
        # the parent holds a separate copy and it stops the
        # child reusing a parent-owned handle.
        self.assertEqual(obj._lifecycle_state, LifecycleState.CLOSED)
        self.assertIsNone(obj._handle)

        # A second foreign teardown stays a no-op,
        # and any operation on the now-closed child copy fails.
        obj.close()
        self.assertEqual(self.freed, [])
        with self.assertRaises(Error):
            obj._ensure_valid_state()

    def test_signer_init_rejects_null_pointer(self):
        with self.assertRaises(Error):
            Signer(None)

    def test_builder_from_archive_wraps_handle(self):
        self._use_real_frees()
        archive = io.BytesIO()
        Builder({"claim_generator": "test", "format": "image/jpeg"}).to_archive(
            archive)

        builder = Builder.from_archive(io.BytesIO(archive.getvalue()))

        self.assertTrue(builder.is_valid)
        self.assertIsNone(builder._context)
        self.assertFalse(builder._has_context_signer)
        builder.close()
        self.assertEqual(builder._lifecycle_state, LifecycleState.CLOSED)

    def test_context_build_failure_consumes_signer(self):
        self._use_real_frees()
        signer = self._make_signer()
        real_build = c2pa_module._lib.c2pa_context_builder_build
        c2pa_module._lib.c2pa_context_builder_build = lambda ptr: None
        try:
            with self.assertRaises(Error):
                Context(signer=signer)
        finally:
            c2pa_module._lib.c2pa_context_builder_build = real_build

        self.assertIsNone(signer._handle,
                          "Signer still holds a pointer the native side freed")
        self.assertEqual(signer._lifecycle_state, LifecycleState.CLOSED)

        # Nothing left to free, so close() must be a no-op.
        freed = []
        with patch.object(ManagedResource, '_free_native_ptr',
                          staticmethod(freed.append)):
            signer.close()
        self.assertEqual(freed, [])

    def test_context_with_signer_consumes_it_on_success(self):
        self._use_real_frees()
        signer = self._make_signer()

        context = Context(signer=signer)

        self.assertTrue(context.is_valid)
        self.assertIsNone(signer._handle)
        self.assertEqual(signer._lifecycle_state, LifecycleState.CLOSED)
        self.assertTrue(context.has_signer)
        context.close()

    def test_construction_failure_leaves_nothing_to_free(self):
        # Activation happens after the null check, so a failed construction
        # has no handle on the object that __del__ can find.
        real_new = c2pa_module._lib.c2pa_context_new
        c2pa_module._lib.c2pa_context_new = lambda: None
        try:
            with self.assertRaises(Error):
                Context()
        finally:
            c2pa_module._lib.c2pa_context_new = real_new

        real_json = c2pa_module._lib.c2pa_builder_from_json
        c2pa_module._lib.c2pa_builder_from_json = lambda j: None
        try:
            with self.assertRaises(Error):
                Builder({"claim_generator": "test"})
        finally:
            c2pa_module._lib.c2pa_builder_from_json = real_json

    def test_context_build_null_return_frees_builder(self):
        # Mock a pointer rejection.
        settings = Settings()
        real_build = c2pa_module._lib.c2pa_context_builder_build
        c2pa_module._lib.c2pa_context_builder_build = _fail_with_native_error(
            b"UntrackedPointer: mocked pre-consume rejection")
        try:
            with self.assertRaises(Error):
                Context(settings=settings)
        finally:
            c2pa_module._lib.c2pa_context_builder_build = real_build

        # One free: the un-consumed builder.
        # Settings borrows, so it is not freed here.
        self.assertEqual(len(self.freed), 1,
                         "un-consumed builder leaked on build failure")
        settings.close()

    def test_consume_no_replacement_marks_consumed_on_success(self):
        res = self._FakeHandleResource()
        res._activate(0xCAFE)

        res._consume_no_replacement(lambda h: 0, "set failed: {}")

        # Native took ownership.
        self.assertEqual(self.freed, [])
        self.assertIsNone(res._handle)
        self.assertEqual(res._lifecycle_state, LifecycleState.CLOSED)

    def test_consume_no_replacement_retains_on_pre_consume_tag(self):
        for message in ("UntrackedPointer: rejected",
                        "PointerInUse: 0x2a",
                        "Other: ForeignProcess: 0x2a"):
            with self.subTest(message=message):
                self.freed.clear()
                res = self._FakeHandleResource()
                res._activate(0xCAFE)
                real_read = c2pa_module._read_native_error
                c2pa_module._read_native_error = lambda: message
                try:
                    with self.assertRaises(Error):
                        res._consume_no_replacement(
                            lambda h: -1, "set failed: {}")
                finally:
                    c2pa_module._read_native_error = real_read

                # Rejected before ownership transferred: handle retained.
                self.assertEqual(res._handle, 0xCAFE)
                self.assertEqual(res._lifecycle_state, LifecycleState.ACTIVE)
                self.assertEqual(self.freed, [])
                res.close()
                self.assertEqual(self.freed, [0xCAFE])

    def test_consume_no_replacement_marks_consumed_on_other_error(self):
        res = self._FakeHandleResource()
        res._activate(0xCAFE)
        real_read = c2pa_module._read_native_error
        c2pa_module._read_native_error = lambda: "OtherError: boom"
        try:
            with self.assertRaises(Error):
                res._consume_no_replacement(lambda h: -1, "set failed: {}")
        finally:
            c2pa_module._read_native_error = real_read

        # A non-tag error means native took ownership then failed and dropped
        # the value itself: mark consumed, do not free.
        self.assertEqual(self.freed, [])
        self.assertIsNone(res._handle)
        self.assertEqual(res._lifecycle_state, LifecycleState.CLOSED)

    def test_invoke_consume_success_does_not_consult_error_slot(self):
        """A successful consuming call must not read the error slot at all:
        only a failure inspects it."""
        res = self._FakeHandleResource()
        res._activate(0xCAFE)

        res._consume_no_replacement(lambda h: 0, "set failed: {}")

        self.assertIsNone(c2pa_module._read_native_error())

    def test_native_section_defers_unrelated_finalizer_free(self):
        """A finalizer for a completely unrelated resource firing mid
        native-call must not free immediately.
        """
        victim = self._FakeHandleResource()
        victim._activate(0xCAFE)
        bystander = self._FakeHandleResource()
        bystander._activate(0xB00B)

        def polluting_free(ptr):
            self.freed.append(ptr)
            # Freeing and untracked/ pointer writes its own error into the
            # same thread-local slot.
            c2pa_module._lib.c2pa_error_set_last(
                "Other: UntrackedPointer: {:#x}".format(ptr).encode())
            return -1
        _patch_free(self, polluting_free)

        def ffi_call(handle):
            nonlocal bystander
            del bystander  # last reference dropped: __del__ fires right here
            return None  # the real call failed but set no error of its own

        # A bare section: the consume needs the error section, but not a
        # borrow on its own handle. _ensure_not_borrowed
        # refuses a consume nested in a _native_call() on the same resource.
        with c2pa_module._native_section():
            with self.assertRaises(Error):
                victim._consume_no_replacement(ffi_call, "op failed: {}")

        # The bystander's free is deferred to the section close, so it
        # runs after the consuming call, before the victim's free.
        self.assertEqual(self.freed, [0xB00B, 0xCAFE])

    def test_nested_native_sections_flush_only_at_outermost_close(self):
        """A native-error section opened inside another, already-open one
        on the same thread must not flush anything until the outermost
        one closes."""
        res = self._FakeHandleResource()
        res._activate(0xCAFE)

        outer = c2pa_module._native_section()
        outer.__enter__()
        try:
            inner = c2pa_module._native_section()
            inner.__enter__()
            try:
                res.close()
            finally:
                inner.__exit__(None, None, None)
            # Inner closed, outer is still open: still deferred.
            self.assertEqual(self.freed, [], "inner section flushed")
        finally:
            outer.__exit__(None, None, None)
        self.assertEqual(self.freed, [0xCAFE])

    def test_stale_error_not_misattributed_after_preset_error(self):
        """A stale tag left by an earlier, unrelated call on this thread
        must not be read as this call's own error."""
        # A stale tag from an earlier, unrelated call.
        c2pa_module._lib.c2pa_error_set_last(
            b"Other: UntrackedPointer: 0xdeadbeef")

        res = self._FakeHandleResource()
        res._activate(0xCAFE)

        # Fails without setting any error of its own.
        # The marker written inside _invoke_consume must have cleared
        # the stale tag, so this routes to the "no error of our own" branch.
        with self.assertRaises(Error):
            res._consume_no_replacement(lambda h: -1, "op failed: {}")

        # A misattributed stale tag would have matched
        # _PRE_CONSUME_ERROR_TAGS and left the resource ACTIVE.
        self.assertEqual(self.freed, [0xCAFE])


class TestManagedResourceObjects(TestContextAPIs):
    """Tests native resource handling management when managed manually.
    """

    @staticmethod
    def _ptr_addr(ptr):
        """Address a ctypes pointer points at, or None for a null pointer.

        ctypes pointers compare by identity, not by value: two pointer objects
        for the same address are unequal. Compare addresses instead.
        """
        if not ptr:
            return None
        return ctypes.cast(ptr, ctypes.c_void_p).value

    def _instrument_frees(self):
        """Record frees instead of performing them, and restore on teardown.
        """
        freed = []
        _patch_free(self, freed.append)
        return freed

    def _free_count(self, freed, handle):
        """How many times `handle` was freed, ignoring unrelated frees."""
        target = self._ptr_addr(handle)
        self.assertIsNotNone(target, "cannot count frees of a null handle")
        return sum(1 for ptr in freed if self._ptr_addr(ptr) == target)

    def _make_archive(self, manifest=None):
        archive = io.BytesIO()
        builder = Builder(manifest or self.test_manifest)
        try:
            builder.to_archive(archive)
        finally:
            builder.close()
        archive.seek(0)
        return archive

    def test_settings_activation_paths(self):
        pid = os.getpid()
        for label, factory in (
            ("Settings()", lambda: Settings()),
            ("from_json", lambda: Settings.from_json('{"version_major": 1}')),
            ("from_dict", lambda: Settings.from_dict({"version_major": 1})),
        ):
            with self.subTest(path=label):
                settings = factory()
                try:
                    self.assertTrue(settings.is_valid)
                    self.assertEqual(settings._owner_pid, pid)
                finally:
                    settings.close()

    def test_context_activation_paths(self):
        pid = os.getpid()
        settings = Settings.from_dict({"version_major": 1})
        try:
            for label, factory in (
                # No settings and no signer takes the c2pa_context_new path.
                ("Context()", lambda: Context()),
                # Anything else goes through the ContextBuilder path.
                ("Context(settings)", lambda: Context(settings)),
                ("from_dict", lambda: Context.from_dict({"version_major": 1})),
                ("builder()",
                 lambda: Context.builder().with_settings(settings).build()),
            ):
                with self.subTest(path=label):
                    context = factory()
                    try:
                        self.assertTrue(context.is_valid)
                        self.assertEqual(context._owner_pid, pid)
                    finally:
                        context.close()
        finally:
            settings.close()

    def test_reader_activation_paths(self):
        pid = os.getpid()
        context = Context()
        try:
            with open(DEFAULT_TEST_FILE, "rb") as f:
                from_stream = Reader("image/jpeg", f)
            self.addCleanup(from_stream.close)
            self.assertEqual(from_stream._owner_pid, pid)

            from_path = Reader(DEFAULT_TEST_FILE)
            self.addCleanup(from_path.close)
            self.assertEqual(from_path._owner_pid, pid)

            with open(DEFAULT_TEST_FILE, "rb") as f:
                with_context = Reader(DEFAULT_TEST_FILE, context=context)
            self.addCleanup(with_context.close)
            self.assertEqual(with_context._owner_pid, pid)

            with open(DEFAULT_TEST_FILE, "rb") as f:
                created = Reader.try_create("image/jpeg", f)
            self.addCleanup(created.close)
            self.assertEqual(created._owner_pid, pid)
        finally:
            context.close()

    def test_builder_activation_paths(self):
        pid = os.getpid()
        context = Context()
        try:
            plain = Builder(self.test_manifest)
            self.addCleanup(plain.close)
            self.assertEqual(plain._owner_pid, pid)

            from_json = Builder.from_json(self.test_manifest)
            self.addCleanup(from_json.close)
            self.assertEqual(from_json._owner_pid, pid)

            with_context = Builder(self.test_manifest, context=context)
            self.addCleanup(with_context.close)
            self.assertEqual(with_context._owner_pid, pid)

            # from_archive is the only caller of _wrap_native_handle,
            # which bypasses __init__ entirely
            wrapped = Builder.from_archive(self._make_archive())
            self.addCleanup(wrapped.close)
            self.assertEqual(wrapped._owner_pid, pid)
            self.assertIsNone(wrapped._context)
            self.assertFalse(wrapped._has_context_signer)
        finally:
            context.close()

    def test_signer_activation_paths(self):
        signer = self._ctx_make_signer()
        self.addCleanup(signer.close)
        self.assertTrue(signer.is_valid)
        self.assertEqual(signer._owner_pid, os.getpid())

        callback_signer = self._ctx_make_callback_signer()
        self.addCleanup(callback_signer.close)
        self.assertEqual(callback_signer._owner_pid, os.getpid())

    def test_builder_with_archive_swaps_the_handle(self):
        context = Context()
        self.addCleanup(context.close)
        builder = Builder(self.test_manifest, context=context)
        original_handle = builder._handle
        original_stamp = builder._owner_pid

        result = builder.with_archive(self._make_archive())

        self.assertIs(result, builder, "with_archive should return self")
        self.assertNotEqual(builder._handle, original_handle,
                            "the native handle was not replaced")
        self.assertEqual(builder._lifecycle_state, LifecycleState.ACTIVE)
        # The replacement came from this process, the stamp still applies.
        self.assertEqual(builder._owner_pid, original_stamp)
        self.assertEqual(builder._owner_pid, os.getpid())
        builder.close()

    def test_reader_with_fragment_swaps_the_handle(self):
        init_path = os.path.join(FIXTURES_DIR, "dashinit.mp4")
        fragment_path = os.path.join(FIXTURES_DIR, "dash1.m4s")
        context = Context()
        self.addCleanup(context.close)

        with open(init_path, "rb") as init:
            reader = Reader("video/mp4", init, context=context)
        self.addCleanup(reader.close)
        original_handle = reader._handle

        # The Reader consumed the first handle, so the init stream is reopened.
        with open(init_path, "rb") as init, open(fragment_path, "rb") as frag:
            result = reader.with_fragment("video/mp4", init, frag)

        self.assertIs(result, reader, "with_fragment should return self")
        self.assertNotEqual(reader._handle, original_handle,
                            "the native handle was not replaced")
        self.assertEqual(reader._lifecycle_state, LifecycleState.ACTIVE)
        self.assertEqual(reader._owner_pid, os.getpid())

    def test_swapped_builder_is_freed_exactly_once(self):
        context = Context()
        self.addCleanup(context.close)
        builder = Builder(self.test_manifest, context=context)
        original_handle = builder._handle
        archive = self._make_archive()

        # Instrument across the swap so a free of the consumed pointer is recorded.
        freed = self._instrument_frees()
        builder.with_archive(archive)
        swapped_handle = builder._handle

        self.assertEqual(self._free_count(freed, original_handle), 0,
                         "the swap freed the consumed pointer")

        builder.close()
        builder.close()

        # The replacement must be freed exactly once; a second close() is a
        # no-op. We don't separately assert original_handle's count here: the
        # native allocator may legally reuse the just-freed original address
        # for the replacement Box (same-size free-then-alloc within one FFI
        # call), so swapped_handle and original_handle can be the same
        # pointer value. The check above already covers that case correctly.
        self.assertEqual(self._free_count(freed, swapped_handle), 1)

    def test_repeated_swaps_on_one_builder(self):
        # Each with_archive consumes the handle the previous one returned, so
        # a chain of swaps is where a wrong swap surfaces: keeping the
        # consumed pointer makes the next call raise UntrackedPointer from
        # the native registry.
        context = Context()
        self.addCleanup(context.close)
        builder = Builder(self.test_manifest, context=context)
        self.addCleanup(builder.close)

        seen = [builder._handle]
        for _ in range(5):
            builder.with_archive(self._make_archive())
            self.assertEqual(builder._lifecycle_state, LifecycleState.ACTIVE)
            seen.append(builder._handle)

        self.assertTrue(builder.is_valid)
        self.assertEqual(builder._owner_pid, os.getpid())

    def test_context_consumes_signer_but_not_settings(self):
        settings = Settings.from_dict({"version_major": 1})
        signer = self._ctx_make_signer()

        context = Context(settings=settings, signer=signer)
        self.addCleanup(context.close)

        # The signer pointer moved to the native context builder.
        self.assertIsNone(signer._handle)
        self.assertEqual(signer._lifecycle_state, LifecycleState.CLOSED)
        self.assertTrue(context.has_signer)

        # Settings are copied, not consumed, so the caller still owns them.
        self.assertTrue(settings.is_valid)
        self.assertEqual(settings._owner_pid, os.getpid())
        settings.close()

    def test_consumed_signer_close_frees_nothing(self):
        signer = self._ctx_make_signer()
        # Captured before the context consumes it:
        # close() nulls the handle, there is no pointer left to identify the free by.
        signer_handle = signer._handle
        context = Context(signer=signer)
        self.addCleanup(context.close)

        freed = self._instrument_frees()
        signer.close()

        self.assertEqual(self._free_count(freed, signer_handle), 0,
                         "closing a consumed Signer freed a pointer the "
                         "context now owns")

    def test_builder_with_archive_null_return_marks_consumed(self):
        builder = Builder(self.test_manifest)
        released_handle = builder._handle
        archive = self._make_archive()

        # Mimic a non-tag error: native took ownership then failed and dropped
        # the value itself, so the handle is marked consumed, not freed.
        real_call = c2pa_module._lib.c2pa_builder_with_archive
        c2pa_module._lib.c2pa_builder_with_archive = _fail_with_native_error(
            b"Other: mocked test error")

        # Instrument before the failure...
        freed = self._instrument_frees()
        try:
            with self.assertRaises(Error):
                builder.with_archive(archive)
        finally:
            c2pa_module._lib.c2pa_builder_with_archive = real_call

        # Nothing left to own after failing.
        self.assertIsNone(builder._handle)
        self.assertEqual(builder._lifecycle_state, LifecycleState.CLOSED)

        # A non-tag error marks consumed: no free (a free here would be a
        # guarded no-op that dirties the error slot and races a recycled
        # address in other threads).
        self.assertEqual(self._free_count(freed, released_handle), 0,
                         "consumed handle was freed instead of marked consumed")

        # close() must not free it either.
        builder.close()
        self.assertEqual(self._free_count(freed, released_handle), 0,
                         "close() freed a handle already marked consumed")

    def test_reader_with_fragment_null_return_marks_consumed(self):
        init_path = os.path.join(FIXTURES_DIR, "dashinit.mp4")
        fragment_path = os.path.join(FIXTURES_DIR, "dash1.m4s")
        with open(init_path, "rb") as init:
            reader = Reader("video/mp4", init)
        released_handle = reader._handle

        # Mimic a non-tag error: native took ownership then failed and dropped
        # the value itself, so the handle is marked consumed, not freed.
        real_call = c2pa_module._lib.c2pa_reader_with_fragment
        c2pa_module._lib.c2pa_reader_with_fragment = _fail_with_native_error(
            b"Other: mocked test error")

        # Instrument before failure so any free would be counted.
        freed = self._instrument_frees()
        try:
            with open(init_path, "rb") as init, \
                    open(fragment_path, "rb") as frag:
                with self.assertRaises(Error):
                    reader.with_fragment("video/mp4", init, frag)
        finally:
            c2pa_module._lib.c2pa_reader_with_fragment = real_call

        self.assertIsNone(reader._handle)
        self.assertEqual(reader._lifecycle_state, LifecycleState.CLOSED)

        # A non-tag error marks consumed: no free.
        self.assertEqual(self._free_count(freed, released_handle), 0,
                         "consumed handle was freed instead of marked consumed")

        # close() must not free it either.
        reader.close()
        self.assertEqual(self._free_count(freed, released_handle), 0,
                         "close() freed a handle already marked consumed")

    def test_reader_with_fragment_ffi_raise_frees_self(self):
        # If the ctypes call itself raises, the failure runs
        # through the except BaseException branch, which frees the handle.
        # with_fragment must free exactly once and leave nothing for close().
        init_path = os.path.join(FIXTURES_DIR, "dashinit.mp4")
        fragment_path = os.path.join(FIXTURES_DIR, "dash1.m4s")
        with open(init_path, "rb") as init:
            reader = Reader("video/mp4", init)
        released_handle = reader._handle

        def _raise(*_args):
            raise RuntimeError("boom")

        real_call = c2pa_module._lib.c2pa_reader_with_fragment
        c2pa_module._lib.c2pa_reader_with_fragment = _raise

        # Instrument before the failure so the eager free is counted.
        freed = self._instrument_frees()
        try:
            with open(init_path, "rb") as init, \
                    open(fragment_path, "rb") as frag:
                with self.assertRaises(Error):
                    reader.with_fragment("video/mp4", init, frag)
        finally:
            c2pa_module._lib.c2pa_reader_with_fragment = real_call

        self.assertIsNone(reader._handle)
        self.assertEqual(reader._lifecycle_state, LifecycleState.CLOSED)

        # The error path frees the old handle.
        self.assertEqual(self._free_count(freed, released_handle), 1,
                         "error path did not free the old handle exactly once")

        # close() must not free it again.
        reader.close()
        self.assertEqual(self._free_count(freed, released_handle), 1,
                         "close() freed a handle the error path already freed")

    # Consume-and-return ownership: the native call can take the handle partway
    # through the call, so a null return does not always say on its own
    # whether the handle was consumed or not, warranting further checks/bookkeeping.

    @staticmethod
    def _is_pre_consume_rejection(error_message):
        """True if this native error means ownership never transferred.
        """
        if not error_message:
            return False
        return ManagedResource._is_pre_consume_rejection(error_message)

    def _stale_reader_handle(self):
        """A freed, untracked pointer, captured before close() nulls it.

        Take a fresh one per call: recycled addresses become tracked again.
        """
        init_path = os.path.join(FIXTURES_DIR, "dashinit.mp4")
        with open(init_path, "rb") as init:
            victim = Reader("video/mp4", init)
        stale = ctypes.cast(victim._handle,
                            ctypes.POINTER(c2pa_module.C2paReader))
        victim.close()
        return stale

    @staticmethod
    def _untracked_reader_handle():
        """A pointer the native registry never handed out.

        Rejected like a stale handle, but not a freed address, so it cannot
        be recycled and start passing the registry lookup.
        """
        buf = ctypes.create_string_buffer(64)
        return (ctypes.cast(buf, ctypes.POINTER(c2pa_module.C2paReader)),
                buf)

    def test_with_fragment_pre_consume_rejection_does_not_leak(self):
        # A handle dropped on this path leaks one reader per call.
        init_path = os.path.join(FIXTURES_DIR, "dashinit.mp4")
        fragment_path = os.path.join(FIXTURES_DIR, "dash1.m4s")

        for _ in range(25):
            with open(init_path, "rb") as init:
                reader = Reader("video/mp4", init)
            real_handle = reader._handle
            reader._handle = self._stale_reader_handle()
            try:
                with open(init_path, "rb") as init, \
                        open(fragment_path, "rb") as frag:
                    with self.assertRaises(Error):
                        reader.with_fragment("video/mp4", init, frag)
            finally:
                reader._handle = real_handle
            # Still owns a working handle every time round.
            self.assertEqual(reader._lifecycle_state, LifecycleState.ACTIVE)
            self.assertTrue(reader.json())
            reader.close()

    def test_reader_with_empty_manifest_data_never_calls_native(self):
        """End-to-end: the guard is wired into the public path, not just
        available as a helper."""
        context = Context()
        self.addCleanup(context.close)
        with open(os.path.join(FIXTURES_DIR,
                               DEFAULT_TEST_FILE_NAME), "rb") as image:
            image_bytes = image.read()

        freed = self._instrument_frees()

        with self.assertRaises(Error):
            Reader("image/jpeg", io.BytesIO(image_bytes),
                   manifest_data=b"", context=context)

        # The guard raises before the FFI call, so the reader handle is still
        # the binding's to free: exactly one free, and no abandoned handle.
        self.assertEqual(len(freed), 1)

    def test_check_cstr_arg_rejects_none_and_embedded_nul(self):
        """Both cases would reach native as something other than the caller
        passed: None as a null pointer, an embedded NUL as a short string."""
        with self.assertRaises(Error):
            c2pa_module._check_cstr_arg('format', None)

        with self.assertRaises(Error):
            c2pa_module._check_cstr_arg('format', "image/\x00jpeg")

        c2pa_module._check_cstr_arg('format', "image/jpeg")
        c2pa_module._check_cstr_arg('format', b"")

    def test_format_embeddable_null_out_pointer_raises_not_crashes(self):
        real = c2pa_module._lib.c2pa_format_embeddable
        c2pa_module._lib.c2pa_format_embeddable = (
            lambda fmt, data, size, out: 128)
        try:
            with self.assertRaises(Error):
                format_embeddable("image/jpeg", b"junk")
        finally:
            c2pa_module._lib.c2pa_format_embeddable = real

    def test_check_bytes_arg_rejects_none_and_empty(self):
        for bad in (None, b""):
            with self.assertRaises(Error):
                c2pa_module._check_bytes_arg('manifest_data', bad)

        c2pa_module._check_bytes_arg('manifest_data', b"x")

    def test_check_handle_arg_rejects_null(self):
        """A null handle is a NullParameter on both native versions."""
        with self.assertRaises(Error):
            c2pa_module._check_handle_arg('stream', None)

        c2pa_module._check_handle_arg(
            'stream', ctypes.cast(1, ctypes.c_void_p))

    def test_repeated_with_fragment_does_not_accumulate_streams(self):
        """Repeated with_fragment Reader calls should not accumulate streams.
        """
        init_path = os.path.join(FIXTURES_DIR, "dashinit.mp4")
        fragment_path = os.path.join(FIXTURES_DIR, "dash1.m4s")

        with open(init_path, "rb") as init:
            reader = Reader("video/mp4", init)
        self.addCleanup(reader.close)

        superseded = []
        for _ in range(25):
            with open(init_path, "rb") as init, \
                    open(fragment_path, "rb") as frag:
                reader.with_fragment("video/mp4", init, frag)
            self.assertLessEqual(len(reader._fragment_streams), 1)
            superseded.append(reader._fragment_streams[-1])

        # Dropping the reference is not enough: the native stream is only
        # released by close(), so every superseded wrapper must be closed.
        self.assertTrue(all(s.closed for s in superseded[:-1]))

    def test_with_archive_post_consume_failure_consumes_handle(self):
        # Ownership taken, then the operation failed:
        # The handle is gone, so close() must not free it again.
        builder = Builder(json.dumps(
            {"claim_generator_info": [{"name": "test", "version": "0.1"}],
             "assertions": []}))
        consumed_handle = builder._handle

        with self.assertRaises(Error):
            builder.with_archive(io.BytesIO(b"not a valid archive"))

        self.assertIsNone(builder._handle)
        self.assertEqual(builder._lifecycle_state, LifecycleState.CLOSED)

        freed = self._instrument_frees()
        builder.close()
        self.assertEqual(self._free_count(freed, consumed_handle), 0,
                         "close() freed a handle the FFI already consumed")

    def test_with_fragment_marshalling_error_keeps_handle(self):
        # Never reaches native code, so nothing was consumed.
        init_path = os.path.join(FIXTURES_DIR, "dashinit.mp4")
        with open(init_path, "rb") as init:
            reader = Reader("video/mp4", init)
        real_handle = reader._handle

        def _bad_marshalling(*_args):
            raise ctypes.ArgumentError("wrong argument type")

        real_call = c2pa_module._lib.c2pa_reader_with_fragment
        c2pa_module._lib.c2pa_reader_with_fragment = _bad_marshalling
        try:
            with open(init_path, "rb") as init, \
                    open(init_path, "rb") as frag:
                with self.assertRaises(ctypes.ArgumentError):
                    reader.with_fragment("video/mp4", init, frag)
        finally:
            c2pa_module._lib.c2pa_reader_with_fragment = real_call

        self.assertIs(reader._handle, real_handle)
        self.assertEqual(reader._lifecycle_state, LifecycleState.ACTIVE)
        self.assertTrue(reader.json(),
                        "a marshalling failure never reached the FFI, so "
                        "the reader must still be usable")

        reader.close()

    def test_unknown_failure_drops_handle_without_freeing(self):
        # Ownership unknowable, so the handle is let go rather than freed.
        # Needs a mock: every real null return sets an error.
        init_path = os.path.join(FIXTURES_DIR, "dashinit.mp4")
        fragment_path = os.path.join(FIXTURES_DIR, "dash1.m4s")
        with open(init_path, "rb") as init:
            reader = Reader("video/mp4", init)

        consumed_handle = reader._handle
        # Simulate an error being set
        real_call = c2pa_module._lib.c2pa_reader_with_fragment
        c2pa_module._lib.c2pa_reader_with_fragment = _fail_with_native_error(
            b"Other: mocked test error")
        try:
            with open(init_path, "rb") as init, \
                    open(fragment_path, "rb") as frag:
                with self.assertRaises(Error):
                    reader.with_fragment("video/mp4", init, frag)
        finally:
            c2pa_module._lib.c2pa_reader_with_fragment = real_call

        # Unplaceable, so the handle is let go rather than freed twice.
        self.assertIsNone(reader._handle)
        self.assertEqual(reader._lifecycle_state, LifecycleState.CLOSED)

        freed = self._instrument_frees()
        reader.close()
        self.assertEqual(self._free_count(freed, consumed_handle), 0,
                         "close() freed a handle of unknown ownership")

    def test_pre_consume_rejection_is_typed(self):
        # Rejections arrive wrapped as "Other: UntrackedPointer: 0x...".
        self.assertTrue(self._is_pre_consume_rejection(
            "Other: UntrackedPointer: 0x600001234567"))
        self.assertTrue(self._is_pre_consume_rejection(
            "Other: WrongPointerType: 0x600001234567"))
        self.assertFalse(self._is_pre_consume_rejection(
            "Verify: invalid JUMBF header"))
        self.assertFalse(self._is_pre_consume_rejection(None))
        self.assertFalse(self._is_pre_consume_rejection(""))

    def test_pre_consume_tags_still_match_the_native_wording(self):
        # Classification keys on error text (the numeric code is not
        # exported), so a native rename would silently misjudge ownership.
        init_path = os.path.join(FIXTURES_DIR, "dashinit.mp4")
        fragment_path = os.path.join(FIXTURES_DIR, "dash1.m4s")
        with open(init_path, "rb") as init:
            reader = Reader("video/mp4", init)
        real_handle = reader._handle

        reader._handle = self._stale_reader_handle()
        try:
            with open(init_path, "rb") as init, \
                    open(fragment_path, "rb") as frag:
                with self.assertRaises(Error) as caught:
                    reader.with_fragment("video/mp4", init, frag)
        finally:
            reader._handle = real_handle

        message = str(caught.exception)
        self.assertTrue(
            self._is_pre_consume_rejection(message),
            f"rejection wording does not match _PRE_CONSUME_ERROR_TAGS, "
            f"so ownership will be misjudged: {message!r}")
        reader.close()

    def test_stale_handle_is_actually_rejected_every_time(self):
        # A handle that stopped being rejected would quietly measure the
        # success path. Uses the never-allocated buffer: freed addresses get
        # recycled and start passing the registry lookup.
        init_path = os.path.join(FIXTURES_DIR, "dashinit.mp4")
        fragment_path = os.path.join(FIXTURES_DIR, "dash1.m4s")

        for _ in range(25):
            with open(init_path, "rb") as init:
                reader = Reader("video/mp4", init)
            real_handle = reader._handle
            bogus, _buf = self._untracked_reader_handle()
            reader._handle = bogus
            try:
                with open(init_path, "rb") as init, \
                        open(fragment_path, "rb") as frag:
                    with self.assertRaises(Error) as caught:
                        reader.with_fragment("video/mp4", init, frag)
                self.assertTrue(
                    self._is_pre_consume_rejection(
                        str(caught.exception)),
                    "the bogus handle was not rejected, so this stopped "
                    "exercising the pre-consume path")
            finally:
                reader._handle = real_handle
                reader.close()

    def test_perf_scenario_bogus_handle_is_rejected(self):
        # The perf scenarios use a plain buffer so looping does not swamp
        # the measurement. It still has to produce a real rejection.
        init_path = os.path.join(FIXTURES_DIR, "dashinit.mp4")
        fragment_path = os.path.join(FIXTURES_DIR, "dash1.m4s")
        with open(init_path, "rb") as init:
            reader = Reader("video/mp4", init)
        real_handle = reader._handle

        bogus, _buf = self._untracked_reader_handle()
        reader._handle = bogus
        try:
            with open(init_path, "rb") as init, \
                    open(fragment_path, "rb") as frag:
                with self.assertRaises(Error) as caught:
                    reader.with_fragment("video/mp4", init, frag)
        finally:
            reader._handle = real_handle

        self.assertTrue(
            self._is_pre_consume_rejection(str(caught.exception)),
            "the perf bogus handle was not rejected, so "
            "with_fragment_pre_consume_rejection measures nothing")
        # Handle kept, so the reader still works and frees normally.
        self.assertEqual(reader._lifecycle_state, LifecycleState.ACTIVE)
        self.assertTrue(reader.json())
        reader.close()

    def test_every_null_return_sets_its_own_error(self):
        # Each null-returning path must report the error it set itself, never
        # one left behind by an earlier call.
        init_path = os.path.join(FIXTURES_DIR, "dashinit.mp4")
        fragment_path = os.path.join(FIXTURES_DIR, "dash1.m4s")

        # Set a recognizable error, so anything stale is caught by the
        # assertNotIn checks.
        c2pa_module._lib.c2pa_error_set_last(
            b"NotSupported: planted by the test")

        # Pre-consume rejection: reports UntrackedPointer, not NotSupported.
        with open(init_path, "rb") as init:
            reader = Reader("video/mp4", init)
        real_handle = reader._handle
        reader._handle = self._stale_reader_handle()
        try:
            with open(init_path, "rb") as init, \
                    open(fragment_path, "rb") as frag:
                with self.assertRaises(Error) as caught:
                    reader.with_fragment("video/mp4", init, frag)
        finally:
            reader._handle = real_handle
        self.assertIn("UntrackedPointer", str(caught.exception))
        self.assertNotIn("NotSupported", str(caught.exception))
        reader.close()

        # Post-consume failure: reports the operation error, not the
        # UntrackedPointer left by the step above.
        builder = Builder(json.dumps(
            {"claim_generator_info": [{"name": "test", "version": "0.1"}],
             "assertions": []}))
        with self.assertRaises(Error) as caught:
            builder.with_archive(io.BytesIO(b"not a valid archive"))
        self.assertNotIn("UntrackedPointer", str(caught.exception))
        builder.close()

    def test_pre_consume_classification_holds_across_threads(self):
        # The error slot is thread-local, so concurrent calls do not mask
        # each other's errors and misjudge ownership.
        init_path = os.path.join(FIXTURES_DIR, "dashinit.mp4")
        fragment_path = os.path.join(FIXTURES_DIR, "dash1.m4s")
        init_bytes = open(init_path, "rb").read()
        frag_bytes = open(fragment_path, "rb").read()
        problems = []

        def worker():
            for _ in range(10):
                reader = Reader("video/mp4", io.BytesIO(init_bytes))
                real_handle = reader._handle
                # A never-allocated buffer, not a freed pointer: with several
                # threads churning the allocator, a freed address gets reused
                # and starts passing the registry lookup, which would end the
                # iteration in a real consume instead of a rejection.
                bogus, _buf = self._untracked_reader_handle()
                reader._handle = bogus
                try:
                    reader.with_fragment("video/mp4",
                                         io.BytesIO(init_bytes),
                                         io.BytesIO(frag_bytes))
                    problems.append("rejection did not raise")
                except Error as e:
                    if not self._is_pre_consume_rejection(str(e)):
                        problems.append(f"misclassified: {str(e)[:60]}")
                finally:
                    reader._handle = real_handle
                    if reader._lifecycle_state != LifecycleState.ACTIVE:
                        problems.append("handle dropped on a rejection")
                    reader.close()

        threads = [threading.Thread(target=worker) for _ in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(problems, [],
                         "ownership was misjudged under concurrency")

    def test_read_native_error_returns_none_for_an_empty_message(self):
        # c2pa_error() returns an owned pointer to "" when no error is set,
        # never NULL, so the pointer cannot be the "is there an error" test.
        c2pa_module._write_no_error_marker()
        original = c2pa_module._lib.c2pa_error
        empty = ctypes.create_string_buffer(b"")

        try:
            c2pa_module._lib.c2pa_error = lambda: ctypes.cast(
                empty, ctypes.c_void_p).value
            self.assertIsNone(
                c2pa_module._read_native_error(),
                "an empty native message must read as None, otherwise "
                "callers' 'if error:' checks are only accidentally right")
        finally:
            c2pa_module._lib.c2pa_error = original

    def test_null_return_with_no_native_error_is_treated_as_consumed(self):
        # A null with no error of its own is the case that breaks without
        # the marker:
        # the slot still held whatever an unrelated, earlier call on this same
        # (pooled) thread left behind, and a stale UntrackedPointer/
        # WrongPointerType tag would make this call believe it still owned a
        # handle the native side already dropped.
        init_path = os.path.join(FIXTURES_DIR, "dashinit.mp4")
        fragment_path = os.path.join(FIXTURES_DIR, "dash1.m4s")

        # A stale, unrelated tag left by a prior call on this thread.
        c2pa_module._lib.c2pa_error_set_last(
            b"UntrackedPointer: 0xdeadbeef")

        with open(init_path, "rb") as init:
            reader = Reader("video/mp4", init)
        consumed_handle = reader._handle

        real_call = c2pa_module._lib.c2pa_reader_with_fragment
        # The fake native call sets no error of its own,
        # the marker planted by _invoke_consume is left in the slot.
        c2pa_module._lib.c2pa_reader_with_fragment = (
            lambda r, f, s, frag: None)
        freed = self._instrument_frees()
        try:
            with open(init_path, "rb") as init, \
                    open(fragment_path, "rb") as frag:
                with self.assertRaises(Error):
                    reader.with_fragment("video/mp4", init, frag)
        finally:
            c2pa_module._lib.c2pa_reader_with_fragment = real_call

        # Ownership is unknown, so the handle is freed once. c2pa_free
        # returns -1 if native had already taken the value.
        self.assertEqual(self._free_count(freed, consumed_handle), 1)

    # Backfilling a pointer minted by a direct FFI call. Builder.from_archive
    # is the only production caller of _wrap_native_handle, so these are the
    # only tests that drive the primitive as the generic entry point it is.

    def _raw_builder_handle(self):
        manifest = json.dumps(
            {"claim_generator": "raw_ffi_test", "format": "image/jpeg"}
        ).encode("utf-8")
        handle = c2pa_module._lib.c2pa_builder_from_json(manifest)
        self.assertTrue(handle, "the FFI did not return a builder pointer")
        return handle

    def test_wrap_raw_ffi_builder_pointer(self):
        builder = Builder._wrap_native_handle(self._raw_builder_handle())

        self.assertTrue(builder.is_valid)
        self.assertEqual(builder._lifecycle_state, LifecycleState.ACTIVE)
        self.assertEqual(builder._owner_pid, os.getpid())

        archive = io.BytesIO()
        builder.to_archive(archive)
        self.assertTrue(archive.getvalue())

        builder.close()
        self.assertEqual(builder._lifecycle_state, LifecycleState.CLOSED)
        self.assertIsNone(builder._handle)

    def test_wrap_raw_ffi_settings_pointer(self):
        handle = c2pa_module._lib.c2pa_settings_new()
        self.assertTrue(handle)

        settings = Settings._wrap_native_handle(handle)
        try:
            self.assertTrue(settings.is_valid)
            self.assertEqual(settings._owner_pid, os.getpid())
            settings.set("version_major", "1")
        finally:
            settings.close()

    def test_wrap_raw_ffi_context_pointer(self):
        handle = c2pa_module._lib.c2pa_context_new()
        self.assertTrue(handle)

        context = Context._wrap_native_handle(handle)
        try:
            self.assertTrue(context.is_valid)
            self.assertEqual(context._owner_pid, os.getpid())
            # Handing the wrapped pointer back to the FFI proves it is live.
            builder = Builder(self.test_manifest, context=context)
            self.assertTrue(builder.is_valid)
            builder.close()
        finally:
            context.close()

    def test_wrapped_raw_pointer_freed_exactly_once(self):
        handle = self._raw_builder_handle()
        freed = self._instrument_frees()

        builder = Builder._wrap_native_handle(handle)
        builder.close()
        builder.close()
        del builder
        gc.collect()

        self.assertEqual(self._free_count(freed, handle), 1,
                         "wrapped handle not freed exactly once")

    def test_wrap_supplies_defaults(self):
        # _init_attrs() runs on the wrap path, so an instance built around a
        # raw handle still has everything the rest of the class reads.
        builder = Builder._wrap_native_handle(self._raw_builder_handle())
        self.addCleanup(builder.close)

        self.assertIsNone(builder._context)
        self.assertFalse(builder._has_context_signer)

    def test_init_attrs_covers_what_init_sets(self):
        # Anything __init__ sets but _init_attrs() misses is absent on a
        # wrapped instance, which is the trap _init_attrs() exists to close.
        for cls in (Builder, Context, Reader, Signer):
            with self.subTest(cls=cls.__name__):
                defaulted = set(re.findall(
                    r"self\.(_[a-z][a-z0-9_]*)\s*=",
                    inspect.getsource(cls._init_attrs)))
                assigned = set(re.findall(
                    r"self\.(_[a-z][a-z0-9_]*)\s*=",
                    inspect.getsource(cls.__init__)))
                self.assertEqual(
                    assigned - defaulted, set(),
                    f"{cls.__name__}.__init__ sets attributes that "
                    f"_init_attrs() does not default")

    def test_init_attrs_overrides_chain_to_super(self):
        # A subclass of these would silently lose the parent's defaults if
        # the chain were broken.
        for cls in (Builder, Context, Reader, Signer):
            with self.subTest(cls=cls.__name__):
                self.assertIn(
                    "super()._init_attrs()",
                    inspect.getsource(cls._init_attrs),
                    f"{cls.__name__}._init_attrs() does not chain to super()")

    def test_wrap_raw_ffi_signer_pointer(self):
        # Signer._release() reads _callback_cb, so a wrap that skipped the
        # defaults would fail during cleanup rather than at the wrap.
        freed = self._instrument_frees()

        signer = Signer._wrap_native_handle(0xABCD)
        self.assertIsNone(signer._callback_cb)
        self.assertEqual(signer._owner_pid, os.getpid())

        # Cleanup swallows a failing _release(), so the error log is the only
        # way to see one.
        with self.assertNoLogs("c2pa", level="ERROR"):
            signer.close()

        self.assertEqual(freed, [0xABCD])

    def test_signer_release_clears_callback(self):
        signer = self._ctx_make_callback_signer()
        self.assertIsNotNone(signer._callback_cb)

        signer.close()

        self.assertIsNone(signer._callback_cb)

    def test_builder_release_clears_context(self):
        context = Context()
        self.addCleanup(context.close)
        builder = Builder(self.test_manifest, context=context)

        builder.close()

        self.assertIsNone(builder._context,
                          "closed Builder still pins its Context")
        # The Builder does not own the Context, so it must not close it.
        self.assertTrue(context.is_valid)

    def test_consumed_reader_closes_backing_file(self):
        # A failed with_fragment consumes the reader.
        # # Reader(path) opened the backing file itself,
        # so nothing else will ever close it.
        reader = Reader(DEFAULT_TEST_FILE)
        backing_file = reader._backing_file
        self.assertFalse(backing_file.closed)

        # Simulate an error being set
        real_call = c2pa_module._lib.c2pa_reader_with_fragment
        c2pa_module._lib.c2pa_reader_with_fragment = _fail_with_native_error(
            b"Other: mocked test error")
        try:
            with open(DEFAULT_TEST_FILE, "rb") as main, \
                    open(DEFAULT_TEST_FILE, "rb") as frag:
                with self.assertRaises(Error):
                    reader.with_fragment("image/jpeg", main, frag)
        finally:
            c2pa_module._lib.c2pa_reader_with_fragment = real_call

        self.assertTrue(backing_file.closed,
                        "consumed Reader leaked its backing file")

    def test_consumed_builder_releases_context(self):
        context = Context()
        self.addCleanup(context.close)
        builder = Builder(self.test_manifest, context=context)
        archive = self._make_archive()

        # Simulate an error being set
        real_call = c2pa_module._lib.c2pa_builder_with_archive
        c2pa_module._lib.c2pa_builder_with_archive = _fail_with_native_error(
            b"Other: mocked test error")
        try:
            with self.assertRaises(Error):
                builder.with_archive(archive)
        finally:
            c2pa_module._lib.c2pa_builder_with_archive = real_call

        self.assertIsNone(builder._context,
                          "consumed Builder still pins its Context")
        self.assertTrue(context.is_valid)

    def test_context_takes_callback_before_consuming_signer(self):
        # Consuming the signer releases its callback reference,
        # so the Context has to take it first or the callback dies with the signer.
        signer = self._ctx_make_callback_signer()
        callback = signer._callback_cb
        self.assertIsNotNone(callback)

        context = Context(signer=signer)
        self.addCleanup(context.close)

        self.assertIs(context._signer_callback_cb, callback)
        self.assertIsNone(signer._callback_cb)

    def test_reader_close_closes_backing_file(self):
        # _close_streams reads the attrs _init_attrs() defaults, so this is
        # the regression guard for reading them directly.
        reader = Reader(DEFAULT_TEST_FILE)
        reader.json()
        backing_file = reader._backing_file
        self.assertIsNotNone(backing_file)

        reader.close()

        self.assertTrue(backing_file.closed, "Reader left its file open")
        self.assertIsNone(reader._backing_file)
        self.assertIsNone(reader._manifest_json_str_cache)
        self.assertIsNone(reader._manifest_data_cache)

    def test_consumed_reader_clears_caches(self):
        # Consuming marks the reader closed, so close() will not run later.
        # Anything cleanup owes the object has to happen at consume time.
        reader = Reader(DEFAULT_TEST_FILE)
        reader.json()
        self.assertIsNotNone(reader._manifest_json_str_cache)

        # Simulate an error being set
        real_call = c2pa_module._lib.c2pa_reader_with_fragment
        c2pa_module._lib.c2pa_reader_with_fragment = _fail_with_native_error(
            b"Other: mocked test error")
        try:
            with open(DEFAULT_TEST_FILE, "rb") as main, \
                    open(DEFAULT_TEST_FILE, "rb") as frag:
                with self.assertRaises(Error):
                    reader.with_fragment("image/jpeg", main, frag)
        finally:
            c2pa_module._lib.c2pa_reader_with_fragment = real_call

        self.assertIsNone(reader._manifest_json_str_cache,
                          "consumed Reader kept its manifest cache")
        self.assertIsNone(reader._manifest_data_cache)

    def test_reader_del_clears_caches(self):
        # __del__ goes through _cleanup_resources, not close(), so cache
        # clearing has to live somewhere both paths reach.
        reader = Reader(DEFAULT_TEST_FILE)
        reader.json()
        self.assertIsNotNone(reader._manifest_json_str_cache)

        # __del__ runs _cleanup_resources directly, so drive that rather than
        # dropping the reference: the assertions need the object afterwards.
        reader._cleanup_resources()

        self.assertIsNone(reader._manifest_json_str_cache,
                          "cleanup left the manifest cache alive")
        self.assertIsNone(reader._manifest_data_cache)

    def test_from_archive_frees_handle_when_wrap_fails(self):
        # The wrap raising means no Python object took ownership, so
        # from_archive still holds the handle and has to free it.
        archive = self._make_archive()  # closes a Builder; keep it off the count
        freed = self._instrument_frees()
        real_wrap = Builder._wrap_native_handle

        def _boom(*args, **kwargs):
            raise Error("wrap failed")

        Builder._wrap_native_handle = _boom
        try:
            with self.assertRaises(Error):
                Builder.from_archive(archive)
        finally:
            Builder._wrap_native_handle = real_wrap

        self.assertEqual(len(freed), 1,
                         "from_archive leaked the handle when the wrap failed")

    def test_sign_failure_chains_the_original_exception(self):
        # The wrapper re-raises as C2paError; losing __cause__ hides which
        # call actually failed.
        builder = Builder(self.test_manifest)
        signer = self._ctx_make_signer()
        self.addCleanup(signer.close)

        sentinel = RuntimeError("native call blew up")
        real_sign = c2pa_module._lib.c2pa_builder_sign

        def _boom(*args):
            raise sentinel

        c2pa_module._lib.c2pa_builder_sign = _boom
        try:
            with self.assertRaises(Error) as ctx:
                builder.sign(signer, "image/jpeg",
                             io.BytesIO(b"x"), io.BytesIO())
        finally:
            c2pa_module._lib.c2pa_builder_sign = real_sign

        self.assertIs(ctx.exception.__cause__, sentinel,
                      "signing error dropped the original exception")


class TestMarkerOutlivesPointerConsumptionSemantics(unittest.TestCase):
    """The marker is needed for reasons independent of pointer ownership.

    The native error slot is sticky and thread-local, so failure paths
    that carry no still need to tell an error this call set from an
    earlier, unrelated call left behind.
    """

    def setUp(self):
        # Leave no message from an earlier test in this thread's slot.
        c2pa_module._write_no_error_marker()

    def test_settings_set_failure_reports_its_own_error(self):
        settings = Settings()
        self.addCleanup(settings.close)

        c2pa_module._lib.c2pa_error_set_last(b"Signature: earlier task")
        self.assertEqual(
            c2pa_module._read_native_error(), "Signature: earlier task")

        with self.assertRaises(Error) as ctx:
            settings.set("builder.thumbnail.enabled", "not-a-json-value")

        self.assertNotIn("earlier task", str(ctx.exception))

    def test_one_thread_marker_does_not_clear_another_threads_error(self):
        """Marking on one thread must leave another thread's pending error
        readable: the slot is per thread, and so is the marker."""
        set_on_worker = threading.Event()
        marked_on_main = threading.Event()
        seen = {}

        def worker():
            c2pa_module._lib.c2pa_error_set_last(b"Io: worker error")
            set_on_worker.set()
            marked_on_main.wait(5)
            seen["worker"] = c2pa_module._read_native_error()

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        set_on_worker.wait(5)

        c2pa_module._write_no_error_marker()
        marked_on_main.set()
        thread.join(5)

        self.assertEqual(seen.get("worker"), "Io: worker error")


class TestErrorsStillRaiseAfterCleanup(unittest.TestCase):
    """Each surface that lost a _clear_error_state() call still reports."""

    def test_reader_on_garbage_raises(self):
        with self.assertRaises(Error):
            Reader("image/jpeg", io.BytesIO(b"not an image")).json()

    def test_signer_from_info_with_bad_certs_raises(self):
        with self.assertRaises(Error):
            c2pa_module.create_signer_from_info(C2paSignerInfo(
                alg=b"es256",
                sign_cert=b"not a certificate",
                private_key=b"not a key",
                ta_url=b"",
            ))

    def test_ed25519_sign_with_empty_data_raises(self):
        with self.assertRaises(Error):
            c2pa_module.ed25519_sign(b"", "not a key")


class TestConsumeOwnership(unittest.TestCase):
    """Ownership of the native handle across the consuming call paths."""

    def setUp(self):
        self.freed = []
        self._real_free = ManagedResource._free_native_ptr

        def counting_free(ptr):
            self.freed.append(ptr)
            return self._real_free(ptr)

        _patch_free(self, counting_free)

    def test_close_called_during_parallel_call(self):
        """Parallel closes handling.
        """
        resource = Settings()
        spare = Settings()
        replacement = spare._handle
        # Only test should be able to free.
        spare._handle = None
        spare._lifecycle_state = LifecycleState.CLOSED
        self.freed.clear()

        def close_then_swap(handle):
            resource.close()
            return replacement

        resource._consume_and_swap(close_then_swap, "swap: {}")

        self.assertIn(replacement, self.freed)
