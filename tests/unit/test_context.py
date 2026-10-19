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
import shutil
import c2pa.c2pa as c2pa_module
from c2pa import Builder, C2paError as Error, Reader, Settings, Context, ContextProvider
from c2pa.c2pa import LifecycleState
from pathlib import Path
from tests.unit._support import (
    FIXTURES_DIR,
    DEFAULT_TEST_FILE_NAME,
    DEFAULT_TEST_FILE,
    INGREDIENT_TEST_FILE,
    load_test_settings_json,
    TestContextAPIs,
)


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

    def test_settings_update_rejects_nul_in_json_string(self):
        settings = Settings.from_dict({
            "builder": {"thumbnail": {"enabled": True}},
        })
        try:
            with self.assertRaises(Error):
                settings.update(
                    '{"verify": {"verify_after_sign": true}}\x00'
                    '{"builder": {"thumbnail": {"enabled": false}}}')
        finally:
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

    def test_context_builder_with_settings_last_wins(self):
        """The last with_settings call determines the settings used.

        Toggles thumbnails on, off, on, off across four calls.
        The last call disables thumbnails, so the signed manifest
        should have no thumbnail.
        """
        settings_on_1 = Settings.from_dict({
            "builder": {"thumbnail": {"enabled": True}},
        })
        settings_off_1 = Settings.from_dict({
            "builder": {"thumbnail": {"enabled": False}},
        })
        settings_on_2 = Settings.from_dict({
            "builder": {"thumbnail": {"enabled": True}},
        })
        settings_off_2 = Settings.from_dict({
            "builder": {"thumbnail": {"enabled": False}},
        })
        context = (
            Context.builder()
            .with_settings(settings_on_1)
            .with_settings(settings_off_1)
            .with_settings(settings_on_2)
            .with_settings(settings_off_2)
            .build()
        )
        signer = self._ctx_make_signer()
        builder = Builder(self.test_manifest, context)
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
            # Last settings disabled thumbnails
            self.assertIsNone(manifest.get("thumbnail"))
            reader.close()
        builder.close()
        context.close()
        settings_on_1.close()
        settings_off_1.close()
        settings_on_2.close()
        settings_off_2.close()


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
        self.assertEqual(signer._lifecycle_state, LifecycleState.CLOSED)
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
        self.assertEqual(signer._lifecycle_state, LifecycleState.CLOSED)
        context.close()


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

    def test_reader_extensionless_path_with_context_autodetects(self):
        context = Context()
        with tempfile.TemporaryDirectory() as tmp:
            no_ext = os.path.join(tmp, "asset")
            shutil.copyfile(DEFAULT_TEST_FILE, no_ext)
            reader = Reader(no_ext, context=context)
            self.assertIn(DEFAULT_TEST_FILE_NAME, reader.json())
            reader.close()
        context.close()

    def test_reader_format_and_path_with_ctx(self):
        context = Context()
        reader = Reader("image/jpeg", DEFAULT_TEST_FILE, context=context)
        data = reader.json()
        self.assertIsNotNone(data)
        reader.close()
        context.close()

    def test_reader_bare_stream_with_context(self):
        # The bare-stream shift runs before the context branch, so
        # Reader(fh, context=ctx) reads via context with auto-detect.
        context = Context()
        with open(DEFAULT_TEST_FILE, "rb") as file_handle:
            reader = Reader(file_handle, context=context)
            self.assertIn(DEFAULT_TEST_FILE_NAME, reader.json())
            reader.close()
        context.close()

    def test_reader_path_object_with_context(self):
        context = Context()
        reader = Reader(Path(DEFAULT_TEST_FILE), context=context)
        self.assertIn(DEFAULT_TEST_FILE_NAME, reader.json())
        reader.close()
        context.close()

    def test_try_create_format_stream_with_context(self):
        context = Context()
        with open(DEFAULT_TEST_FILE, "rb") as file_handle:
            reader = Reader.try_create(
                "image/jpeg", file_handle, context=context)
            self.assertIsNotNone(reader)
            if reader is not None:
                self.assertIn(DEFAULT_TEST_FILE_NAME, reader.json())
                reader.close()
        context.close()

    def test_try_create_bare_stream_with_context(self):
        context = Context()
        with open(DEFAULT_TEST_FILE, "rb") as file_handle:
            reader = Reader.try_create(file_handle, context=context)
            self.assertIsNotNone(reader)
            if reader is not None:
                self.assertIn(DEFAULT_TEST_FILE_NAME, reader.json())
                reader.close()
        context.close()

    def test_context_only_no_source_raises(self):
        # A context supplies settings, not the asset,
        # so no path/stream is an error rather than open("None").
        context = Context()
        with self.assertRaises(Error) as ctx:
            Reader(context=context)
        self.assertIn("stream", str(ctx.exception).lower())
        context.close()

    def test_reader_with_closed_context_raises(self):
        context = Context()
        context.close()
        with self.assertRaises(Error):
            Reader(DEFAULT_TEST_FILE, context=context)

    def test_with_fragment_on_closed_reader_raises(self):
        context = Context()
        reader = Reader(DEFAULT_TEST_FILE, context=context)
        reader.close()
        with self.assertRaises(Error):
            reader.with_fragment(
                "video/mp4",
                io.BytesIO(b"\x00" * 100),
                io.BytesIO(b"\x00" * 100),
            )
        context.close()

    def test_with_fragment_unsupported_format_raises(self):
        context = Context()
        reader = Reader(DEFAULT_TEST_FILE, context=context)
        with self.assertRaises(Error):
            reader.with_fragment(
                "text/plain",
                io.BytesIO(b"\x00" * 100),
                io.BytesIO(b"\x00" * 100),
            )
        reader.close()
        context.close()

    def test_with_fragment_with_dash_fixtures(self):
        context = Context()
        init_path = os.path.join(FIXTURES_DIR, "dashinit.mp4")
        with open(init_path, "rb") as init_fragment:
            reader = Reader("video/mp4", init_fragment, context=context)
        frag_path = os.path.join(FIXTURES_DIR, "dash1.m4s")
        with open(init_path, "rb") as init_fragment, \
             open(frag_path, "rb") as next_fragment:
            reader.with_fragment("video/mp4", init_fragment, next_fragment)
        reader.close()
        context.close()


