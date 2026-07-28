# Python example code

The `examples` directory contains some small examples of using this Python library.
The examples use asset files from the `tests/fixtures` directory, save the resulting signed assets to the temporary `output` directory, and display manifest store data and other output to the console.

## Signing and verifying assets

The [`examples/sign.py`](https://github.com/contentauth/c2pa-python/blob/main/examples/sign.py) script shows how to sign an asset with a C2PA manifest and verify the asset.

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

## Using a custom HTTP resolver

A custom HTTP resolver lets you intercept every HTTP request the SDK makes through a `Context`. You can use custom resolvers to add headers, cache responses, log traffic, or serve responses from memory in tests.

A resolver is either an object with a `resolve(request)` method or a plain callable. It receives a request object exposing `.url`, `.method`, `.headers` (dict), and `.body` (bytes), and must return a response object exposing `.status` (int) and `.body` (bytes) — any object with those attributes works, there is no type to import:

```py
class AnHttpResolver:
    def resolve(self, request):
        # request.url, request.method, request.headers, request.body
        return SomeResponse(status=200, body=b"...")

context = c2pa.Context.builder().with_resolver(MyResolver()).build()
reader = c2pa.Reader("image/jpeg", stream, context=context)
```

Raising from the resolver marks the request as a hard failure. Returning a non-200 status passes that status through, and the SDK turns it into a typed `C2paError`.

Two things to note before writing one:

- A custom resolver bypasses the `core.allowed_network_hosts` setting, which only filters the built-in resolver. Host filtering becomes your responsibility.
- The SDK does not follow redirects by default. Delegating to `urllib.request` in the examples below gives you redirect handling for free.

Custom resolvers need a live remote manifest to demonstrate against, so their examples live as runnable tests rather than standalone scripts:

The [`tests/network/test_http_resolver_debug.py`](https://github.com/contentauth/c2pa-python/blob/main/tests/network/test_http_resolver_debug.py) test logs the method and URL of each request and the status of each response, delegating the transfer to `urllib`.

The [`tests/network/test_http_resolver_cache.py`](https://github.com/contentauth/c2pa-python/blob/main/tests/network/test_http_resolver_cache.py) test adds an LRU cache with a TTL (defaults: 100 items, 120 seconds) and retries throttled requests. Only GET requests answered with 200 are cached.

Both use `tests/fixtures/cloud.jpg`, which has no embedded manifest, only a remote one, so they need network access; each test skips (rather than fails) when it can't reach the network. Run them with:

```bash
python -m pytest tests/network/ -v
```

## Running the examples

To run the examples, make sure you have the c2pa-python package installed (`pip install c2pa-python`) and you're in the root directory of the project. We recommend working using virtual environments (venv). Then run the examples as shown below.

### Run the reading C2PA data example

```bash
python examples/read.py
```

### Run the "do not train" assertion example:

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

See [Using a custom HTTP resolver](#using-a-custom-http-resolver) above for the debugging and caching resolver examples — they need internet access, so they live under `tests/network/` as runnable (skip-if-offline) tests instead of standalone scripts here.

## Backend application example

[c2pa-python-example](https://github.com/contentauth/c2pa-python-example) is an example of a simple application that accepts an uploaded JPEG image file, attaches a C2PA manifest, and signs it using a certificate. The app uses the CAI Python library and the Flask Python framework to implement a back-end REST endpoint; it does not have an HTML front-end, so you have to use something like curl to access it. This example is a development setup and should not be deployed as-is to a production environment.
