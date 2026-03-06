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

import json
import unittest

from c2pa import Reader
from c2pa import Settings, Context

from test_common import DEFAULT_TEST_FILE, INGREDIENT_TEST_FILE
from test_context_base import TestContextAPIs

class TestReaderWithContext(TestContextAPIs):

    def test_reader_with_default_context(self):
        context = Context()
        with open(DEFAULT_TEST_FILE, "rb") as file_handle:
            reader = Reader("image/jpeg", file_handle, context=context,)
            data = reader.json()
            self.assertIsNotNone(data)
            reader.close()
        context.close()

    def test_reader_with_settings_context(self):
        settings = Settings()
        context = Context(settings)
        with open(DEFAULT_TEST_FILE, "rb") as file_handle:
            reader = Reader("image/jpeg", file_handle, context=context,)
            data = reader.json()
            self.assertIsNotNone(data)
            reader.close()
        context.close()
        settings.close()

    def test_reader_without_context(self):
        with open(DEFAULT_TEST_FILE, "rb") as file_handle:
            reader = Reader("image/jpeg", file_handle)
            data = reader.json()
            self.assertIsNotNone(data)
            reader.close()

    def test_reader_try_create_with_context(self):
        context = Context()
        reader = Reader.try_create(DEFAULT_TEST_FILE, context=context,)
        self.assertIsNotNone(reader)
        data = reader.json()
        self.assertIsNotNone(data)
        reader.close()
        context.close()

    def test_reader_try_create_no_manifest(self):
        context = Context()
        reader = Reader.try_create(INGREDIENT_TEST_FILE, context=context,)
        self.assertIsNone(reader)
        context.close()

    def test_reader_file_path_with_context(self):
        context = Context()
        reader = Reader(DEFAULT_TEST_FILE, context=context,)
        data = reader.json()
        self.assertIsNotNone(data)
        reader.close()
        context.close()

    def test_reader_format_and_path_with_ctx(self):
        context = Context()
        reader = Reader("image/jpeg", DEFAULT_TEST_FILE, context=context)
        data = reader.json()
        self.assertIsNotNone(data)
        reader.close()
        context.close()



if __name__ == '__main__':
    unittest.main(warnings='ignore')
