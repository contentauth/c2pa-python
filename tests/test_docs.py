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

"""
Tests for documentation examples.
These tests verify that all code examples in the docs/ folder work correctly.
"""

import os
import io
import json
import unittest
import warnings

warnings.filterwarnings("ignore", category=DeprecationWarning)

from c2pa import (
    Builder,
    Reader,
    Signer,
    C2paSignerInfo,
    C2paBuilderIntent,
    C2paDigitalSourceType,
)

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")

ACTIONS_LABELS = {"c2pa.actions", "c2pa.actions.v2"}


def transfer_ingredient_resources(reader, builder, ingredients):
    """Copy binary resources for a list of ingredients from reader to builder."""
    for ingredient in ingredients:
        for key in ("thumbnail", "manifest_data"):
            if key in ingredient:
                uri = ingredient[key]["identifier"]
                buf = io.BytesIO()
                reader.resource_to_stream(uri, buf)
                buf.seek(0)
                builder.add_resource(uri, buf)


def get_active_manifest(manifest_store):
    """Return the active manifest from a parsed manifest store."""
    return manifest_store["manifests"][manifest_store["active_manifest"]]


def find_actions(manifest):
    """Return the actions list from a manifest's assertions, or None."""
    for assertion in manifest["assertions"]:
        if assertion["label"] in ACTIONS_LABELS:
            return assertion["data"]["actions"]
    return None


class BaseDocTest(unittest.TestCase):
    """Base class with shared setUp for doc tests."""

    def setUp(self):
        with open(os.path.join(FIXTURES_DIR, "es256_certs.pem"), "rb") as f:
            self.certs = f.read()
        with open(os.path.join(FIXTURES_DIR, "es256_private.key"), "rb") as f:
            self.key = f.read()

        self.signer = Signer.from_info(C2paSignerInfo(
            alg=b"es256",
            sign_cert=self.certs,
            private_key=self.key,
            ta_url=b"http://timestamp.digicert.com",
        ))

        # A.jpg has no existing manifest
        self.source_file = os.path.join(FIXTURES_DIR, "A.jpg")
        # C.jpg has an existing manifest
        self.signed_file = os.path.join(FIXTURES_DIR, "C.jpg")
        # cloud.jpg - another unsigned file for ingredient use
        self.ingredient_file = os.path.join(FIXTURES_DIR, "cloud.jpg")

    def _sign_to_buffer(self, builder, source_path=None):
        """Sign a builder using source_path (defaults to self.source_file), return BytesIO at position 0."""
        path = source_path or self.source_file
        with open(path, "rb") as source:
            output = io.BytesIO(bytearray())
            builder.sign(self.signer, "image/jpeg", source, output)
        output.seek(0)
        return output

    def _sign_and_read(self, builder, source_path=None):
        """Sign and return the parsed active manifest."""
        output = self._sign_to_buffer(builder, source_path)
        with Reader("image/jpeg", output) as reader:
            return get_active_manifest(json.loads(reader.json()))

    def _create_signed_asset(self):
        """Helper: create a signed JPEG asset in memory."""
        with Builder({
            "claim_generator_info": [{"name": "test_app", "version": "1.0"}],
            "assertions": [
                {
                    "label": "c2pa.actions",
                    "data": {
                        "actions": [
                            {
                                "action": "c2pa.created",
                                "digitalSourceType": "http://cv.iptc.org/newscodes/digitalsourcetype/digitalCreation",
                            }
                        ]
                    },
                }
            ],
        }) as builder:
            return self._sign_to_buffer(builder)


# ============================================================
# Intent docs tests (docs/tbd_intents.md.md)
# ============================================================

