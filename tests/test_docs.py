# Copyright 2024 Adobe. All rights reserved.
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

"""
Tests that verify code examples from the documentation actually work.

Each test corresponds to one or more code snippets from the docs/ folder.
The doc file and section are noted in each test's docstring.
"""

import os
import io
import json
import unittest
import tempfile
import warnings

warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", message="load_settings\\(\\) is deprecated")

from c2pa import (  # noqa: E402
    Builder,
    C2paError as Error,
    Reader,
    C2paSigningAlg as SigningAlg,
    C2paSignerInfo,
    Signer,
    Settings,
    Context,
    ContextProvider,
    load_settings,
)


# ── Paths ────────────────────────────────────────────────────

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
SIGNED_IMAGE = os.path.join(FIXTURES_DIR, "C.jpg")       # has C2PA manifest
UNSIGNED_IMAGE = os.path.join(FIXTURES_DIR, "A.jpg")      # no manifest
CERTS_FILE = os.path.join(FIXTURES_DIR, "es256_certs.pem")
KEY_FILE = os.path.join(FIXTURES_DIR, "es256_private.key")
THUMBNAIL_FILE = os.path.join(FIXTURES_DIR, "A_thumbnail.jpg")


def _load_creds():
    """Load test signing credentials."""
    with open(CERTS_FILE, "rb") as f:
        certs = f.read()
    with open(KEY_FILE, "rb") as f:
        key = f.read()
    return certs, key


def _make_signer():
    """Create a fresh Signer for tests."""
    certs, key = _load_creds()
    info = C2paSignerInfo(
        alg=b"es256",
        sign_cert=certs,
        private_key=key,
        ta_url=b"http://timestamp.digicert.com",
    )
    return Signer.from_info(info)


def _manifest_def():
    """Return a basic manifest definition dict."""
    return {
        "claim_generator_info": [{"name": "doc-tests", "version": "0.1.0"}],
        "title": "Doc Test Image",
        "assertions": [],
    }


def _manifest_def_json():
    """Return a basic manifest definition as JSON string."""
    return json.dumps(_manifest_def())


# ═══════════════════════════════════════════════════════════════
# context.md examples
# ═══════════════════════════════════════════════════════════════


