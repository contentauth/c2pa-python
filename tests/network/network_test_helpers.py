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

"""Shared helpers for the tests/network resolver reference tests.

These tests exercise a custom HTTP resolver against the real network
(tests/fixtures/cloud.jpg only has a remote manifest, no embedded one).
"""

import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_REPO_ROOT, "src"))

FIXTURES = os.path.join(_REPO_ROOT, "tests", "fixtures")


def skip_if_offline(testcase, resolver, exc):
    """Skip the test iff the resolver itself observed a transport failure.

    resolver must record urllib.error.URLError instances it catches (DNS
    failure, connection refused, timeout) in a `transport_errors` list
    before re-raising. Skipping only on an *observed* transport error --
    rather than sniffing exc's message for substrings like "fetch" or
    "resolver" -- means a real bug in the resolver or the SDK still fails
    the test instead of being silently skipped: a typed error mentioning
    "resolver" (the trampoline's own failure-message prefix) is exactly
    the kind of bug this distinction is meant to catch.
    """
    if resolver.transport_errors:
        testcase.skipTest(
            "needs internet access to fetch the remote manifest for "
            f"tests/fixtures/cloud.jpg: {resolver.transport_errors[-1]}")
    raise exc
