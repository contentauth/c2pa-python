# C2PA Python

Python bindings for the C2PA Content Authenticity Initiative (CAI) library.

This library enables you to read and validate C2PA data in supported media files and add signed manifests to supported media files.

**NOTE**: This is a completely different API from 0.4.0. Check [Release notes](#release-notes) for changes.

**WARNING**: This is an prerelease version of this library.  There may be bugs and unimplemented features, and the API is subject to change.

## Installation

Install from PyPI by entering this command:

```
pip install -U c2pa-python
```

This is a platform wheel built with Rust that works on Windows, macOS, and most Linux distributions (using [manylinux](https://github.com/pypa/manylinux)). If you need to run on another platform, see [Development](#development) for information on how to build from source.

### Reinstalling 

If you tried unsuccessfully to install this package before the [0.40 release](https://github.com/contentauth/c2pa-python/releases/tag/v0.4), then use this command to reinstall: 

```
pip install --upgrade --force-reinstall c2pa-python
```

## Usage

### Import

Import the API as follows:

```py
from c2pa import *
```

### Read and validate C2PA data in a file or stream

Use the `Reader` to read C2PA data from the specified file.
This  examines the specified media file for C2PA data and generates a report of any data it finds. If there are validation errors, the report includes a `validation_status` field.  For a summary of supported media types, see [Supported file formats](#supported-file-formats).

A media file may contain many manifests in a manifest store. The most recent manifest is identified by the value of the `active_manifest` field in the manifests map.

The manifests may contain binary resources such as thumbnails which can be retrieved with `resource_to_stream` or `resource_to_file` using the associated `identifier` field values and a `uri`.

NOTE: For a comprehensive reference to the JSON manifest structure, see the [Manifest store reference](https://opensource.contentauthenticity.org/docs/manifest/manifest-ref).
```py
try:
  # Create a reader from a file path
  reader = c2pa.Reader.from_file("path/to/media_file.jpg")
  # It's also possible to create a reader from a format and stream
  # Note that these two readers are functionally equivalent
  stream = open("path/to/media_file.jpg", "rb")
  reader = c2pa.Reader("image/jpeg", stream)

  # Print the JSON for a manifest. 
  print("manifest store:", reader.json())

  # Get the active manifest.
  manifest = reader.get_active_manifest()
  if manifest != None:

    # get the uri to the manifest's thumbnail and write it to a file
    uri = manifest["thumbnail"]["identifier"]
    reader.resource_to_file(uri, "thumbnail_v2.jpg") 

except Exception as err:
    print(err)
```

### Add a signed manifest to a media file or stream

**WARNING**: This example accesses the private key and security certficate directly from the local file system.  This is fine during development, but doing so in production may be insecure. Instead use a Key Management Service (KMS) or a hardware security module (HSM) to access the certificate and key; for example as show in the [C2PA Python Example](https://github.com/contentauth/c2pa-python-example).

Use a `Builder` to add a manifest to an asset:

```py
try:
  # Define a function to sign the claim bytes
  # In this case we are using a pre-defined sign_ps256 method, passing in our private cert
  # Normally this cert would be kept safe in some other location
  def private_sign(data: bytes) -> bytes:
    return sign_ps256(data, "tests/fixtures/ps256.pem")

  # read our public certs into memory    
  certs = open(data_dir + "ps256.pub", "rb").read()
  
  # Create a signer from the private signer, certs and a time stamp service url
  signer = create_signer(private_sign, SigningAlg.PS256, certs, "http://timestamp.digicert.com")

  # Define a manifest with thumbnail and an assertion.
  manifest_json = {
      "claim_generator_info": [{
          "name": "python_test",
          "version": "0.1"
      }],
      "title": "Do Not Train Example",
      "thumbnail": {
          "format": "image/jpeg",
          "identifier": "thumbnail"
      },
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
  }

  # Create a builder add a thumbnail resource and an ingredient file.
  builder = Builder(manifest_json)

  # The uri provided here "thumbnail" must match an identifier in the manifest definition.
  builder.add_resource_file("thumbnail", "tests/fixtures/A_thumbnail.jpg")

  # Or add the resource from a stream
  a_thumbnail_jpg_stream = open("tests/fixtures/A_thumbnail.jpg", "rb")
  builder.add_resource("image/jpeg", a_thumbnail_jpg_stream)

  # Define an ingredient, in this case a parent ingredient named A.jpg, with a thumbnail
  ingredient_json = {
    "title": "A.jpg",
    "relationship": "parentOf", # "parentOf", "componentOf" or "inputTo"
    "thumbnail": {
        "identifier": "thumbnail",
        "format": "image/jpeg"
    }
  }

  # Add the ingredient to the builder loading information  from a source file.
  builder.add_ingredient_file(ingredient_json, "tests/fixtures/A.jpg")

  # Or add the ingredient from a stream
  a_jpg_stream = open("tests/fixtures/A.jpg", "rb")
  builder.add_ingredient("image/jpeg", a_jpg_stream)

  # At this point we could archive or unarchive our Builder to continue later.
  # In this example we use a bytearray for the archive stream.
  # all ingredients and resources will be saved in the archive
  archive = io.BytesIO(bytearray())
  builder.to_archive(archive)
  archive.seek()
  builder = builder.from_archive(archive)

  # Sign and add our manifest to a source file, writing it to an output file.
  # This returns the binary manifest data that could be uploaded to cloud storage.
  c2pa_data = builder.sign_file(signer, "tests/fixtures/A.jpg", "target/out.jpg")

  # Or sign the builder with a stream and output it to a stream
  input_stream = open("tests/fixtures/A.jpg", "rb")
  output_stream = open("target/out.jpg", "wb")
  c2pa_data = builder.sign(signer, "image/jpeg", input_stream, output_stream)

except Exception as err:
    print(err)
 ```

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


## Development

It is best to [set up a virtual environment](https://virtualenv.pypa.io/en/latest/installation.html) for development and testing. To build from source on Linux, install `curl` and `rustup` then set up Python.

First update `apt` then (if needed) install `curl`:

```
apt update
apt install curl
```

Install Rust:

```
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
source "$HOME/.cargo/env"
```

Install Python, `pip`, and `venv`:

```
apt install python3
apt install pip
apt install python3.11-venv
python3 -m venv .venv
```

Build the wheel for your platform:

```
source .venv/bin/activate
pip install maturin
pip install uniffi-bindgen
python3 -m pip install build
pip install -U pytest

python3 -m build --wheel
```

### ManyLinux build

Build using [manylinux](https://github.com/pypa/manylinux) by using a Docker image as follows:

```
docker run -it quay.io/pypa/manylinux_2_28_aarch64 bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
source "$HOME/.cargo/env"
export PATH=/opt/python/cp312-cp312/bin:$PATH
pip install maturin
pip install venv
pip install build
pip install -U pytest

cd home
git clone https://github.com/contentauth/c2pa-python.git 
cd c2pa-python
python3 -m build --wheel
auditwheel repair target/wheels/c2pa_python-0.4.0-py3-none-linux_aarch64.whl 
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

For example:

```
source .venv/bin/activate
maturin develop
python3 tests/training.py
deactivate
```

## Release notes

### Version 0.5.0

- This release rewrites the API to be stream based using a Builder and Reader model.
- The functions now support throwing c2pa.Error values, caught with try/except.
- Instead of `c2pa.read_file` you now call `c2pa_api.Reader.from_file` and `reader.json`.
- Read thumbnails and other resources use `reader.resource_to_stream` or `reader.resource.to_file`.
- Instead of `c2pa.sign_file` use `c2pa_api.Builder.from_json` and `builder.sign` or `builder.sign_file`.
- Add thumbnails or other resources with `builder.add_resource` or `builder.add_resource_file`.
- Add Ingredients with `builder.add_ingredient` or `builder.add_ingredient_file`.
- You can archive a `Builder` using `builder.to_archive` and reconstruct it with `builder.from_archive`.
- Signers can be constructed with `c2pa_api.create_signer`.
- The signer now requires a signing function to keep private keys private.
- Example signing functions are provided in c2pa_api.py

### Version 0.4.0

This release:

- Changes the name of the import from `c2pa-python` to `c2pa`.
- Supports pre-built platform wheels for macOS, Windows and [manylinux](https://github.com/pypa/manylinux).

### Version 0.3.0

This release includes some breaking changes to align with future APIs:
- `C2paSignerInfo` moves the `alg` to the first parameter from the 3rd.
- `c2pa.verify_from_file_json` is now `c2pa.read_file`.
- `c2pa.ingredient_from_file_json` is now `c2pa.read_ingredient_file`.
- `c2pa.add_manifest_to_file_json` is now `c2pa.sign_file`.
- There are many more specific errors types now, and Error messages always start with the name of the error i.e (str(err.value).startswith("ManifestNotFound")).
- The ingredient thumbnail identifier may be jumbf uri reference if a valid thumb already exists in the active manifest.
- Extracted file paths for read_file now use a folder structure and different naming conventions.

## License

This package is distributed under the terms of both the [MIT license](https://github.com/contentauth/c2pa-python/blob/main/LICENSE-MIT) and the [Apache License (Version 2.0)](https://github.com/contentauth/c2pa-python/blob/main/LICENSE-APACHE).

Note that some components and dependent crates are licensed under different terms; please check the license terms for each crate and component for details.

### Contributions and feedback

We welcome contributions to this project.  For information on contributing, providing feedback, and about ongoing work, see [Contributing](https://github.com/contentauth/c2pa-python/blob/main/CONTRIBUTING.md).


