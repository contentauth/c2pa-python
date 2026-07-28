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

"""Lifetime and memory tests for the custom HTTP resolver bindings.

These tests are fully offline. The fixture is built once by signing a real
asset with set_no_embed() + set_remote_url(), which makes the SDK fetch the
manifest over HTTP; the test resolvers then serve those bytes from memory.

Assertion discipline: never assert on exact native error text, because the
wording drifts between native releases. Assert only on the C2paError
(sub)type, the numeric status code, or a substring this test injected
itself. Likewise the signed fixture uses a test certificate that is not in
any trust list, so validation_state is Invalid by design: assert on the
presence of an active manifest, not on validity.
"""

import ctypes
import gc
import io
import json
import os
import sys
import threading
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO_ROOT, "src"))

from c2pa import (  # noqa: E402
    Builder,
    C2paError,
    C2paSignerInfo,
    Context,
    HttpResponse,
    Reader,
    Signer,
)
from c2pa.c2pa import (  # noqa: E402
    HttpResolverCallback,
    _get_native_malloc,
    _lib,
    _parse_header_lines,
)

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
REMOTE_URL = "http://manifests.example.test/m1.c2pa"

MANIFEST_DEFINITION = {
    "claim_generator": "python_test",
    "claim_generator_info": [{"name": "python_test", "version": "0.1"}],
    "format": "image/jpeg",
    "title": "resolver test",
    "assertions": [],
}


def _free_native_buffer(body_ptr):
    """Free a buffer from _get_native_malloc that nothing else took over.

    Only for buffers the SDK never received: once a response body is handed
    to the native layer, it owns it on every return path.
    """
    crt = ctypes.CDLL("ucrtbase") if sys.platform == "win32" \
        else ctypes.CDLL(None)
    crt.free.argtypes = [ctypes.c_void_p]
    crt.free.restype = None
    crt.free(ctypes.cast(body_ptr, ctypes.c_void_p))


def _make_signer():
    """Build an es256 signer.

    ta_url is None, meaning "no timestamp authority": an empty string is
    treated as a URL and fails signing with a Signature error.
    """
    with open(os.path.join(FIXTURES, "es256_certs.pem"), "rb") as f:
        certs = f.read()
    with open(os.path.join(FIXTURES, "es256_private.key"), "rb") as f:
        key = f.read()
    return Signer.from_info(C2paSignerInfo(b"es256", certs, key, None))


class CountingResolver:
    """Resolver serving fixed bytes and recording every request."""

    def __init__(self, manifest, status=200):
        self._manifest = manifest
        self._status = status
        self._lock = threading.Lock()
        self.requests = []

    @property
    def call_count(self):
        with self._lock:
            return len(self.requests)

    def resolve(self, request):
        with self._lock:
            self.requests.append(request)
        return HttpResponse(self._status, self._manifest)


class HttpResolverTestBase(unittest.TestCase):
    """Builds the offline remote-manifest fixture once for all tests."""

    @classmethod
    def setUpClass(cls):
        builder = Builder(MANIFEST_DEFINITION)
        builder.set_no_embed()
        builder.set_remote_url(REMOTE_URL)
        output = io.BytesIO()
        with open(os.path.join(FIXTURES, "A.jpg"), "rb") as source:
            cls.manifest_bytes = builder.sign(
                _make_signer(), "image/jpeg", source, output)
        cls.asset_bytes = output.getvalue()

    def asset_stream(self):
        return io.BytesIO(self.asset_bytes)


class TestResolverInvocation(HttpResolverTestBase):

    def test_resolver_invoked_on_remote_read(self):
        resolver = CountingResolver(self.manifest_bytes)
        with Context.builder().with_resolver(resolver).build() as ctx:
            reader = Reader("image/jpeg", self.asset_stream(), context=ctx)
            manifest_store = json.loads(reader.json())

        self.assertEqual(resolver.call_count, 1)
        request = resolver.requests[0]
        self.assertEqual(request.method, "GET")
        self.assertEqual(request.url, REMOTE_URL)
        # Request data is copied out of native memory, so it stays usable.
        self.assertIsInstance(request.url, str)
        self.assertIsInstance(request.method, str)
        self.assertIsInstance(request.headers, dict)
        self.assertIsInstance(request.body, bytes)
        # A manifest fetch is a GET with no body.
        self.assertEqual(request.body, b"")
        self.assertTrue(manifest_store.get("active_manifest"))

    def test_with_resolver_accepts_callable_and_object(self):
        calls = []

        def resolve_fn(request):
            calls.append(request)
            return HttpResponse(200, self.manifest_bytes)

        with Context.builder().with_resolver(resolve_fn).build() as ctx:
            Reader("image/jpeg", self.asset_stream(), context=ctx)
        self.assertEqual(len(calls), 1)

        resolver = CountingResolver(self.manifest_bytes)
        with Context.builder().with_resolver(resolver).build() as ctx:
            Reader("image/jpeg", self.asset_stream(), context=ctx)
        self.assertEqual(resolver.call_count, 1)

    def test_non_callable_resolver_rejected(self):
        # Rejected while coercing, before any native resolver is created.
        with self.assertRaises(C2paError):
            Context.builder().with_resolver(42).build()

    def test_parse_header_lines(self):
        # The native side sends an empty string, never NULL, when a request
        # carries no headers.
        self.assertEqual(_parse_header_lines(""), {})
        self.assertEqual(
            _parse_header_lines("accept: */*\nx-token: abc\n"),
            {"accept": "*/*", "x-token": "abc"})
        # Repeated names arrive on separate lines; the last one wins.
        self.assertEqual(
            _parse_header_lines("a: 1\na: 2\n"), {"a": "2"})


