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

from c2pa import Settings, Context

from test_context_base import TestContextAPIs

class TestContext(TestContextAPIs):

    def test_context_default(self):
        context = Context()
        self.assertTrue(context.is_valid)
        self.assertFalse(context.has_signer)
        context.close()

    def test_context_from_settings(self):
        settings = Settings()
        context = Context(settings)
        self.assertTrue(context.is_valid)
        context.close()
        settings.close()

    def test_context_from_json(self):
        context = Context.from_json(
            '{"builder":{"thumbnail":'
            '{"enabled":false}}}'
        )
        self.assertTrue(context.is_valid)
        context.close()

    def test_context_from_dict(self):
        context = Context.from_dict({
            "builder": {
                "thumbnail": {"enabled": False}
            }
        })
        self.assertTrue(context.is_valid)
        context.close()

    def test_context_context_manager(self):
        with Context() as context:
            self.assertTrue(context.is_valid)

    def test_context_is_valid_after_close(self):
        context = Context()
        context.close()
        self.assertFalse(context.is_valid)



if __name__ == '__main__':
    unittest.main(warnings='ignore')
