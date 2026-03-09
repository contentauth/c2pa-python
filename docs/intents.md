# Using Builder intents

Intents enable validation, add required default actions, and help prevent invalid operations when using a `Builder`. Intents are about the operation (create, edit, update) executed on the source asset.

## Why use intents?

Without intents, the caller must manually construct the correct manifest structure: adding the required actions (`c2pa.created` or `c2pa.opened` as the first action per the specification), setting digital source types, managing ingredients, and linking actions to ingredients. Getting any of this wrong produces a non-compliant manifest.

With intents, the caller declares *what is being done* and the Builder handles the rest:

```py
# Without intents: a caller must manually wire things up, and make sure ingredients are properly linked to actions.
# This is especially important in the case of parentOf ingredient relationships, with the c2pa.opened action
with Builder({
    "assertions": [
        {
            "label": "c2pa.actions",
            "data": {
                "actions": [
                    {
                        "action": "c2pa.created",
                        "digitalSourceType": "http://cv.iptc.org/newscodes/digitalsourcetype/trainedAlgorithmicMedia",
                    }
                ]
            },
        }
    ],
}) as builder:
    with open("source.jpg", "rb") as source, open("output.jpg", "wb") as dest:
        builder.sign(signer, "image/jpeg", source, dest)

# With intents: the Builder generates the actions automatically
with Builder({}) as builder:
    builder.set_intent(
        C2paBuilderIntent.CREATE,
        C2paDigitalSourceType.TRAINED_ALGORITHMIC_MEDIA,
    )
    with open("source.jpg", "rb") as source, open("output.jpg", "wb") as dest:
        builder.sign(signer, "image/jpeg", source, dest)
```

Both ways of writing the code produce the same signed manifest. With intents, the Builder validates the setup and fills in the spec-required structure.

## Setting the intent

There are three ways to set the intent on a `Builder` object instance.

### Using Context

Pass the intent through a `Context` object when creating the `Builder`. This keeps intent configuration alongside other builder settings such as `claim_generator_info` and `thumbnail`.

```py
from c2pa import Context, Builder

ctx = Context.from_dict({
    "builder": {
        "intent": {"Create": "digitalCapture"},
        "claim_generator_info": {"name": "My App", "version": "0.1.0"},
    }
})

with Builder({}, context=ctx) as builder:
    with open("source.jpg", "rb") as source, open("output.jpg", "wb") as dest:
        builder.sign(signer, "image/jpeg", source, dest)
```

The same `Context` can be reused across multiple `Builder` instances, ensuring consistent configuration:

```py
ctx = Context.from_dict({
    "builder": {
        "intent": "edit",
        "claim_generator_info": {"name": "Batch Editor"},
    }
})

for path in image_paths:
    with Builder({}, context=ctx) as builder:
        builder.sign_file(path, output_path(path), signer)
```

### Using `set_intent` on the Builder

Call `set_intent` directly on a `Builder` instance. This is useful for one-off operations or when the intent needs to be determined at runtime:

```py
with Builder({}) as builder:
    builder.set_intent(
        C2paBuilderIntent.CREATE,
        C2paDigitalSourceType.TRAINED_ALGORITHMIC_MEDIA,
    )
    with open("source.jpg", "rb") as source, open("output.jpg", "wb") as dest:
        builder.sign(signer, "image/jpeg", source, dest)
```

### Intent setting precedence

When an intent is configured in multiple places , the most specific setting wins:

```mermaid
flowchart TD
    Check{Was set_intent called
    on the Builder?}
    Check --> |Yes| UseSetIntent["Use set_intent value"]
    Check --> |No| CheckCtx{Was a Context with
    builder.intent provided?}
    CheckCtx --> |Yes| UseCtx["Use Context intent"]
    CheckCtx --> |No| CheckGlobal{Was load_settings called
    with builder.intent?}
    CheckGlobal --> |Yes| UseGlobal["Use global intent
    (deprecated)"]
    CheckGlobal --> |No| NoIntent["No intent set.
    Caller must define actions
    manually in manifest JSON."]
```

If a `set_intent` call is present on the Builder, it takes precedence over all other sources.

## How intents relate to the source stream

The intent operates on the source passed to `sign()`, not on any ingredient added via `add_ingredient`.

The following diagram shows what happens at sign time for each intent:

```mermaid
flowchart LR
    subgraph CREATE
        S1[source stream] --> B1[Builder]
        B1 --> O1[signed output]
        B1 -. adds .-> A1["c2pa.created action
        + digital source type"]
    end
```

```mermaid
flowchart LR
    subgraph EDIT
        S2[source stream] --> B2[Builder]
        B2 --> O2[signed output]
        S2 -. auto-created as .-> P2[parentOf ingredient]
        P2 --> B2
        B2 -. adds .-> A2["c2pa.opened action
        linked to parent"]
    end
```