class TestResolverErrorPaths(HttpResolverTestBase):

    def test_non_200_statuses(self):
        for status in (404, 500, 204, 301):
            with self.subTest(status=status):
                body = b"boom" if status == 500 else b""

                def resolve_fn(request, status=status, body=body):
                    return HttpResponse(status, body)

                with Context.builder().with_resolver(
                        resolve_fn).build() as ctx:
                    with self.assertRaises(C2paError) as caught:
                        Reader("image/jpeg", self.asset_stream(), context=ctx)
                # The status code is a stable signal; the wording is not.
                self.assertIn(str(status), str(caught.exception))

        # The process is still healthy afterwards.
        resolver = CountingResolver(self.manifest_bytes)
        with Context.builder().with_resolver(resolver).build() as ctx:
            Reader("image/jpeg", self.asset_stream(), context=ctx)
        self.assertEqual(resolver.call_count, 1)

    def test_resolver_exception_is_contained(self):
        sentinel = "resolver_sentinel_9f3a"

        def resolve_fn(request):
            raise RuntimeError(sentinel)

        with Context.builder().with_resolver(resolve_fn).build() as ctx:
            with self.assertRaises(C2paError) as caught:
                Reader("image/jpeg", self.asset_stream(), context=ctx)
        # Only assert on text this test injected itself.
        self.assertIn(sentinel, str(caught.exception))

        # The error slot is not sticky: a fresh context still works.
        resolver = CountingResolver(self.manifest_bytes)
        with Context.builder().with_resolver(resolver).build() as ctx:
            reader = Reader("image/jpeg", self.asset_stream(), context=ctx)
        self.assertTrue(json.loads(reader.json()).get("active_manifest"))

    def test_resolver_bad_return_types(self):
        cases = {
            "none": lambda request: None,
            "no_status_attr": lambda request: object(),
            "str_body": lambda request: HttpResponse(200, "not-bytes"),
        }
        for name, resolve_fn in cases.items():
            with self.subTest(case=name):
                with Context.builder().with_resolver(
                        resolve_fn).build() as ctx:
                    # Contained as a typed error, never a crash.
                    with self.assertRaises(C2paError):
                        Reader("image/jpeg", self.asset_stream(), context=ctx)