class TestIntentDocs(BaseDocTest):
    """Tests for intent documentation examples."""

    def test_create_intent_digital_creation(self):
        """Example: Creating a brand-new digital asset with CREATE intent."""
        with Builder({}) as builder:
            builder.set_intent(
                C2paBuilderIntent.CREATE,
                C2paDigitalSourceType.DIGITAL_CREATION,
            )
            active = self._sign_and_read(builder)

        actions = find_actions(active)
        self.assertIsNotNone(actions)

        created = [a for a in actions if a["action"] == "c2pa.created"]
        self.assertEqual(len(created), 1)
        self.assertEqual(len(active.get("ingredients", [])), 0)

    def test_create_intent_trained_algorithmic_media(self):
        """Example: Marking AI-generated content with CREATE intent."""
        with Builder({}) as builder:
            builder.set_intent(
                C2paBuilderIntent.CREATE,
                C2paDigitalSourceType.TRAINED_ALGORITHMIC_MEDIA,
            )
            active = self._sign_and_read(builder)

        actions = find_actions(active)
        created = [a for a in actions if a["action"] == "c2pa.created"]
        self.assertEqual(len(created), 1)
        self.assertIn("digitalSourceType", created[0])
        self.assertIn("trainedAlgorithmicMedia", created[0]["digitalSourceType"])

    def test_create_intent_with_manifest_definition(self):
        """Example: CREATE intent with additional manifest metadata."""
        manifest_def = {
            "claim_generator_info": [{"name": "my_app", "version": "1.0.0"}],
            "title": "My New Image",
            "assertions": [
                {
                    "label": "cawg.training-mining",
                    "data": {
                        "entries": {
                            "cawg.ai_inference": {"use": "notAllowed"},
                            "cawg.ai_generative_training": {"use": "notAllowed"},
                        }
                    },
                }
            ],
        }

        with Builder(manifest_def) as builder:
            builder.set_intent(
                C2paBuilderIntent.CREATE,
                C2paDigitalSourceType.DIGITAL_CAPTURE,
            )
            active = self._sign_and_read(builder)

        self.assertEqual(active["title"], "My New Image")

    def test_edit_intent(self):
        """Example: Editing an existing asset with EDIT intent."""
        with Builder({}) as builder:
            builder.set_intent(C2paBuilderIntent.EDIT)
            active = self._sign_and_read(builder)

        ingredients = active.get("ingredients", [])
        self.assertEqual(len(ingredients), 1)
        self.assertEqual(ingredients[0]["relationship"], "parentOf")

        actions = find_actions(active)
        opened = [a for a in actions if a["action"] == "c2pa.opened"]
        self.assertEqual(len(opened), 1)
        self.assertIn("ingredients", opened[0].get("parameters", {}))

    def test_edit_intent_with_manual_parent(self):
        """Example: Editing with a manually-added parent ingredient."""
        with Builder({}) as builder:
            builder.set_intent(C2paBuilderIntent.EDIT)

            # Manually add a parent instead of letting the Builder auto-create one
            with open(self.signed_file, "rb") as original:
                builder.add_ingredient(
                    {"title": "Original Photo", "relationship": "parentOf"},
                    "image/jpeg",
                    original,
                )

            # Sign using a different source (the parent was added manually)
            active = self._sign_and_read(builder)

        ingredients = active.get("ingredients", [])
        self.assertEqual(len(ingredients), 1)
        self.assertEqual(ingredients[0]["relationship"], "parentOf")
        self.assertEqual(ingredients[0]["title"], "Original Photo")

        actions = find_actions(active)
        opened = [a for a in actions if a["action"] == "c2pa.opened"]
        self.assertEqual(len(opened), 1)

    def test_edit_intent_with_component_ingredients(self):
        """Example: EDIT intent with auto-parent plus component ingredients."""
        with Builder({
            "assertions": [
                {
                    "label": "c2pa.actions.v2",
                    "data": {
                        "actions": [
                            {
                                "action": "c2pa.placed",
                                "parameters": {"ingredientIds": ["overlay_label"]},
                            }
                        ]
                    },
                }
            ],
        }) as builder:
            builder.set_intent(C2paBuilderIntent.EDIT)

            # Add a component ingredient manually
            with open(self.ingredient_file, "rb") as overlay:
                builder.add_ingredient(
                    {
                        "title": "overlay.png",
                        "relationship": "componentOf",
                        "label": "overlay_label",
                    },
                    "image/jpeg",
                    overlay,
                )

            # The Builder auto-creates a parent from the source stream
            active = self._sign_and_read(builder)

        ingredients = active.get("ingredients", [])
        relationships = {ing["relationship"] for ing in ingredients}
        self.assertIn("parentOf", relationships)
        self.assertIn("componentOf", relationships)

        actions = find_actions(active)
        # Intent auto-added c2pa.opened for the parent
        opened = [a for a in actions if a["action"] == "c2pa.opened"]
        self.assertEqual(len(opened), 1)
        # Our manual c2pa.placed for the component
        placed = [a for a in actions if a["action"] == "c2pa.placed"]
        self.assertEqual(len(placed), 1)

    def test_edit_intent_with_existing_manifest(self):
        """Example: Editing a file that already has a C2PA manifest."""
        with Builder({}) as builder:
            builder.set_intent(C2paBuilderIntent.EDIT)
            output = self._sign_to_buffer(builder, self.signed_file)

        with Reader("image/jpeg", output) as reader:
            manifest_store = json.loads(reader.json())

        self.assertGreater(len(manifest_store["manifests"]), 1)

        active = get_active_manifest(manifest_store)
        ingredients = active.get("ingredients", [])
        self.assertEqual(len(ingredients), 1)
        self.assertEqual(ingredients[0]["relationship"], "parentOf")

    def test_update_intent(self):
        """Example: Non-editorial update with UPDATE intent."""
        initial_output = self._create_signed_asset()

        with Builder({}) as builder:
            builder.set_intent(C2paBuilderIntent.UPDATE)

            final_output = io.BytesIO(bytearray())
            builder.sign(self.signer, "image/jpeg", initial_output, final_output)

        final_output.seek(0)
        with Reader("image/jpeg", final_output) as reader:
            active = get_active_manifest(json.loads(reader.json()))

        ingredients = active.get("ingredients", [])
        self.assertEqual(len(ingredients), 1)
        self.assertEqual(ingredients[0]["relationship"], "parentOf")


