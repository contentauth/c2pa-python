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
from c2pa.c2pa import sdk_version
from tests.unit._support import parse_native_version


class TestC2paSdk(unittest.TestCase):
    def test_sdk_version(self):
        # This test verifies the native libraries used match the expected version.
        self.assertIn(parse_native_version(), sdk_version())