```mermaid
flowchart LR
    subgraph UPDATE
        S3[source stream] --> B3[Builder]
        B3 --> O3[signed output]
        S3 -. auto-created as .-> P3[parentOf ingredient]
        P3 --> B3
        B3 -. adds .-> A3["c2pa.opened action
        linked to parent"]
        B3 -. restricts .-> R3[content must not change]
    end
```

For **EDIT** and **UPDATE**, the Builder looks at the source stream, and if no `parentOf` ingredient has been added manually, it automatically creates one from that stream (and adds the needed action). The source stream *becomes* the parent ingredient. If a `parentOf` ingredient has already been added manually (via `add_ingredient`), the Builder uses that one instead and does not auto-create one from the source.

### How intent relates to `add_ingredient`

The intent controls what the Builder does with the source stream at sign time. The `add_ingredient` method adds other ingredients explicitly. These are separate concerns.

```mermaid
flowchart TD
    Intent["Intent
    (via Context, set_intent,
    or load_settings)"] --> Q{Intent type?}
    Q --> |CREATE| CreateFlow["No parent allowed
    Source stream is new content"]
    Q --> |EDIT or UPDATE| EditFlow{Was a parentOf ingredient
    added via add_ingredient?}
    EditFlow --> |No| Auto["Builder auto-creates
    parentOf from source stream"]
    EditFlow --> |Yes| Manual["Builder uses the
    manually-added parent"]
    Auto --> Opened["Builder adds c2pa.opened
    action linked to parent"]
    Manual --> Opened
    CreateFlow --> Created["Builder adds c2pa.created
    action + digital source type"]

    AddIngredient["add_ingredient()"] --> IngType{relationship?}
    IngType --> |parentOf| ParentIng["Overrides auto-parent
    for EDIT/UPDATE"]
    IngType --> |componentOf| CompIng["Additional ingredient
    not affected by intent"]
    ParentIng --> EditFlow
```

## Import

Intents and digital source types are provided as enums by two imports.

```py
from c2pa import (
    C2paBuilderIntent,
    C2paDigitalSourceType,
)
```

## Intent types

| Intent | Operation | Parent ingredient | Auto-generated action  |
| --- | --- | --- | --- |
| `CREATE` | Brand-new content          | Must NOT have one                                     | `c2pa.created`                   |
| `EDIT`   | Modifying existing content | Auto-created from the source stream if not provided   | `c2pa.opened` (linked to parent) |
| `UPDATE` | Metadata-only changes      | Auto-created from the source stream if not provided   | `c2pa.opened` (linked to parent) |

## Choosing the right intent

```mermaid
flowchart TD
    Start([Start]) --> HasParent{Does the asset have
    prior history?}
    HasParent --> |No| IsNew[Brand-new content]
    IsNew --> CREATE["Use CREATE
    + C2paDigitalSourceType"]
    HasParent --> |Yes| ContentChanged{Will the content
    itself change?}
    ContentChanged --> |Yes| EDIT[Use EDIT]
    ContentChanged --> |No, metadata only| UPDATE[Use UPDATE]
    ContentChanged --> |Need full manual control| MANUAL["Skip intents.
    Define actions and ingredients
    directly in manifest JSON."]
```

## CREATE intent

Use `CREATE` when the asset has no prior history. A `C2paDigitalSourceType` is required to describe how the asset was produced. The Builder will:

- Add a `c2pa.created` action with the specified digital source type.
- Reject the operation if a `parentOf` ingredient exists.

### Example: New digital creation

Using `Context`:

```py
ctx = Context.from_dict({
    "builder": {"intent": {"Create": "digitalCreation"}}
})

with Builder({}, context=ctx) as builder:
    with open("source.jpg", "rb") as source, open("output.jpg", "wb") as dest:
        builder.sign(signer, "image/jpeg", source, dest)
```

Using `set_intent`:

```py
with Builder({}) as builder:
    builder.set_intent(
        C2paBuilderIntent.CREATE,
        C2paDigitalSourceType.DIGITAL_CREATION,
    )

    with open("source.jpg", "rb") as source, open("output.jpg", "wb") as dest:
        builder.sign(signer, "image/jpeg", source, dest)
```

### Example: Marking AI-generated content

```py
ctx = Context.from_dict({
    "builder": {"intent": {"Create": "trainedAlgorithmicMedia"}}
})

with Builder({}, context=ctx) as builder:
    with open("ai_output.jpg", "rb") as source, open("signed_ai_output.jpg", "wb") as dest:
        builder.sign(signer, "image/jpeg", source, dest)
```

### Example: CREATE with additional manifest metadata

A `Context` and a manifest definition can be combined. The context handles the intent; the manifest definition provides additional metadata and assertions:

