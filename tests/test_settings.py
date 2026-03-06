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
from c2pa import Settings

from test_context_base import TestContextAPIs

class TestSettings(TestContextAPIs):

    def test_settings_default_construction(self):
        settings = Settings()
        self.assertTrue(settings.is_valid)
        settings.close()

    def test_settings_set_chaining(self):
        settings = Settings()
        result = (
            settings.set(
                "builder.thumbnail.enabled", "false"
            ).set(
                "builder.thumbnail.enabled", "true"
            )
        )
        self.assertIs(result, settings)
        settings.close()

    def test_settings_from_json(self):
        settings = Settings.from_json(
            '{"builder":{"thumbnail":'
            '{"enabled":false}}}'
        )
        self.assertTrue(settings.is_valid)
        settings.close()

    def test_settings_from_dict(self):
        settings = Settings.from_dict({
            "builder": {
                "thumbnail": {"enabled": False}
            }
        })
        self.assertTrue(settings.is_valid)
        settings.close()

    def test_settings_update_json(self):
        settings = Settings()
        result = settings.update(
            '{"builder":{"thumbnail":'
            '{"enabled":false}}}'
        )
        self.assertIs(result, settings)
        settings.close()

    def test_settings_update_dict(self):
        settings = Settings()
        result = settings.update({
            "builder": {
                "thumbnail": {"enabled": False}
            }
        })
        self.assertIs(result, settings)
        settings.close()

    def test_settings_is_valid_after_close(self):
        settings = Settings()
        settings.close()
        self.assertFalse(settings.is_valid)

    def test_settings_raises_after_close(self):
        settings = Settings()
        settings.close()
        with self.assertRaises(Error):
            settings.set(
                "builder.thumbnail.enabled", "false"
            )



if __name__ == '__main__':
    unittest.main(warnings='ignore')
