# Using settings

You can configure SDK settings using a JSON format that controls many aspects of the library's behavior.
The settings JSON format is the same across all languages for the C2PA SDKs (Rust, C/C++, Python, and so on).

This document describes how to use settings in Python. The Settings schema is the same as the [Rust library](https://github.com/contentauth/c2pa-rs); for the complete JSON schema, see the [Settings reference](https://opensource.contentauthenticity.org/docs/manifest/json-ref/settings-schema/).

## Using settings with Context

The recommended approach is to pass settings to a `Context` object and then use the `Context` with `Reader` and `Builder`. This gives you explicit, isolated configuration with no global state. For details on creating and using contexts, see [Using Context to configure the SDK](context.md).

**Legacy approach:** The deprecated `load_settings()` function sets global settings. Don't use that approach; instead pass a `Context` (with settings) to `Reader` and `Builder`. See [Using Context with Reader](context.md#configuring-reader) and [Using Context with Builder](context.md#configuring-builder).

## Settings API

Create and configure settings:

| Method | Description |
|--------|-------------|
| `Settings()` | Create default settings with SDK defaults. |
| `Settings.from_json(json_str)` | Create settings from a JSON string. Raises `C2paError` on parse error. |
| `Settings.from_dict(config)` | Create settings from a Python dictionary. |
| `set(path, value)` | Set a single value by dot-separated path (e.g. `"verify.verify_after_sign"`). Value must be a string. Returns `self` for chaining. Use this for programmatic configuration. |
| `update(data, format="json")` | Merge JSON configuration into existing settings. `data` can be a JSON string or a dict. Later keys override earlier ones. Use this to apply configuration files or JSON strings. Only `"json"` format is supported. |
| `settings["path"] = "value"` | Dict-like setter. Equivalent to `set(path, value)`. |
| `is_valid` | Property that returns `True` if the object holds valid resources (not closed). |
| `close()` | Release native resources. Called automatically when used as a context manager. |

**Important notes:**

- The `set()` and `update()` methods can be chained for sequential configuration.
- When using multiple configuration methods, later calls override earlier ones (last wins).
- Use the `with` statement for automatic resource cleanup.
- Only JSON format is supported for settings in the Python SDK.

```py
from c2pa import Settings

# Create with defaults
settings = Settings()

# Set individual values by dot-notation path
settings.set("builder.thumbnail.enabled", "false")

# Method chaining
settings.set("builder.thumbnail.enabled", "false").set("verify.verify_after_sign", "true")

# Dict-like access
settings["builder.thumbnail.enabled"] = "false"

# Create from JSON string
settings = Settings.from_json('{"builder": {"thumbnail": {"enabled": false}}}')

# Create from a dictionary
settings = Settings.from_dict({"builder": {"thumbnail": {"enabled": False}}})

# Merge additional configuration
settings.update({"verify": {"remote_manifest_fetch": True}})

# Use as a context manager for automatic cleanup
with Settings() as settings:
    settings.set("builder.thumbnail.enabled", "false")
```

## Overview of the Settings structure

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

### Settings format

Settings are provided in **JSON** only. Pass JSON strings to `Settings.from_json()` or dictionaries to `Settings.from_dict()`.

```py
# From JSON string
settings = Settings.from_json('{"verify": {"verify_after_sign": true}}')

# From dict
settings = Settings.from_dict({"verify": {"verify_after_sign": True}})

# Context from JSON string
ctx = Context.from_json('{"verify": {"verify_after_sign": true}}')

# Context from dict
ctx = Context.from_dict({"verify": {"verify_after_sign": True}})
```

To load from a file, read the file contents and pass them to `Settings.from_json()`:

```py
import json

with open("config/settings.json", "r") as f:
    settings = Settings.from_json(f.read())
```

## Default configuration

The settings JSON schema — including the complete default configuration with all properties and their default values — is shared with all languages in the SDK:

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

## Overview of Settings

For a complete reference to all the Settings properties, see the [SDK object reference - Settings](https://opensource.contentauthenticity.org/docs/manifest/json-ref/settings-schema).

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

The top-level `version` property must be `1`. All other properties are optional.

For Boolean values, use JSON Booleans `true` and `false` in JSON strings, or Python `True` and `False` when using `from_dict()` or `update()` with a dict.

> [!IMPORTANT]
> If you don't specify a value for a property, the SDK uses the default value. If you specify a value of `null` (or `None` in a dict), the property is explicitly set to `null`, not the default. This distinction is important when you want to override a default behavior.

### Trust configuration

The [`trust` properties](https://opensource.contentauthenticity.org/docs/manifest/json-ref/settings-schema/#trust) control which certificates are trusted when validating C2PA manifests.

- Using `user_anchors`: recommended for development
- Using `allowed_list` (bypass chain validation)

| Property | Type | Description | Default |
|----------|------|-------------|---------|
| `trust.allowed_list` | string | Explicitly allowed certificates (PEM format). These certificates are trusted regardless of chain validation. Use for development/testing. | — |
| `trust.trust_anchors` | string | Default trust anchor root certificates (PEM format). **Replaces** the SDK's built-in trust anchors entirely. | — |
| `trust.trust_config` | string | Allowed Extended Key Usage (EKU) OIDs. Controls which certificate purposes are accepted (e.g., document signing: `1.3.6.1.4.1.311.76.59.1.9`). | — |
| `trust.user_anchors` | string | Additional user-provided root certificates (PEM format). Adds custom certificate authorities without replacing the SDK's built-in trust anchors. | — |

When using self-signed certificates or custom certificate authorities during development, you need to configure trust settings so the SDK can validate your test signatures.

#### Using `user_anchors`

For development, you can add your test root CA to the trusted anchors without replacing the SDK's default trust store.
For example:

```py
with open("test-ca.pem", "r") as f:
    test_root_ca = f.read()

ctx = Context.from_dict({
    "trust": {
        "user_anchors": test_root_ca
    }
})

reader = Reader("signed_asset.jpg", context=ctx)
```

#### Using `allowed_list`

To bypass chain validation, for quick testing, explicitly allow a specific certificate without validating the chain.
For example:

```py
with open("test_cert.pem", "r") as f:
    test_cert = f.read()

settings = Settings()
settings.update({
    "trust": {
        "allowed_list": test_cert
    }
})

ctx = Context(settings=settings)
reader = Reader("signed_asset.jpg", context=ctx)
```

### CAWG trust configuration

The `cawg_trust` properties configure CAWG (Creator Assertions Working Group) validation of identity assertions in C2PA manifests. The `cawg_trust` object has the same properties as [`trust`](https://opensource.contentauthenticity.org/docs/manifest/json-ref/settings-schema/#trust).

> [!NOTE]
> CAWG trust settings are only used when processing identity assertions with X.509 certificates. If your workflow doesn't use CAWG identity assertions, these settings have no effect.

### Core

The [`core` properties](https://opensource.contentauthenticity.org/docs/manifest/json-ref/settings-schema/#core) specify core SDK behavior and performance tuning options.

Use cases:

- **Performance tuning for large files**: Set `core.backing_store_memory_threshold_in_mb` to `2048` or higher if processing large video files with sufficient RAM.
- **Restricted network environments**: Set `core.allowed_network_hosts` to limit which domains the SDK can contact.

### Verify

The [`verify` properties](https://opensource.contentauthenticity.org/docs/manifest/json-ref/settings-schema/#verify) specify how the SDK validates C2PA manifests. These settings affect both reading existing manifests and verifying newly signed content.

Common use cases include:

- [Offline or air-gapped environments](#offline-or-air-gapped-environments).
- [Fast development iteration](#fast-development-iteration) with verification disabled.
- [Strict validation](#strict-validation) for certification or compliance testing.

By default, the following `verify` properties are `true`, which enables verification:

- `remote_manifest_fetch` - Fetch remote manifests referenced in the asset. Disable in offline or air-gapped environments.
- `verify_after_reading` - Automatically verify manifests when reading assets. Disable only if you want to manually control verification timing.
- `verify_after_sign` - Automatically verify manifests after signing. Recommended to keep enabled to catch signing errors immediately.
- `verify_timestamp_trust` - Verify timestamp authority (TSA) certificates. WARNING: Disabling this setting makes verification non-compliant.
- `verify_trust` - Verify signing certificates against configured trust anchors. WARNING: Disabling this setting makes verification non-compliant.

> [!WARNING]
> Disabling verification options (changing `true` to `false`) can make verification non-compliant with the C2PA specification. Only modify these settings in controlled environments or when you have specific requirements.

#### Offline or air-gapped environments

Set `remote_manifest_fetch` and `ocsp_fetch` to `false` to disable network-dependent verification features:

```py
ctx = Context.from_dict({
    "verify": {
        "remote_manifest_fetch": False,
        "ocsp_fetch": False
    }
})

reader = Reader("signed_asset.jpg", context=ctx)
```

See also [Using Context with Reader](context.md#configuring-reader).

#### Fast development iteration

During active development, you can disable verification for faster iteration:

```py
# WARNING: Only use during development, not in production!
settings = Settings()
settings.set("verify.verify_after_reading", "false")
settings.set("verify.verify_after_sign", "false")

dev_ctx = Context(settings=settings)
```

#### Strict validation

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
validation_result = reader.json()
```

### Builder

The [`builder` properties](https://opensource.contentauthenticity.org/docs/manifest/json-ref/settings-schema/#buildersettings) control how the SDK creates and embeds C2PA manifests in assets.

#### Claim generator information

The `claim_generator_info` object identifies your application in the C2PA manifest. **Recommended fields:**

- `name` (string, required): Your application name (e.g., `"My Photo Editor"`)
- `version` (string, recommended): Application version (e.g., `"2.1.0"`)
- `icon` (string, optional): Icon in C2PA format
- `operating_system` (string, optional): OS identifier or `"auto"` to auto-detect

**Example:**

```py
ctx = Context.from_dict({
    "builder": {
        "claim_generator_info": {
            "name": "My Photo Editor",
            "version": "2.1.0",
            "operating_system": "auto"
        }
    }
})
```

#### Thumbnail settings

The [`builder.thumbnail`](https://opensource.contentauthenticity.org/docs/manifest/json-ref/settings-schema/#thumbnailsettings) properties control automatic thumbnail generation.

For examples of configuring thumbnails for mobile bandwidth or disabling them for batch processing, see [Controlling thumbnail generation](context.md#controlling-thumbnail-generation).

#### Action tracking settings

| Property | Type | Description | Default |
|----------|------|-------------|---------|
| `builder.actions.auto_created_action.enabled` | Boolean | Automatically add a `c2pa.created` action when creating new content. | `true` |
| `builder.actions.auto_created_action.source_type` | string | Source type for the created action. Usually `"empty"` for new content. | `"empty"` |
| `builder.actions.auto_opened_action.enabled` | Boolean | Automatically add a `c2pa.opened` action when opening/reading content. | `true` |
| `builder.actions.auto_placed_action.enabled` | Boolean | Automatically add a `c2pa.placed` action when placing content as an ingredient. | `true` |

#### Other builder settings

| Property | Type | Description | Default |
|----------|------|-------------|---------|
| `builder.intent` | object | Claim intent: `{"Create": "digitalCapture"}`, `{"Edit": null}`, or `{"Update": null}`. Describes the purpose of the claim. | `null` |
| `builder.generate_c2pa_archive` | Boolean | Generate content in C2PA archive format. Keep enabled for standard C2PA compliance. | `true` |

##### Setting Builder intent

You can use `Context` to set `Builder` intent for different workflows.

For example, for original digital capture (photos from camera):

```py
camera_ctx = Context.from_dict({
    "builder": {
        "intent": {"Create": "digitalCapture"},
        "claim_generator_info": {"name": "Camera App", "version": "1.0"}
    }
})
```

Or for editing existing content:

```py
editor_ctx = Context.from_dict({
    "builder": {
        "intent": {"Edit": None},
        "claim_generator_info": {"name": "Photo Editor", "version": "2.0"}
    }
})
```

### Signer

The [`signer` properties](https://opensource.contentauthenticity.org/docs/manifest/json-ref/settings-schema/#signersettings) configure the primary C2PA signer configuration. Set it to `null` if you provide the signer at runtime, or configure as either a **local** or **remote** signer in settings.

> [!NOTE]
> The typical approach in Python is to create a `Signer` object with `Signer.from_info()` and pass it directly to `Builder.sign()`. Alternatively, pass a `Signer` to `Context` for the signer-on-context pattern. See [Configuring a signer](context.md#configuring-a-signer) for details.

#### Local signer

Use a local signer when you have direct access to the private key and certificate.
For information on all `signer.local` properties, see [signer.local](https://opensource.contentauthenticity.org/docs/manifest/json-ref/settings-schema/#signerlocal) in the SDK object reference.

#### Remote signer

Use a remote signer when the private key is stored on a secure signing service (HSM, cloud KMS, and so on).
For information on all `signer.remote` properties, see [signer.remote](https://opensource.contentauthenticity.org/docs/manifest/json-ref/settings-schema/#signerremote) in the SDK object reference.

### CAWG X.509 signer configuration

The `cawg_x509_signer` property specifies configuration for identity assertions. This has the same structure as `signer` (can be local or remote).

**When to use:** If you need to sign identity assertions separately from the main C2PA claim. When both `signer` and `cawg_x509_signer` are configured, the SDK uses a dual signer:

- Main claim signature comes from `signer`
- Identity assertions are signed with `cawg_x509_signer`

For additional JSON configuration examples (minimal configuration, local/remote signer, development/production configurations), see the [Rust SDK settings examples](https://github.com/contentauth/c2pa-rs/blob/main/docs/settings.md#examples).

## See also

- [Using Context to configure the SDK](context.md): how to create and use contexts with settings.
- [Usage](usage.md): reading and signing with `Reader` and `Builder`.
- [Rust SDK settings](https://github.com/contentauth/c2pa-rs/blob/main/docs/settings.md): the shared settings schema, default configuration, and JSON examples (language-independent).
- [CAI settings schema reference](https://opensource.contentauthenticity.org/docs/manifest/json-ref/settings-schema/): full schema reference.