class TestSidecarReader(TestContextAPIs):
    """Reader over a detached (sidecar) manifest with a Context"""

    def _make_detached_manifest(self):
        """Sign DEFAULT_TEST_FILE with no-embed, return (asset_bytes,
        manifest_bytes) where manifest_bytes is the "detached" sidecar
        C2PA manifest."""

        signer = self._ctx_make_signer()
        with open(DEFAULT_TEST_FILE, "rb") as f:
            asset_bytes = f.read()
        builder = Builder(self.test_manifest)
        builder.set_no_embed()
        # Output is discarded: with no-embed the asset is unchanged and the
        # manifest is returned by sign().
        manifest_bytes = builder.sign(
            signer, "image/jpeg", io.BytesIO(asset_bytes), io.BytesIO())
        builder.close()
        signer.close()
        self.assertIsInstance(manifest_bytes, bytes)
        self.assertGreater(len(manifest_bytes), 0)
        return asset_bytes, manifest_bytes

    def test_reader_with_manifest_data_and_context(self):
        asset_bytes, manifest_bytes = self._make_detached_manifest()
        context = Context()
        reader = Reader(
            "image/jpeg",
            io.BytesIO(asset_bytes),
            manifest_bytes,
            context=context,
        )
        try:
            data = reader.json()
            self.assertTrue(data)
            self.assertFalse(reader.is_embedded())
            self.assertIn("manifests", json.loads(data))
        finally:
            reader.close()
            context.close()

    def test_reader_manifest_data_context_invalid_manifest_raises(self):
        with open(DEFAULT_TEST_FILE, "rb") as f:
            asset_bytes = f.read()
        context = Context()
        reader = None
        try:
            with self.assertRaises(Error):
                reader = Reader(
                    "image/jpeg",
                    io.BytesIO(asset_bytes),
                    b"not a real manifest",
                    context=context,
                )
            # The consumed-pointer error branch must leave no usable handle.
            if reader is not None:
                self.assertEqual(
                    reader._lifecycle_state, LifecycleState.CLOSED)
                self.assertIsNone(reader._handle)
        finally:
            if reader is not None:
                reader.close()
            context.close()

    def test_reader_manifest_data_context_wrong_type_raises(self):
        with open(DEFAULT_TEST_FILE, "rb") as f:
            asset_bytes = f.read()
        context = Context()
        try:
            # Non-bytes manifest_data must raise TypeError before any native
            # reader handle is allocated (no leak on this path).
            with self.assertRaises(TypeError):
                Reader(
                    "image/jpeg",
                    io.BytesIO(asset_bytes),
                    "manifest as str, not bytes",
                    context=context,
                )
        finally:
            context.close()

    def test_reader_manifest_data_context_use_after_close_raises(self):
        asset_bytes, manifest_bytes = self._make_detached_manifest()
        context = Context()
        reader = Reader(
            "image/jpeg",
            io.BytesIO(asset_bytes),
            manifest_bytes,
            context=context,
        )
        reader.close()
        self.assertEqual(reader._lifecycle_state, LifecycleState.CLOSED)
        with self.assertRaises(Error):
            reader.json()
        # Idempotent close after use-after-close attempt.
        reader.close()
        context.close()

    def test_reader_manifest_data_context_as_context_manager(self):
        asset_bytes, manifest_bytes = self._make_detached_manifest()
        context = Context()
        with Reader(
            "image/jpeg",
            io.BytesIO(asset_bytes),
            manifest_bytes,
            context=context,
        ) as reader:
            self.assertEqual(reader._lifecycle_state, LifecycleState.ACTIVE)
            self.assertTrue(reader.json())
        self.assertEqual(reader._lifecycle_state, LifecycleState.CLOSED)
        context.close()


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
                manifest_bytes = builder.sign(
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
                    builder.sign(
                        "image/jpeg",
                        source_file,
                        dest_file,
                    )
        builder.close()
        context.close()

    def test_sign_file_with_context_signer_no_explicit_signer(self):
        signer = self._ctx_make_signer()
        context = Context(signer=signer)
        builder = Builder(
            self.test_manifest, context=context,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            dest_path = os.path.join(temp_dir, "out.jpg")
            manifest_bytes = builder.sign_file(
                source_path=DEFAULT_TEST_FILE,
                dest_path=dest_path,
            )
            self.assertIsNotNone(manifest_bytes)
            self.assertGreater(len(manifest_bytes), 0)
            reader = Reader(dest_path)
            data = reader.json()
            self.assertIsNotNone(data)
            reader.close()
        builder.close()
        context.close()

    def test_sign_file_no_signer_raises(self):
        context = Context()
        builder = Builder(
            self.test_manifest, context=context,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            dest_path = os.path.join(temp_dir, "out.jpg")
            with self.assertRaises(Error):
                builder.sign_file(
                    source_path=DEFAULT_TEST_FILE,
                    dest_path=dest_path,
                )
        builder.close()
        context.close()

    def test_with_archive_preserves_settings(self):
        """with_archive() preserves the builder's context settings.

        Settings live on the builder's context, not in the archive.
        The archive only carries the manifest definition. This test
        proves that a builder created with no-thumbnail settings
        keeps those settings after loading an archive.
        """
        settings = Settings.from_dict({
            "builder": {
                "thumbnail": {"enabled": False}
            }
        })
        context = Context(settings)
        signer = self._ctx_make_signer()
        builder = Builder(
            self.test_manifest, context,
        )
        archive = io.BytesIO(bytearray())
        builder.to_archive(archive)

        # Context provides the no-thumbnail setting;
        # with_archive only loads the manifest definition.
        builder2 = Builder({}, context)
        builder2.with_archive(archive)
        with (
            open(DEFAULT_TEST_FILE, "rb") as source,
            io.BytesIO(bytearray()) as output,
        ):
            builder2.sign(
                signer, "image/jpeg", source, output,
            )
            output.seek(0)
            reader = Reader(
                "image/jpeg", output, context=Context(),
            )
            manifest = reader.get_active_manifest()
            self.assertIsNone(
                manifest.get("thumbnail"),
                "with_archive should preserve no-thumbnail setting",
            )
            reader.close()
        archive.close()
        builder2.close()
        signer.close()
        context.close()
        settings.close()

    def test_with_archive_replaces_definition(self):
        """with_archive() restores the original builder's
        manifest definition, even if something set on new Builder."""
        context = Context()
        signer = self._ctx_make_signer()
        original_manifest = dict(self.test_manifest)
        original_manifest["title"] = "Original Title"
        builder = Builder(original_manifest, context)
        archive = io.BytesIO(bytearray())
        builder.to_archive(archive)

        replaced_manifest = dict(self.test_manifest)
        replaced_manifest["title"] = "Replaced Title"
        builder2 = Builder(replaced_manifest, context)
        builder2.with_archive(archive)
        with (
            open(DEFAULT_TEST_FILE, "rb") as source,
            io.BytesIO(bytearray()) as output,
        ):
            builder2.sign(
                signer, "image/jpeg", source, output,
            )
            output.seek(0)
            reader = Reader(
                "image/jpeg", output, context=Context(),
            )
            json_data = reader.json()
            self.assertIn("Original Title", json_data)
            self.assertNotIn("Replaced Title", json_data)
            reader.close()
        archive.close()
        builder2.close()
        signer.close()
        context.close()

    def test_with_archive_on_closed_builder_raises(self):
        """with_archive() on a closed builder raises C2paError."""
        context = Context()
        builder = Builder(
            self.test_manifest, context=context,
        )
        archive = io.BytesIO(bytearray())
        builder.to_archive(archive)
        builder.close()
        with self.assertRaises(Error):
            builder.with_archive(archive)
        context.close()

    def test_from_archive_roundtrip(self):
        """from_archive() can't propagate contexts."""
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
        archive = io.BytesIO(bytearray())
        builder.to_archive(archive)

        # from_archive creates a context-free builder
        builder2 = Builder.from_archive(archive)
        with (
            open(DEFAULT_TEST_FILE, "rb") as source,
            io.BytesIO(bytearray()) as output,
        ):
            builder2.sign(
                signer, "image/jpeg", source, output,
            )
            output.seek(0)
            reader = Reader(
                "image/jpeg", output, context=Context(),
            )
            manifest = reader.get_active_manifest()
            # from_archive can't propagate contexts
            self.assertIsNotNone(
                manifest.get("thumbnail"),
                "from_archive should lose settings and generate thumbnail",
            )
            reader.close()
        archive.close()
        builder2.close()
        signer.close()
        context.close()
        settings.close()


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
                builder.sign(
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
        builder = Builder({}, context=context)
        builder.with_archive(archive)
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
        builder = Builder({}, context=context)
        builder.with_archive(archive)
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

    def test_remote_sign_trusted_via_context(self):
        trust_dict = load_test_settings_json()
        settings = Settings.from_dict(trust_dict)
        context = Context(settings=settings)
        signer = self._ctx_make_signer()
        builder = Builder(
            self.test_manifest, context=context,
        )
        builder.set_no_embed()
        with open(DEFAULT_TEST_FILE, "rb") as source:
            with io.BytesIO() as output_buffer:
                manifest_data = builder.sign(
                    signer, "image/jpeg",
                    source, output_buffer,
                )
                output_buffer.seek(0)
                read_buffer = io.BytesIO(
                    output_buffer.getvalue()
                )
                reader = Reader(
                    "image/jpeg", read_buffer,
                    manifest_data, context=context,
                )
                validation_state = (
                    reader.get_validation_state()
                )
                self.assertEqual(
                    validation_state, "Trusted",
                )
                reader.close()
                read_buffer.close()
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
                manifest_bytes = builder.sign(
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


class TestContextProviderContract(unittest.TestCase):
    """The published ContextProvider contract is is_valid plus
    execution_context, and nothing more.
    """

    class _MinimalProvider(ContextProvider):
        """Implements exactly what the abstract base class declares."""

        def __init__(self):
            self._inner = Context(Settings())

        @property
        def is_valid(self):
            return self._inner.is_valid

        @property
        def execution_context(self):
            return self._inner.execution_context

    def test_built_in_context_still_gets_in_flight_protection(self):
        """The compatibility shim must not silently drop the guard for the
        provider that does implement it.
        """
        context = Context(Settings())
        with c2pa_module._context_guard(context):
            self.assertGreater(context._inflight, 0)
