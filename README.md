# C2PA Python

Python bindings for the C2PA Content Authenticity Initiative (CAI) library.

This library enables you to read and validate C2PA data in supported media files and add signed manifests to supported media files.

**WARNING**: This is an early prerelease version of this library.  There may be bugs and unimplemented features, and the API is subject to change.

## Installation

Install from PyPI by entering this command:

```
pip install -U c2pa-python
```

## Usage

### Import

Import the C2PA module as follows:

```py
import c2pa_python as c2pa
```

### Read and validate C2PA data in a file

Use the `read_file` function to read C2PA data from the specified file:

```py
json_store = c2pa.read_file("path/to/media_file.jpg", "path/to/data_dir")
```

This function examines the specified media file for C2PA data and generates a JSON report of any data it finds. If there are validation errors, the report includes a `validation_status` field.  For a summary of supported media types, see [Supported file formats](#supported-file-formats).

A media file may contain many manifests in a manifest store. The most recent manifest is identified by the value of the `active_manifest` field in the manifests map.

If the optional `data_dir` is provided, the function extracts any binary resources, such as thumbnails, icons, and C2PA data into that directory. These files are referenced by the identifier fields in the manifest store report.

NOTE: For a comprehensive reference to the JSON manifest structure, see the [CAI manifest store reference](https://contentauth.github.io/json-manifest-reference/manifest-reference).

### Add a signed manifest to a media file

Use the `sign_file` function to add a signed manifest to a media file.

```py
result = c2pa.sign_file("path/to/source.jpg", 
                                        "path/to/dest.jpg", 
                                        manifest_json, 
                                        sign_info, 
                                        data_dir)
```

The parameters (in order) are:
- The source (original) media file.
- The destination file that will contain a copy of the source file with the manifest data added.
- `manifest_json`, a JSON-formatted string containing the manifest data you want to add; see [Creating a manifest JSON definition file](#creating-a-manifest-json-definition-file) below.
- `sign_info`, a `SignerInfo` object instance; see [Generating SignerInfo](#generating-signerinfo) below.
- `data_dir` optionally specifies a directory path from which to load resource files referenced in the manifest JSON identifier fields; for example, thumbnails, icons, and manifest data for ingredients.

### Create a SignerInfo Instance

A `SignerInfo` object contains information about a signature.  To create an instance of `SignerInfo`, first set up the signer information from the public and private key `.pem` files as follows:

```py
certs = open("path/to/public_certs.pem","rb").read()
prv_key = open("path/to/private_key.pem","rb").read()
```

Then create a new `SignerInfo` instance using the keys as follows, specifying the signing algorithm used and optionally a time stamp authority URL:

```py
sign_info = c2pa.SignerInfo("es256", certs, priv_key, "http://timestamp.digicert.com")
```

For the list of supported signing algorithms, see [Creating and using an X.509 certificate](https://opensource.contentauthenticity.org/docs/c2patool/x_509).

### Creating a manifest JSON definition file

The manifest JSON string defines the C2PA manifest to add to the file.

```py
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

It is best to [set up a virtual environment](https://virtualenv.pypa.io/en/latest/installation.html) for development and testing.

We use `maturin` for packaging Rust in Python. Install it as follows: 

```
pip install maturin
```

You also must install `uniffi`, `bindgen`, and `pytest` for testing

```
pip install uniffi_bindgen
pip install -U pytest
pip install <path-to-whl> --force-reinstall
```

### Testing

We use [PyTest](https://docs.pytest.org/) for testing.

Run tests by entering this command:

```
source .venv/bin/activate
maturin develop
pytest
deactivate
```

### Example 

Run the example code like this:

```
source .venv/bin/activate
maturin develop
python3 tests/training.py
deactivate
```

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


## Change Notes:

Version 0.3.0 changes:
There are some breaking changes to align with future APIs:
- `C2paSignerInfo` moves the `alg` to the first parameter from the 3rd.
- `c2pa.verify_from_file_json` is now `c2pa.read_file`.
- `c2pa.ingredient_from_file_json` is now `c2pa.read_ingredient_file`.
- `c2pa.add_manifest_to_file_json` is now `c2pa.sign_file`.
- There are many more specific errors types now, and Error messages always start with the name of the error i.e (str(err.value).startswith("ManifestNotFound")).
- The ingredient thumbnail identifier may be jumbf uri reference if a valid thumb already exists in the active manifest.
- Extracted file paths for read_file now use a folder structure and different naming conventions.

## License

This package is distributed under the terms of both the [MIT license](https://github.com/contentauth/c2pa-rs/blob/main/LICENSE-MIT) and the [Apache License (Version 2.0)](https://github.com/contentauth/c2pa-rs/blob/main/LICENSE-APACHE).

Note that some components and dependent crates are licensed under different terms; please check the license terms for each crate and component for details.

### Contributions and feedback

We welcome contributions to this project.  For information on contributing, providing feedback, and about ongoing work, see [Contributing](https://github.com/contentauth/c2pa-js/blob/main/CONTRIBUTING.md).


