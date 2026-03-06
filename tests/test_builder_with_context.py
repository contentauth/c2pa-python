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
import unittest
import json
import tempfile

from c2pa import Builder, C2paError as Error, Reader
from c2pa import Settings, Context

from test_common import DEFAULT_TEST_FILE
from test_context_base import TestContextAPIs

class TestBuilderWithContext(TestContextAPIs):

    def test_contextual_builder_with_default_context(self):
        context = Context()
        builder = Builder(self.test_manifest, context)
        self.assertIsNotNone(builder)
        builder.close()
        context.close()

    def test_contextual_builder_with_settings_context(self):
        settings = Settings.from_dict({
            "builder": {
                "thumbnail": {"enabled": False}
            }
        })
        context = Context(settings)
        builder = Builder(self.test_manifest, context)
        signer = self._ctx_make_signer()
        with tempfile.TemporaryDirectory() as temp_dir:
            dest_path = os.path.join(temp_dir, "out.jpg")
            with (
                open(DEFAULT_TEST_FILE, "rb") as source_file,
                open(dest_path, "w+b") as dest_file,
            ):
                builder.sign(
                    signer, "image/jpeg", source_file, dest_file,
                )
            reader = Reader(dest_path)
            manifest = reader.get_active_manifest()
            self.assertIsNone(
                manifest.get("thumbnail")
            )
            reader.close()
        builder.close()
        context.close()
        settings.close()

    def test_contextual_builder_from_json_with_context(self):
        context = Context()
        builder = Builder.from_json(self.test_manifest, context)
        self.assertIsNotNone(builder)
        builder.close()
        context.close()

    def test_contextual_builder_sign_context_signer(self):
        signer = self._ctx_make_signer()
        context = Context(signer=signer)
        builder = Builder(
            self.test_manifest, context=context,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            dest_path = os.path.join(temp_dir, "out.jpg")
            with (
                open(DEFAULT_TEST_FILE, "rb") as source_file,
                open(dest_path, "w+b") as dest_file,
            ):
                manifest_bytes = builder.sign_with_context(
                    "image/jpeg",
                    source_file,
                    dest_file,
                )
                self.assertIsNotNone(manifest_bytes)
                self.assertGreater(len(manifest_bytes), 0)
            reader = Reader(dest_path)
            data = reader.json()
            self.assertIsNotNone(data)
            reader.close()
        builder.close()
        context.close()

    def test_contextual_builder_sign_signer_ovverride(self):
        context_signer = self._ctx_make_signer()
        context = Context(signer=context_signer)
        builder = Builder(
            self.test_manifest, context=context,
        )
        explicit_signer = self._ctx_make_signer()
        with tempfile.TemporaryDirectory() as temp_dir:
            dest_path = os.path.join(temp_dir, "out.jpg")
            with (
                open(DEFAULT_TEST_FILE, "rb") as source_file,
                open(dest_path, "w+b") as dest_file,
            ):
                manifest_bytes = builder.sign(
                    explicit_signer,
                    "image/jpeg", source_file, dest_file,
                )
                self.assertIsNotNone(manifest_bytes)
                self.assertGreater(len(manifest_bytes), 0)
        builder.close()
        explicit_signer.close()
        context.close()

    def test_contextual_builder_sign_no_signer_raises(self):
        context = Context()
        builder = Builder(
            self.test_manifest, context=context,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            dest_path = os.path.join(temp_dir, "out.jpg")
            with (
                open(DEFAULT_TEST_FILE, "rb") as source_file,
                open(dest_path, "w+b") as dest_file,
            ):
                with self.assertRaises(Error):
                    builder.sign_with_context(
                        "image/jpeg",
                        source_file,
                        dest_file,
                    )
        builder.close()
        context.close()



if __name__ == '__main__':
    unittest.main(warnings='ignore')
