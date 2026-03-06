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

from c2pa import C2paError as Error
from c2pa import Settings, Context
from c2pa.c2pa import LifecycleState

from test_context_base import TestContextAPIs

class TestContextWithSigner(TestContextAPIs):

    def test_context_with_signer(self):
        signer = self._ctx_make_signer()
        context = Context(signer=signer)
        self.assertTrue(context.is_valid)
        self.assertTrue(context.has_signer)
        context.close()

    def test_context_with_settings_and_signer(self):
        settings = Settings()
        signer = self._ctx_make_signer()
        context = Context(settings, signer)
        self.assertTrue(context.is_valid)
        self.assertTrue(context.has_signer)
        context.close()
        settings.close()

    def test_consumed_signer_is_closed(self):
        signer = self._ctx_make_signer()
        context = Context(signer=signer)
        self.assertEqual(signer._state, LifecycleState.CLOSED)
        context.close()

    def test_consumed_signer_raises_on_use(self):
        signer = self._ctx_make_signer()
        context = Context(signer=signer)
        with self.assertRaises(Error):
            signer._ensure_valid_state()
        context.close()

    def test_context_has_signer_flag(self):
        signer = self._ctx_make_signer()
        context = Context(signer=signer)
        self.assertTrue(context.has_signer)
        context.close()

    def test_context_no_signer_flag(self):
        context = Context()
        self.assertFalse(context.has_signer)
        context.close()

    def test_context_from_json_with_signer(self):
        signer = self._ctx_make_signer()
        context = Context.from_json(
            '{"builder":{"thumbnail":'
            '{"enabled":false}}}',
            signer,
        )
        self.assertTrue(context.has_signer)
        self.assertEqual(signer._state, LifecycleState.CLOSED)
        context.close()



if __name__ == '__main__':
    unittest.main(warnings='ignore')
