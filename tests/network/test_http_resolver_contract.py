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

"""Offline-safe contract tests for the custom HTTP resolver feature.

No network needed, unlike test_http_resolver_debug.py and
test_http_resolver_cache.py: these pin the resolver validation behavior
(eager TypeError, not deferred to Context.build()), dual bare-callable/
HttpResolver support, and that c2pa ships no resolver types at all --
HttpRequest/HttpResponse/HttpResolver here come from the local reference
implementation (tests/network/http_resolver.py), not from c2pa itself.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from http_resolver import HttpResolver, HttpResponse  # noqa: E402

import c2pa  # noqa: E402
import c2pa.c2pa  # noqa: E402


class TestResolverValidation(unittest.TestCase):

    def test_with_resolver_rejects_non_callable_eagerly(self):
        # Raised by with_resolver() itself, not deferred to build().
        with self.assertRaises(TypeError):
            c2pa.Context.builder().with_resolver(42)

    def test_with_resolver_rejects_object_without_resolve_eagerly(self):
        with self.assertRaises(TypeError):
            c2pa.Context.builder().with_resolver(object())

    def test_with_resolver_accepts_bare_callable(self):
        # Bare callables/duck-typed resolvers are fully supported --
        # c2pa never requires an HttpResolver subclass, or any particular
        # class at all.
        builder = c2pa.Context.builder().with_resolver(
            lambda request: HttpResponse(200, b""))
        self.assertIsInstance(builder, c2pa.ContextBuilder)

    def test_with_resolver_accepts_resolve_method_object(self):
        class DuckTypedResolver:
            def resolve(self, request):
                return HttpResponse(200, b"")

        builder = c2pa.Context.builder().with_resolver(DuckTypedResolver())
        self.assertIsInstance(builder, c2pa.ContextBuilder)

    def test_with_resolver_accepts_http_resolver_subclass(self):
        # HttpResolver is the reference implementation's optional base
        # class (tests/network/http_resolver.py) -- not required, but
        # accepted like anything else with a resolve() method.
        class MyResolver(HttpResolver):
            def resolve(self, request):
                return HttpResponse(200, b"")

        builder = c2pa.Context.builder().with_resolver(MyResolver())
        self.assertIsInstance(builder, c2pa.ContextBuilder)

    def test_context_constructor_rejects_invalid_resolver_eagerly(self):
        # Covers the non-builder path: Context(resolver=...) directly.
        with self.assertRaises(TypeError):
            c2pa.Context(resolver="nope")


class TestNoShippedResolverTypes(unittest.TestCase):
    """c2pa ships no HttpRequest/HttpResponse/HttpResolver at all: they
    aren't reachable from c2pa.c2pa, let alone re-exported from the
    top-level c2pa package."""

    def test_resolver_contract_types_not_in_c2pa_c2pa(self):
        for name in ("HttpRequest", "HttpResponse", "HttpResolver"):
            self.assertFalse(
                hasattr(c2pa.c2pa, name),
                f"c2pa.c2pa.{name} should not exist -- the resolver "
                "contract is fully duck-typed, with no shipped type. See "
                "tests/network/http_resolver.py for a reference "
                "implementation.")


if __name__ == "__main__":
    unittest.main()
