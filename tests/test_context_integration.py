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
import tempfile

from c2pa import Builder, Reader
from c2pa import Settings, Context

from test_common import DEFAULT_TEST_FILE, load_test_settings_json
from test_context_base import TestContextAPIs

class TestContextIntegration(TestContextAPIs):

    def test_sign_no_thumbnail_via_context(self):
        settings = Settings.from_dict({
            "builder": {
                "thumbnail": {"enabled": False}
            }
        })
        context = Context(settings)
        signer = self._ctx_make_signer()
        builder = Builder(
            self.test_manifest, context=context,
        )
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
        signer.close()
        context.close()
        settings.close()

    def test_sign_read_roundtrip(self):
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
                builder.sign_with_context(
                    "image/jpeg",
                    source_file,
                    dest_file,
                )
            reader = Reader(dest_path)
            data = reader.json()
            self.assertIsNotNone(data)
            self.assertIn("manifests", data)
            reader.close()
        builder.close()
        context.close()

    def test_shared_context_multi_builders(self):
        context = Context()
        signer1 = self._ctx_make_signer()
        signer2 = self._ctx_make_signer()

        builder1 = Builder(self.test_manifest, context)
        builder2 = Builder(self.test_manifest, context)

        with tempfile.TemporaryDirectory() as temp_dir:
            for index, (builder, signer) in enumerate(
                [(builder1, signer1), (builder2, signer2)]
            ):
                dest_path = os.path.join(
                    temp_dir, f"out{index}.jpg"
                )
                with (
                    open(
                        DEFAULT_TEST_FILE, "rb"
                    ) as source_file,
                    open(dest_path, "w+b") as dest_file,
                ):
                    manifest_bytes = builder.sign(
                        signer, "image/jpeg",
                        source_file, dest_file,
                    )
                    self.assertGreater(len(manifest_bytes), 0)

        builder1.close()
        builder2.close()
        signer1.close()
        signer2.close()
        context.close()

    def test_trusted_sign_no_thumbnail_via_context(self):
        trust_dict = load_test_settings_json()
        trust_dict.setdefault("builder", {})["thumbnail"] = {
            "enabled": False,
        }
        settings = Settings.from_dict(trust_dict)
        context = Context(settings)
        signer = self._ctx_make_signer()
        builder = Builder(
            self.test_manifest, context=context,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            dest_path = os.path.join(temp_dir, "out.jpg")
            with (
                open(DEFAULT_TEST_FILE, "rb") as source_file,
                open(dest_path, "w+b") as dest_file,
            ):
                builder.sign(
                    signer, "image/jpeg",
                    source_file, dest_file,
                )
            reader = Reader(dest_path, context=context)
            manifest = reader.get_active_manifest()
            self.assertIsNone(manifest.get("thumbnail"))
            validation_state = reader.get_validation_state()
            self.assertEqual(validation_state, "Trusted")
            reader.close()
        builder.close()
        signer.close()
        context.close()
        settings.close()

    def test_shared_trusted_context_multi_builders(self):
        trust_dict = load_test_settings_json()
        settings = Settings.from_dict(trust_dict)
        context = Context(settings)
        signer1 = self._ctx_make_signer()
        signer2 = self._ctx_make_signer()

        builder1 = Builder(
            self.test_manifest, context=context,
        )
        builder2 = Builder(
            self.test_manifest, context=context,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            for index, (builder, signer) in enumerate(
                [(builder1, signer1), (builder2, signer2)]
            ):
                dest_path = os.path.join(
                    temp_dir, f"out{index}.jpg"
                )
                with (
                    open(
                        DEFAULT_TEST_FILE, "rb"
                    ) as source_file,
                    open(dest_path, "w+b") as dest_file,
                ):
                    manifest_bytes = builder.sign(
                        signer, "image/jpeg",
                        source_file, dest_file,
                    )
                    self.assertGreater(
                        len(manifest_bytes), 0,
                    )
                reader = Reader(
                    dest_path, context=context,
                )
                validation_state = (
                    reader.get_validation_state()
                )
                self.assertEqual(
                    validation_state, "Trusted",
                )
                reader.close()

        builder1.close()
        builder2.close()
        signer1.close()
        signer2.close()
        context.close()
        settings.close()

    def test_read_validation_trusted_via_context(self):
        trust_dict = load_test_settings_json()
        settings = Settings.from_dict(trust_dict)
        context = Context(settings)
        with open(DEFAULT_TEST_FILE, "rb") as f:
            reader = Reader("image/jpeg", f, context=context)
            validation_state = (
                reader.get_validation_state()
            )
            self.assertEqual(
                validation_state, "Trusted",
            )
            reader.close()
        context.close()
        settings.close()

    def test_sign_es256_trusted_via_context(self):
        trust_dict = load_test_settings_json()
        settings = Settings.from_dict(trust_dict)
        context = Context(settings)
        signer = self._ctx_make_signer()
        builder = Builder(
            self.test_manifest, context=context,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            dest_path = os.path.join(temp_dir, "out.jpg")
            with (
                open(DEFAULT_TEST_FILE, "rb") as source,
                open(dest_path, "w+b") as dest,
            ):
                builder.sign(
                    signer, "image/jpeg", source, dest,
                )
            reader = Reader(dest_path, context=context)
            validation_state = (
                reader.get_validation_state()
            )
            self.assertEqual(
                validation_state, "Trusted",
            )
            reader.close()
        builder.close()
        signer.close()
        context.close()
        settings.close()

    def test_sign_ed25519_trusted_via_context(self):
        trust_dict = load_test_settings_json()
        settings = Settings.from_dict(trust_dict)
        context = Context(settings)
        signer = self._ctx_make_ed25519_signer()
        builder = Builder(
            self.test_manifest, context=context,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            dest_path = os.path.join(temp_dir, "out.jpg")
            with (
                open(DEFAULT_TEST_FILE, "rb") as source,
                open(dest_path, "w+b") as dest,
            ):
                builder.sign(
                    signer, "image/jpeg", source, dest,
                )
            reader = Reader(dest_path, context=context)
            validation_state = (
                reader.get_validation_state()
            )
            self.assertEqual(
                validation_state, "Trusted",
            )
            reader.close()
        builder.close()
        signer.close()
        context.close()
        settings.close()

    def test_sign_ps256_trusted_via_context(self):
        trust_dict = load_test_settings_json()
        settings = Settings.from_dict(trust_dict)
        context = Context(settings)
        signer = self._ctx_make_ps256_signer()
        builder = Builder(
            self.test_manifest, context=context,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            dest_path = os.path.join(temp_dir, "out.jpg")
            with (
                open(DEFAULT_TEST_FILE, "rb") as source,
                open(dest_path, "w+b") as dest,
            ):
                builder.sign(
                    signer, "image/jpeg", source, dest,
                )
            reader = Reader(dest_path, context=context)
            validation_state = (
                reader.get_validation_state()
            )
            self.assertEqual(
                validation_state, "Trusted",
            )
            reader.close()
        builder.close()
        signer.close()
        context.close()
        settings.close()

    def test_archive_sign_trusted_via_context(self):
        trust_dict = load_test_settings_json()
        settings = Settings.from_dict(trust_dict)
        context = Context(settings)
        signer = self._ctx_make_signer()
        builder = Builder(
            self.test_manifest, context=context,
        )
        archive = io.BytesIO(bytearray())
        builder.to_archive(archive)
        builder = Builder.from_archive(
            archive, context,
        )
        with (
            open(DEFAULT_TEST_FILE, "rb") as source,
            io.BytesIO(bytearray()) as output,
        ):
            builder.sign(
                signer, "image/jpeg", source, output,
            )
            output.seek(0)
            reader = Reader(
                "image/jpeg", output, context=context,
            )
            validation_state = (
                reader.get_validation_state()
            )
            self.assertEqual(
                validation_state, "Trusted",
            )
            reader.close()
        archive.close()
        builder.close()
        signer.close()
        context.close()
        settings.close()

    def test_archive_sign_with_ingredient_trusted_via_context(self):
        trust_dict = load_test_settings_json()
        settings = Settings.from_dict(trust_dict)
        context = Context(settings)
        signer = self._ctx_make_signer()
        builder = Builder(
            self.test_manifest, context=context,
        )
        archive = io.BytesIO(bytearray())
        builder.to_archive(archive)
        builder = Builder.from_archive(
            archive, context,
        )
        ingredient_json = '{"test": "ingredient"}'
        with open(DEFAULT_TEST_FILE, "rb") as f:
            builder.add_ingredient(
                ingredient_json, "image/jpeg", f,
            )
        with (
            open(DEFAULT_TEST_FILE, "rb") as source,
            io.BytesIO(bytearray()) as output,
        ):
            builder.sign(
                signer, "image/jpeg", source, output,
            )
            output.seek(0)
            reader = Reader(
                "image/jpeg", output, context=context,
            )
            validation_state = (
                reader.get_validation_state()
            )
            self.assertEqual(
                validation_state, "Trusted",
            )
            reader.close()
        archive.close()
        builder.close()
        signer.close()
        context.close()
        settings.close()

    def test_sign_callback_signer_in_ctx(self):
        signer = self._ctx_make_callback_signer()
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
                self.assertGreater(len(manifest_bytes), 0)
            reader = Reader(dest_path)
            data = reader.json()
            self.assertIsNotNone(data)
            reader.close()
        builder.close()
        context.close()



if __name__ == '__main__':
    unittest.main(warnings='ignore')
