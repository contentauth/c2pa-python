# Using the Python library

This package works with media files in the [supported formats](https://github.com/contentauth/c2pa-rs/blob/main/docs/supported-formats.md).

For complete working examples, see the [examples folder](https://github.com/contentauth/c2pa-python/tree/main/examples) in the repository.

Reference material:
- [Class diagram](class-diagram.md)
- [API reference documentation](https://contentauth.github.io/c2pa-python/api/c2pa/index.html)

## Import

Import the objects needed from the API:

```py
from c2pa import Builder, Reader, Signer, C2paSigningAlg, C2paSignerInfo
```

If you want to use per-instance configuration with `Context` and `Settings`:

```py
from c2pa import Settings, Context, ContextBuilder, ContextProvider
```

All of `Builder`, `Reader`, `Signer`, `Context`, and `Settings` support context managers (the `with` statement) for automatic resource cleanup.

## Define manifest JSON

The Python library works with both file-based and stream-based operations.
In both cases, the manifest JSON string defines the C2PA manifest to add to an asset. For example:

```py
manifest_json = json.dumps({
    "claim_generator": "python_test/0.1",
    "assertions": [
    {
      "label": "cawg.training-mining",
      "data": {
        "entries": {
          "cawg.ai_inference": {
            "use": "notAllowed"
          },
          "cawg.ai_generative_training": {
            "use": "notAllowed"
          }
        }
      }
    }
  ]
 })
```

## Settings, Context, and ContextProvider

The `Settings` and `Context` classes provide per-instance configuration for `Reader` and `Builder` operations, replacing the global `load_settings()` function, which is now deprecated. See [Context and settings](context-settings.md) for details.

### Settings

`Settings` controls behavior such as thumbnail generation, trust lists, and verification flags.

```py
from c2pa import Settings

settings = Settings()
settings.set("builder.thumbnail.enabled", "false")  # dot-notation path; value is a string
settings.update({"verify": {"remote_manifest_fetch": True}})  # merge additional config

settings = Settings.from_json('{"builder": {"thumbnail": {"enabled": false}}}')
settings = Settings.from_dict({"builder": {"thumbnail": {"enabled": False}}})
```

For the full Settings API reference, see [Settings API](context-settings.md#settings-api).

### Context

A `Context` carries `Settings` and optionally a `Signer`, and is passed to `Reader` or `Builder` to control their behavior.

```py
from c2pa import Context, Settings

ctx = Context()  # SDK defaults
ctx = Context(settings)
ctx = Context.from_json('{"builder": {"thumbnail": {"enabled": false}}}')
ctx = Context.from_dict({"builder": {"thumbnail": {"enabled": False}}})

reader = Reader("path/to/media_file.jpg", context=ctx)
builder = Builder(manifest_json, ctx)
```

For full details on configuring `Context` and using it with `Reader` and `Builder`, see [Using Context](context-settings.md#using-context) and the [Settings reference](context-settings.md#settings-reference).

### ContextBuilder (fluent API)

`ContextBuilder` provides a fluent interface for constructing a `Context`. Use `Context.builder()` to get started.

```py
from c2pa import Context, ContextBuilder, Settings, Signer

ctx = (
    Context.builder()
    .with_settings(settings)
    .with_signer(signer)
    .build()
)

ctx = Context.builder().with_settings(settings).build()
ctx = Context.builder().build()  # equivalent to Context()
```

You can call `with_settings()` multiple times; each call replaces the previous `Settings` object entirely (last one wins). To merge multiple configurations, use `Settings.update()` on a single `Settings` object before passing it to the context; for example:

```py
settings = Settings.from_dict({"builder": {"thumbnail": {"enabled": False}}})
settings.update({"verify": {"remote_manifest_fetch": True}})

ctx = Context.builder().with_settings(settings).build()
```

### Context with a Signer

When a `Signer` is passed to `Context`, the `Signer` object is consumed and must not be reused directly. The `Context` takes ownership, enabling signing without passing an explicit signer to `Builder.sign()`:

```py
ctx = Context(settings=settings, signer=signer)
# signer is now invalid and must not be used directly again

builder = Builder(manifest_json, ctx)
with open("source.jpg", "rb") as src, open("output.jpg", "w+b") as dst:
    manifest_bytes = builder.sign(format="image/jpeg", source=src, dest=dst)
```

If both an explicit signer and a context signer are available, the explicit signer takes precedence. For more details, including remote signers, see [Configuring signers](context-settings.md#configuring-signers).

### ContextProvider (abstract base class)

`ContextProvider` is an abstract base class (ABC) that defines the interface `Reader` and `Builder` use to access a context. It requires two properties:

- `is_valid` (bool): Whether the provider is in a usable state.
- `execution_context`: The raw native context pointer (`C2paContext` handle).

The built-in `Context` class is the standard `ContextProvider` implementation. Custom providers must wrap a compatible native resource rather than constructing native pointers independently. `Settings` is not a `ContextProvider` and cannot be passed directly to `Reader` or `Builder`. For more details and a custom implementation example, see [ContextProvider](context-settings.md#contextprovider-abstract-base-class).

### Migrating from load_settings

The `load_settings()` function is deprecated. Replace it with `Settings` and `Context`. See [Migrating from load_settings](context-settings.md#migrating-from-load_settings) for details.

## File-based operation

### Read and validate C2PA data

Use the `Reader` to read C2PA data from the specified asset file.

This examines the specified media file for C2PA data and generates a report of any data it finds. If there are validation errors, the report includes a `validation_status` field.

An asset file may contain many manifests in a manifest store. The most recent manifest is identified by the value of the `active_manifest` field in the manifests map. The manifests may contain binary resources such as thumbnails which can be retrieved with `resource_to_stream` using the associated `identifier` field values and a `uri`.

NOTE: For a comprehensive reference to the JSON manifest structure, see the [Manifest store reference](https://opensource.contentauthenticity.org/docs/manifest/manifest-ref).

#### Reading without Context

```py
try:
    # Create a Reader from a file path.
    with Reader("path/to/media_file.jpg") as reader:
        # Print manifest store as JSON.
        print("Manifest store:", reader.json())

        # Get the active manifest.
        manifest = json.loads(reader.json())
        active_manifest = manifest["manifests"][manifest["active_manifest"]]
        if active_manifest:
            # Get the uri to the manifest's thumbnail and write it to a file.
            uri = active_manifest["thumbnail"]["identifier"]
            with open("thumbnail.jpg", "wb") as f:
                reader.resource_to_stream(uri, f)

except Exception as err:
    print(err)
```

#### Reading with Context

Pass a `Context` to apply custom settings to the Reader, such as trust anchors or verification flags.

```py
try:
    settings = Settings.from_dict({
        "verify": {"verify_cert_anchors": True},
        "trust": {"trust_anchors": anchors_pem}
    })

    with Context(settings) as ctx:
        with Reader("path/to/media_file.jpg", context=ctx) as reader:
            print("Manifest store:", reader.json())

except Exception as err:
    print(err)
```

### Add a signed manifest

**WARNING**: This example accesses the private key and security certificate directly from the local file system.  This is fine during development, but doing so in production may be insecure. Instead use a Key Management Service (KMS) or a hardware security module (HSM) to access the certificate and key; for example as show in the [C2PA Python Example](https://github.com/contentauth/c2pa-python-example).

#### Signing without Context

Use a `Builder` and `Signer` to add a manifest to an asset:

```py
try:
    # Load certificate and key files
    with open("path/to/cert.pem", "rb") as cert_file, open("path/to/key.pem", "rb") as key_file:
        cert_data = cert_file.read()
        key_data = key_file.read()

        # Create signer info with the correct field names
        signer_info = C2paSignerInfo(
            alg=C2paSigningAlg.PS256,
            sign_cert=cert_data,
            private_key=key_data,
            ta_url=b"http://timestamp.digicert.com"
        )

        # Create signer using the defined SignerInfo
        signer = Signer.from_info(signer_info)

        # Create builder with manifest and add ingredients
        with Builder(manifest_json) as builder:
            with open("path/to/ingredient.jpg", "rb") as ingredient_file:
                ingredient_json = json.dumps({"title": "Ingredient Image"})
                builder.add_ingredient(ingredient_json, "image/jpeg", ingredient_file)

            # Sign the file (dest must be opened in w+b mode)
            with open("path/to/source.jpg", "rb") as source, open("path/to/output.jpg", "w+b") as dest:
                builder.sign(signer, "image/jpeg", source, dest)

        # Verify the signed file by reading data from the signed output file
        with Reader("path/to/output.jpg") as reader:
            manifest_store = json.loads(reader.json())
            active_manifest = manifest_store["manifests"][manifest_store["active_manifest"]]
            print("Signed manifest:", active_manifest)

except Exception as e:
    print("Failed to sign manifest store: " + str(e))
```

#### Signing with Context

Pass a `Context` to the Builder to apply custom settings during signing. The signer is still passed explicitly to `builder.sign()`.

```py
try:
    with open("path/to/cert.pem", "rb") as cert_file, open("path/to/key.pem", "rb") as key_file:
        cert_data = cert_file.read()
        key_data = key_file.read()

        signer_info = C2paSignerInfo(
            alg=C2paSigningAlg.PS256,
            sign_cert=cert_data,
            private_key=key_data,
            ta_url=b"http://timestamp.digicert.com"
        )

        with Context() as ctx:
            with Signer.from_info(signer_info) as signer:
                with Builder(manifest_json, ctx) as builder:
                    with open("path/to/ingredient.jpg", "rb") as ingredient_file:
                        ingredient_json = json.dumps({"title": "Ingredient Image"})
                        builder.add_ingredient(ingredient_json, "image/jpeg", ingredient_file)

                    # Sign using file paths
                    builder.sign_file("path/to/source.jpg", "path/to/output.jpg", signer)

            # Verify the signed file with the same context
            with Reader("path/to/output.jpg", context=ctx) as reader:
                manifest_store = json.loads(reader.json())
                active_manifest = manifest_store["manifests"][manifest_store["active_manifest"]]
                print("Signed manifest:", active_manifest)

except Exception as e:
    print("Failed to sign manifest store: " + str(e))
```

## Stream-based operations

Instead of working with files, you can read, validate, and add a signed manifest to streamed data. This example is similar to what the file-based example does.

### Read and validate C2PA data using streams

#### Stream reading without Context

```py
try:
    with open("path/to/media_file.jpg", "rb") as stream:
        with Reader("image/jpeg", stream) as reader:
            print("Manifest store:", reader.json())

            manifest = json.loads(reader.json())
            active_manifest = manifest["manifests"][manifest["active_manifest"]]
            if active_manifest:
                uri = active_manifest["thumbnail"]["identifier"]
                with open("thumbnail.jpg", "wb") as f:
                    reader.resource_to_stream(uri, f)

except Exception as err:
    print(err)
```

#### Stream reading with Context

```py
try:
    settings = Settings.from_dict({"verify": {"verify_cert_anchors": True}})

    with Context(settings) as ctx:
        with open("path/to/media_file.jpg", "rb") as stream:
            with Reader("image/jpeg", stream, context=ctx) as reader:
                print("Manifest store:", reader.json())

except Exception as err:
    print(err)
```

### Add a signed manifest to a stream

**WARNING**: These examples access the private key and security certificate directly from the local file system. This is fine during development, but doing so in production may be insecure. Instead use a Key Management Service (KMS) or a hardware security module (HSM) to access the certificate and key; for example as shown in the [C2PA Python Example](https://github.com/contentauth/c2pa-python-example).

#### Stream signing without Context

```py
try:
    with open("path/to/cert.pem", "rb") as cert_file, open("path/to/key.pem", "rb") as key_file:
        cert_data = cert_file.read()
        key_data = key_file.read()

        signer_info = C2paSignerInfo(
            alg=C2paSigningAlg.PS256,
            sign_cert=cert_data,
            private_key=key_data,
            ta_url=b"http://timestamp.digicert.com"
        )

        signer = Signer.from_info(signer_info)

        with Builder(manifest_json) as builder:
            with open("path/to/ingredient.jpg", "rb") as ingredient_file:
                ingredient_json = json.dumps({"title": "Ingredient Image"})
                builder.add_ingredient(ingredient_json, "image/jpeg", ingredient_file)

            # Sign using streams (dest must be opened in w+b mode)
            with open("path/to/source.jpg", "rb") as source, open("path/to/output.jpg", "w+b") as dest:
                builder.sign(signer, "image/jpeg", source, dest)

            # Verify the signed file
            with open("path/to/output.jpg", "rb") as stream:
                with Reader("image/jpeg", stream) as reader:
                    manifest_store = json.loads(reader.json())
                    active_manifest = manifest_store["manifests"][manifest_store["active_manifest"]]
                    print("Signed manifest:", active_manifest)

except Exception as e:
    print("Failed to sign manifest store: " + str(e))
```

#### Stream signing with Context

```py
try:
    with open("path/to/cert.pem", "rb") as cert_file, open("path/to/key.pem", "rb") as key_file:
        cert_data = cert_file.read()
        key_data = key_file.read()

        signer_info = C2paSignerInfo(
            alg=C2paSigningAlg.PS256,
            sign_cert=cert_data,
            private_key=key_data,
            ta_url=b"http://timestamp.digicert.com"
        )

        with Context() as ctx:
            with Signer.from_info(signer_info) as signer:
                with Builder(manifest_json, ctx) as builder:
                    with open("path/to/ingredient.jpg", "rb") as ingredient_file:
                        ingredient_json = json.dumps({"title": "Ingredient Image"})
                        builder.add_ingredient(ingredient_json, "image/jpeg", ingredient_file)

                    with open("path/to/source.jpg", "rb") as source, open("path/to/output.jpg", "w+b") as dest:
                        builder.sign(signer, "image/jpeg", source, dest)

            # Verify the signed file with the same context
            with open("path/to/output.jpg", "rb") as stream:
                with Reader("image/jpeg", stream, context=ctx) as reader:
                    manifest_store = json.loads(reader.json())
                    active_manifest = manifest_store["manifests"][manifest_store["active_manifest"]]
                    print("Signed manifest:", active_manifest)

except Exception as e:
    print("Failed to sign manifest store: " + str(e))
```
