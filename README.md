# C2PA Python

Python bindings for the C2PA Content Authenticity Initiative (CAI) library

This library allows you to read and validate c2pa data in supported media files
And to add signed manifests to supported media files.

## Installation

```pip install c2pa-python```

## Usage

### Import

```import c2pa-python as c2pa```

### Reading and Validating C2PA data in a file

Read any C2PA data from a given file 

```json_store = c2pa.verify_from_file_json("path/to/media_file.jpg", data_dir)```

This will examine any supported media file for c2pa data and generate
a JSON report of any data it finds. The report will include a validation_status field if any validation errors were found.

A media file may contain many manifests in a manifest store. The most recent manifest can be accessed by looking up the active_manifest field value in the manifests map.

If the optional data_dir is provided, any binary resources, such as thumbnails, icons and c2pa_data will be extracted into that directory.
These files will be referenced by the identifier fields in the manifest store report.


### Adding a Signed Manifest to a media file
The source is the media file which should receive new c2pa data.
The destination will have a copy of the source with the data added.
The manifest Json is a a JSON formatted string containing the data you want to add.
(see: [Generating SignerInfo](#generating-signerinfo) for how to construct SignerInfo)
The optional data_dir allows you to load resource files referenced from manifest_json identifiers.
When building your manifest, any files referenced by identifier fields will be loaded relative to this path.
This allows you to load thumbnails, icons and manifest data for ingredients

```result = c2pa.add_manifest_to_file_json("path/to/source.jpg", "path/to/dest.jpg", manifest_json, sign_info, data_dir)```

### Generating SignerInfo

Set up the signer info from pem and key files.

```certs = open("path/to/public_certs.pem","rb").read()```
```prv_key = open("path/to/private_key.pem","rb").read()```

Then create a new SignerInfo instance using those keys.
You must specify the signing algorithm used and may optionally add a time stamp authority URL. 

```sign_info = c2pa.SignerInfo(certs, priv_key, "es256", "http://timestamp.digicert.com") ```


### Creating a Manifest Json Definition File

The manifest json string defines the c2pa to add to the file.

```
manifest_json = json.dumps({
    "claim_generator": "python_test/0.1",
    "assertions": [
    {
      "label": "c2pa.training-mining",
      "data": {
        "entries": {
          "c2pa.ai_generative_training": { "use": "notAllowed" },
          "c2pa.ai_inference": { "use": "notAllowed" },
          "c2pa.ai_training": { "use": "notAllowed" },
          "c2pa.data_mining": { "use": "notAllowed" }
        }
      }
    }
  ]
 })
 ```
## Development

It is best to set up a virtual environment for development and testing
https://virtualenv.pypa.io/en/latest/installation.html

We use maturin for packaging Rust in Python. It can can be installed with pip

```pip install maturin```

You will also need to install uniffi bindgen and pytest for testing

``pip install uniffi_bindgen`` 

``pip install -U pytest`` 

``pip install <path to.whl> --force-reinstall``

### Testing

```pytest```


## Supported file formats

 | Extensions    | MIME type                                           |
 | ------------- | --------------------------------------------------- |
 | `avi`         | `video/msvideo`, `video/avi`, `application-msvideo` |
 | `avif`        | `image/avif`                                        |
 | `c2pa`        | `application/x-c2pa-manifest-store`                 |
 | `dng`         | `image/x-adobe-dng`                                 |
 | `heic`        | `image/heic`                                        |
 | `heif`        | `image/heif`                                        |
 | `jpg`, `jpeg` | `image/jpeg`                                        |
 | `m4a`         | `audio/mp4`                                         |
 | `mp4`         | `video/mp4`, `application/mp4`                      |
 | `mov`         | `video/quicktime`                                   |
 | `png`         | `image/png`                                         |
 | `svg`         | `image/svg+xml`                                     |
 | `tif`,`tiff`  | `image/tiff`                                        |
 | `wav`         | `audio/x-wav`                                       |
 | `webp`        | `image/webp`                                        |

## License

This package is distributed under the terms of both the [MIT license](https://github.com/contentauth/c2pa-rs/blob/main/LICENSE-MIT) and the [Apache License (Version 2.0)](https://github.com/contentauth/c2pa-rs/blob/main/LICENSE-APACHE).

Note that some components and dependent crates are licensed under different terms; please check the license terms for each crate and component for details.

### Contributions and feedback

We welcome contributions to this project.  For information on contributing, providing feedback, and about ongoing work, see [Contributing](https://github.com/contentauth/c2pa-js/blob/main/CONTRIBUTING.md).


