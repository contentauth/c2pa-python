# Python example code 

The `examples` directory contains some small examples of using the Python library.
The examples use asset files from the `tests/fixtures` directory, save the resulting signed assets to the temporary `output` directory, and display manifest store data and other output to the console.

## Signing and verifying assets

The [`examples/sign.py`](https://github.com/contentauth/c2pa-python/blob/main/examples/sign.py) script shows how to sign an asset with a C2PA manifest and verify the asset.


The `examples/sign.py` script shows how to sign an asset with a C2PA manifest and verify it using a callback signer. Callback signers let you define signing logic, for example where to load keys from.

The `examples/sign_info.py` script shows how to sign an asset with a C2PA manifest and verify it using a "default" signer created with the needed signer information.

These statements create a `builder` object with the specified manifest JSON (omitted in the snippet below), call `builder.sign()` to sign and attach the manifest to the source file, `tests/fixtures/C.jpg`, and save the signed asset to the output file, `output/C_signed.jpg`:

```py
manifest_definition = {
  // ... JSON omitted here
}

builder = c2pa.Builder(manifest_definition)

with open(fixtures_dir + "C.jpg", "rb") as source:
    with open(output_dir + "C_signed.jpg", "wb") as dest:
        result = builder.sign(signer, "image/jpeg", source, dest)
```

Then these statements read and verify the signed asset:

```py
print("\nReading signed image metadata:")
with open(output_dir + "C_signed.jpg", "rb") as file:
    reader = c2pa.Reader("image/jpeg", file)
    print(reader.json())
```

## Adding a "do not train" assertion

The [`examples/training.py`](https://github.com/contentauth/c2pa-python/blob/main/examples/training.py) script shows how to add a "do not train" assertion to an asset, then verify the asset and display to the console whether its manifest indicates ML training is allowed.

These statements sign the asset using a stream:

```py
    with open(testFile, "rb") as source_file:
        with open(testOutputFile, "wb") as dest_file:
            result = builder.sign(signer, "image/jpeg", source_file, dest_file)
```

These statements verify the asset and check its attached manifest for a "do not train" assertion:

```py
allowed = True # opt out model, assume training is ok if the assertion doesn't exist
try:
    # Create reader using the current API
    reader = c2pa.Reader(testOutputFile)
    manifest_store = json.loads(reader.json())

    manifest = manifest_store["manifests"][manifest_store["active_manifest"]]
    for assertion in manifest["assertions"]:
        if assertion["label"] == "c2pa.training-mining":
            if getitem(assertion, ("data","entries","c2pa.ai_training","use")) == "notAllowed":
                allowed = False

    # get the ingredient thumbnail and save it to a file using resource_to_stream
    uri = getitem(manifest,("ingredients", 0, "thumbnail", "identifier"))
    with open(output_dir + "thumbnail_v2.jpg", "wb") as thumbnail_output:
        reader.resource_to_stream(uri, thumbnail_output)

except Exception as err:
    sys.exit(err)
```

## Running the examples

To run the examples, make sure you have the c2pa-python package installed (`pip install c2pa-python`) and you're in the root directory of the project. We recommend working using virtual environments (venv). Then run the examples as shown below.

Run the "do not train" assertion example:

```bash
python examples/training.py
```

### Run the callback signing and verification example

In this example, a callback signer is the signer:

```bash
python examples/sign.py
```

### Run the signing and verification example

In this example, `SignerInfo` creates a `Signer` object that signs the manifest.

```bash
python examples/sign_info.py
```