class TestResolverLifetime(HttpResolverTestBase):

    def test_callback_alive_after_context_close(self):
        """The resolver must survive Context.close().

        The native context is an Arc that Builder clones, so the resolver
        can be called after the Python Context is closed. Regression test
        for keeping _http_resolver_cb alive in _release().
        """
        resolver = CountingResolver(self.manifest_bytes)
        ctx = Context.builder().with_resolver(resolver).build()
        builder = Builder(MANIFEST_DEFINITION, context=ctx)

        ctx.close()
        del ctx
        gc.collect()

        builder.add_ingredient(
            {"title": "remote ingredient"}, "image/jpeg", self.asset_stream())
        self.assertEqual(resolver.call_count, 1)

    def test_context_lifecycle_with_resolver(self):
        resolver = CountingResolver(self.manifest_bytes)
        ctx = Context.builder().with_resolver(resolver).build()
        self.assertTrue(ctx.is_valid)

        ctx.close()
        ctx.close()  # idempotent
        self.assertFalse(ctx.is_valid)
        with self.assertRaises(C2paError):
            ctx._ensure_valid_state()

        with Context.builder().with_resolver(resolver).build() as ctx2:
            self.assertTrue(ctx2.is_valid)

    def test_init_attrs_invariant(self):
        # _init_attrs must define the attribute, so instances built by
        # _wrap_native_handle (which skips __init__) always have it.
        ctx = Context()
        try:
            self.assertIsNone(ctx._http_resolver_cb)
        finally:
            ctx.close()

    def test_shared_context_threaded(self):
        resolver = CountingResolver(self.manifest_bytes)
        errors = []

        def read_once():
            try:
                Reader("image/jpeg", self.asset_stream(), context=ctx)
            except BaseException as e:  # noqa: B036 - report, don't swallow
                errors.append(e)

        with Context.builder().with_resolver(resolver).build() as ctx:
            threads = [threading.Thread(target=read_once) for _ in range(8)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

        self.assertEqual(errors, [])
        self.assertGreaterEqual(resolver.call_count, 8)

    def test_default_paths_untouched(self):
        # No context at all: the built-in resolver path is unchanged.
        with open(os.path.join(FIXTURES, "C.jpg"), "rb") as f:
            reader = Reader("image/jpeg", f)
        self.assertTrue(json.loads(reader.json()).get("active_manifest"))

        # A context with no resolver still takes the c2pa_context_new fast
        # path.
        with Context() as ctx:
            self.assertTrue(ctx.is_valid)


class TestResolverSettingsInteraction(HttpResolverTestBase):

    def test_settings_gate_resolver(self):
        resolver = CountingResolver(self.manifest_bytes)
        ctx = Context.from_dict(
            {"verify": {"remote_manifest_fetch": False}}, resolver=resolver)
        try:
            with self.assertRaises(C2paError):
                Reader("image/jpeg", self.asset_stream(), context=ctx)
            # Settings gate the resolver: it is never consulted.
            self.assertEqual(resolver.call_count, 0)
        finally:
            ctx.close()

    def test_settings_resolver_and_signer_together(self):
        """The full builder path: settings, then resolver, then signer."""
        resolver = CountingResolver(self.manifest_bytes)
        ctx = Context.from_dict(
            {"verify": {"remote_manifest_fetch": True}},
            signer=_make_signer(),
            resolver=resolver)
        try:
            builder = Builder(MANIFEST_DEFINITION, context=ctx)
            builder.add_ingredient(
                {"title": "first"}, "image/jpeg", self.asset_stream())
            builder.add_ingredient(
                {"title": "second"}, "image/jpeg", self.asset_stream())
            self.assertEqual(resolver.call_count, 2)

            output = io.BytesIO()
            with open(os.path.join(FIXTURES, "A.jpg"), "rb") as source:
                builder.sign(_make_signer(), "image/jpeg", source, output)
            self.assertGreater(len(output.getvalue()), 0)

            # Reading the signed output back uses the embedded manifest, so
            # it needs no further fetches.
            before = resolver.call_count
            reader = Reader(
                "image/jpeg", io.BytesIO(output.getvalue()), context=ctx)
            self.assertTrue(json.loads(reader.json()).get("active_manifest"))
            self.assertEqual(resolver.call_count, before)
        finally:
            ctx.close()


def _current_rss_mb():
    """Resident set size of this process, in MB.

    Deliberately not resource.getrusage(): ru_maxrss is a high-water mark,
    so once a peak is reached a later leak stays hidden underneath it. A
    leak sentinel needs the current value.
    """
    with open("/proc/self/statm") as f:
        return int(f.read().split()[1]) * os.sysconf("SC_PAGE_SIZE") / 1048576


def _current_rss_mb_darwin():
    import subprocess
    out = subprocess.run(
        ["ps", "-o", "rss=", "-p", str(os.getpid())],
        capture_output=True, text=True, check=True)
    return int(out.stdout.strip()) / 1024


@unittest.skipUnless(sys.platform in ("linux", "darwin"),
                     "RSS sampling is implemented for Linux and macOS only")
class TestResolverMemory(HttpResolverTestBase):
    """Leak sentinels for the response-body ownership contract.

    The native library frees the response body on BOTH return paths, so the
    binding must hand the buffer over and never free it afterwards. True
    growth is ~0 MB; the threshold only absorbs allocator noise.

    The payload is written into every buffer on purpose. malloc alone does
    not commit pages, so an untouched leak would not move RSS and the
    sentinel would pass while leaking. Calibrated by injecting the
    body_len == 0 leak: 200 iterations of 256 KB grows ~50 MB, well clear
    of the threshold.
    """

    ITERATIONS = 200
    CHUNK = 256 * 1024
    THRESHOLD_MB = 20

    @staticmethod
    def _rss_mb():
        if sys.platform == "darwin":
            return _current_rss_mb_darwin()
        return _current_rss_mb()

    def _assert_rss_stable(self, run_once, label):
        # Warm up so first-call allocations are not counted as growth.
        for _ in range(5):
            run_once()
        gc.collect()
        before = self._rss_mb()
        for _ in range(self.ITERATIONS):
            run_once()
        gc.collect()
        growth = self._rss_mb() - before
        would_leak = self.ITERATIONS * self.CHUNK / 1048576
        self.assertLess(
            growth, self.THRESHOLD_MB,
            f"{label}: RSS grew {growth:.1f} MB "
            f"(a full leak would be ~{would_leak:.0f} MB)")

    def test_repeated_cycles_no_leak(self):
        """Success path: the native side copies the body then frees it."""
        payload = b"x" * self.CHUNK

        def resolve_fn(request):
            # Not a valid manifest, so the read fails; the body is still
            # handed to the native side and must still be freed.
            return HttpResponse(200, payload)

        def run_once():
            with Context.builder().with_resolver(resolve_fn).build() as ctx:
                try:
                    Reader("image/jpeg", self.asset_stream(), context=ctx)
                except C2paError:
                    pass

        self._assert_rss_stable(run_once, "success path")

    def test_valid_manifest_cycles_no_leak(self):
        """Success path with a real manifest, which is fully parsed."""
        resolver = CountingResolver(self.manifest_bytes)

        def run_once():
            with Context.builder().with_resolver(resolver).build() as ctx:
                Reader("image/jpeg", self.asset_stream(), context=ctx)

        self._assert_rss_stable(run_once, "valid manifest")

    def test_error_path_body_is_freed(self):
        """Error path: a body left behind on a non-zero return is freed.

        Uses a raw callback so the buffer is deliberately assigned before
        returning -1, which the binding's own trampoline never does.
        """
        chunk = self.CHUNK
        malloc = _get_native_malloc()

        def raw_callback(_ctx, request_ptr, response_ptr):
            buf = malloc(chunk)
            ctypes.memmove(buf, b"x" * chunk, chunk)
            response = response_ptr.contents
            response.body = ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte))
            response.body_len = chunk
            _lib.c2pa_error_set_last(b"Other: forced resolver failure")
            return -1

        callback_cb = HttpResolverCallback(raw_callback)
        resolver_ptr = _lib.c2pa_http_resolver_create(None, callback_cb)
        self.assertTrue(resolver_ptr)

        builder_ptr = _lib.c2pa_context_builder_new()
        self.assertEqual(
            _lib.c2pa_context_builder_set_http_resolver(
                builder_ptr, resolver_ptr), 0)
        context_ptr = _lib.c2pa_context_builder_build(builder_ptr)
        self.assertTrue(context_ptr)

        wrapped = Context._wrap_native_handle(context_ptr)
        # Keep the thunk alive for as long as the context can call it.
        wrapped._http_resolver_cb = callback_cb
        try:
            def run_once():
                try:
                    Reader("image/jpeg", self.asset_stream(), context=wrapped)
                except C2paError:
                    pass

            self._assert_rss_stable(run_once, "error path")
        finally:
            wrapped.close()

    def test_empty_body_is_null_not_zero_length(self):
        """An empty body must be emitted as NULL, not a zero-length buffer.

        The native side skips its free when body_len == 0, so a non-NULL
        pointer with a zero length is never freed and leaks. Rather than
        infer this from RSS, drive the trampoline directly and inspect the
        response struct it fills in.
        """
        from c2pa.c2pa import (C2paHttpRequest, C2paHttpResponse,
                               _make_http_resolver_trampoline)

        callback_cb = _make_http_resolver_trampoline(
            lambda request: HttpResponse(200, b""))

        request = C2paHttpRequest(
            url=b"http://example.test/m.c2pa", method=b"GET",
            headers=b"", body=None, body_len=0)
        response = C2paHttpResponse(status=0, body=None, body_len=0)

        rc = callback_cb(
            None, ctypes.byref(request), ctypes.byref(response))

        self.assertEqual(rc, 0)
        self.assertEqual(response.status, 200)
        self.assertEqual(response.body_len, 0)
        # The pointer must be NULL, so the native layer has nothing to free.
        self.assertFalse(bool(response.body))

    def test_non_empty_body_is_handed_over(self):
        """A non-empty body arrives as a native buffer of the right size."""
        from c2pa.c2pa import (C2paHttpRequest, C2paHttpResponse,
                               _make_http_resolver_trampoline)

        payload = b"manifest-bytes"
        callback_cb = _make_http_resolver_trampoline(
            lambda request: HttpResponse(200, payload))

        request = C2paHttpRequest(
            url=b"http://example.test/m.c2pa", method=b"GET",
            headers=b"", body=None, body_len=0)
        response = C2paHttpResponse(status=0, body=None, body_len=0)

        rc = callback_cb(
            None, ctypes.byref(request), ctypes.byref(response))
        try:
            self.assertEqual(rc, 0)
            self.assertEqual(response.body_len, len(payload))
            self.assertTrue(bool(response.body))
            self.assertEqual(
                ctypes.string_at(response.body, response.body_len), payload)
        finally:
            # Nothing consumed this buffer, so free it here to keep the test
            # itself leak-free. Never do this once the SDK has taken it.
            if response.body:
                _free_native_buffer(response.body)


if __name__ == "__main__":
    unittest.main()