# ============================================================
# Selective manifest docs tests (docs/tbd_selective-manifests.md)
# ============================================================

class TestSelectiveManifestDocs(BaseDocTest):
    """Tests for selective manifest documentation examples."""

    def test_reading_existing_manifest(self):
        """Example: Reading an existing manifest with Reader."""
        with open(self.signed_file, "rb") as source:
            with Reader("image/jpeg", source) as reader:
                manifest_store = json.loads(reader.json())
                manifest = get_active_manifest(manifest_store)

                assertions = manifest["assertions"]
                self.assertIsInstance(assertions, list)
                self.assertGreater(len(assertions), 0)

    def test_extracting_binary_resources(self):
        """Example: Extracting binary resources (thumbnail) from a manifest."""
        with open(self.signed_file, "rb") as source:
            with Reader("image/jpeg", source) as reader:
                manifest = get_active_manifest(json.loads(reader.json()))

                if "thumbnail" in manifest:
                    thumbnail_id = manifest["thumbnail"]["identifier"]
                    thumb_stream = io.BytesIO()
                    reader.resource_to_stream(thumbnail_id, thumb_stream)
                    self.assertGreater(thumb_stream.tell(), 0)

    def test_keep_only_specific_ingredients(self):
        """Example: Filtering ingredients to keep only parentOf."""
        # First create an asset with multiple ingredients
        with Builder({
            "claim_generator_info": [{"name": "test_app", "version": "1.0"}],
            "assertions": [
                {
                    "label": "c2pa.actions",
                    "data": {
                        "actions": [
                            {
                                "action": "c2pa.opened",
                                "parameters": {"ingredientIds": ["parent_label"]},
                            },
                            {
                                "action": "c2pa.placed",
                                "parameters": {"ingredientIds": ["component_label"]},
                            },
                        ]
                    },
                }
            ],
        }) as builder:
            with open(self.signed_file, "rb") as parent:
                builder.add_ingredient(
                    {"title": "parent.jpg", "relationship": "parentOf", "label": "parent_label"},
                    "image/jpeg",
                    parent,
                )

            with open(self.ingredient_file, "rb") as component:
                builder.add_ingredient(
                    {"title": "overlay.jpg", "relationship": "componentOf", "label": "component_label"},
                    "image/jpeg",
                    component,
                )

            multi_output = self._sign_to_buffer(builder)

        # Now read it back and filter to keep only parentOf ingredients
        with Reader("image/jpeg", multi_output) as reader:
            manifest_store = json.loads(reader.json())
            active = get_active_manifest(manifest_store)

            kept = [
                ing for ing in active["ingredients"]
                if ing["relationship"] == "parentOf"
            ]
            self.assertEqual(len(kept), 1)

            with Builder({
                "claim_generator_info": [{"name": "test_app", "version": "1.0"}],
                "ingredients": kept,
            }) as new_builder:
                transfer_ingredient_resources(reader, new_builder, kept)

                multi_output.seek(0)
                final_output = io.BytesIO(bytearray())
                new_builder.sign(self.signer, "image/jpeg", multi_output, final_output)

        # Verify only parentOf ingredient remains
        final_output.seek(0)
        with Reader("image/jpeg", final_output) as reader:
            final_active = get_active_manifest(json.loads(reader.json()))
            self.assertTrue(
                all(ing["relationship"] == "parentOf" for ing in final_active.get("ingredients", []))
            )

    def test_keep_only_specific_assertions(self):
        """Example: Filtering assertions to keep only training-mining."""
        with Builder({
            "claim_generator_info": [{"name": "test_app", "version": "1.0"}],
            "assertions": [
                {
                    "label": "c2pa.actions",
                    "data": {
                        "actions": [
                            {
                                "action": "c2pa.created",
                                "digitalSourceType": "http://cv.iptc.org/newscodes/digitalsourcetype/digitalCreation",
                            }
                        ]
                    },
                },
                {
                    "label": "cawg.training-mining",
                    "data": {
                        "entries": {
                            "cawg.ai_inference": {"use": "notAllowed"},
                            "cawg.ai_generative_training": {"use": "notAllowed"},
                        }
                    },
                },
            ],
        }) as builder:
            signed_output = self._sign_to_buffer(builder)

        # Read it back and filter assertions
        with Reader("image/jpeg", signed_output) as reader:
            active = get_active_manifest(json.loads(reader.json()))

            kept = [a for a in active["assertions"] if a["label"] == "cawg.training-mining"]

            with Builder({
                "claim_generator_info": [{"name": "test_app", "version": "1.0"}],
                "assertions": kept,
            }) as new_builder:
                signed_output.seek(0)
                final_output = io.BytesIO(bytearray())
                new_builder.sign(self.signer, "image/jpeg", signed_output, final_output)

        final_output.seek(0)
        with Reader("image/jpeg", final_output) as reader:
            final_active = get_active_manifest(json.loads(reader.json()))
            labels = [a["label"] for a in final_active["assertions"]]
            self.assertIn("cawg.training-mining", labels)

    def test_preserve_provenance_with_add_ingredient(self):
        """Example: Starting fresh while preserving provenance chain."""
        with Builder({
            "claim_generator_info": [{"name": "test_app", "version": "1.0"}],
            "assertions": [],
        }) as new_builder:
            with open(self.signed_file, "rb") as original:
                new_builder.add_ingredient(
                    {"title": "original.jpg", "relationship": "parentOf"},
                    "image/jpeg",
                    original,
                )

            active = self._sign_and_read(new_builder)

        ingredients = active.get("ingredients", [])
        self.assertEqual(len(ingredients), 1)
        self.assertEqual(ingredients[0]["relationship"], "parentOf")

    def test_adding_actions(self):
        """Example: Adding actions to a builder using add_action."""
        with Builder({
            "claim_generator_info": [{"name": "test_app", "version": "1.0"}],
        }) as builder:
            builder.add_action({
                "action": "c2pa.color_adjustments",
                "parameters": {"name": "brightnesscontrast"},
            })
            builder.add_action({
                "action": "c2pa.filtered",
                "parameters": {"name": "A filter"},
                "description": "Filtering applied",
            })

            active = self._sign_and_read(builder)

        actions = find_actions(active)
        self.assertIsNotNone(actions)
        action_types = {a["action"] for a in actions}
        self.assertIn("c2pa.color_adjustments", action_types)
        self.assertIn("c2pa.filtered", action_types)

    def test_linking_action_to_ingredient_with_label(self):
        """Example: Linking an action to an ingredient using label."""
        with Builder({
            "claim_generator_info": [{"name": "test_app", "version": "1.0"}],
            "assertions": [
                {
                    "label": "c2pa.actions.v2",
                    "data": {
                        "actions": [
                            {
                                "action": "c2pa.created",
                                "digitalSourceType": "http://cv.iptc.org/newscodes/digitalsourcetype/digitalCreation",
                            },
                            {
                                "action": "c2pa.placed",
                                "parameters": {"ingredientIds": ["c2pa.ingredient.v3"]},
                            },
                        ]
                    },
                }
            ],
        }) as builder:
            with open(self.ingredient_file, "rb") as photo:
                builder.add_ingredient(
                    {
                        "title": "photo.jpg",
                        "format": "image/jpeg",
                        "relationship": "componentOf",
                        "label": "c2pa.ingredient.v3",
                    },
                    "image/jpeg",
                    photo,
                )

            active = self._sign_and_read(builder)

        self.assertGreater(len(active.get("ingredients", [])), 0)

        actions = find_actions(active)
        placed = [a for a in actions if a["action"] == "c2pa.placed"]
        self.assertEqual(len(placed), 1)
        self.assertIn("ingredients", placed[0].get("parameters", {}))

    def test_linking_multiple_ingredients(self):
        """Example: Linking multiple ingredients to different actions."""
        with Builder({
            "claim_generator_info": [{"name": "test_app", "version": "1.0"}],
            "assertions": [
                {
                    "label": "c2pa.actions.v2",
                    "data": {
                        "actions": [
                            {
                                "action": "c2pa.opened",
                                "digitalSourceType": "http://cv.iptc.org/newscodes/digitalsourcetype/digitalCreation",
                                "parameters": {"ingredientIds": ["c2pa.ingredient.v3_1"]},
                            },
                            {
                                "action": "c2pa.placed",
                                "parameters": {"ingredientIds": ["c2pa.ingredient.v3_2"]},
                            },
                        ]
                    },
                }
            ],
        }) as builder:
            with open(self.signed_file, "rb") as original:
                builder.add_ingredient(
                    {
                        "title": "original.jpg",
                        "format": "image/jpeg",
                        "relationship": "parentOf",
                        "label": "c2pa.ingredient.v3_1",
                    },
                    "image/jpeg",
                    original,
                )

            with open(self.ingredient_file, "rb") as overlay:
                builder.add_ingredient(
                    {
                        "title": "overlay.jpg",
                        "format": "image/jpeg",
                        "relationship": "componentOf",
                        "label": "c2pa.ingredient.v3_2",
                    },
                    "image/jpeg",
                    overlay,
                )

            active = self._sign_and_read(builder)

        ingredients = active.get("ingredients", [])
        self.assertEqual(len(ingredients), 2)
        relationships = {ing["relationship"] for ing in ingredients}
        self.assertEqual(relationships, {"parentOf", "componentOf"})

    def test_reading_linked_ingredients_after_signing(self):
        """Example: Reading back linked ingredients from a signed manifest."""
        with Builder({
            "claim_generator_info": [{"name": "test_app", "version": "1.0"}],
            "assertions": [
                {
                    "label": "c2pa.actions.v2",
                    "data": {
                        "actions": [
                            {
                                "action": "c2pa.placed",
                                "parameters": {"ingredientIds": ["c2pa.ingredient.v3"]},
                            }
                        ]
                    },
                }
            ],
        }) as builder:
            with open(self.ingredient_file, "rb") as photo:
                builder.add_ingredient(
                    {
                        "title": "photo.jpg",
                        "relationship": "componentOf",
                        "label": "c2pa.ingredient.v3",
                    },
                    "image/jpeg",
                    photo,
                )

            output = self._sign_to_buffer(builder)

        # Read back and match actions to ingredients
        with Reader("image/jpeg", output) as reader:
            manifest = get_active_manifest(json.loads(reader.json()))

            label_to_ingredient = {
                ing["label"]: ing for ing in manifest["ingredients"]
            }

            for assertion in manifest["assertions"]:
                if assertion["label"] != "c2pa.actions.v2":
                    continue
                for action in assertion["data"]["actions"]:
                    for ref in action.get("parameters", {}).get("ingredients", []):
                        label = ref["url"].rsplit("/", 1)[-1]
                        self.assertIn(label, label_to_ingredient)

    def test_custom_vendor_parameters_in_actions(self):
        """Example: Using vendor-namespaced parameters in actions."""
        with Builder({
            "claim_generator_info": [{"name": "test_app", "version": "1.0"}],
            "assertions": [
                {
                    "label": "c2pa.actions.v2",
                    "data": {
                        "actions": [
                            {
                                "action": "c2pa.created",
                                "digitalSourceType": "http://cv.iptc.org/newscodes/digitalsourcetype/compositeCapture",
                                "parameters": {
                                    "com.mycompany.tool": "my-editor",
                                    "com.mycompany.session_id": "session-abc-123",
                                },
                            },
                            {
                                "action": "c2pa.placed",
                                "description": "Placed an image",
                                "parameters": {
                                    "com.mycompany.layer_id": "layer-42",
                                    "ingredientIds": ["c2pa.ingredient.v3"],
                                },
                            },
                        ]
                    },
                }
            ],
        }) as builder:
            with open(self.ingredient_file, "rb") as photo:
                builder.add_ingredient(
                    {
                        "title": "photo.jpg",
                        "relationship": "componentOf",
                        "label": "c2pa.ingredient.v3",
                    },
                    "image/jpeg",
                    photo,
                )

            active = self._sign_and_read(builder)

        actions = find_actions(active)
        placed = [a for a in actions if a["action"] == "c2pa.placed"]
        self.assertEqual(len(placed), 1)
        self.assertEqual(placed[0]["parameters"]["com.mycompany.layer_id"], "layer-42")

    def test_archive_round_trip(self):
        """Example: Saving and restoring a Builder via archive."""
        # Step 1: Build a working store and archive it
        with Builder({
            "claim_generator_info": [{"name": "test_app", "version": "1.0"}],
        }) as builder:
            with open(self.source_file, "rb") as ing_a:
                builder.add_ingredient(
                    {"title": "A.jpg", "relationship": "componentOf"},
                    "image/jpeg",
                    ing_a,
                )

            with open(self.ingredient_file, "rb") as ing_b:
                builder.add_ingredient(
                    {"title": "B.jpg", "relationship": "componentOf"},
                    "image/jpeg",
                    ing_b,
                )

            archive_stream = io.BytesIO()
            builder.to_archive(archive_stream)
            self.assertGreater(archive_stream.tell(), 0)

        # Step 2: Read the archive and pick specific ingredients
        archive_stream.seek(0)
        with Reader("application/c2pa", archive_stream) as reader:
            active = get_active_manifest(json.loads(reader.json()))
            ingredients = active["ingredients"]
            self.assertEqual(len(ingredients), 2)

            # Step 3: Create a new Builder with only selected ingredients
            selected = [ing for ing in ingredients if ing["title"] == "A.jpg"]
            self.assertEqual(len(selected), 1)

            with Builder({
                "claim_generator_info": [{"name": "test_app", "version": "1.0"}],
                "ingredients": selected,
            }) as new_builder:
                transfer_ingredient_resources(reader, new_builder, selected)

                final_active = self._sign_and_read(new_builder)

        self.assertEqual(len(final_active.get("ingredients", [])), 1)

    def test_override_ingredient_properties(self):
        """Example: Overriding ingredient properties when adding."""
        with Builder({
            "claim_generator_info": [{"name": "test_app", "version": "1.0"}],
        }) as builder:
            with open(self.signed_file, "rb") as signed:
                builder.add_ingredient(
                    {
                        "title": "my-custom-title.jpg",
                        "relationship": "parentOf",
                        "instance_id": "my-tracking-id:asset-example-id",
                    },
                    "image/jpeg",
                    signed,
                )

            active = self._sign_and_read(builder)

        ingredients = active.get("ingredients", [])
        self.assertEqual(len(ingredients), 1)
        self.assertEqual(ingredients[0]["title"], "my-custom-title.jpg")
        self.assertEqual(ingredients[0]["relationship"], "parentOf")
        self.assertEqual(ingredients[0]["instance_id"], "my-tracking-id:asset-example-id")


if __name__ == "__main__":
    unittest.main()