class TestContextDocs(unittest.TestCase):
    """Tests for docs/context.md code examples."""

    # -- Creating a Context -------------------------------------------

    def test_context_default(self):
        """context.md § Using SDK default settings"""
        from c2pa import Context

        ctx = Context()  # Uses SDK defaults
        self.assertTrue(ctx.is_valid)
        ctx.close()

    def test_context_from_json(self):
        """context.md § From a JSON string"""
        ctx = Context.from_json('''{
          "verify": {"verify_after_sign": true},
          "builder": {
            "thumbnail": {"enabled": false},
            "claim_generator_info": {"name": "An app", "version": "0.1.0"}
          }
        }''')
        self.assertTrue(ctx.is_valid)
        ctx.close()

    def test_context_from_dict(self):
        """context.md § From a dictionary"""
        ctx = Context.from_dict({
            "verify": {"verify_after_sign": True},
            "builder": {
                "thumbnail": {"enabled": False},
                "claim_generator_info": {"name": "An app", "version": "0.1.0"}
            }
        })
        self.assertTrue(ctx.is_valid)
        ctx.close()

    def test_context_from_settings_object(self):
        """context.md § From a Settings object"""
        from c2pa import Settings, Context

        settings = Settings()
        settings.set("builder.thumbnail.enabled", "false")
        settings.set("verify.verify_after_sign", "true")
        settings.update({
            "builder": {
                "claim_generator_info": {"name": "An app", "version": "0.1.0"}
            }
        })

        ctx = Context(settings=settings)
        self.assertTrue(ctx.is_valid)
        ctx.close()
        settings.close()

    # -- Common configuration patterns --------------------------------

    def test_env_var_config(self):
        """context.md § Configuration from environment variables"""
        import os

        env = os.environ.get("ENVIRONMENT", "dev")

        settings = Settings()
        if env == "production":
            settings.update({"verify": {"strict_v1_validation": True}})
        else:
            settings.update({"verify": {"remote_manifest_fetch": False}})

        ctx = Context(settings=settings)
        self.assertTrue(ctx.is_valid)
        ctx.close()
        settings.close()

    # -- Configuring Reader -------------------------------------------

    def test_reader_with_context_from_file(self):
        """context.md § Reading from a file"""
        ctx = Context.from_dict({
            "verify": {
                "remote_manifest_fetch": False,
                "ocsp_fetch": False
            }
        })

        reader = Reader(SIGNED_IMAGE, context=ctx)
        json_data = reader.json()
        self.assertIsNotNone(json_data)
        reader.close()
        ctx.close()

    def test_reader_with_context_from_stream(self):
        """context.md § Reading from a stream"""
        ctx = Context.from_dict({
            "verify": {
                "remote_manifest_fetch": False,
                "ocsp_fetch": False
            }
        })

        with open(SIGNED_IMAGE, "rb") as stream:
            reader = Reader("image/jpeg", stream, context=ctx)
            json_data = reader.json()
            self.assertIsNotNone(json_data)
            reader.close()
        ctx.close()

    def test_reader_full_validation(self):
        """context.md § Full validation"""
        ctx = Context.from_dict({
            "verify": {
                "verify_after_reading": True,
                "verify_trust": True,
                "verify_timestamp_trust": True,
                "remote_manifest_fetch": True
            }
        })

        reader = Reader(SIGNED_IMAGE, context=ctx)
        self.assertIsNotNone(reader.json())
        reader.close()
        ctx.close()

    def test_reader_offline(self):
        """context.md § Offline operation"""
        ctx = Context.from_dict({
            "verify": {
                "remote_manifest_fetch": False,
                "ocsp_fetch": False
            }
        })

        reader = Reader(SIGNED_IMAGE, context=ctx)
        self.assertIsNotNone(reader.json())
        reader.close()
        ctx.close()

    # -- Configuring Builder ------------------------------------------

    def test_builder_with_context(self):
        """context.md § Basic use"""
        ctx = Context.from_dict({
            "builder": {
                "claim_generator_info": {
                    "name": "An app",
                    "version": "0.1.0"
                },
            }
        })

        manifest_json = _manifest_def()
        builder = Builder(manifest_json, context=ctx)

        signer = _make_signer()
        with tempfile.TemporaryDirectory() as td:
            dest = os.path.join(td, "out.jpg")
            with open(UNSIGNED_IMAGE, "rb") as src, open(dest, "w+b") as dst:
                builder.sign(signer, "image/jpeg", src, dst)
            # Verify output is valid
            reader = Reader(dest)
            self.assertIsNotNone(reader.json())
            reader.close()
        builder.close()
        ctx.close()

    def test_builder_no_thumbnails_context(self):
        """context.md § Controlling thumbnail generation"""
        no_thumbnails_ctx = Context.from_dict({
            "builder": {
                "claim_generator_info": {"name": "Batch Processor"},
                "thumbnail": {"enabled": False}
            }
        })
        self.assertTrue(no_thumbnails_ctx.is_valid)

        mobile_ctx = Context.from_dict({
            "builder": {
                "claim_generator_info": {"name": "Mobile App"},
                "thumbnail": {
                    "enabled": True,
                    "long_edge": 512,
                    "quality": "low",
                    "prefer_smallest_format": True
                }
            }
        })
        self.assertTrue(mobile_ctx.is_valid)

        # Verify no thumbnails
        builder = Builder(_manifest_def(), context=no_thumbnails_ctx)
        signer = _make_signer()
        with tempfile.TemporaryDirectory() as td:
            dest = os.path.join(td, "out.jpg")
            with open(UNSIGNED_IMAGE, "rb") as src, open(dest, "w+b") as dst:
                builder.sign(signer, "image/jpeg", src, dst)
            reader = Reader(dest)
            manifest = reader.get_active_manifest()
            self.assertIsNone(manifest.get("thumbnail"))
            reader.close()
        builder.close()
        no_thumbnails_ctx.close()
        mobile_ctx.close()

    # -- Configuring a signer -----------------------------------------

    def test_signer_on_context(self):
        """context.md § From Settings (signer-on-context)"""
        from c2pa import Context, Settings, Builder, Signer, C2paSignerInfo, C2paSigningAlg

        certs, key = _load_creds()

        signer_info = C2paSignerInfo(
            alg=C2paSigningAlg.ES256,
            sign_cert=certs,
            private_key=key,
            ta_url=b"http://timestamp.digicert.com"
        )
        signer = Signer.from_info(signer_info)

        settings = Settings()
        ctx = Context(settings=settings, signer=signer)
        # signer is now consumed
        self.assertTrue(signer._closed)

        manifest_json = _manifest_def()
        builder = Builder(manifest_json, context=ctx)
        with tempfile.TemporaryDirectory() as td:
            dest = os.path.join(td, "out.jpg")
            with open(UNSIGNED_IMAGE, "rb") as src, open(dest, "w+b") as dst:
                builder.sign(format="image/jpeg", source=src, dest=dst)
            reader = Reader(dest)
            self.assertIsNotNone(reader.json())
            reader.close()
        builder.close()
        ctx.close()
        settings.close()

    def test_explicit_signer(self):
        """context.md § Explicit signer"""
        signer = _make_signer()
        ctx = Context()
        manifest_json = _manifest_def()
        builder = Builder(manifest_json, context=ctx)

        with tempfile.TemporaryDirectory() as td:
            dest = os.path.join(td, "out.jpg")
            with open(UNSIGNED_IMAGE, "rb") as src, open(dest, "w+b") as dst:
                builder.sign(signer, "image/jpeg", src, dst)
        builder.close()
        signer.close()
        ctx.close()

    # -- Context lifetime and usage -----------------------------------

    def test_context_as_context_manager(self):
        """context.md § Context as a context manager"""
        with Context() as ctx:
            reader = Reader(SIGNED_IMAGE, context=ctx)
            json_data = reader.json()
            self.assertIsNotNone(json_data)
            reader.close()

    def test_reusable_contexts(self):
        """context.md § Reusable contexts"""
        settings = Settings()
        ctx = Context(settings=settings)

        manifest1 = _manifest_def()
        manifest2 = _manifest_def()
        manifest2["title"] = "Second Image"

        builder1 = Builder(manifest1, context=ctx)
        builder2 = Builder(manifest2, context=ctx)
        reader = Reader(SIGNED_IMAGE, context=ctx)

        self.assertIsNotNone(reader.json())
        builder1.close()
        builder2.close()
        reader.close()
        ctx.close()
        settings.close()

    def test_multiple_contexts(self):
        """context.md § Multiple contexts for different purposes"""
        dev_settings = Settings.from_dict({
            "builder": {"thumbnail": {"enabled": False}}
        })
        prod_settings = Settings.from_dict({
            "builder": {"thumbnail": {"enabled": True}}
        })
        dev_ctx = Context(settings=dev_settings)
        prod_ctx = Context(settings=prod_settings)

        manifest = _manifest_def()
        dev_builder = Builder(manifest, context=dev_ctx)
        prod_builder = Builder(manifest, context=prod_ctx)

        self.assertIsNotNone(dev_builder)
        self.assertIsNotNone(prod_builder)

        dev_builder.close()
        prod_builder.close()
        dev_ctx.close()
        prod_ctx.close()
        dev_settings.close()
        prod_settings.close()

    def test_context_provider_protocol(self):
        """context.md § ContextProvider protocol"""
        from c2pa import ContextProvider, Context

        ctx = Context()
        self.assertIsInstance(ctx, ContextProvider)  # True
        ctx.close()

    # -- Migrating from load_settings ---------------------------------

    def test_migration_from_load_settings(self):
        """context.md § Migrating from load_settings - new API"""
        from c2pa import Settings, Context, Reader

        settings = Settings.from_dict({"builder": {"thumbnail": {"enabled": False}}})
        ctx = Context(settings=settings)
        reader = Reader(SIGNED_IMAGE, context=ctx)
        self.assertIsNotNone(reader.json())
        reader.close()
        ctx.close()
        settings.close()


