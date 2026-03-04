# Using the Python library

This package works with media files in the [supported formats](https://github.com/contentauth/c2pa-rs/blob/main/docs/supported-formats.md).

For complete working examples, see the [examples folder](https://github.com/contentauth/c2pa-python/tree/main/examples) in the repository.

## Import

Import the objects needed from the API:

```py
from c2pa import Builder, Reader, Signer, C2paSigningAlg, C2paSignerInfo
from c2pa import Settings, Context, ContextProvider
```

You can use `Builder`, `Reader`, `Signer`, `Settings`, and `Context` classes with context managers by using a `with` statement.
Doing this is recommended to ensure proper resource and memory cleanup.

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

## File-based operation

### Read and validate C2PA data

Use the `Reader` to read C2PA data from the specified asset file.

This examines the specified media file for C2PA data and generates a report of any data it finds. If there are validation errors, the report includes a `validation_status` field.

An asset file may contain many manifests in a manifest store. The most recent manifest is identified by the value of the `active_manifest` field in the manifests map. The manifests may contain binary resources such as thumbnails which can be retrieved with `resource_to_stream` using the associated `identifier` field values and a `uri`.

NOTE: For a comprehensive reference to the JSON manifest structure, see the [Manifest store reference](https://opensource.contentauthenticity.org/docs/manifest/manifest-ref).

```py
try:
    # Create a reader from a file path
    with Reader("path/to/media_file.jpg") as reader:
        # Print manifest store as JSON
        print("Manifest store:", reader.json())

        # Get the active manifest.
        manifest = json.loads(reader.json())
        active_manifest = manifest["manifests"][manifest["active_manifest"]]
        if active_manifest:
            # Get the uri to the manifest's thumbnail and write it to a file
            uri = active_manifest["thumbnail"]["identifier"]
            with open("thumbnail_v2.jpg", "wb") as f:
                reader.resource_to_stream(uri, f)

except Exception as err:
    print(err)
```

### Add a signed manifest

**WARNING**: This example accesses the private key and security certificate directly from the local file system.  This is fine during development, but doing so in production may be insecure. Instead use a Key Management Service (KMS) or a hardware security module (HSM) to access the certificate and key; for example as show in the [C2PA Python Example](https://github.com/contentauth/c2pa-python-example).

Use a `Builder` to add a manifest to an asset:

```py
try:
    # Create a signer from certificate and key files
    with open("path/to/cert.pem", "rb") as cert_file, open("path/to/key.pem", "rb") as key_file:
        cert_data = cert_file.read()
        key_data = key_file.read()

        # Create signer info using cert and key info
        signer_info = C2paSignerInfo(
            alg=C2paSigningAlg.PS256,
            cert=cert_data,
            key=key_data,
            timestamp_url="http://timestamp.digicert.com"
        )

        # Create signer using the defined SignerInfo
        signer = Signer.from_info(signer_info)

        # Create builder with manifest and add ingredients
        with Builder(manifest_json) as builder:
            # Add any ingredients if needed
            with open("path/to/ingredient.jpg", "rb") as ingredient_file:
                ingredient_json = json.dumps({"title": "Ingredient Image"})
                builder.add_ingredient(ingredient_json, "image/jpeg", ingredient_file)

            # Sign the file
            with open("path/to/source.jpg", "rb") as source_file, open("path/to/output.jpg", "wb") as dest_file:
                manifest_bytes = builder.sign(signer, "image/jpeg", source_file, dest_file)

        # Verify the signed file by reading data from the signed output file
        with Reader("path/to/output.jpg") as reader:
            manifest_store = json.loads(reader.json())
            active_manifest = manifest_store["manifests"][manifest_store["active_manifest"]]
            print("Signed manifest:", active_manifest)

except Exception as e:
    print("Failed to sign manifest store: " + str(e))
```

## Settings, Context, and ContextProvider

The `Settings` and `Context` classes provide **per-instance configuration** for Reader and Builder operations. This replaces the global `load_settings()` function, which is now deprecated.

### Settings

`Settings` controls behavior such as thumbnail generation, trust lists, and verification flags.

```py
from c2pa import Settings

# Create with defaults
settings = Settings()

# Set individual values by dot-notation path
settings.set("builder.thumbnail.enabled", "false")

# Method chaining
settings.set("builder.thumbnail.enabled", "false").set("verify.remote_manifest_fetch", "true")

# Dict-like access
settings["builder.thumbnail.enabled"] = "false"

# Create from JSON string
settings = Settings.from_json('{"builder": {"thumbnail": {"enabled": false}}}')

# Create from a dictionary
settings = Settings.from_dict({"builder": {"thumbnail": {"enabled": False}}})

# Merge additional configuration
settings.update({"verify": {"remote_manifest_fetch": True}})
```

### Context

A `Context` carries optional `Settings` and an optional `Signer`, and is passed to `Reader` or `Builder` to control their behavior.

```py
from c2pa import Context, Settings, Reader, Builder, Signer

# Default context (no custom settings)
ctx = Context()

# Context with settings
settings = Settings.from_dict({"builder": {"thumbnail": {"enabled": False}}})
ctx = Context(settings=settings)

# Create from JSON or dict directly
ctx = Context.from_json('{"builder": {"thumbnail": {"enabled": false}}}')
ctx = Context.from_dict({"builder": {"thumbnail": {"enabled": False}}})

# Use with Reader
reader = Reader("path/to/media_file.jpg", context=ctx)

# Use with Builder
builder = Builder(manifest_json, context=ctx)
```

### Context with a Signer

When a `Signer` is passed to `Context`, the signer is **consumed** — the `Signer` object becomes invalid after this call and must not be reused. The `Context` takes ownership of the underlying native signer. This allows signing without passing an explicit signer to `Builder.sign()`.

```py
from c2pa import Context, Settings, Builder, Signer, C2paSignerInfo, C2paSigningAlg

# Create a signer
signer_info = C2paSignerInfo(
    alg=C2paSigningAlg.ES256,
    sign_cert=cert_data,
    private_key=key_data,
    ta_url=b"http://timestamp.digicert.com"
)
signer = Signer.from_info(signer_info)

# Create context with signer (signer is consumed)
ctx = Context(settings=settings, signer=signer)
# signer is now invalid and must not be used again

# Build and sign — no signer argument needed
builder = Builder(manifest_json, context=ctx)
with open("source.jpg", "rb") as src, open("output.jpg", "w+b") as dst:
    manifest_bytes = builder.sign(format="image/jpeg", source=src, dest=dst)
```

If both an explicit signer and a context signer are available, the explicit signer always takes precedence:

```py
# Explicit signer wins over context signer
manifest_bytes = builder.sign(explicit_signer, "image/jpeg", source, dest)
```

### ContextProvider protocol

The `ContextProvider` protocol allows third-party implementations of custom context providers. Any class that implements `is_valid` and `_c_context` properties satisfies the protocol and can be passed to `Reader` or `Builder` as `context`.

```py
from c2pa import ContextProvider, Context

# The built-in Context satisfies ContextProvider
ctx = Context()
assert isinstance(ctx, ContextProvider)  # True
```

### Migrating from load_settings

The `load_settings()` function is deprecated. Replace it with `Settings` and `Context`:

```py
# Before (deprecated):
from c2pa import load_settings
load_settings({"builder": {"thumbnail": {"enabled": False}}})
reader = Reader("file.jpg")

# After (recommended):
from c2pa import Settings, Context, Reader
settings = Settings.from_dict({"builder": {"thumbnail": {"enabled": False}}})
ctx = Context(settings=settings)
reader = Reader("file.jpg", context=ctx)
```

## Stream-based operation

Instead of working with files, you can read, validate, and add a signed manifest to streamed data. This example is similar to what the file-based example does.

### Read and validate C2PA data using streams

```py
try:
    # Create a reader from a format and stream
    with open("path/to/media_file.jpg", "rb") as stream:
        # First parameter should be the type of the file (here, we use the mimetype)
        # But in any case we need something to identify the file type
        with Reader("image/jpeg", stream) as reader:
            # Print manifest store as JSON, as extracted by the Reader
            print("manifest store:", reader.json())

            # Get the active manifest
            manifest = json.loads(reader.json())
            active_manifest = manifest["manifests"][manifest["active_manifest"]]
            if active_manifest:
                # get the uri to the manifest's thumbnail and write it to a file
                uri = active_manifest["thumbnail"]["identifier"]
                with open("thumbnail_v2.jpg", "wb") as f:
                    reader.resource_to_stream(uri, f)

except Exception as err:
    print(err)
```

### Add a signed manifest to a stream

**WARNING**: This example accesses the private key and security certificate directly from the local file system.  This is fine during development, but doing so in production may be insecure. Instead use a Key Management Service (KMS) or a hardware security module (HSM) to access the certificate and key; for example as show in the [C2PA Python Example](https://github.com/contentauth/c2pa-python-example).

Use a `Builder` to add a manifest to an asset:

```py
try:
    # Create a signer from certificate and key files
    with open("path/to/cert.pem", "rb") as cert_file, open("path/to/key.pem", "rb") as key_file:
        cert_data = cert_file.read()
        key_data = key_file.read()

        # Create signer info using the read certificate and key data
        signer_info = C2paSignerInfo(
            alg=C2paSigningAlg.PS256,
            cert=cert_data,
            key=key_data,
            timestamp_url="http://timestamp.digicert.com"
        )

        # Create a Signer using the SignerInfo defined previously
        signer = Signer.from_info(signer_info)

        # Create a Builder with manifest and add ingredients
        with Builder(manifest_json) as builder:
            # Add any ingredients as needed
            with open("path/to/ingredient.jpg", "rb") as ingredient_file:
                ingredient_json = json.dumps({"title": "Ingredient Image"})
                # Here the ingredient is added using streams
                builder.add_ingredient(ingredient_json, "image/jpeg", ingredient_file)

            # Sign using streams
            with open("path/to/source.jpg", "rb") as source_file, open("path/to/output.jpg", "wb") as dest_file:
                manifest_bytes = builder.sign(signer, "image/jpeg", source_file, dest_file)

            # Verify the signed file
            with open("path/to/output.jpg", "rb") as stream:
                # Create a Reader to read data
                with Reader("image/jpeg", stream) as reader:
                    manifest_store = json.loads(reader.json())
                    active_manifest = manifest_store["manifests"][manifest_store["active_manifest"]]
                    print("Signed manifest:", active_manifest)

except Exception as e:
    print("Failed to sign manifest store: " + str(e))
```
