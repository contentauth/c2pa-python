# Using the Python library

This package works with media files in the [supported formats](https://github.com/contentauth/c2pa-rs/blob/main/docs/supported-formats.md).

## Import

Import the API as follows:

```py
from c2pa import *
```

## Define manifest JSON

The Python library works with both file-based and stream-based operations.
In both cases, the manifest JSON string defines the C2PA manifest to add to an asset; for example:

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

## Signing function

The `sign_ps256` function is [defined in the library](https://github.com/contentauth/c2pa-python/blob/main/c2pa/c2pa_api/c2pa_api.py#L244) and  used in both file-based and stream-based methods. It's reproduced here to show how signing is performed.

```py
# Example of using Python crypto to sign data using openssl with Ps256
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

def sign_ps256(data: bytes, key: bytes) -> bytes:
    private_key = serialization.load_pem_private_key(
        key,
        password=None,
    )
    signature = private_key.sign(
        data,
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.MAX_LENGTH
        ),
        hashes.SHA256()
    )
    return signature
```

## File-based operation

### Read and validate C2PA data

Use the `Reader` to read C2PA data from the specified asset file. 

This examines the specified media file for C2PA data and generates a report of any data it finds. If there are validation errors, the report includes a `validation_status` field.

An asset file may contain many manifests in a manifest store. The most recent manifest is identified by the value of the `active_manifest` field in the manifests map. The manifests may contain binary resources such as thumbnails which can be retrieved with `resource_to_stream` or `resource_to_file` using the associated `identifier` field values and a `uri`.

NOTE: For a comprehensive reference to the JSON manifest structure, see the [Manifest store reference](https://opensource.contentauthenticity.org/docs/manifest/manifest-ref).

```py
try:
  # Create a reader from a file path
  reader = c2pa.Reader.from_file("path/to/media_file.jpg")

  # Print the JSON for a manifest. 
  print("Manifest store:", reader.json())

  # Get the active manifest.
  manifest = reader.get_active_manifest()
  if manifest != None:

    # get the uri to the manifest's thumbnail and write it to a file
    uri = manifest["thumbnail"]["identifier"]
    reader.resource_to_file(uri, "thumbnail_v2.jpg") 

except Exception as err:
    print(err)
```

### Add a signed manifest

**WARNING**: This example accesses the private key and security certificate directly from the local file system.  This is fine during development, but doing so in production may be insecure. Instead use a Key Management Service (KMS) or a hardware security module (HSM) to access the certificate and key; for example as show in the [C2PA Python Example](https://github.com/contentauth/c2pa-python-example).

Use a `Builder` to add a manifest to an asset:

```py
def test_v2_sign(self):
    # Define source folder for any assets being read.
    data_dir = "tests/fixtures/"
    try:
        key = open(data_dir + "ps256.pem", "rb").read()
        def sign(data: bytes) -> bytes:
            return sign_ps256(data, key)

        certs = open(data_dir + "ps256.pub", "rb").read()
        # Create a local signer from a certificate pem file.
        signer = create_signer(sign, SigningAlg.PS256, certs, "http://timestamp.digicert.com")

        builder = Builder(manifest_def)

        builder.add_ingredient_file(ingredient_def, data_dir + "A.jpg")

        builder.add_resource_file("A.jpg", data_dir + "A.jpg")

        builder.to_archive(open("target/archive.zip", "wb"))

        builder = Builder.from_archive(open("target/archive.zip", "rb"))

        with tempfile.TemporaryDirectory() as output_dir:
            output_path = output_dir + "out.jpg"
            if os.path.exists(output_path):
                os.remove(output_path)
            c2pa_data = builder.sign_file(signer, data_dir + "A.jpg", output_dir + "out.jpg")
            assert len(c2pa_data) > 0

        reader = Reader.from_file(output_dir + "out.jpg")
        print(reader.json())
        manifest_store = json.loads(reader.json())
        manifest = manifest_store["manifests"][manifest_store["active_manifest"]]
        assert "python_test" in manifest["claim_generator"]
        # Check custom title and format.
        assert manifest["title"]== "My Title" 
        assert manifest,["format"] == "image/jpeg"
        # There should be no validation status errors.
        assert manifest.get("validation_status") == None
        assert manifest["ingredients"][0]["relationship"] == "parentOf"
        assert manifest["ingredients"][0]["title"] == "A.jpg"

    except Exception as e:
        print("Failed to sign manifest store: " + str(e))
        exit(1)
```

## Stream-based operation

Instead of working with files, you can read, validate, and add a signed manifest to streamed data.  This example code does the same thing as the file-based example.

### Read and validate C2PA data

```py
try:
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

### Add a signed manifest to a stream

**WARNING**: This example accesses the private key and security certificate directly from the local file system.  This is fine during development, but doing so in production may be insecure. Instead use a Key Management Service (KMS) or a hardware security module (HSM) to access the certificate and key; for example as show in the [C2PA Python Example](https://github.com/contentauth/c2pa-python-example).

Use a `Builder` to add a manifest to an asset:

```py
from c2pa import Builder, Error, Reader, SigningAlg, create_signer, sdk_version, sign_ps256, version
...
data_dir = "tests/fixtures/"
try:
    key = open(data_dir + "ps256.pem", "rb").read()
    def sign(data: bytes) -> bytes:
        return sign_ps256(data, key)

    certs = open(data_dir + "ps256.pub", "rb").read()
    # Create a local signer from a certificate pem file
    signer = create_signer(sign, SigningAlg.PS256, certs, "http://timestamp.digicert.com")

    builder = Builder(manifest_def)

    builder.add_ingredient_file(ingredient_def, data_dir + "A.jpg")
    builder.add_resource_file("A.jpg", data_dir + "A.jpg")
    builder.to_archive(open("target/archive.zip", "wb"))
    
    builder = Builder.from_archive(open("target/archive.zip", "rb"))

    with tempfile.TemporaryDirectory() as output_dir:
        output_path = output_dir + "out.jpg"
        if os.path.exists(output_path):
            os.remove(output_path)
        c2pa_data = builder.sign_file(signer, data_dir + "A.jpg", output_dir + "out.jpg")
        assert len(c2pa_data) > 0

    reader = Reader.from_file(output_dir + "out.jpg")
    print(reader.json())
    manifest_store = json.loads(reader.json())
    manifest = manifest_store["manifests"][manifest_store["active_manifest"]]

except Exception as e:
    print("Failed to sign manifest store: " + str(e))
    exit(1)
 ```
