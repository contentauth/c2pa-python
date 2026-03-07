# Manifests, working stores, and archives

This table summarizes the fundamental entities that you work with when using the CAI SDK.

| Object | Description | Where it is | Primary API |
|--------|-------------|-------------|-------------|
| [**Manifest store**](#manifest-store) | Final signed provenance data. Contains one or more manifests. | Embedded in asset or remotely in cloud | `Reader` class |
| [**Working store**](#working-store) | Editable in-progress manifest. | `Builder` object | `Builder` class |
| [**Archive**](#archive) | Serialized working store | `.c2pa` file/stream | `Builder.to_archive()` / `Builder.from_archive()` |
| [**Resources**](#working-with-resources) | Binary assets referenced by manifest assertions, such as thumbnails or ingredient thumbnails. | In manifest. | `Builder.add_resource()` / `Reader.resource_to_stream()` |
| [**Ingredients**](#working-with-ingredients) | Source materials used to create an asset. | In manifest. | `Builder.add_ingredient()` |

This diagram summarizes the relationships among these entities.

```mermaid
graph TD
    subgraph MS["Manifest Store"]
        subgraph M1["Manifests"]
            R1[Resources]
            I1[Ingredients]
        end
    end

    A[Working Store<br/>Builder object] -->|sign| MS
    A -->|to_archive| C[C2PA Archive<br/>.c2pa file]
    C -->|from_archive or with_archive| A
```

## Key entities

### Manifest store

A _manifest store_ is the data structure that's embedded in (or attached to) a signed asset. It contains one or more manifests that contain provenance data and cryptographic signatures.

**Characteristics:**

- Final, immutable signed data embedded in or attached to an asset.
- Contains one or more manifests (identified by URIs).
- Has exactly one `active_manifest` property pointing to the most recent manifest.
- Read it by using a `Reader` object.

**Example:** When you open a signed JPEG file, the C2PA data embedded in it is the manifest store.

For more information, see:

- [Reading manifest stores from assets](#reading-manifest-stores-from-assets)
- [Creating and signing manifests](#creating-and-signing-manifests)
- [Embedded vs external manifests](#embedded-vs-external-manifests)

### Working store

A _working store_ is a `Builder` object representing an editable, in-progress manifest that has not yet been signed and bound to an asset. Think of it as a manifest in progress, or a manifest being built.

**Characteristics:**

- Editable, mutable state in memory (a Builder object).
- Contains claims, ingredients, and assertions that can be modified.
- Can be saved to a C2PA archive (`.c2pa` JUMBF binary format) for later use.

**Example:** When you create a `Builder` object and add assertions to it, you're dealing with a working store, as it is an "in progress" manifest being built.

For more information, see [Using Working stores](#using-working-stores).

### Archive

A _C2PA archive_ (or just _archive_) contains the serialized bytes of a working store saved to a file or stream (typically a `.c2pa` file). It uses the standard JUMBF `application/c2pa` format.

**Characteristics:**

- Portable serialization of a working store (Builder).
- Save an archive by using `Builder.to_archive()` and restore a full working store from an archive by using `Builder.from_archive()`.
- Useful for separating manifest preparation ("work in progress") from final signing.

For more information, see [Working with archives](#working-with-archives).

## Reading manifest stores from assets

Use the `Reader` class to read manifest stores from signed assets.

### Reading from a file

```py
from c2pa import Reader

try:
    # Without Context
    reader = Reader("signed_image.jpg")
    manifest_store_json = reader.json()
except Exception as e:
    print(f"C2PA Error: {e}")
```

```py
from c2pa import Context, Reader

# With Context (custom validation and trust settings)
ctx = Context.from_dict({
    "verify": {
        "verify_after_sign": True
    }
})
reader = Reader("signed_image.jpg", context=ctx)
manifest_store_json = reader.json()
```

### Reading from a stream

```py
# Without Context
with open("signed_image.jpg", "rb") as stream:
    reader = Reader("image/jpeg", stream)
    manifest_json = reader.json()
```

```py
# With Context
with open("signed_image.jpg", "rb") as stream:
    reader = Reader("image/jpeg", stream, context=ctx)
    manifest_json = reader.json()
```

For full details on `Context` and `Settings`, see [Using Context to configure the SDK](../context.md).

### Understanding Reader output

`Reader.json()` returns a JSON string representing the manifest store. The top-level structure looks like this:

```json
{
  "active_manifest": "urn:uuid:...",
  "manifests": {
    "urn:uuid:...": {
      "claim_generator": "MyApp/1.0",
      "claim_generator_info": [{"name": "MyApp", "version": "1.0"}],
      "title": "signed_image.jpg",
      "assertions": [
        {"label": "c2pa.actions", "data": {"actions": [...]}},
        {"label": "c2pa.hash.data", "data": {...}}
      ],
      "ingredients": [...],
      "signature_info": {
        "alg": "Es256",
        "issuer": "...",
        "time": "2025-01-15T12:00:00Z"
      }
    }
  }
}
```

- `active_manifest`: The URI label of the most recent manifest. This is typically the one to inspect first.
- `manifests`: A dictionary of all manifests in the store, keyed by their URI label. Assets that have been re-signed or that contain ingredient history may have multiple manifests.
- Within each manifest: `assertions` contain the provenance statements, `ingredients` list source materials, and `signature_info` provides details about who signed and when.

The SDK also provides convenience methods to avoid manual JSON parsing:

```py
reader = Reader("signed_image.jpg")

# Get the active manifest directly as a dict
active = reader.get_active_manifest()

# Get a specific manifest by label
manifest = reader.get_manifest("urn:uuid:...")

# Check validation status
state = reader.get_validation_state()
results = reader.get_validation_results()
```

`Reader.detailed_json()` returns a more comprehensive JSON representation with a different structure than `json()`. It is useful when additional details about the manifest internals are needed.

## Using working stores

A **working store** is represented by a `Builder` object. It contains "live" manifest data as you add information to it.

### Creating a working store

```py
import json
from c2pa import Builder

# Without Context
manifest_json = json.dumps({
    "claim_generator_info": [{
        "name": "example-app",
        "version": "0.1.0"
    }],
    "title": "Example asset",
    "assertions": []
})

builder = Builder(manifest_json)
```

```py
from c2pa import Builder, Context

# With Context (custom settings applied)
ctx = Context.from_dict({
    "builder": {
        "thumbnail": {"enabled": True}
    }
})
builder = Builder(manifest_json, context=ctx)
```

### Modifying a working store

Before signing, you can modify the working store (Builder):

```py
import io

# Add binary resources (like thumbnails)
with open("thumbnail.jpg", "rb") as thumb:
    builder.add_resource("thumbnail", thumb)

# Add ingredients (source files)
ingredient_json = json.dumps({
    "title": "Original asset",
    "relationship": "parentOf"
})
with open("source.jpg", "rb") as ingredient:
    builder.add_ingredient(ingredient_json, "image/jpeg", ingredient)

# Add actions
action_json = {
    "action": "c2pa.created",
    "digitalSourceType": "http://cv.iptc.org/newscodes/digitalsourcetype/trainedAlgorithmicMedia"
}
builder.add_action(action_json)

# Configure embedding behavior
builder.set_no_embed()  # Don't embed manifest in asset
builder.set_remote_url("https://example.com/manifests/")
```

### From working store to manifest store

When you sign an asset, the working store (Builder) becomes a manifest store embedded in the output:

```py
from c2pa import Signer, C2paSignerInfo, C2paSigningAlg

# Create a signer
signer_info = C2paSignerInfo(
    alg=C2paSigningAlg.ES256,
    sign_cert=certs,
    private_key=private_key,
    ta_url=b"http://timestamp.digicert.com"
)
signer = Signer.from_info(signer_info)

# Sign the asset - working store becomes a manifest store
with open("source.jpg", "rb") as src, open("signed.jpg", "w+b") as dst:
    builder.sign(signer, "image/jpeg", src, dst)

# Now "signed.jpg" contains a manifest store
# You can read it back with Reader
reader = Reader("signed.jpg")
manifest_store_json = reader.json()
```

## Creating and signing manifests

### Creating a Builder (working store)

```py
# Without Context
builder = Builder(manifest_json)
```

```py
# With Context
ctx = Context.from_dict({
    "builder": {
        "thumbnail": {"enabled": True}
    }
})
builder = Builder(manifest_json, context=ctx)
```

### Creating a Signer

For testing, create a `Signer` with certificates and private key:

```py
from c2pa import Signer, C2paSignerInfo, C2paSigningAlg

# Load credentials
with open("certs.pem", "rb") as f:
    certs = f.read()
with open("private_key.pem", "rb") as f:
    private_key = f.read()

# Create signer
signer_info = C2paSignerInfo(
    alg=C2paSigningAlg.ES256,  # ES256, ES384, ES512, PS256, PS384, PS512, ED25519
    sign_cert=certs,            # Certificate chain in PEM format
    private_key=private_key,    # Private key in PEM format
    ta_url=b"http://timestamp.digicert.com"  # Optional timestamp authority URL
)
signer = Signer.from_info(signer_info)
```

**WARNING**: Never hard-code or directly access private keys in production. Use a Hardware Security Module (HSM) or Key Management Service (KMS).

### Signing an asset

```py
# Without Context (explicit signer)
try:
    with open("source.jpg", "rb") as src, open("signed.jpg", "w+b") as dst:
        manifest_bytes = builder.sign(signer, "image/jpeg", src, dst)
    print("Signed successfully!")
except Exception as e:
    print(f"Signing failed: {e}")
```

```py
# With Context (signer configured in context)
# The Builder must have been created with a Context that has a signer.
try:
    with open("source.jpg", "rb") as src, open("signed.jpg", "w+b") as dst:
        manifest_bytes = builder.sign_with_context("image/jpeg", src, dst)
    print("Signed successfully!")
except Exception as e:
    print(f"Signing failed: {e}")
```

### Signing with file paths

You can also sign using file paths directly:

```py
# Without Context (explicit signer)
manifest_bytes = builder.sign_file("source.jpg", "signed.jpg", signer)
```

```py
# With Context (uses the context's signer when no signer argument is passed)
manifest_bytes = builder.sign_file("source.jpg", "signed.jpg")
```

### Complete example with Context

This code combines the above examples to create, sign, and read a manifest.

```py
import json
from c2pa import Builder, Reader, Context, Signer, C2paSignerInfo, C2paSigningAlg

try:
    # 1. Define manifest
    manifest_json = json.dumps({
        "claim_generator_info": [{"name": "demo-app", "version": "0.1.0"}],
        "title": "Signed image",
        "assertions": []
    })

    # 2. Load credentials and create signer
    with open("certs.pem", "rb") as f:
        certs = f.read()
    with open("private_key.pem", "rb") as f:
        private_key = f.read()

    signer_info = C2paSignerInfo(
        alg=C2paSigningAlg.ES256,
        sign_cert=certs,
        private_key=private_key,
        ta_url=b"http://timestamp.digicert.com"
    )
    signer = Signer.from_info(signer_info)

    # 3. Create context with settings and signer
    ctx = Context.from_dict({
        "builder": {"thumbnail": {"enabled": True}}
    }, signer=signer)

    # 4. Create Builder with context and sign
    builder = Builder(manifest_json, context=ctx)
    with open("source.jpg", "rb") as src, open("signed.jpg", "w+b") as dst:
        builder.sign_with_context("image/jpeg", src, dst)

    print("Asset signed with context settings")

    # 5. Read back the manifest store
    reader = Reader("signed.jpg", context=ctx)
    print(reader.json())

except Exception as e:
    print(f"Error: {e}")
```

### Complete example (legacy, without Context)

This code combines the examples to create, sign, and read a manifest.

```py
import json
from c2pa import Builder, Reader, Signer, C2paSignerInfo, C2paSigningAlg

try:
    # 1. Define manifest for working store
    manifest_json = json.dumps({
        "claim_generator_info": [{"name": "demo-app", "version": "0.1.0"}],
        "title": "Signed image",
        "assertions": []
    })

    # 2. Load credentials
    with open("certs.pem", "rb") as f:
        certs = f.read()
    with open("private_key.pem", "rb") as f:
        private_key = f.read()

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
    with open("source.jpg", "rb") as src, open("signed.jpg", "w+b") as dst:
        builder.sign(signer, "image/jpeg", src, dst)

    print("Asset signed - working store is now a manifest store")

    # 5. Read back the manifest store
    reader = Reader("signed.jpg")
    print(reader.json())

except Exception as e:
    print(f"Error: {e}")
```

## Working with resources

_Resources_ are binary assets referenced by manifest assertions, such as thumbnails or ingredient thumbnails.

C2PA manifest data is not just JSON. A manifest store also contains binary resources (thumbnails, ingredient data, and other embedded files) that are referenced from the JSON metadata by JUMBF URIs. When `reader.json()` is called, the JSON includes URI references (like `"self#jumbf=c2pa.assertions/c2pa.thumbnail.claim.jpeg"`) that point to these binary resources. To retrieve the actual binary data, use `reader.resource_to_stream()` with the URI from the JSON. This separation keeps the JSON lightweight while allowing manifests to carry rich binary content alongside the metadata.

### Understanding resource identifiers

When you add a resource to a working store (Builder), you assign it an identifier string. When the manifest store is created during signing, the SDK automatically converts this to a proper JUMBF URI.

**Resource identifier workflow:**

```mermaid
graph LR
    A[Simple identifier<br/>'thumbnail'] -->|add_resource| B[Working Store<br/>Builder]
    B -->|sign| C[JUMBF URI<br/>'self#jumbf=...']
    C --> D[Manifest Store<br/>in asset]
```

1. **During manifest creation**: You use a string identifier (e.g., `"thumbnail"`, `"thumbnail1"`).
2. **During signing**: The SDK converts these to JUMBF URIs (e.g., `"self#jumbf=c2pa.assertions/c2pa.thumbnail.claim.jpeg"`).
3. **After signing**: The manifest store contains the full JUMBF URI that you use to extract the resource.

### Extracting resources from a manifest store

To extract a resource, you need its JUMBF URI from the manifest store:

```py
import json

reader = Reader("signed_image.jpg")
manifest_store = json.loads(reader.json())

# Get active manifest
active_uri = manifest_store["active_manifest"]
manifest = manifest_store["manifests"][active_uri]

# Extract thumbnail if it exists
if "thumbnail" in manifest:
    # The identifier is the JUMBF URI
    thumbnail_uri = manifest["thumbnail"]["identifier"]
    # Example: "self#jumbf=c2pa.assertions/c2pa.thumbnail.claim.jpeg"

    # Extract to a stream
    with open("thumbnail.jpg", "wb") as f:
        reader.resource_to_stream(thumbnail_uri, f)
    print("Thumbnail extracted")
```

### Adding resources to a working store

When building a manifest, you add resources using identifiers. The SDK will reference these in your manifest JSON and convert them to JUMBF URIs during signing.

```py
builder = Builder(manifest_json)

# Add resource from a stream
with open("thumbnail.jpg", "rb") as thumb:
    builder.add_resource("thumbnail", thumb)

# Sign: the "thumbnail" identifier becomes a JUMBF URI in the manifest store
with open("source.jpg", "rb") as src, open("signed.jpg", "w+b") as dst:
    builder.sign(signer, "image/jpeg", src, dst)
```

## Working with ingredients

### Why ingredients matter

Ingredients are how C2PA tracks the history of content through edits, compositions, and transformations to build a content provenance chain represented by the manifest store. Adding an ingredient to a manifest creates a verifiable link from the current asset back to its source material. This builds a **provenance chain**: original photo, then edited version, then composite, then published asset, etc.

The `relationship` field describes how the source (ingredient) was used: `"parentOf"` for a direct edit, `"componentOf"` for an element composited into a larger work, or `"inputTo"` for a general input. This lets verifiers understand not just what the sources were, but how they contributed to the final asset.

### Overview

Ingredients represent source materials used to create an asset, preserving the provenance chain. Ingredients themselves can be turned into ingredient archives (`.c2pa`). An ingredient archive is a serialized `Builder` with _exactly one and only one_ ingredient. Once archived with only one ingredient, the Builder archive is an ingredient archive. Such ingredient archives can be used as ingredient in other working stores, as an ingredient archive can be added back directly to a working store (no un-archiving of the ingredient needed, use `application/c2pa` format when adding an ingredient archive to a Builder instance).

### Adding ingredients to a working store

When creating a manifest, add ingredients to preserve the provenance chain:

```py
builder = Builder(manifest_json)

# Define ingredient metadata
ingredient_json = json.dumps({
    "title": "Original asset",
    "relationship": "parentOf"
})

# Add ingredient from a stream
with open("source.jpg", "rb") as ingredient:
    builder.add_ingredient(ingredient_json, "image/jpeg", ingredient)

# Sign: ingredients become part of the manifest store
with open("new_asset.jpg", "rb") as src, open("signed_asset.jpg", "w+b") as dst:
    builder.sign(signer, "image/jpeg", src, dst)
```

### Ingredient relationships

Specify the relationship between the ingredient and the current asset:

| Relationship | Meaning |
|--------------|---------|
| `parentOf` | The ingredient is a direct parent of this asset |
| `componentOf` | The ingredient is a component used in this asset |
| `inputTo` | The ingredient was an input to creating this asset |

Example with explicit relationship:

```py
ingredient_json = json.dumps({
    "title": "Base layer",
    "relationship": "componentOf"
})

with open("base_layer.png", "rb") as ingredient:
    builder.add_ingredient(ingredient_json, "image/png", ingredient)
```

## Working with archives

An _archive_ (C2PA archive) is a serialized working store (`Builder` object) saved to a stream.

Using archives provides these advantages:

- **Save work-in-progress**: Persist a working store between sessions.
- **Separate creation from signing**: Prepare manifests on one machine, sign on another.
- **Share manifests**: Transfer working stores between systems.
- **Offline preparation**: Build manifests offline, sign them later.

The default binary format of an archive is the **C2PA JUMBF binary format** (`application/c2pa`), which is the standard way to save and restore working stores.

### Saving a working store to archive

```py
import io

# Create and configure a working store
builder = Builder(manifest_json)
with open("thumbnail.jpg", "rb") as thumb:
    builder.add_resource("thumbnail", thumb)
with open("source.jpg", "rb") as ingredient:
    builder.add_ingredient(ingredient_json, "image/jpeg", ingredient)

# Save working store to archive stream
archive = io.BytesIO()
builder.to_archive(archive)

# Or save to a file
with open("manifest.c2pa", "wb") as f:
    archive.seek(0)
    f.write(archive.read())

print("Working store saved to archive")
```

A Builder containing **only one ingredient and only the ingredient data** (no other ingredient, no other actions) is an ingredient archive. Ingredient archives can be added directly as ingredient to other working stores too.

### Restoring a working store from archive

There are two ways to load a working store from an archive. They differ in whether the builder's current context (settings) is preserved or not.

#### `with_archive()`

Use `with_archive()` when you need the restored builder to use specific settings that you put on the Builder on instanciation by using a context as parameter of the Builder constructor. Create a `Builder` with a `Context` first, then call `with_archive()` to load the archived manifest definition into it. The archive replaces only the manifest definition; the builder's context and settings are preserved.

```py
# Create context with custom settings
ctx = Context.from_dict({
    "builder": {
        "thumbnail": {"enabled": False},
        "claim_generator_info": {"name": "My App", "version": "1.0"}
    }
})

# Create builder with context, then load archive into it
with open("manifest.c2pa", "rb") as archive:
    builder = Builder({}, context=ctx)
    builder.with_archive(archive)

# The builder has the archived manifest definition
# but keeps the context settings (no thumbnails, custom claim generator)
with open("asset.jpg", "rb") as src, open("signed.jpg", "w+b") as dst:
    builder.sign(signer, "image/jpeg", src, dst)
```

> [!IMPORTANT]
> `with_archive()` replaces the builder's manifest definition with the one from the archive. Any definition passed to `Builder()` on instanciation is discarded. An empty dict `{}` is idiomatic for the initial definition when you plan to load an archive immediately after.

#### `from_archive()` (legacy)

Use `from_archive()` for quick one-off operations where you don't need custom settings. It creates a **context-free** builder: no `Context` is attached, so all settings revert to SDK defaults.

```py
# Restore from stream — no context, SDK defaults apply
with open("manifest.c2pa", "rb") as archive:
    builder = Builder.from_archive(archive)

# Sign with SDK default settings
with open("asset.jpg", "rb") as src, open("signed_asset.jpg", "w+b") as dst:
    builder.sign(signer, "image/jpeg", src, dst)
```

> [!WARNING]
> `from_archive()` does not accept a `context` parameter. Any settings that were active when the archive was created are not stored in the archive and are therefore lost. For example, if the original builder had thumbnails disabled via a `Context`, the builder returned by `from_archive()` will generate thumbnails using SDK defaults. Use `with_archive()` instead when you need to preserve settings on the Builder instance you are loading an archive into.

#### Choosing between `with_archive()` and `from_archive()`

| | `with_archive()` | `from_archive()` |
|---|---|---|
| **Context preserved** | Yes — settings come from the builder's context | No — SDK defaults apply |
| **Usage pattern** | `Builder({}, context=ctx).with_archive(stream)` | `Builder.from_archive(stream)` |
| **When to use** | Production workflows, custom settings needed | Quick prototyping, SDK defaults are acceptable |
| **What the archive carries** | Only the manifest definition | Only the manifest definition |
| **What it does NOT carry** | Settings, signer, context | Settings, signer, context |

### Two-phase workflow example

#### Phase 1: Prepare manifest

This step prepares the manifest on a Builder, and archives it into a Builder archive for later reuse.

```py
import io
import json

manifest_json = json.dumps({
    "title": "Artwork draft",
    "assertions": []
})

with open("thumb.jpg", "rb") as thumb:
    builder.add_resource("thumbnail", thumb)
with open("sketch.png", "rb") as sketch:
    builder.add_ingredient(
        json.dumps({"title": "Sketch"}), "image/png", sketch
    )

# Save working store as archive
with open("artwork_manifest.c2pa", "wb") as f:
    builder.to_archive(f)

print("Working store saved to artwork_manifest.c2pa")
```

#### Phase 2: Sign the asset

```py
# Restore the working store
with open("artwork_manifest.c2pa", "rb") as archive:
    builder = Builder.from_archive(archive)

# Sign
with open("artwork.jpg", "rb") as src, open("signed_artwork.jpg", "w+b") as dst:
    builder.sign(signer, "image/jpeg", src, dst)

print("Asset signed with manifest store")
```

#### Phase 2 alternative: Sign with context

In this step, after reloading the working store into a Builder instance configured with a context, settings on the Builder context can configure signing settings (e.g. thumbnails on/off).

```py
# Restore the working store with context settings preserved
ctx = Context.from_dict({
    "builder": {"thumbnail": {"enabled": False}}
}, signer=signer)

with open("artwork_manifest.c2pa", "rb") as archive:
    builder = Builder({}, context=ctx)
    builder.with_archive(archive)

# Sign using the context's signer
with open("artwork.jpg", "rb") as src, open("signed_artwork.jpg", "w+b") as dst:
    builder.sign_with_context("image/jpeg", src, dst)
```

## Embedded vs external manifests

By default, manifest stores are **embedded** directly into the asset file. You can also use **external** or **remote** manifest stores.

### Default: embedded manifest stores

```py
builder = Builder(manifest_json)
# A builder object in this case can also be created
# using an additional Context parameter for settings propagation

# Default behavior: manifest store is embedded in the output
with open("source.jpg", "rb") as src, open("signed.jpg", "w+b") as dst:
    builder.sign(signer, "image/jpeg", src, dst)

# Read it back — manifest store is embedded
reader = Reader("signed.jpg")
```

### External manifest stores (no embed)

Prevent embedding the manifest store in the asset:

```py
builder = Builder(manifest_json)
# A builder object in this case can also be created
# using an additional Context parameter for settings propagation

builder.set_no_embed()  # Don't embed the manifest store

# Sign: manifest store is NOT embedded, manifest bytes are returned
with open("source.jpg", "rb") as src, open("output.jpg", "w+b") as dst:
    manifest_bytes = builder.sign(signer, "image/jpeg", src, dst)

# manifest_bytes contains the manifest store
# Save it separately (as a sidecar file or upload to server)
with open("output.c2pa", "wb") as f:
    f.write(manifest_bytes)

print("Manifest store saved externally to output.c2pa")
```

### Remote manifest stores

Reference a manifest store stored at a remote URL:

```py
builder = Builder(manifest_json)
# A builder object in this case can also be created
# using an additional Context parameter for settings propagation

builder.set_remote_url("https://example.com/manifests/")

# The asset will contain a reference to the remote manifest store
with open("source.jpg", "rb") as src, open("output.jpg", "w+b") as dst:
    builder.sign(signer, "image/jpeg", src, dst)
```

## Best practices

### Use Context for configuration

Use `Context` objects for SDK configuration:

```py
ctx = Context.from_dict({
    "verify": {
        "verify_after_sign": True
    },
    "trust": {
        "user_anchors": trust_anchors_pem
    }
})

builder = Builder(manifest_json, context=ctx)
reader = Reader("asset.jpg", context=ctx)
```

### Use ingredients to build provenance chains

Add ingredients to your manifests to maintain a provenance chain:

```py
ingredient_json = json.dumps({
    "title": "Original source",
    "relationship": "parentOf"
})

with open("original.jpg", "rb") as ingredient:
    builder.add_ingredient(ingredient_json, "image/jpeg", ingredient)

with open("edited.jpg", "rb") as src, open("signed.jpg", "w+b") as dst:
    builder.sign(signer, "image/jpeg", src, dst)
```

## Additional resources

- [Manifest reference](https://opensource.contentauthenticity.org/docs/manifest/manifest-ref)
- [X.509 certificates](https://opensource.contentauthenticity.org/docs/c2patool/x_509)
- [Trust lists](https://opensource.contentauthenticity.org/docs/conformance/trust-lists/)
- [CAWG identity](https://cawg.io/identity/)