```py
ctx = Context.from_dict({
    "builder": {
        "intent": {"Create": "digitalCapture"},
        "claim_generator_info": {"name": "an_app", "version": "0.1.0"},
    }
})

manifest_def = {
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

with Builder(manifest_def, context=ctx) as builder:
    with open("photo.jpg", "rb") as source, open("signed_photo.jpg", "wb") as dest:
        builder.sign(signer, "image/jpeg", source, dest)
```

## EDIT intent

Use `EDIT` when modifying an existing asset. The Builder will:

1. Check if a `parentOf` ingredient has already been added. If not, it automatically creates one from the source stream passed to `sign()`.
2. Add a `c2pa.opened` action linked to the parent ingredient.

No `digital_source_type` parameter is needed.

### Example: Editing an asset

Using `Context`:

```py
ctx = Context.from_dict({"builder": {"intent": "edit"}})

with Builder({}, context=ctx) as builder:
    with open("original.jpg", "rb") as source, open("edited.jpg", "wb") as dest:
        builder.sign(signer, "image/jpeg", source, dest)
```

Using `set_intent`:

```py
with Builder({}) as builder:
    builder.set_intent(C2paBuilderIntent.EDIT)

    # The Builder reads "original.jpg" as the parent ingredient,
    # then writes the new manifest into "edited.jpg"
    with open("original.jpg", "rb") as source, open("edited.jpg", "wb") as dest:
        builder.sign(signer, "image/jpeg", source, dest)
```

The resulting manifest contains one ingredient with `relationship: "parentOf"` pointing to `original.jpg` and a `c2pa.opened` action referencing that ingredient. If the source file already has a C2PA manifest, the ingredient preserves the full provenance chain.

### Example: Editing with a manually-added parent

To control the parent ingredient's metadata (for example, to set a title or use a different source), add it explicitly:

```py
ctx = Context.from_dict({"builder": {"intent": "edit"}})

with Builder({}, context=ctx) as builder:
    with open("original.jpg", "rb") as original:
        builder.add_ingredient(
            {"title": "Original Photo", "relationship": "parentOf"},
            "image/jpeg",
            original,
        )

    with open("canvas.jpg", "rb") as source, open("edited.jpg", "wb") as dest:
        builder.sign(signer, "image/jpeg", source, dest)
```

### Example: Editing with additional component ingredients

A parent ingredient can be combined with component or input ingredients. The intent creates the `c2pa.opened` action for the parent; additional actions can reference components (`componentOf`) or inputs (`inputTo`):

```py
ctx = Context.from_dict({"builder": {"intent": "edit"}})

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
}, context=ctx) as builder:

    # The Builder auto-creates a parent from the source stream
    # and generates a c2pa.opened action for it

    # Add a component ingredient manually
    with open("overlay.png", "rb") as overlay:
        builder.add_ingredient(
            {
                "title": "overlay.png",
                "relationship": "componentOf",
                "label": "overlay_label",
            },
            "image/png",
            overlay,
        )

    with open("original.jpg", "rb") as source, open("composite.jpg", "wb") as dest:
        builder.sign(signer, "image/jpeg", source, dest)
```

## UPDATE intent

Use `UPDATE` for metadata-only changes where the asset content itself is not modified. This is a restricted form of `EDIT`:

- Allows exactly one ingredient (only the parent).
- Does not allow changes to the parent's hashed content.
- Produces a more compact manifest than `EDIT`.

As with `EDIT`, the Builder auto-creates a parent ingredient from the source stream if one is not provided.

### Example: Adding metadata to a signed asset

Using `Context`:

```py
ctx = Context.from_dict({"builder": {"intent": "update"}})

with Builder({}, context=ctx) as builder:
    with open("signed_asset.jpg", "rb") as source, open("updated_asset.jpg", "wb") as dest:
        builder.sign(signer, "image/jpeg", source, dest)
```

Using `set_intent`:

```py
with Builder({}) as builder:
    builder.set_intent(C2paBuilderIntent.UPDATE)

    with open("signed_asset.jpg", "rb") as source, open("updated_asset.jpg", "wb") as dest:
        builder.sign(signer, "image/jpeg", source, dest)
```

## Intent values in settings

When configuring settings, the intent is specified as a string or object in the `builder.intent` field:

| Intent | Settings value | With digital source type |
|--------|---------------|--------------------------|
| Create | `{"Create": "<sourceType>"}` | Required. E.g., `{"Create": "digitalCapture"}` |
| Edit   | `"edit"` | Not applicable |
| Update | `"update"` | Not applicable |

## API reference

### `Builder.set_intent(intent, digital_source_type=C2paDigitalSourceType.EMPTY)`

| Parameter | Type | Description |
|-----------|------|-------------|
| `intent` | `C2paBuilderIntent` | The intent: `CREATE`, `EDIT`, or `UPDATE`. |
| `digital_source_type` | `C2paDigitalSourceType` | Required for `CREATE`. Describes how the asset was made. Defaults to `EMPTY`. |

Raises `C2paError` if the intent cannot be set (for example, a `parentOf` ingredient exists with `CREATE`).