# ═══════════════════════════════════════════════════════════════
# settings.md examples
# ═══════════════════════════════════════════════════════════════


class TestSettingsDocs(unittest.TestCase):
    """Tests for docs/settings.md code examples."""

    def test_settings_api(self):
        """settings.md § Settings API"""
        from c2pa import Settings

        # Create with defaults
        settings = Settings()

        # Set individual values by dot-notation path
        settings.set("builder.thumbnail.enabled", "false")

        # Method chaining
        settings.set("builder.thumbnail.enabled", "false").set(
            "verify.verify_after_sign", "true"
        )

        # Dict-like access
        settings["builder.thumbnail.enabled"] = "false"

        settings.close()

        # Create from JSON string
        settings = Settings.from_json('{"builder": {"thumbnail": {"enabled": false}}}')
        settings.close()

        # Create from a dictionary
        settings = Settings.from_dict({"builder": {"thumbnail": {"enabled": False}}})

        # Merge additional configuration
        settings.update({"verify": {"remote_manifest_fetch": True}})
        settings.close()

        # Use as a context manager for automatic cleanup
        with Settings() as settings:
            settings.set("builder.thumbnail.enabled", "false")

    def test_settings_from_json_string(self):
        """settings.md § Settings format - From JSON string"""
        settings = Settings.from_json('{"verify": {"verify_after_sign": true}}')
        self.assertTrue(settings.is_valid)
        settings.close()

    def test_settings_from_dict(self):
        """settings.md § Settings format - From dict"""
        settings = Settings.from_dict({"verify": {"verify_after_sign": True}})
        self.assertTrue(settings.is_valid)
        settings.close()

    def test_context_from_json_string(self):
        """settings.md § Settings format - Context from JSON"""
        ctx = Context.from_json('{"verify": {"verify_after_sign": true}}')
        self.assertTrue(ctx.is_valid)
        ctx.close()

    def test_context_from_dict(self):
        """settings.md § Settings format - Context from dict"""
        ctx = Context.from_dict({"verify": {"verify_after_sign": True}})
        self.assertTrue(ctx.is_valid)
        ctx.close()

    def test_offline_settings(self):
        """settings.md § Offline or air-gapped environments"""
        ctx = Context.from_dict({
            "verify": {
                "remote_manifest_fetch": False,
                "ocsp_fetch": False
            }
        })

        reader = Reader(SIGNED_IMAGE, context=ctx)
        self.assertIsNotNone(reader.json())
        reader.close()
        ctx.close()

    def test_fast_dev_iteration_settings(self):
        """settings.md § Fast development iteration"""
        settings = Settings()
        settings.set("verify.verify_after_reading", "false")
        settings.set("verify.verify_after_sign", "false")

        dev_ctx = Context(settings=settings)
        self.assertTrue(dev_ctx.is_valid)
        dev_ctx.close()
        settings.close()

    def test_strict_validation_settings(self):
        """settings.md § Strict validation"""
        ctx = Context.from_dict({
            "verify": {
                "strict_v1_validation": True,
                "ocsp_fetch": True,
                "verify_trust": True,
                "verify_timestamp_trust": True
            }
        })

        reader = Reader(SIGNED_IMAGE, context=ctx)
        validation_result = reader.json()
        self.assertIsNotNone(validation_result)
        reader.close()
        ctx.close()

    def test_claim_generator_info(self):
        """settings.md § Claim generator information"""
        ctx = Context.from_dict({
            "builder": {
                "claim_generator_info": {
                    "name": "My Photo Editor",
                    "version": "2.1.0",
                    "operating_system": "auto"
                }
            }
        })
        self.assertTrue(ctx.is_valid)
        ctx.close()

    def test_builder_intent_create(self):
        """settings.md § Setting Builder intent - Create"""
        camera_ctx = Context.from_dict({
            "builder": {
                "intent": {"Create": "digitalCapture"},
                "claim_generator_info": {"name": "Camera App", "version": "1.0"}
            }
        })
        self.assertTrue(camera_ctx.is_valid)
        camera_ctx.close()

    def test_builder_intent_edit(self):
        """settings.md § Setting Builder intent - Edit"""
        editor_ctx = Context.from_dict({
            "builder": {
                "intent": {"Edit": None},
                "claim_generator_info": {"name": "Photo Editor", "version": "2.0"}
            }
        })
        self.assertTrue(editor_ctx.is_valid)
        editor_ctx.close()

    def test_update_only_json(self):
        """settings.md - Only JSON format is supported"""
        s = Settings()
        with self.assertRaises(Error):
            s.update("data", format="toml")
        s.close()


