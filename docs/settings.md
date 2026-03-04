# Using settings

You can configure SDK settings using a JSON format that controls many aspects of the library's behavior.
The settings JSON format is the same across all languages in the SDK (Rust, C/C++, Python, and so on).

This document describes how to use settings in C++. The Settings schema is the same as the [Rust library](https://github.com/contentauth/c2pa-rs); for the complete JSON schema, see the [Settings reference](https://opensource.contentauthenticity.org/docs/manifest/json-ref/settings-schema/).

## Using settings with Context

The recommended approach is to pass settings to a `Context` object and then use the `Context` with `Reader` and `Builder`. This gives you explicit, isolated configuration with no global or thread-local state. For details on creating and using contexts, see [Using Context to configure the SDK](context.md).

**Legacy approach:** The deprecated `c2pa::load_settings(data, format)` sets thread-local settings. Don't use that approach; instead pass a `Context` (with settings) to `Reader` and `Builder`. See [Using Context with Reader](context.md#using-context-with-reader) and [Using Context with Builder](context.md#using-context-with-builder).

## Settings API

Create and configure settings:

| Method | Description |
|--------|-------------|
| `Settings()` | Create default settings with SDK defaults. |
| `Settings(data, format)` | Parse settings from a string. `format` is `"json"` or `"toml"`. Throws `C2paException` on parse error. |
| `set(path, json_value)` | Set a single value by dot-separated path (e.g. `"verify.verify_after_sign"`). Value must be JSON-encoded. Returns `*this` for chaining. Use this for programmatic configuration. |
| `update(data)` | Merge JSON configuration into existing settings (same as `update(data, "json")`). Later keys override earlier ones. Use this to apply configuration files or JSON strings. |
| `update(data, format)` | Merge configuration from a string; `format` is `"json"` or `"toml"`. |
| `is_valid()` | Returns `true` if the object holds a valid handle (e.g. not moved-from). |

**Important notes:**

- Settings are **not copyable**; they are **moveable**. After moving, the source's `is_valid()` is `false`.
- The `set()` and `update()` methods can be chained for sequential configuration.
- When using multiple configuration methods, later calls override earlier ones (last wins).

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

Settings can be provided in **JSON** or **TOML**. Use `Settings(data, format)` with `"json"` or `"toml"`, or pass JSON to `Context(json_string)` or `ContextBuilder::with_json()`. JSON is preferred for settings in the C++ SDK.

```cpp
// JSON
c2pa::Settings settings(R"({"verify": {"verify_after_sign": true}})", "json");

// TOML
c2pa::Settings settings(R"(
    [verify]
    verify_after_sign = true
)", "toml");

// Context from JSON string
c2pa::Context context(R"({"verify": {"verify_after_sign": true}})");
```

To load from a file, read the file contents into a string and pass to `Settings` or use `Context::ContextBuilder::with_json_settings_file(path)`.

## Default configuration

The settings JSON schema&mdash;including the complete default configuration with all properties and their default values&mdash;is shared with all languages in the SDK:

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
    },    
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
| [`builder`](https://opensource.contentauthenticity.org/docs/manifest/json-ref/settings-schema#buildersettings) | Configuration for [Builder](https://contentauth.github.io/c2pa-c/da/db7/classc2pa_1_1Builder.html). |
| [`cawg_trust`](https://opensource.contentauthenticity.org/docs/manifest/json-ref/settings-schema#trust) | Configuration for CAWG trust lists. |
| [`cawg_x509_signer`](https://opensource.contentauthenticity.org/docs/manifest/json-ref/settings-schema#signersettings) | Configuration for the CAWG x.509 signer. |
| [`core`](https://opensource.contentauthenticity.org/docs/manifest/json-ref/settings-schema#core) | Configuration for core features. |
| [`signer`](https://opensource.contentauthenticity.org/docs/manifest/json-ref/settings-schema#signersettings) | Configuration for the base [C2PA signer](https://contentauth.github.io/c2pa-c/d3/da1/classc2pa_1_1Signer.html). |
| [`trust`](https://opensource.contentauthenticity.org/docs/manifest/json-ref/settings-schema#trust) | Configuration for C2PA trust lists. |
| [`verify`](https://opensource.contentauthenticity.org/docs/manifest/json-ref/settings-schema#verify) | Configuration for verification (validation). |

The top-level `version` property must be `1`. All other properties are optional.

For Boolean values, use JSON Booleans `true` and `false`, not the strings `"true"` and `"false"`.

> [!IMPORTANT]
> If you don't specify a value for a property, the SDK uses the default value. If you specify a value of `null`, the property is explicitly set to `null`, not the default. This distinction is important when you want to override a default behavior.

### Trust configuration

The [`trust` properties](https://opensource.contentauthenticity.org/docs/manifest/json-ref/settings-schema/#trust) control which certificates are trusted when validating C2PA manifests.

- Using `user_anchors`: recommended for development
- Using `allowed_list` (bypass chain validation)
- For team development, you can load trust configuration from a file using `ContextBuilder`; see [Using Context to configure the SDK](context.md#using-contextbuilder) for details.

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

```cpp
// Read your test root CA certificate
std::string test_root_ca = R"(-----BEGIN CERTIFICATE-----
MIICEzCCAcWgAwIBAgIUW4fUnS38162x10PCnB8qFsrQuZgwBQYDK2VwMHcxCzAJ
...
-----END CERTIFICATE-----)";

c2pa::Context context(R"({
    "version": 1,
    "trust": {
        "user_anchors": ")" + test_root_ca + R"("
    }
})");

c2pa::Reader reader(context, "signed_asset.jpg");
```

#### Using `allowed_list`

To bypass chain validation, for quick testing, explicitly allow a specific certificate without validating the chain.
For example:

```cpp
// Read your test signing certificate
std::string test_cert = read_file("test_cert.pem");

c2pa::Settings settings;
settings.update(R"({
    "version": 1,
    "trust": {
        "allowed_list": ")" + test_cert + R"("
    }
})");

c2pa::Context context(settings);
c2pa::Reader reader(context, "signed_asset.jpg");
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

```cpp
c2pa::Context context(R"({
    "version": 1,
    "verify": {
        "remote_manifest_fetch": false,
        "ocsp_fetch": false
    }
})");

c2pa::Reader reader(context, "signed_asset.jpg");
```

See also [Using Context with Reader](context.md#using-context-with-reader).

#### Fast development iteration

During active development, you can disable verification for faster iteration:

```cpp
// WARNING: Only use during development, not in production!
c2pa::Settings dev_settings;
dev_settings.set("verify.verify_after_reading", "false");
dev_settings.set("verify.verify_after_sign", "false");

c2pa::Context dev_context(dev_settings);
```

#### Strict validation

For certification or compliance testing, enable strict validation:

```cpp
c2pa::Context context(R"({
    "version": 1,
    "verify": {
        "strict_v1_validation": true,
        "ocsp_fetch": true,
        "verify_trust": true,
        "verify_timestamp_trust": true
    }
})");

c2pa::Reader reader(context, "asset_to_validate.jpg");
auto validation_result = reader.json();
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

```cpp
c2pa::Context context(R"({
    "version": 1,
    "builder": {
        "claim_generator_info": {
            "name": "My Photo Editor",
            "version": "2.1.0",
            "operating_system": "auto"
        }
    }
})");
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

```cpp
c2pa::Context camera_context(R"({
    "version": 1,
    "builder": {
        "intent": {"Create": "digitalCapture"},
        "claim_generator_info": {"name": "Camera App", "version": "1.0"}
    }
})");
```

Or for editing existing content:

```cpp
c2pa::Context editor_context(R"({
    "version": 1,
    "builder": {
        "intent": {"Edit": null},
        "claim_generator_info": {"name": "Photo Editor", "version": "2.0"}
    }
})");
```

### Signer

The [`signer` properties](https://opensource.contentauthenticity.org/docs/manifest/json-ref/settings-schema/#signersettings) configure the primary C2PA signer configuration. Set it to `null` if you provide the signer at runtime, or configure as either a **local** or **remote** signer in settings.

> [!NOTE]
> While you can configure the signer in settings, the typical approach is to pass a `Signer` object directly to the `Builder.sign()` method. Use settings-based signing when you need the same signing configuration across multiple operations or when loading configuration from files.

#### Local signer

Use a local signer when you have direct access to the private key and certificate.
For information on all `signer.local` properties, see [signer.local](https://opensource.contentauthenticity.org/docs/manifest/json-ref/settings-schema/#signerlocal) in the SDK object reference.

**Example: Local signer with ES256**

```cpp
std::string config = R"({
    "version": 1,
    "signer": {
        "local": {
            "alg": "es256",
            "sign_cert": "-----BEGIN CERTIFICATE-----\n...\n-----END CERTIFICATE-----",
            "private_key": "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----",
            "tsa_url": "http://timestamp.digicert.com"
        }
    }
})";

c2pa::Context context(config);
c2pa::Builder builder(context, manifest_json);
// Signer is already configured in context
builder.sign(source_path, dest_path);
```

#### Remote signer

Use a remote signer when the private key is stored on a secure signing service (HSM, cloud KMS, and so on).
For information on all `signer.remote` properties, see [signer.remote](https://opensource.contentauthenticity.org/docs/manifest/json-ref/settings-schema/#signerremote) in the SDK object reference.

The remote signing service receives a POST request with the data to sign and must return the signature in the expected format.

For example:

```cpp
c2pa::Context context(R"({
    "version": 1,
    "signer": {
        "remote": {
            "url": "https://signing-service.example.com/sign",
            "alg": "ps256",
            "sign_cert": "-----BEGIN CERTIFICATE-----\n...\n-----END CERTIFICATE-----",
            "tsa_url": "http://timestamp.digicert.com"
        }
    }
})");
```

### CAWG X.509 signer configuration

The `cawg_x509_signer` property specifies configuration for identity assertions. This has the same structure as `signer` (can be local or remote).

**When to use:** If you need to sign identity assertions separately from the main C2PA claim. When both `signer` and `cawg_x509_signer` are configured, the SDK uses a dual signer:

- Main claim signature comes from `signer`
- Identity assertions are signed with `cawg_x509_signer`

**Example: Dual signer configuration**

```cpp
c2pa::Context context(R"({
    "version": 1,
    "signer": {
        "local": {
            "alg": "es256",
            "sign_cert": "...",
            "private_key": "..."
        }
    },
    "cawg_x509_signer": {
        "local": {
            "alg": "ps256",
            "sign_cert": "...",
            "private_key": "..."
        }
    }
})");
```

For additional JSON configuration examples (minimal configuration, local/remote signer, development/production configurations), see the [Rust SDK settings examples](https://github.com/contentauth/c2pa-rs/blob/main/docs/settings.md#examples).

## See also

- [Using Context to configure the SDK](context.md): how to create and use contexts with settings.
- [Usage](usage.md): reading and signing with `Reader` and `Builder`.
- [Rust SDK settings](https://github.com/contentauth/c2pa-rs/blob/main/docs/settings.md): the shared settings schema, default configuration, and JSON examples (language-independent).
- [CAI settings schema reference](https://opensource.contentauthenticity.org/docs/manifest/json-ref/settings-schema/): full schema reference.
