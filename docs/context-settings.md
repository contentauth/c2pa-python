# Context and settings

This guide shows you how to configure the C2PA Python SDK using the `Context` API with declarative settings in JSON format.

## Overview

The `Context` class encapsulates configuration for:

- **Settings**: Verification options, builder behavior, trust configuration, thumbnail settings, and more.
- **Signer configuration**: Optional signer credentials stored in the `Context` for reuse.
- **State isolation**: Each `Context` is independent, allowing different configurations to coexist in the same application.

`Context` replaces the deprecated global `load_settings()` function with explicit, isolated configuration:

- **Makes dependencies explicit**: Configuration is passed directly to `Reader` and `Builder`, not hidden in global state.
- **Enables multiple configurations**: Run different configurations simultaneously (for example, one for development with test certificates, another for production with strict validation).
- **Eliminates global state**: Each `Reader` and `Builder` gets its configuration from the `Context` you pass, avoiding subtle bugs from shared state.
- **Simplifies testing**: Create isolated configurations for tests without worrying about cleanup or interference.

> [!NOTE]
> The deprecated `load_settings()` function still works for backward compatibility, but you are encouraged to migrate your code to use `Context`. See [Migrating from load_settings](#migrating-from-load_settings).

## Quick start

### Using SDK default settings

Without additional parameters, `Context` uses [SDK default settings](#default-configuration).

**When to use:** For quick prototyping, or when SDK defaults are acceptable (verification enabled, thumbnails enabled at 1024px, and so on).

```py
from c2pa import Context

ctx = Context()  # Uses SDK defaults
```

### From a JSON string

**When to use:** For simple configuration that doesn't need to be shared across the codebase.

```py
ctx = Context.from_json('''{
  "verify": {"verify_after_sign": true},
  "builder": {
    "thumbnail": {"enabled": false},
    "claim_generator_info": {"name": "An app", "version": "0.1.0"}
  }
}''')
```

### From a dictionary

**When to use:** When you want to build configuration programmatically using native Python data structures.

```py
ctx = Context.from_dict({
    "verify": {"verify_after_sign": True},
    "builder": {
        "thumbnail": {"enabled": False},
        "claim_generator_info": {"name": "An app", "version": "0.1.0"}
    }
})
```

### From a Settings object

**When to use:** For configuration that needs runtime logic (conditional settings based on environment, or incremental/layered configuration).

```py
from c2pa import Settings, Context

settings = Settings()
settings.set("builder.thumbnail.enabled", "false")
settings.set("verify.verify_after_sign", "true")
settings.update({
    "builder": {
        "claim_generator_info": {"name": "An app", "version": "0.1.0"}
    }
})

ctx = Context(settings)
```

To load settings from a file:

```py
import json

with open("config/settings.json", "r") as f:
    settings = Settings.from_json(f.read())

ctx = Context(settings)
```

## Class diagram 

```mermaid
classDiagram
    class ContextProvider {
        <<abstract>>
        +is_valid bool
        +execution_context
    }

    class Settings {
        +set(path, value) Settings
        +update(data) Settings
        +from_json(json_str)$ Settings
        +from_dict(config)$ Settings
        +close()
    }

    class Context {
        +has_signer bool
        +builder()$ ContextBuilder
        +from_json(json_str, signer)$ Context
        +from_dict(config, signer)$ Context
        +close()
    }

    class ContextBuilder {
        +with_settings(settings) ContextBuilder
        +with_signer(signer) ContextBuilder
        +build() Context
    }

    class Signer {
        +from_info(signer_info)$ Signer
        +from_callback(callback, alg, certs, tsa_url)$ Signer
        +close()
    }

    class Reader {
        +json() str
        +resource_to_stream(uri, stream)
        +close()
    }

    class Builder {
        +add_ingredient(json, format, stream)
        +sign(signer, format, source, dest) bytes
        +close()
    }

    ContextProvider <|-- Context
    ContextBuilder --> Context : builds
    Context o-- Settings : optional
    Context o-- Signer : optional, consumed
    Reader ..> ContextProvider : uses
    Builder ..> ContextProvider : uses
```

## Settings API

Create and configure settings independently of a `Context`:

| Method | Description |
|--------|-------------|
| `Settings()` | Create default settings with SDK defaults. |
| `Settings.from_json(json_str)` | Create settings from a JSON string. Raises `C2paError` on parse error. |
| `Settings.from_dict(config)` | Create settings from a Python dictionary. |
| `set(path, value)` | Set a single value by dot-separated path (for example, `"verify.verify_after_sign"`). Value must be a string. Returns `self` for chaining. |
| `update(data)` | Merge configuration into existing settings. `data` can be a JSON string or a dict. Later keys override earlier ones. |

The `set()` and `update()` methods can be chained for incremental configuration. When using multiple configuration methods, later calls override earlier ones (last call wins when the same setting is set multiple times).

```py
from c2pa import Settings

settings = Settings()
settings.set("builder.thumbnail.enabled", "false").set("verify.verify_after_sign", "true")

settings.update({"verify": {"remote_manifest_fetch": True}})
```

## Using Context

### With Reader

`Reader` uses `Context` to control how it validates manifests and handles remote resources:

- **Verification behavior**: Whether to verify after reading, check trust, and so on.
- **Trust configuration**: Which certificates to trust when validating signatures.
- **Network access**: Whether to fetch remote manifests or OCSP responses.

> [!IMPORTANT]
> `Context` is used only at construction time. `Reader` copies the configuration it needs internally, so the `Context` does not need to outlive the `Reader`. A single `Context` can be reused for multiple `Reader` instances.

```py
ctx = Context.from_dict({"verify": {"remote_manifest_fetch": False}})
reader = Reader("image.jpg", context=ctx)
print(reader.json())
```

Reading from a stream:

```py
with open("image.jpg", "rb") as stream:
    reader = Reader("image/jpeg", stream, context=ctx)
    print(reader.json())
```

### With Builder

`Builder` uses `Context` to control how it creates and signs C2PA manifests. The `Context` affects:

- **Claim generator information**: Application name, version, and metadata embedded in the manifest.
- **Thumbnail generation**: Whether to create thumbnails, and their size, quality, and format.
- **Action tracking**: Auto-generation of actions like `c2pa.created`, `c2pa.opened`, `c2pa.placed`.
- **Intent**: The purpose of the claim (create, edit, or update).
- **Verification after signing**: Whether to validate the manifest immediately after signing.
- **Signer configuration** (optional): Credentials stored in the context for reuse.

> [!IMPORTANT]
> `Context` is used only when constructing the `Builder`. The `Builder` copies the configuration it needs internally, so the `Context` does not need to outlive the `Builder`. A single `Context` can be reused for multiple `Builder` instances.

```py
ctx = Context.from_dict({
    "builder": {
        "claim_generator_info": {"name": "An app", "version": "0.1.0"},
        "intent": {"Create": "digitalCapture"}
    }
})

builder = Builder(manifest_json, ctx)

with open("source.jpg", "rb") as src, open("output.jpg", "w+b") as dst:
    builder.sign(signer, "image/jpeg", src, dst)
```

#### Context and archives

Archives (`.c2pa` files) store only the manifest definition. They do **not** store settings or context:

- **`Builder.from_archive(stream)`** creates a context-free builder. All settings revert to SDK defaults regardless of what context the original builder had.
- **`Builder({}, ctx).with_archive(stream)`** creates a builder with a context first, then loads the archived manifest definition into it. The context settings are preserved.

Use `with_archive()` when your workflow depends on specific settings (thumbnails, claim generator, intent, and so on). Use `from_archive()` only for quick prototyping where SDK defaults are acceptable.

```py
ctx = Context.from_dict({
    "builder": {
        "thumbnail": {"enabled": False},
        "claim_generator_info": {"name": "My App", "version": "0.1.0"}
    }
})

with open("manifest.c2pa", "rb") as archive:
    builder = Builder({}, ctx)
    builder.with_archive(archive)
    # builder now has the archived definition + context settings
```

For more details, see [Working with archives](working-stores.md#working-with-archives).

## Settings reference

### Structure

The Settings JSON has this top-level structure:

```json
{
  "version": 1,
  "trust": { ... },
  "cawg_trust": { ... },
  "core": { ... },
  "verify": { ... },
  "builder": { ... },
  "signer": { ... },
  "cawg_x509_signer": { ... }
}
```

The settings format is **JSON** only. Pass JSON strings to `Settings.from_json()` or `Context.from_json()`, and dictionaries to `Settings.from_dict()` or `Context.from_dict()`. The `from_dict()` methods convert Python dictionaries to a format compatible with the underlying native libraries.

Notes:
- All properties are optional. If you don't specify a value, the SDK uses the default value.
- If you specify a value of `null` (or `None` in a dict), the property is explicitly set to `null`, not the default. This distinction is important when you want to override a default behavior.
- For Boolean values, use JSON Booleans `true`/`false` in JSON strings, or Python `True`/`False` in dicts.

The settings JSON schema is shared across all C2PA SDKs (Rust, C/C++, Python, and so on). For a complete reference to all properties, see the [SDK object reference - Settings](https://opensource.contentauthenticity.org/docs/manifest/json-ref/settings-schema).

| Property | Description |
|----------|-------------|
| `version` | Settings format version (integer). The default and only supported value is 1. |
| [`builder`](https://opensource.contentauthenticity.org/docs/manifest/json-ref/settings-schema#buildersettings) | Configuration for Builder. |
| [`cawg_trust`](https://opensource.contentauthenticity.org/docs/manifest/json-ref/settings-schema#trust) | Configuration for CAWG trust lists. |
| [`cawg_x509_signer`](https://opensource.contentauthenticity.org/docs/manifest/json-ref/settings-schema#signersettings) | Configuration for the CAWG x.509 signer. |
| [`core`](https://opensource.contentauthenticity.org/docs/manifest/json-ref/settings-schema#core) | Configuration for core features. |
| [`signer`](https://opensource.contentauthenticity.org/docs/manifest/json-ref/settings-schema#signersettings) | Configuration for the base C2PA signer. |
| [`trust`](https://opensource.contentauthenticity.org/docs/manifest/json-ref/settings-schema#trust) | Configuration for C2PA trust lists. |
| [`verify`](https://opensource.contentauthenticity.org/docs/manifest/json-ref/settings-schema#verify) | Configuration for verification (validation). |

### Default configuration

```json
{
  "version": 1,
  "builder": {
    "claim_generator_info": null,
    "created_assertion_labels": null,
    "certificate_status_fetch": null,
    "certificate_status_should_override": null,
    "generate_c2pa_archive": true,
    "intent": null,
    "actions": {
      "all_actions_included": null,
      "templates": null,
      "actions": null,
      "auto_created_action": {
        "enabled": true,
        "source_type": "empty"
      },
      "auto_opened_action": {
        "enabled": true,
        "source_type": null
      },
      "auto_placed_action": {
        "enabled": true,
        "source_type": null
      }
    },
    "thumbnail": {
      "enabled": true,
      "ignore_errors": true,
      "long_edge": 1024,
      "format": null,
      "prefer_smallest_format": true,
      "quality": "medium"
    }
  },
  "cawg_trust": {
    "verify_trust_list": true,
    "user_anchors": null,
    "trust_anchors": null,
    "trust_config": null,
    "allowed_list": null
  },
  "cawg_x509_signer": null,
  "core": {
    "merkle_tree_chunk_size_in_kb": null,
    "merkle_tree_max_proofs": 5,
    "backing_store_memory_threshold_in_mb": 512,
    "decode_identity_assertions": true,
    "allowed_network_hosts": null
  },
  "signer": null,
  "trust": {
    "user_anchors": null,
    "trust_anchors": null,
    "trust_config": null,
    "allowed_list": null
  },
  "verify": {
    "verify_after_reading": true,
    "verify_after_sign": true,
    "verify_trust": true,
    "verify_timestamp_trust": true,
    "ocsp_fetch": false,
    "remote_manifest_fetch": true,
    "skip_ingredient_conflict_resolution": false,
    "strict_v1_validation": false
  }
}
```

### Trust

The [`trust` properties](https://opensource.contentauthenticity.org/docs/manifest/json-ref/settings-schema/#trust) control which certificates are trusted when validating C2PA manifests.

| Property | Type | Description |
|----------|------|-------------|
| `trust.user_anchors` | string | Additional user-provided root certificates (PEM format). Adds custom certificate authorities without replacing the SDK's built-in trust anchors. Recommended for development. |
| `trust.trust_anchors` | string | Default trust anchor root certificates (PEM format). **Replaces** the SDK's built-in trust anchors entirely. |
| `trust.trust_config` | string | Allowed Extended Key Usage (EKU) OIDs. Controls which certificate purposes are accepted (for example, `1.3.6.1.4.1.311.76.59.1.9` for document signing). |
| `trust.allowed_list` | string | Explicitly allowed certificates (PEM format). Trusted regardless of chain validation. Use for development/testing to bypass chain validation. |

Use `user_anchors` to add your test root CA without replacing the SDK's default trust store:

```py
with open("test-ca.pem", "r") as f:
    test_root_ca = f.read()

ctx = Context.from_dict({"trust": {"user_anchors": test_root_ca}})
reader = Reader("signed_asset.jpg", context=ctx)
```

Use `allowed_list` to bypass chain validation entirely for quick testing:

```py
with open("test_cert.pem", "r") as f:
    test_cert = f.read()

ctx = Context.from_dict({"trust": {"allowed_list": test_cert}})
reader = Reader("signed_asset.jpg", context=ctx)
```

### CAWG trust

The `cawg_trust` properties configure CAWG (Creator Assertions Working Group) validation of identity assertions in C2PA manifests. It has the same properties as [`trust`](https://opensource.contentauthenticity.org/docs/manifest/json-ref/settings-schema/#trust).

> [!NOTE]
> CAWG trust settings are only used when processing identity assertions with X.509 certificates. If your workflow doesn't use CAWG identity assertions, these settings have no effect.

### Core

The [`core` properties](https://opensource.contentauthenticity.org/docs/manifest/json-ref/settings-schema/#core) specify core SDK behavior and performance tuning options.

Common use cases:

- **Performance tuning for large files**: Set `core.backing_store_memory_threshold_in_mb` to `2048` or higher when processing large video files with sufficient RAM.
- **Restricted network environments**: Set `core.allowed_network_hosts` to limit which domains the SDK can contact.

### Verify

The [`verify` properties](https://opensource.contentauthenticity.org/docs/manifest/json-ref/settings-schema/#verify) control how the SDK validates C2PA manifests, affecting both reading existing manifests and verifying newly signed content.

The following properties default to `true` (verification enabled):

- `verify_after_reading` - Automatically verify manifests when reading assets. Disable only if you want to manually control verification timing.
- `verify_after_sign` - Automatically verify manifests after signing. Recommended to keep enabled to catch signing errors immediately.
- `verify_trust` - Verify signing certificates against configured trust anchors. WARNING: Disabling makes verification non-compliant.
- `verify_timestamp_trust` - Verify timestamp authority (TSA) certificates. WARNING: Disabling makes verification non-compliant.
- `remote_manifest_fetch` - Fetch remote manifests referenced in the asset. Disable in offline or air-gapped environments.

> [!WARNING]
> Disabling verification options can make verification non-compliant with the C2PA specification. Only modify these settings in controlled environments or when you have specific requirements.

### Builder

The [`builder` properties](https://opensource.contentauthenticity.org/docs/manifest/json-ref/settings-schema/#buildersettings) control how the SDK creates and embeds C2PA manifests in assets.

#### Claim generator information

The `claim_generator_info` object identifies your application in the C2PA manifest:

- `name` (string, required): Your application name (for example, `"My Photo Editor"`)
- `version` (string, recommended): Application version (for example, `"2.1.0"`)
- `icon` (string, optional): Icon in C2PA format
- `operating_system` (string, optional): OS identifier, or `"auto"` to auto-detect

#### Thumbnail settings

The [`builder.thumbnail`](https://opensource.contentauthenticity.org/docs/manifest/json-ref/settings-schema/#thumbnailsettings) properties control automatic thumbnail generation:

```py
# Disable thumbnails for batch processing
ctx = Context.from_dict({
    "builder": {
        "thumbnail": {"enabled": False}
    }
})

# Customize for mobile bandwidth
ctx = Context.from_dict({
    "builder": {
        "thumbnail": {
            "enabled": True,
            "long_edge": 512,
            "quality": "low",
            "prefer_smallest_format": True
        }
    }
})
```

#### Action tracking

| Property | Type | Description | Default |
|----------|------|-------------|---------|
| `builder.actions.auto_created_action.enabled` | Boolean | Automatically add a `c2pa.created` action when creating new content. | `true` |
| `builder.actions.auto_created_action.source_type` | string | Source type for the created action. Usually `"empty"` for new content. | `"empty"` |
| `builder.actions.auto_opened_action.enabled` | Boolean | Automatically add a `c2pa.opened` action when opening/reading content. | `true` |
| `builder.actions.auto_placed_action.enabled` | Boolean | Automatically add a `c2pa.placed` action when placing content as an ingredient. | `true` |

#### Intent

The `builder.intent` property describes the purpose of the claim: `{"Create": "digitalCapture"}`, `{"Edit": null}`, or `{"Update": null}`. Defaults to `null`.

#### Other builder settings

| Property | Type | Description | Default |
|----------|------|-------------|---------|
| `builder.generate_c2pa_archive` | Boolean | Generate content in C2PA archive format. Keep enabled for standard C2PA compliance. | `true` |

### Signer

The [`signer` properties](https://opensource.contentauthenticity.org/docs/manifest/json-ref/settings-schema/#signersettings) configure the primary C2PA signer. Set to `null` if you provide the signer at runtime. Configure as either a **local** or **remote** signer:

- **Local signer**: For local certificate and private key access. See [signer.local](https://opensource.contentauthenticity.org/docs/manifest/json-ref/settings-schema/#signerlocal) in the SDK object reference.
- **Remote signer**: For private keys on a secure signing service (HSM, cloud KMS, and so on). See [signer.remote](https://opensource.contentauthenticity.org/docs/manifest/json-ref/settings-schema/#signerremote) in the SDK object reference.

For details on configuring and using signers, see [Configuring signers](#configuring-signers).

### CAWG X.509 signer

The `cawg_x509_signer` property configures signing of identity assertions. It has the same structure as `signer` (local or remote). When both `signer` and `cawg_x509_signer` are configured, the SDK uses a dual signer:

- Main claim signature comes from `signer`
- Identity assertions are signed with `cawg_x509_signer`

## Configuration examples

### Minimal configuration

```py
ctx = Context.from_dict({
    "builder": {
        "claim_generator_info": {"name": "My app", "version": "0.1"},
        "intent": {"Create": "digitalCapture"}
    }
})
```

### Development environment with test certificates

During development, you often need to trust self-signed or custom CA certificates with looser verification:

```py
with open("test-ca.pem", "r") as f:
    test_ca = f.read()

ctx = Context.from_dict({
    "trust": {"user_anchors": test_ca},
    "verify": {
        "verify_after_reading": True,
        "verify_after_sign": True,
        "remote_manifest_fetch": False,
        "ocsp_fetch": False
    },
    "builder": {
        "claim_generator_info": {"name": "Dev Build", "version": "dev"},
        "thumbnail": {"enabled": False}
    }
})
```

### Offline operation

Disable all network-dependent features for air-gapped environments:

```py
ctx = Context.from_dict({
    "verify": {
        "remote_manifest_fetch": False,
        "ocsp_fetch": False
    }
})

reader = Reader("local_asset.jpg", context=ctx)
```

### Strict validation

For certification or compliance testing, enable strict validation:

```py
ctx = Context.from_dict({
    "verify": {
        "strict_v1_validation": True,
        "ocsp_fetch": True,
        "verify_trust": True,
        "verify_timestamp_trust": True
    }
})

reader = Reader("asset_to_validate.jpg", context=ctx)
```

### Production configuration

```py
with open("trust-anchors.pem", "r") as f:
    trust_anchors = f.read()

ctx = Context.from_dict({
    "trust": {
        "trust_anchors": trust_anchors,
        "trust_config": "1.3.6.1.5.5.7.3.4\n1.3.6.1.5.5.7.3.36"
    },
    "core": {"backing_store_memory_threshold_in_mb": 1024},
    "builder": {
        "intent": {"Create": "digitalCapture"},
        "thumbnail": {"long_edge": 512, "quality": "high"}
    }
})
```

### Layered configuration

Load base configuration and apply runtime overrides:

```py
import json

with open("config/base.json", "r") as f:
    base_config = json.load(f)

settings = Settings.from_dict(base_config)
settings.update({"builder": {"claim_generator_info": {"version": app_version}}})

ctx = Context(settings)
```

### Configuration from environment variables

```py
import os

env = os.environ.get("ENVIRONMENT", "dev")

settings = Settings()
if env == "production":
    settings.update({"verify": {"strict_v1_validation": True}})
else:
    settings.update({"verify": {"remote_manifest_fetch": False}})

ctx = Context(settings)
```

## Configuring signers

### Signing concepts

C2PA uses a certificate-based trust model to prove who signed an asset. When creating a `Signer`, the following are key parameters:

- **Certificate chain** (`sign_cert`): An X.509 certificate chain in PEM format. The first certificate identifies the signer; subsequent certificates form a chain up to a trusted root. Verifiers use this chain to confirm the signature comes from a trusted source.
- **Timestamp authority URL** (`ta_url`): An optional [RFC 3161](https://www.rfc-editor.org/rfc/rfc3161) timestamp server URL. When provided, the SDK requests a trusted timestamp during signing, proving _when_ the signature was made. This keeps signatures verifiable even after the signing certificate expires.

### Signer from settings (recommended)

Configure signer credentials directly in settings. This is the most common approach:

```py
ctx = Context.from_dict({
    "signer": {
        "local": {
            "alg": "ps256",
            "sign_cert": "-----BEGIN CERTIFICATE-----\nMIIExample...\n-----END CERTIFICATE-----",
            "private_key": "-----BEGIN PRIVATE KEY-----\nMIIExample...\n-----END PRIVATE KEY-----",
            "tsa_url": "http://timestamp.digicert.com"
        }
    }
})

builder = Builder(manifest_json, ctx)
with open("source.jpg", "rb") as src, open("output.jpg", "w+b") as dst:
    builder.sign("image/jpeg", src, dst)
```

### Signer on Context (signer object)

Create a `Signer` object and pass it to the `Context`. The signer is **consumed**: the `Signer` object becomes invalid after this call and the `Context` takes ownership.

```py
from c2pa import Context, Settings, Builder, Signer, C2paSignerInfo, C2paSigningAlg

signer_info = C2paSignerInfo(
    C2paSigningAlg.ES256, cert_data, key_data, b"http://timestamp.digicert.com"
)
signer = Signer.from_info(signer_info)

ctx = Context(settings, signer)
# signer is now invalid and must not be used directly again

builder = Builder(manifest_json, ctx)
with open("source.jpg", "rb") as src, open("output.jpg", "w+b") as dst:
    builder.sign("image/jpeg", src, dst)
```

### Explicit signer at signing time

For full programmatic control, pass a `Signer` directly to `Builder.sign()`:

```py
signer = Signer.from_info(signer_info)
builder = Builder(manifest_json, ctx)

with open("source.jpg", "rb") as src, open("output.jpg", "w+b") as dst:
    builder.sign(signer, "image/jpeg", src, dst)
```

### Precedence rules

If both an explicit signer (passed to `sign()`) and a context signer are available, the explicit signer always takes precedence.

### Remote signer

Use a remote signer when the private key is stored on a secure signing service (HSM, cloud KMS, and so on):

```py
ctx = Context.from_dict({
    "signer": {
        "remote": {
            "alg": "ps256",
            "url": "https://my-signing-service.com/sign",
            "sign_cert": "-----BEGIN CERTIFICATE-----\nMIIExample...\n-----END CERTIFICATE-----",
            "tsa_url": "http://timestamp.digicert.com"
        }
    }
})
```

For all `signer.local` and `signer.remote` properties, see the [SDK object reference - Settings](https://opensource.contentauthenticity.org/docs/manifest/json-ref/settings-schema/#signersettings).

## Advanced topics

### Context lifetime

`Context` supports the `with` statement for automatic resource cleanup:

```py
with Context() as ctx:
    reader = Reader("image.jpg", context=ctx)
    print(reader.json())
# Resources are automatically released
```

### Reusable contexts

You can reuse the same `Context` to create multiple readers and builders. The `Context` can be closed after construction; readers and builders it was used to create still work correctly.

```py
ctx = Context(settings)

builder1 = Builder(manifest1, ctx)
builder2 = Builder(manifest2, ctx)
reader = Reader("image.jpg", context=ctx)
```

### Multiple contexts for different purposes

Use different `Context` objects when you need different configurations at the same time:

```py
dev_ctx = Context(dev_settings)
prod_ctx = Context(prod_settings)

dev_builder = Builder(manifest, dev_ctx)
prod_builder = Builder(manifest, prod_ctx)
```

### ContextProvider abstract base class

`ContextProvider` is an abstract base class (ABC) that enables custom context provider implementations. Subclass it and implement the `is_valid` and `execution_context` abstract properties to create a provider that can be passed to `Reader` or `Builder` as a context. The built-in `Context` class inherits from `ContextProvider`.

```py
from c2pa import ContextProvider, Context

ctx = Context()
assert isinstance(ctx, ContextProvider)  # True
```

## Migrating from load_settings

The `load_settings()` function is deprecated. Replace it with `Settings` and `Context` APIs:

| Aspect | `load_settings` (legacy) | `Context` |
|--------|--------------------------|-----------|
| Scope | Global state | Per Reader/Builder, passed explicitly |
| Multiple configs | Not supported | One context per configuration |
| Testing | Shared global state | Isolated contexts per test |

**Deprecated:**

```py
from c2pa import load_settings, Reader

load_settings({"builder": {"thumbnail": {"enabled": False}}})
reader = Reader("image.jpg")  # uses global settings
```

**Current approach:**

```py
from c2pa import Settings, Context, Reader

ctx = Context.from_dict({"builder": {"thumbnail": {"enabled": False}}})
reader = Reader("image.jpg", context=ctx)
```

## See also

- [Usage](usage.md): reading and signing with `Reader` and `Builder`.
- [CAI settings schema reference](https://opensource.contentauthenticity.org/docs/manifest/json-ref/settings-schema/): full schema reference.