# ═══════════════════════════════════════════════════════════════
# faqs.md examples
# ═══════════════════════════════════════════════════════════════


class TestFaqsDocs(unittest.TestCase):
    """Tests for docs/faqs.md code examples."""

    def test_reader_only(self):
        """faqs.md § When to use Reader"""
        ctx = Context()
        reader = Reader(SIGNED_IMAGE, context=ctx)
        json_data = reader.json()                    # inspect the manifest
        self.assertIsNotNone(json_data)

        # Extract a thumbnail
        manifest_store = json.loads(json_data)
        active_uri = manifest_store["active_manifest"]
        manifest = manifest_store["manifests"][active_uri]
        if "thumbnail" in manifest:
            thumb_uri = manifest["thumbnail"]["identifier"]
            thumb_stream = io.BytesIO()
            reader.resource_to_stream(thumb_uri, thumb_stream)
            self.assertGreater(thumb_stream.tell(), 0)

        reader.close()
        ctx.close()

    def test_builder_only(self):
        """faqs.md § When to use a Builder"""
        ctx = Context()
        manifest_json = _manifest_def()
        builder = Builder(manifest_json, context=ctx)

        ingredient_json = json.dumps({"title": "Original"})
        with open(UNSIGNED_IMAGE, "rb") as ingredient:
            builder.add_ingredient(ingredient_json, "image/jpeg", ingredient)

        signer = _make_signer()
        with tempfile.TemporaryDirectory() as td:
            dest = os.path.join(td, "out.jpg")
            with open(UNSIGNED_IMAGE, "rb") as src, open(dest, "w+b") as dst:
                builder.sign(signer, "image/jpeg", src, dst)
            # Verify output was created
            self.assertTrue(os.path.exists(dest))
            reader = Reader(dest)
            self.assertIsNotNone(reader.json())
            reader.close()
        builder.close()
        ctx.close()

    def test_reader_and_builder_together(self):
        """faqs.md § When to use both Reader and Builder together"""
        ctx = Context()

        # Read existing
        reader = Reader(SIGNED_IMAGE, context=ctx)
        parsed = json.loads(reader.json())
        reader.close()

        # "Filter" - just use the parsed data as-is for testing
        # (In a real app you'd filter assertions/ingredients)
        kept = _manifest_def()

        # Create a new Builder with the "filtered" content
        builder = Builder(json.dumps(kept), context=ctx)
        signer = _make_signer()
        with tempfile.TemporaryDirectory() as td:
            dest = os.path.join(td, "out.jpg")
            with open(UNSIGNED_IMAGE, "rb") as src, open(dest, "w+b") as dst:
                builder.sign(signer, "image/jpeg", src, dst)
            self.assertTrue(os.path.exists(dest))
        builder.close()
        ctx.close()

    def test_archive_from_archive_with_context(self):
        """faqs.md § When to use archives"""
        ctx = Context.from_dict({
            "builder": {"thumbnail": {"enabled": False}}
        })

        # Create a builder and archive it
        builder = Builder(_manifest_def(), context=ctx)
        archive = io.BytesIO()
        builder.to_archive(archive)
        builder.close()

        # Restore from archive with context
        archive.seek(0)
        builder = Builder.from_archive(archive, context=ctx)
        self.assertIsNotNone(builder)

        signer = _make_signer()
        with tempfile.TemporaryDirectory() as td:
            dest = os.path.join(td, "out.jpg")
            with open(UNSIGNED_IMAGE, "rb") as src, open(dest, "w+b") as dst:
                builder.sign(signer, "image/jpeg", src, dst)
            # Verify output is readable
            reader = Reader(dest)
            self.assertIsNotNone(reader.json())
            reader.close()
        builder.close()
        ctx.close()


