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
# each license.import unittest

import os
import sys
import pytest

@pytest.fixture
def fixtures_dir():
    """Provide the path to the fixtures directory."""
    return os.path.join(os.path.dirname(__file__), "fixtures")

pytest.fixture(scope="session", autouse=True)
def setup_c2pa_library():
    """Ensure the src/c2pa library path is added to sys.path."""
    c2pa_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../src/c2pa"))
    if c2pa_path not in sys.path:
        sys.path.insert(0, c2pa_path)