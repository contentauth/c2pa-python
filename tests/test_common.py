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
import json
import unittest
import ctypes
import warnings
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.backends import default_backend
import tempfile
import shutil
import toml
import threading

# Suppress deprecation warnings
warnings.simplefilter("ignore", category=DeprecationWarning)

from c2pa import Builder, C2paError as Error, Reader, C2paSigningAlg as SigningAlg, C2paSignerInfo, Signer, sdk_version, C2paBuilderIntent, C2paDigitalSourceType
from c2pa import Settings, Context, ContextBuilder, ContextProvider
from c2pa.c2pa import Stream, LifecycleState, read_ingredient_file, read_file, sign_file, load_settings, create_signer, create_signer_from_info, ed25519_sign, format_embeddable


PROJECT_PATH = os.getcwd()
FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
DEFAULT_TEST_FILE_NAME = "C.jpg"
INGREDIENT_TEST_FILE_NAME = "A.jpg"
DEFAULT_TEST_FILE = os.path.join(FIXTURES_DIR, DEFAULT_TEST_FILE_NAME)
INGREDIENT_TEST_FILE = os.path.join(FIXTURES_DIR, INGREDIENT_TEST_FILE_NAME)
ALTERNATIVE_INGREDIENT_TEST_FILE = os.path.join(FIXTURES_DIR, "cloud.jpg")


def load_test_settings_json():
    """
    Load default (legacy) trust configuration test settings from a
    JSON config file and return its content as JSON-compatible dict.
    The return value is used to load settings (thread_local) in tests.

    Returns:
        dict: The parsed JSON content as a Python dictionary (JSON-compatible).

    Raises:
        FileNotFoundError: If trust_config_test_settings.json is not found.
        json.JSONDecodeError: If the JSON file is malformed.
    """
    # Locate the file which contains default settings for tests
    tests_dir = os.path.dirname(os.path.abspath(__file__))
    settings_path = os.path.join(tests_dir, 'trust_config_test_settings.json')

    # Load the located default test settings
    with open(settings_path, 'r') as f:
        settings_data = json.load(f)

    return settings_data