# ═══════════════════════════════════════════════════════════════
# working-stores.md examples
# ═══════════════════════════════════════════════════════════════


class TestWorkingStoresDocs(unittest.TestCase):
    """Tests for docs/working-stores.md code examples."""

    # -- Reading manifest stores from assets --------------------------

    def test_reading_from_file(self):
        """working-stores.md § Reading from a file"""
        from c2pa import Reader

        try:
            reader = Reader(SIGNED_IMAGE)
            manifest_store_json = reader.json()
            self.assertIsNotNone(manifest_store_json)
            reader.close()
        except Exception as e:
            self.fail(f"C2PA Error: {e}")

    def test_reading_from_stream(self):
        """working-stores.md § Reading from a stream"""
        with open(SIGNED_IMAGE, "rb") as stream:
            reader = Reader("image/jpeg", stream)
            manifest_json = reader.json()
            self.assertIsNotNone(manifest_json)
            reader.close()

    def test_reading_with_context(self):
        """working-stores.md § Using Context for configuration"""
        from c2pa import Context, Reader

        ctx = Context.from_dict({
            "verify": {
                "verify_after_sign": True
            }
        })

        reader = Reader(SIGNED_IMAGE, context=ctx)
        manifest_json = reader.json()
        self.assertIsNotNone(manifest_json)
        reader.close()
        ctx.close()

    # -- Using working stores ----------------------------------------

    def test_creating_working_store(self):
        """working-stores.md § Creating a working store"""
        manifest_json = json.dumps({
            "claim_generator_info": [{
                "name": "example-app",
                "version": "0.1.0"
            }],
            "title": "Example asset",
            "assertions": []
        })

        builder = Builder(manifest_json)
        self.assertIsNotNone(builder)
        builder.close()

        # Or with custom context
        ctx = Context.from_dict({
            "builder": {
                "thumbnail": {"enabled": True}
            }
        })
        builder = Builder(manifest_json, context=ctx)
        self.assertIsNotNone(builder)
        builder.close()
        ctx.close()

    def test_modifying_working_store(self):
        """working-stores.md § Modifying a working store"""
        manifest_json = _manifest_def()
        builder = Builder(manifest_json)

        # Add binary resources (like thumbnails)
        with open(THUMBNAIL_FILE, "rb") as thumb:
            builder.add_resource("thumbnail", thumb)

        # Add ingredients (source files)
        ingredient_json = json.dumps({
            "title": "Original asset",
            "relationship": "parentOf"
        })
        with open(UNSIGNED_IMAGE, "rb") as ingredient:
            builder.add_ingredient(ingredient_json, "image/jpeg", ingredient)

        # Add actions
        action_json = {
            "action": "c2pa.created",
            "digitalSourceType": "http://cv.iptc.org/newscodes/digitalsourcetype/trainedAlgorithmicMedia"
        }
        builder.add_action(action_json)

        # Configure embedding behavior
        builder.set_no_embed()

        builder.close()

    def test_working_store_to_manifest_store(self):
        """working-stores.md § From working store to manifest store"""
        certs, private_key = _load_creds()

        from c2pa import Signer, C2paSignerInfo, C2paSigningAlg

        signer_info = C2paSignerInfo(
            alg=C2paSigningAlg.ES256,
            sign_cert=certs,
            private_key=private_key,
            ta_url=b"http://timestamp.digicert.com"
        )
        signer = Signer.from_info(signer_info)

        manifest_json = _manifest_def()
        builder = Builder(manifest_json)

        with tempfile.TemporaryDirectory() as td:
            dest = os.path.join(td, "signed.jpg")
            with open(UNSIGNED_IMAGE, "rb") as src, open(dest, "w+b") as dst:
                builder.sign(signer, "image/jpeg", src, dst)

            # Read it back with Reader
            reader = Reader(dest)
            manifest_store_json = reader.json()
            self.assertIsNotNone(manifest_store_json)
            reader.close()
        builder.close()

    # -- Creating and signing manifests ------------------------------

    def test_creating_signer(self):
        """working-stores.md § Creating a Signer"""
        from c2pa import Signer, C2paSignerInfo, C2paSigningAlg

        certs, private_key = _load_creds()

        signer_info = C2paSignerInfo(
            alg=C2paSigningAlg.ES256,
            sign_cert=certs,
            private_key=private_key,
            ta_url=b"http://timestamp.digicert.com"
        )
        signer = Signer.from_info(signer_info)
        self.assertIsNotNone(signer)
        signer.close()

    def test_signing_asset_streams(self):
        """working-stores.md § Signing an asset"""
        builder = Builder(_manifest_def())
        signer = _make_signer()

        with tempfile.TemporaryDirectory() as td:
            dest = os.path.join(td, "signed.jpg")
            try:
                with open(UNSIGNED_IMAGE, "rb") as src, open(dest, "w+b") as dst:
                    manifest_bytes = builder.sign(signer, "image/jpeg", src, dst)

                self.assertIsNotNone(manifest_bytes)
                self.assertGreater(len(manifest_bytes), 0)

            except Exception as e:
                self.fail(f"Signing failed: {e}")

    def test_signing_with_file_paths(self):
        """working-stores.md § Signing with file paths"""
        builder = Builder(_manifest_def())
        signer = _make_signer()

        with tempfile.TemporaryDirectory() as td:
            dest = os.path.join(td, "signed.jpg")
            manifest_bytes = builder.sign_file(
                UNSIGNED_IMAGE, dest, signer
            )
            self.assertIsNotNone(manifest_bytes)
            self.assertGreater(len(manifest_bytes), 0)

    def test_complete_sign_and_read(self):
        """working-stores.md § Complete example"""
        from c2pa import Builder, Reader, Signer, C2paSignerInfo, C2paSigningAlg

        try:
            # 1. Define manifest for working store
            manifest_json = json.dumps({
                "claim_generator_info": [{"name": "demo-app", "version": "0.1.0"}],
                "title": "Signed image",
                "assertions": []
            })

            # 2. Load credentials
            certs, private_key = _load_creds()

            # 3. Create signer
            signer_info = C2paSignerInfo(
                alg=C2paSigningAlg.ES256,
                sign_cert=certs,
                private_key=private_key,
                ta_url=b"http://timestamp.digicert.com"
            )
            signer = Signer.from_info(signer_info)

            # 4. Create working store (Builder) and sign
            builder = Builder(manifest_json)
            with tempfile.TemporaryDirectory() as td:
                dest = os.path.join(td, "signed.jpg")
                with open(UNSIGNED_IMAGE, "rb") as src, open(dest, "w+b") as dst:
                    builder.sign(signer, "image/jpeg", src, dst)

                # 5. Read back the manifest store
                reader = Reader(dest)
                data = reader.json()
                self.assertIn("manifests", data)
                reader.close()

        except Exception as e:
            self.fail(f"Error: {e}")

    # -- Working with resources ---------------------------------------

    def test_extract_resource_from_manifest(self):
        """working-stores.md § Extracting resources from a manifest store"""
        reader = Reader(SIGNED_IMAGE)
        manifest_store = json.loads(reader.json())

        # Get active manifest
        active_uri = manifest_store["active_manifest"]
        manifest = manifest_store["manifests"][active_uri]

        # Extract thumbnail if it exists
        if "thumbnail" in manifest:
            thumbnail_uri = manifest["thumbnail"]["identifier"]

            with tempfile.NamedTemporaryFile(suffix=".jpg") as f:
                reader.resource_to_stream(thumbnail_uri, f)
                self.assertGreater(f.tell(), 0)

        reader.close()

    def test_add_resource_to_working_store(self):
        """working-stores.md § Adding resources to a working store"""
        manifest_json = _manifest_def()
        builder = Builder(manifest_json)

        # Add resource from a stream
        with open(THUMBNAIL_FILE, "rb") as thumb:
            builder.add_resource("thumbnail", thumb)

        signer = _make_signer()
        with tempfile.TemporaryDirectory() as td:
            dest = os.path.join(td, "signed.jpg")
            with open(UNSIGNED_IMAGE, "rb") as src, open(dest, "w+b") as dst:
                builder.sign(signer, "image/jpeg", src, dst)
        builder.close()

    # -- Working with ingredients -------------------------------------

    def test_add_ingredient_to_working_store(self):
        """working-stores.md § Adding ingredients to a working store"""
        manifest_json = _manifest_def()
        builder = Builder(manifest_json)

        ingredient_json = json.dumps({
            "title": "Original asset",
            "relationship": "parentOf"
        })

        # Add ingredient from a stream
        with open(UNSIGNED_IMAGE, "rb") as ingredient:
            builder.add_ingredient(ingredient_json, "image/jpeg", ingredient)

        signer = _make_signer()
        with tempfile.TemporaryDirectory() as td:
            dest = os.path.join(td, "signed_asset.jpg")
            with open(UNSIGNED_IMAGE, "rb") as src, open(dest, "w+b") as dst:
                builder.sign(signer, "image/jpeg", src, dst)

            # Verify it signed
            reader = Reader(dest)
            data = json.loads(reader.json())
            self.assertIn("manifests", data)
            reader.close()
        builder.close()

    def test_ingredient_relationships(self):
        """working-stores.md § Ingredient relationships"""
        builder = Builder(_manifest_def())

        ingredient_json = json.dumps({
            "title": "Base layer",
            "relationship": "componentOf"
        })

        with open(UNSIGNED_IMAGE, "rb") as ingredient:
            builder.add_ingredient(ingredient_json, "image/jpeg", ingredient)

        builder.close()

    # -- Working with archives ----------------------------------------

    def test_save_working_store_to_archive(self):
        """working-stores.md § Saving a working store to archive"""
        manifest_json = _manifest_def()
        ingredient_json = json.dumps({"title": "Source"})

        builder = Builder(manifest_json)
        with open(THUMBNAIL_FILE, "rb") as thumb:
            builder.add_resource("thumbnail", thumb)
        with open(UNSIGNED_IMAGE, "rb") as ingredient:
            builder.add_ingredient(ingredient_json, "image/jpeg", ingredient)

        # Save working store to archive stream
        archive = io.BytesIO()
        builder.to_archive(archive)
        self.assertGreater(archive.tell(), 0)

        # Verify we can save to a "file"
        archive.seek(0)
        archive_copy = io.BytesIO()
        archive_copy.write(archive.read())
        self.assertGreater(archive_copy.tell(), 0)

        builder.close()

    def test_restore_working_store_from_archive(self):
        """working-stores.md § Restoring a working store from archive"""
        # First create an archive
        builder = Builder(_manifest_def())
        archive = io.BytesIO()
        builder.to_archive(archive)
        builder.close()

        # Restore from stream
        archive.seek(0)
        builder = Builder.from_archive(archive)
        self.assertIsNotNone(builder)

        # Now sign
        signer = _make_signer()
        with tempfile.TemporaryDirectory() as td:
            dest = os.path.join(td, "signed_asset.jpg")
            with open(UNSIGNED_IMAGE, "rb") as src, open(dest, "w+b") as dst:
                builder.sign(signer, "image/jpeg", src, dst)
            self.assertTrue(os.path.exists(dest))
        builder.close()

    def test_restore_with_context_preservation(self):
        """working-stores.md § Restoring with context preservation"""
        ctx = Context.from_dict({
            "builder": {
                "thumbnail": {"enabled": False}
            }
        })

        # Create archive
        builder = Builder(_manifest_def(), context=ctx)
        archive = io.BytesIO()
        builder.to_archive(archive)
        builder.close()

        # Restore from archive with context
        archive.seek(0)
        builder = Builder.from_archive(archive, context=ctx)

        signer = _make_signer()
        with tempfile.TemporaryDirectory() as td:
            dest = os.path.join(td, "signed.jpg")
            with open(UNSIGNED_IMAGE, "rb") as src, open(dest, "w+b") as dst:
                builder.sign(signer, "image/jpeg", src, dst)

            # Verify output is readable
            reader = Reader(dest)
            self.assertIsNotNone(reader.json())
            reader.close()
        builder.close()
        ctx.close()

    def test_two_phase_workflow(self):
        """working-stores.md § Two-phase workflow example"""
        # Phase 1: Prepare manifest
        manifest_json = json.dumps({
            "title": "Artwork draft",
            "assertions": []
        })

        builder = Builder(manifest_json)
        with open(THUMBNAIL_FILE, "rb") as thumb:
            builder.add_resource("thumbnail", thumb)
        with open(UNSIGNED_IMAGE, "rb") as sketch:
            builder.add_ingredient(
                json.dumps({"title": "Sketch"}), "image/jpeg", sketch
            )

        # Save working store as archive
        archive = io.BytesIO()
        builder.to_archive(archive)
        builder.close()

        # Phase 2: Sign the asset
        archive.seek(0)
        builder = Builder.from_archive(archive)

        signer = _make_signer()
        with tempfile.TemporaryDirectory() as td:
            dest = os.path.join(td, "signed_artwork.jpg")
            with open(UNSIGNED_IMAGE, "rb") as src, open(dest, "w+b") as dst:
                builder.sign(signer, "image/jpeg", src, dst)

            self.assertTrue(os.path.exists(dest))
            reader = Reader(dest)
            self.assertIsNotNone(reader.json())
            reader.close()
        builder.close()

    # -- Embedded vs external manifests -------------------------------

    def test_default_embedded_manifest(self):
        """working-stores.md § Default: embedded manifest stores"""
        builder = Builder(_manifest_def())
        signer = _make_signer()

        with tempfile.TemporaryDirectory() as td:
            dest = os.path.join(td, "signed.jpg")
            with open(UNSIGNED_IMAGE, "rb") as src, open(dest, "w+b") as dst:
                builder.sign(signer, "image/jpeg", src, dst)

            # Read it back - manifest store is embedded
            reader = Reader(dest)
            self.assertIsNotNone(reader.json())
            reader.close()

    def test_external_manifest_no_embed(self):
        """working-stores.md § External manifest stores (no embed)"""
        builder = Builder(_manifest_def())
        builder.set_no_embed()

        signer = _make_signer()
        with tempfile.TemporaryDirectory() as td:
            dest = os.path.join(td, "output.jpg")
            with open(UNSIGNED_IMAGE, "rb") as src, open(dest, "w+b") as dst:
                manifest_bytes = builder.sign(signer, "image/jpeg", src, dst)

            # manifest_bytes contains the manifest store
            self.assertIsNotNone(manifest_bytes)
            self.assertGreater(len(manifest_bytes), 0)

            # Save it separately
            c2pa_path = os.path.join(td, "output.c2pa")
            with open(c2pa_path, "wb") as f:
                f.write(manifest_bytes)
            self.assertTrue(os.path.exists(c2pa_path))

            # Asset should NOT have embedded manifest
            with self.assertRaises(Error):
                Reader(dest)

    def test_remote_manifest_url(self):
        """working-stores.md § Remote manifest stores"""
        builder = Builder(_manifest_def())
        builder.set_remote_url("https://example.com/manifests/")

        signer = _make_signer()
        with tempfile.TemporaryDirectory() as td:
            dest = os.path.join(td, "output.jpg")
            with open(UNSIGNED_IMAGE, "rb") as src, open(dest, "w+b") as dst:
                builder.sign(signer, "image/jpeg", src, dst)
            # File should exist
            self.assertTrue(os.path.exists(dest))

    # -- Best practices -----------------------------------------------

    def test_best_practice_context_for_config(self):
        """working-stores.md § Use Context for configuration"""
        ctx = Context.from_dict({
            "verify": {
                "verify_after_sign": True
            },
        })

        builder = Builder(_manifest_def(), context=ctx)
        reader = Reader(SIGNED_IMAGE, context=ctx)

        self.assertIsNotNone(reader.json())
        builder.close()
        reader.close()
        ctx.close()

    def test_best_practice_ingredients_provenance(self):
        """working-stores.md § Use ingredients to build provenance chains"""
        builder = Builder(_manifest_def())

        ingredient_json = json.dumps({
            "title": "Original source",
            "relationship": "parentOf"
        })

        with open(UNSIGNED_IMAGE, "rb") as ingredient:
            builder.add_ingredient(ingredient_json, "image/jpeg", ingredient)

        signer = _make_signer()
        with tempfile.TemporaryDirectory() as td:
            dest = os.path.join(td, "signed.jpg")
            with open(UNSIGNED_IMAGE, "rb") as src, open(dest, "w+b") as dst:
                builder.sign(signer, "image/jpeg", src, dst)
            self.assertTrue(os.path.exists(dest))
        builder.close()


if __name__ == "__main__":
    unittest.main()
