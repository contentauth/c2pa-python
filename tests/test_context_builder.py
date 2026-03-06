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

class TestContextBuilder(TestContextAPIs):

    def test_context_builder_default(self):
        context = Context.builder().build()
        self.assertTrue(context.is_valid)
        self.assertFalse(context.has_signer)
        context.close()

    def test_context_builder_with_settings(self):
        settings = Settings()
        context = Context.builder().with_settings(settings).build()
        self.assertTrue(context.is_valid)
        context.close()
        settings.close()

    def test_context_builder_with_signer(self):
        signer = self._ctx_make_signer()
        context = (
            Context.builder()
            .with_signer(signer)
            .build()
        )
        self.assertTrue(context.is_valid)
        self.assertTrue(context.has_signer)
        context.close()

    def test_context_builder_with_settings_and_signer(self):
        settings = Settings()
        signer = self._ctx_make_signer()
        context = (
            Context.builder()
            .with_settings(settings)
            .with_signer(signer)
            .build()
        )
        self.assertTrue(context.is_valid)
        self.assertTrue(context.has_signer)
        context.close()
        settings.close()

    def test_context_builder_chaining_returns_self(self):
        settings = Settings()
        context_builder = Context.builder()
        result = context_builder.with_settings(settings)
        self.assertIs(result, context_builder)
        context = context_builder.build()
        context.close()
        settings.close()



if __name__ == '__main__':
    unittest.main(warnings='ignore')
