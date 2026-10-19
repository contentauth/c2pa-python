# AI Workflow Guidelines for c2pa-python

Guidance for AI assistants working with or on c2pa-python, the Python bindings for the
C2PA library. The bindings call the c2pa-rs C FFI library through `ctypes`.

## Read first: when using the library

Writing code that uses this `c2pa` Python package (applications, scripts, examples, tests):
read [Part 1: Using the library](#part-1-using-the-library).

| Topic | Document |
| --- | --- |
| API walkthrough, file and stream operations | [docs/usage.md](docs/usage.md) |
| Class relationships | [docs/class-diagram.md](docs/class-diagram.md) |
| Runnable examples | [examples/README.md](examples/README.md) |
| `Context`, `Settings`, signer configuration, settings reference | [docs/context-settings.md](docs/context-settings.md) |
| Manifest stores, working stores, archives, resources, ingredients | [docs/working-stores.md](docs/working-stores.md) |
| Reading, filtering and rebuilding selected manifest parts | [docs/selective-manifests.md](docs/selective-manifests.md) |
| Builder intents and digital source types | [docs/intents.md](docs/intents.md) |

## Read first: when developing c2pa-python

Changing this repository: read [Part 2: Developing c2pa-python](#part-2-developing-c2pa-python),
and Part 1 for the API the repository exposes.

| Topic | Document |
| --- | --- |
| Setup, wheels, tests, API docs | [docs/project-contributions.md](docs/project-contributions.md) |
| Native pointers, lifecycle, locking, streams | [docs/native-resources-management.md](docs/native-resources-management.md) |

---

## Part 1: Using the library

### Lifetimes and consumption

#### ALWAYS USE `with`

**Every `Reader`, `Builder`, `Signer`, `Context` and `Settings` goes in a `with` block.
No exceptions in new code.**

Each of these objects holds memory allocated by the native library. Python's garbage
collector does not know that memory exists. The `with` block is what frees it, at a
known point, even when the block raises. Without it:

- The native memory stays allocated until `__del__` runs, and when that happens is not
  predictable: an object in a reference cycle waits for the cycle collector, and at
  interpreter shutdown objects are collected in any order.
- A `Reader` opened from a path keeps that file open until it is freed.
- Leaks add up in loops and long-running services, where one `Reader` or `Builder` per
  request without `with` grows memory with every request.

```python
# BAD: native memory released whenever the garbage collector gets to it
reader = Reader("image.jpg")
print(reader.json())

builder = Builder(manifest_definition, ctx)
builder.sign_file("source.jpg", "signed.jpg", signer)
```

```python
# GOOD: released at the end of each block, even on error
with Reader("image.jpg") as reader:
    print(reader.json())

with Builder(manifest_definition, ctx) as builder:
    builder.sign_file("source.jpg", "signed.jpg", signer)
```

Rules for `with`:

- **Nest in dependency order**: `Context` outermost, then `Signer`, then `Builder` or
  `Reader`. Objects close in reverse order, inner first, so nothing outlives what it uses.
  One statement works the same way, right to left:
  `with Context() as ctx, Signer.from_info(info) as signer, Builder(m, ctx) as builder:`
- **Files and streams go in `with` too.** The SDK never closes a file object passed to it;
  the caller that opened it closes it.
  `with open("photo.jpg", "rb") as f, Reader("image/jpeg", f) as reader:`
- **Never let an object escape its block.** Returning or storing a `Reader` created in a
  `with` block hands out a closed object; every method on it raises `C2paError`. Return
  the data instead (`reader.json()`, `reader.get_active_manifest()`).
- **Long-lived objects** that cannot sit in one block (a `Context` stored on a service
  object) use `try`/`finally` with `close()`, or close from the owner's own `close()` /
  `__exit__`. `close()` can be called more than once safely.
- `close()` and `with` are equivalent. `__del__` is a fallback for mistakes, never the
  plan.

Details: [Releasing memory](docs/native-resources-management.md#releasing-memory).

#### What consumes an object

- A `Builder` signs once. `sign()` and `sign_file()` consume it and close it, whether
  signing succeeds or fails. Create a new `Builder`, in its own `with` block, per signed
  output.
- A `Signer` passed to `Context(signer=...)` or `ContextBuilder.with_signer` is consumed.
  The `Context` owns it from then on; do not use the `Signer` again. `Builder.sign`
  without a signer argument uses the context's signer.
- A `Signer` passed to `Builder.sign(signer, ...)` is borrowed and can sign again.
- A `Settings` passed to `Context(settings=...)` or `ContextBuilder.with_settings` is
  borrowed, not consumed: the `Context` copies its configuration and the `Settings`
  object stays open and reusable, unlike `Signer`. Close it yourself, or let its own
  `with` block do it; the `Context` does not close it for you.
- A failed `with_archive` can consume the `Builder`; create a new one to retry.
- Any method on a closed object raises `C2paError`.

#### Threads

Read-only calls (`Reader.json()`, `get_active_manifest()`, ...) on one object can run from
several threads. A mutating call (`add_ingredient`, `with_archive`, `sign`, ...) on an
object another thread is using can fail with `C2paError` ("in use by another operation",
"running a mutating operation") instead of waiting. Use one `Builder` per thread, and do
not close an object another thread is still using.

### C2PA concepts

| Term | Meaning in this library |
| --- | --- |
| Manifest | One signed set of provenance statements about an asset: claim, assertions, ingredients, signature. |
| Manifest store | All manifests attached to an asset. |
| Active manifest | The most recent manifest in the store. Its label is the `active_manifest` field of the store JSON. |
| Assertion | One statement inside a manifest, identified by a label (example: `c2pa.actions`). |
| Action | An entry in the `c2pa.actions` assertion describing what was done to the asset (`c2pa.created`, `c2pa.edited`, ...). |
| Ingredient | An asset the current asset was made from. Added with `Builder.add_ingredient`. A `parentOf` ingredient is the asset being edited. |
| Resource | Binary data referenced by a manifest (thumbnails, icons). Added by identifier with `Builder.add_resource`; in the signed store the identifier becomes a JUMBF URI, read back with `Reader.resource_to_stream`. |
| Working store | An unsigned manifest under construction. In this library, a `Builder`. |
| Archive | A serialized working store (`application/c2pa`), saved with `Builder.to_archive` and restored with `Builder.with_archive`. |
| Signer | Certificate chain, private key (or signing callback), algorithm, optional timestamp authority URL. Wrapped by `Signer`. |
| Trust | Trust anchors and trust settings in `Settings`. A signing certificate that chains to a configured anchor makes a valid manifest `Trusted`. |
| Validation state | `Reader.get_validation_state()`: `Invalid` (a check failed), `Valid` (signature and content bindings check out), `Trusted` (valid, and the signer chains to a configured trust anchor). |
| Digital source type | How the content was made (`DIGITAL_CAPTURE`, `TRAINED_ALGORITHMIC_MEDIA`, ...). Required with `CREATE`. |

Details: [docs/working-stores.md](docs/working-stores.md), [docs/intents.md](docs/intents.md),
[docs/selective-manifests.md](docs/selective-manifests.md), and the
[manifest store reference](https://opensource.contentauthenticity.org/docs/manifest/manifest-ref).

### Public API

Everything public is exported from `c2pa` (`src/c2pa/__init__.py` `__all__`). Import from
the package root only.

| Name | Purpose |
| --- | --- |
| `Context` | Configuration passed to `Reader` and `Builder`: `Settings` plus an optional `Signer`. `Context()`, `Context(settings, signer)`, `Context.from_json`, `Context.from_dict`, `Context.builder()`. |
| `ContextBuilder` | Fluent construction: `Context.builder().with_settings(s).with_signer(sig).build()`. |
| `Settings` | Settings object: `Settings()`, `from_json`, `from_dict`, `set(path, value)`, `update(dict_or_json)`. |
| `ContextProvider` | Abstract base class for custom context providers. `Context` is the standard implementation. |
| `Reader` | Reads and validates a manifest store from a file path or stream. `json()`, `detailed_json()`, `crjson()`, `get_active_manifest()`, `get_manifest(label)`, `get_validation_state()`, `get_validation_results()`, `resource_to_stream(uri, stream)`, `is_embedded()`, `get_remote_url()`, `with_fragment(...)`, `Reader.try_create(...)`. |
| `Builder` | Working store. `Builder(manifest_json, context)`, `add_ingredient`, `add_resource`, `add_action`, `set_intent`, `set_no_embed`, `set_remote_url`, `to_archive`, `with_archive`, `write_ingredient_archive`, `add_ingredient_from_archive`, `sign`, `sign_file`. |
| `Signer` | Signing credentials. `Signer.from_info(C2paSignerInfo)`, `Signer.from_callback(callback, alg, certs, tsa_url)`. |
| `C2paSignerInfo` | Certificate chain, private key, algorithm and timestamp URL for `Signer.from_info`. |
| `Stream` | Internal wrapper around Python file-like objects. Pass ordinary file objects or `io.BytesIO` to the API instead. |
| `C2paSigningAlg` | `ES256`, `ES384`, `ES512`, `PS256`, `PS384`, `PS512`, `ED25519`. |
| `C2paBuilderIntent` | `CREATE`, `EDIT`, `UPDATE`. |
| `C2paDigitalSourceType` | IPTC digital source types (`DIGITAL_CAPTURE`, `TRAINED_ALGORITHMIC_MEDIA`, ...). |
| `C2paError` | Base exception. Typed subclasses: `C2paError.ManifestNotFound`, `C2paError.NotSupported`, `C2paError.Signature`, `C2paError.Verify`, `C2paError.Io`, `C2paError.Json`, ... |
| `sdk_version()` | Version string of the native library. |
| `load_settings()` | Deprecated global settings. Use `Context` instead. |

### Core patterns

#### Read and validate an asset

```python
from c2pa import Reader

with Reader("path/to/image.jpg") as reader:
    store_json = reader.json()
    active = reader.get_active_manifest()
    state = reader.get_validation_state()
```

From a stream, pass the MIME type first:

```python
with open("path/to/image.jpg", "rb") as f:
    with Reader("image/jpeg", f) as reader:
        print(reader.json())
```

An asset without C2PA data raises `C2paError.ManifestNotFound`. To check for a manifest
without exception handling, `Reader.try_create(...)` returns `None` instead.

#### Configure with Context and Settings

```python
from c2pa import Context, Settings, Reader

config = {
    "verify": {"verify_cert_anchors": True},
    "trust": {"trust_anchors": anchors_pem},
}
with Settings.from_dict(config) as settings, Context(settings) as ctx:
    with Reader("path/to/image.jpg", context=ctx) as reader:
        print(reader.get_validation_state())
```

One `Context` can be reused across many `Reader` and `Builder` instances. Settings
reference: [docs/context-settings.md](docs/context-settings.md#settings-reference).

#### Create a signer

From a certificate and key (`Signer.from_info`):

```python
from c2pa import C2paSignerInfo, C2paSigningAlg, Signer

signer_info = C2paSignerInfo(
    alg=C2paSigningAlg.ES256,
    sign_cert=cert_pem_bytes,
    private_key=key_pem_bytes,
    ta_url=b"http://timestamp.digicert.com",
)
with Signer.from_info(signer_info) as signer:
    ...
```

From a callback that signs bytes (`Signer.from_callback`), for keys held in a key
management service or hardware security module:

```python
def sign_bytes(data: bytes) -> bytes:
    return private_key.sign(data, ec.ECDSA(hashes.SHA256()))

with Signer.from_callback(
        sign_bytes, C2paSigningAlg.ES256, cert_chain_pem_str,
        "http://timestamp.digicert.com") as signer:
    ...
```

The callback computes a signature and returns it. It does not call any `c2pa` API.

#### Build and sign

```python
from c2pa import Builder, C2paSignerInfo, C2paSigningAlg, Context, Signer

manifest_definition = {
    "claim_generator_info": [{"name": "my_app", "version": "0.1.0"}],
    "title": "My image",
    "assertions": [{
        "label": "c2pa.actions",
        "data": {"actions": [{
            "action": "c2pa.created",
            "digitalSourceType": "http://cv.iptc.org/newscodes/digitalsourcetype/digitalCreation",
        }]},
    }],
}

signer_info = C2paSignerInfo(
    alg=C2paSigningAlg.ES256,
    sign_cert=cert_pem_bytes,
    private_key=key_pem_bytes,
    ta_url=b"http://timestamp.digicert.com",
)
with Context() as ctx, Signer.from_info(signer_info) as signer, \
        Builder(manifest_definition, ctx) as builder:
    builder.sign_file("source.jpg", "signed.jpg", signer)
```

`digitalSourceType` on `c2pa.created` must match how the asset was actually made: a camera
capture is `http://cv.iptc.org/newscodes/digitalsourcetype/digitalCapture`, generative AI
output is `http://cv.iptc.org/newscodes/digitalsourcetype/trainedAlgorithmicMedia`, and so
on. Do not copy `digitalCreation` from this example without checking it applies. When the
source type is unknown, use `http://c2pa.org/digitalsourcetype/empty`
(`C2paDigitalSourceType.EMPTY` with `set_intent`).

With streams:

```python
with Builder(manifest_definition, ctx) as builder:
    with open("source.jpg", "rb") as source, open("signed.jpg", "w+b") as dest:
        manifest_bytes = builder.sign(signer, "image/jpeg", source, dest)
```

`sign_file` infers the format from the file extension and raises
`C2paError.NotSupported` when it cannot.

#### Ingredients, resources, actions, intents

```python
with Builder(manifest_definition, ctx) as builder:
    with open("parent.jpg", "rb") as parent:
        builder.add_ingredient(
            {"title": "parent.jpg", "relationship": "parentOf"}, "image/jpeg", parent)
    with open("thumbnail.jpg", "rb") as thumb:
        builder.add_resource("thumbnail", thumb)
    builder.add_action({"action": "c2pa.color_adjustments"})
    builder.set_intent(C2paBuilderIntent.EDIT)
    builder.sign_file("edited.jpg", "edited_signed.jpg", signer)
```

Intent can also come from settings (`{"builder": {"intent": "edit"}}`); `set_intent`
takes precedence. See [docs/intents.md](docs/intents.md).

#### Archives

```python
import io

archive = io.BytesIO()
with Builder(manifest_definition, ctx) as builder:
    with open("thumbnail.jpg", "rb") as thumb:
        builder.add_resource("thumbnail", thumb)
    builder.to_archive(archive)

archive.seek(0)
with Builder({}, ctx) as restored:
    restored.with_archive(archive)
    restored.sign_file("source.jpg", "signed.jpg", signer)
```

`with_archive` keeps the `Context` of the receiving `Builder`; `Builder.from_archive`
creates a `Builder` with no context. Per-ingredient archives:
`write_ingredient_archive` / `add_ingredient_from_archive`, see
[docs/working-stores.md](docs/working-stores.md#working-with-archives).

### Pitfalls

#### DON'T: reuse a Builder after signing

```python
# BAD: the Builder is closed after the first sign
builder.sign_file("a.jpg", "a_signed.jpg", signer)
builder.sign_file("b.jpg", "b_signed.jpg", signer)  # C2paError
```

#### DO: one Builder per output

```python
# GOOD
for src, dst in jobs:
    with Builder(manifest_definition, ctx) as builder:
        builder.sign_file(src, dst, signer)
```

#### DON'T: use a Signer after giving it to a Context

```python
# BAD
with Context(settings, signer) as ctx:
    with Builder(manifest_definition, ctx) as builder:
        builder.sign_file("a.jpg", "out.jpg", signer)  # C2paError: signer is consumed
```

#### DO: let the Context sign, or keep the Signer out of the Context

```python
# GOOD: the Context owns the signer and signs
with Context(settings, signer) as ctx:
    with Builder(manifest_definition, ctx) as builder:
        builder.sign_file("a.jpg", "out.jpg")
```

#### DON'T: configure globally

```python
# BAD: deprecated, process-wide
c2pa.load_settings({"builder": {"thumbnail": {"enabled": False}}})
```

#### DO: pass a Context

```python
# GOOD
with Context.from_dict({"builder": {"thumbnail": {"enabled": False}}}) as ctx:
    with Builder(manifest_definition, ctx) as builder:
        builder.sign_file("source.jpg", "signed.jpg", signer)
```

#### DON'T: treat `Valid` as trusted

`Valid` means the signature and content bindings check out. It says nothing about who
signed. An asset signed with the test certificates in `tests/fixtures/` reads `Valid`
with default settings and `Trusted` only once trust is configured
(`tests/trust_config_test_settings.json` shows the `trust.trust_anchors` /
`trust.trust_config` shape). When the signer's identity matters, configure trust through
`Settings` and require `Trusted`. `get_validation_results()` gives the per-check detail.

#### DON'T: call the SDK from a callback

A signing callback, or a file-like object passed as a stream, runs while a native call on
the `Builder` or `Reader` is in progress. It must not call `c2pa` APIs. A call on the
same object is refused with `C2paError`.

#### DON'T: catch bare `Exception`

```python
# BAD: hides programming errors
try:
    with Reader(path) as reader:
        manifest = reader.get_active_manifest()
except Exception:
    manifest = None
```

#### DO: catch the typed error

```python
# GOOD
try:
    with Reader(path) as reader:
        manifest = reader.get_active_manifest()
except C2paError.ManifestNotFound:
    manifest = None
```

#### DON'T: leave the format to guessing when it is known

Format auto-detection for streams (`Reader(stream)`, `format=None`) is best effort. Pass
the MIME type when it is known. Supported types: `Reader.get_supported_mime_types()`,
`Builder.get_supported_mime_types()`.

---

## Part 2: Developing c2pa-python

### Repository map

| Path | Contents |
| --- | --- |
| `src/c2pa/c2pa.py` | Public API classes and the ctypes bindings |
| `src/c2pa/lib.py` | Native library discovery and loading |
| `src/c2pa/build.py` | `download-artifacts` console entry point |
| `src/c2pa/__init__.py` | Public exports (`__all__`) |
| `src/c2pa/libs/` | Native library staged for the installed package (gitignored) |
| `artifacts/` | Downloaded or locally built native libraries per platform |
| `c2pa-native-version.txt` | Pinned c2pa-rs release tag for `make download-native-artifacts` |
| `scripts/download_artifacts.py` | Download prebuilt native libraries from c2pa-rs releases |
| `scripts/build_local_artifacts.py` | Build the native library from a local c2pa-rs checkout |
| `scripts/generate_api_docs.py` | Sphinx API documentation |
| `tests/unit/` | Unit tests, one module per area (`test_reader.py`, `test_builder.py`, `test_context.py`, ...); shared constants, helpers and `TestContextAPIs` in `_support.py` |
| `tests/test_unit_tests_threaded.py` | Concurrency tests |
| `tests/fixtures/` | Test assets, certificates and keys |
| `tests/perf/` | Memory (memray) and thread-safety harnesses, run in Docker |
| `examples/` | Runnable examples, also run by `make test` |
| `docs/` | User and developer documentation |
| `api-docs/` | Sphinx configuration and output |
| `.github/workflows/` | CI (build and test, wheels, benchmarks, c2pa-rs source build), docs publishing, issue-label automation |

### Workflows

All commands run from the repository root. `make` uses the active virtual environment,
then `./.venv`, then `python3`; override with `make <target> PYTHON=...`.

#### Set up an environment

```bash
make create-venv && source .venv/bin/activate
make download-native-artifacts   # version from c2pa-native-version.txt
make build-python                # pip install -e . (also installs runtime dependencies)
```

Success: `python -c "import c2pa; print(c2pa.sdk_version())"` prints the native version.

`make download-native-artifacts` is required: nothing downloads the native library
automatically. `pip install -e .` only copies it from `artifacts/` into `src/c2pa/libs/`,
and prints "No platform-specific libraries found in artifacts directory" when there is
nothing to copy. Skip the download only when building from source (next workflow).

`make install-deps` (`requirements.txt` and `requirements-dev.txt`) is needed only for the
developer tools: pytest, flake8, autopep8 and Sphinx, used by `make check-format`,
`make format`, `pytest` and `make docs`.

#### Use a local c2pa-rs build

```bash
make build-from-source C2PA_RS_PATH=/path/to/c2pa-rs
make build-from-source C2PA_RS_PATH=/path/to/c2pa-rs EXTRA_BUILD_ARGS="--debug"
```

Needs a Rust toolchain. Builds `c2pa-c-ffi`, stages the library in `artifacts/` and
`src/c2pa/libs/`, and reinstalls the package in editable mode.

`src/c2pa/lib.py` loads the native library; `C2PA_LIBRARY_NAME` overrides the file name.
An import error about missing required function symbols means the loaded library lacks a
name in `_REQUIRED_FUNCTIONS`: a stale copy in `src/c2pa/libs/`, or a c2pa-rs version
older than the bindings expect.

#### Run tests

```bash
make test                                    # examples, unit tests, threaded tests
make test-unit                               # unit tests only
make test-threaded                           # concurrency tests only
make test-one T=tests.unit.test_reader.TestReader.<test_name>   # one module, class or test
pytest tests/unit -v                         # as CI runs them
```

Run new tests by name and read their own result lines; a passing suite does not show a new
test ran.

`TestC2paSdk.test_sdk_version` fails with an assertion like `'0.91.0' not found in
'0.91.1'` when the installed native library's version does not match
`c2pa-native-version.txt`. First troubleshooting step: a clean rebuild --
`make clean-c2pa-env install-deps download-native-artifacts build-python`, or
`make rebuild`.

#### Lint and format

```bash
make check-format   # py_compile + flake8 --extend-ignore=E501 on src/c2pa/c2pa.py
make format         # autopep8
```

CI runs `make check-format` too (`.github/workflows/build.yml`), so this is the one check
to run locally before pushing; no separate command to match by hand.

#### Benchmarks

Run in Docker; details in [tests/perf/README.md](tests/perf/README.md).

```bash
make perf-image            # build the image once
make memory-use-bench      # memray; compares against tests/perf/baseline.json
make threading-bench       # harness self-test, then thread-safety scenarios
```

Required for changes to `ManagedResource`, locking, `Stream`, callbacks, or anything that
allocates or frees native memory.

#### API documentation

```bash
make docs   # output in api-docs/_build/html/index.html
```

A public API change also updates the topic document in `docs/` and
`docs/class-diagram.md`.

#### Versioning

- Python package version: bump `version` in `pyproject.toml` and the `# Version:` header
  in `src/c2pa/c2pa.py` together, on every change that ships.
- `c2pa-native-version.txt`: bump only when pinning a new c2pa-rs release. Not tied to
  the Python package version; bump it alone, then `make download-native-artifacts` and
  run the tests.

#### Pull request titles

Conventional commits: `feat`, `fix`, `chore`, `docs`, `test`, `refactor`, `perf`, `ci`,
`build`, `style`, `revert`, with an optional scope, for example
`feat(builder): Add set_label`. See `CONTRIBUTING.md`.

#### Add a public API feature end to end

1. Confirm the native function exists in the c2pa-rs version pinned in
   `c2pa-native-version.txt`.
2. Bind it following [Changing the binding layer](#changing-the-binding-layer).
3. Add any new public name to `__all__` in `src/c2pa/__init__.py`.
4. Add tests to the matching module in `tests/unit/`; run them by name.
5. Document it in the matching topic document in `docs/` and in `docs/class-diagram.md`.
6. Bump the Python package version.

### Changing the binding layer

Rules for `src/c2pa/c2pa.py` internals: native pointers, locks, strings, errors and
callbacks. Read the `ManagedResource` class docstring and
[docs/native-resources-management.md](docs/native-resources-management.md) first.

#### Core principle: always use the helpers

Every use of a native handle goes through a `ManagedResource` helper. Every native result
goes through `_check_ffi_operation_result`. Every native string goes through
`_convert_to_py_string`. Before writing any ctypes pattern by hand, check whether a helper
exists for it.

---

#### Reference example: `Reader.json`

`Reader.json` shows the full path for one native function. Copy its shape.

##### 1. Register the symbol

Add the name to `_REQUIRED_FUNCTIONS`. Import fails if the loaded library lacks it.

```python
_REQUIRED_FUNCTIONS = [
    ...
    'c2pa_reader_json',
    ...
]
```

##### 2. Declare the prototype

```python
_setup_function(
    _lib.c2pa_reader_json, [
        ctypes.POINTER(C2paReader)], ctypes.c_void_p)
```

The return is an owned native string, so the restype is `c_void_p`. With `c_char_p`,
ctypes copies the bytes into a Python `bytes` object and discards the pointer, so it can
never be freed.

##### 3. Declare instance attributes in `_init_attrs`

```python
def _init_attrs(self):
    super()._init_attrs()
    ...
    self._manifest_json_str_cache = None
```

`_wrap_native_handle` builds instances without running `__init__`, and `_release()` can
run on a half-built object. Every attribute goes in `_init_attrs`.

##### 4. Write the method

```python
def json(self) -> str:
    with self._native_call():
        if self._manifest_json_str_cache is not None:
            return self._manifest_json_str_cache

        result = _lib.c2pa_reader_json(self._handle)
        _check_ffi_operation_result(
            result, "Error during manifest parsing in Reader")

        self._manifest_json_str_cache = _convert_to_py_string(result)
        return self._manifest_json_str_cache
```

- `with self._native_call():` validates state and reserves the handle as a shared call.
  No `_ensure_valid_state()` call is needed inside it.
- `_check_ffi_operation_result(result, msg)` uses the default `not r` check for a pointer
  return, reads the native error and raises a typed `C2paError`.
- `_convert_to_py_string(result)` decodes the string and frees it with
  `c2pa_string_free`.

##### 5. Test

Add a test in `tests/unit/test_reader.py` (`TestReader` covers `json()`). Run it by name
and read its own result line.

---

#### Freeing memory: the free function must match the allocator

Memory is freed by the allocator that issued it, through the free function made for that
kind of allocation. A mismatch is undefined behavior: an abort (SIGABRT) when the
allocator detects it, heap corruption surfacing later when it does not. See
[Crashes](docs/native-resources-management.md#crashes) and
[Freeing memory](docs/native-resources-management.md#freeing-memory).

| What native returned | Free function | Called only from |
| --- | --- | --- |
| Object handle (`C2paReader*`, `C2paBuilder*`, `C2paSigner*`, `C2paContext*`, ...) | `c2pa_free` | `ManagedResource._free_native_ptr`, via `ManagedResource` cleanup |
| C string (`char*`) | `c2pa_string_free` | `_convert_to_py_string` |
| String array plus count | `c2pa_free_string_array(arr, count)` | Next to the call that returned it, with the count native returned |
| Byte buffer plus length (manifest bytes) | `c2pa_manifest_bytes_free` | Next to the call that returned it, in a `finally` |

Rules:

- Native memory is never left to Python's garbage collector. It does not know the pointer exists.
- Python memory (`bytes`, `ctypes.create_string_buffer`, `(c_ubyte * n).from_buffer_copy(...)`,
  callback objects) is never passed to a native free function.
- Native memory is freed exactly once. A pointer handed to a consuming call is never freed by
  Python, whether the call succeeds or fails.
- Copy, then free in `finally`:

```python
try:
    result_bytes = ctypes.string_at(result_bytes_ptr, size)
finally:
    _lib.c2pa_manifest_bytes_free(result_bytes_ptr)
```

- Anything native keeps using after the call returns (callbacks, streams) stays referenced
  from a Python attribute until native is done with it. See
  [Keeping references alive](docs/native-resources-management.md#keeping-references-alive).

---

#### Locking rules

Background: [Locking](docs/native-resources-management.md#locking),
[Lock ordering](docs/native-resources-management.md#lock-ordering),
[Borrowing vs consuming](docs/native-resources-management.md#borrowing-vs-consuming),
[Closing during a (native) call](docs/native-resources-management.md#closing-during-a-native-call),
[Fork safety](docs/native-resources-management.md#fork-safety).

1. **Check and act in one guarded region.** Using a handle is two steps: validate it, then
   pass it to native. Another thread can close the object between the two. The state check
   and the native call always sit inside the same guard.
2. **The GIL protects nothing here.** ctypes releases the GIL for the duration of a foreign
   call. Another thread runs while native code runs, including on free-threaded builds.
3. **Two idioms. Pick one per native call.**

   | Idiom | What it does | State check |
   | --- | --- | --- |
   | `with self._guarded_op():` / `_guarded_op(exclusive=True)` | Holds `_op_lock` across the native call | Call `self._ensure_valid_state()` inside it |
   | `with self._native_call():` (shared) / `with self._exclusive_native_call():` (mutating) | Reserves the handle with in-flight counters; does not hold the lock across the call | Done by the reservation |

4. **Choose by one question: does this native call run caller-supplied Python?**
   Stream read/seek/write/flush callbacks and signer callbacks run Python on this thread
   while native code is mid-call. This covers construction from streams, signing, the
   `Builder` stream methods, `Reader.resource_to_stream`, and anything else taking a `Stream`.
   - Yes: use `_native_call()` or `_exclusive_native_call()`. Never `_guarded_op`.
   - No: default to `_guarded_op`. It holds `_op_lock` for the whole call, so no other
     call on this object can interleave at all, not even another shared call. Use
     `_native_call()` / `_exclusive_native_call()` instead only when something else in the
     same call needs the weaker guarantee (shared calls allowed to overlap).
5. **Shared or exclusive, once rule 4 picked the reservation idiom.** A call that changes
   native state for this handle uses `exclusive=True` / `_exclusive_native_call()`. A
   read-only call uses the shared form. Exclusive calls refuse to start while any call is
   in flight; shared calls refuse while an exclusive call is in flight. Do not add checks
   of your own. (`_guarded_op`'s own `exclusive` flag follows the same split when rule 4
   picks `_guarded_op` instead.)
6. **Consuming calls use the consume helpers**, which reserve the handle as mutating for
   the whole call: `_consume_and_swap`, `_consume_into`, `_consume_no_replacement`.
7. **Lock order**, outermost to innermost: a method-specific lock (for example
   `Reader._fragment_lock`), then the lock of the object the method runs on, then the lock
   of any object it borrows. A lock held across a native call must be one no callback path
   acquires.
8. **Module-level functions** with no `ManagedResource` (for example `format_embeddable`)
   wrap the native call and its result check in `with _native_section():`.
9. **Never touch `_op_lock`, `_inflight`, `_mut_inflight` or `_live_op_lock()` directly.**

---

#### Callbacks: no SDK use inside a callback

A ctypes callback (`ReadCallback`, `SeekCallback`, `WriteCallback`, `FlushCallback`,
`SignerCallback`) runs while a native call on the calling object is in flight. Its body
touches only the Python object it wraps: the file-like stream, or the user's signing
callable.

It never calls `_lib.*` and never calls a `Reader`, `Builder`, `Signer`, `Context` or
`Settings` method. A call on the same object is refused by the in-flight counters, or, if
the outer call wrongly holds `_guarded_op`, re-enters the reentrant lock and reaches native
while native still uses the handle.

Callbacks also:

- Catch every exception and return the error value native expects (`-1` for the existing
  callbacks). An exception escaping a ctypes callback is printed and swallowed by ctypes,
  and native sees a meaningless return value.
- Validate pointer and length arguments before reading through them.
- When the callback needs its owning object (the `Stream` callbacks do), capture it through
  a weak reference and check its state on every call. A strong capture forms a reference
  cycle: object, ctypes callback, closure, object.

See [Streams](docs/native-resources-management.md#streams) and
[Reentrant callbacks](docs/native-resources-management.md#reentrant-callbacks). The
existing callbacks in `Stream.__init__` and `Signer.from_callback` follow these rules.

---

#### Common anti-patterns to AVOID

##### DON'T: assign the handle directly

```python
# BAD
ptr = _lib.c2pa_my_resource_new(arg)
if not ptr:
    raise C2paError("Failed")
self._handle = ptr
self._lifecycle_state = LifecycleState.ACTIVE
```

##### DO: create and activate

```python
# GOOD: validates, takes ownership, frees the pointer if any step fails
self._create_and_activate(
    lambda: _lib.c2pa_my_resource_new(arg),
    "Failed to create MyResource: {}")
```

##### DON'T: free on an error path by hand

```python
# BAD
ptr = _lib.c2pa_reader_from_context(ctx_ptr)
try:
    _check_ffi_operation_result(ptr, "Failed")
except C2paError:
    _lib.c2pa_free(ptr)
    raise
```

##### DO: let the helper own the failure path

```python
# GOOD
self._create_and_activate(
    lambda: _lib.c2pa_reader_from_context(ctx_ptr),
    "Failed to create Reader: {}")
```

##### DON'T: read and free a native string by hand

```python
# BAD: crashes on NULL, leaks on decode error, or frees twice
raw = ctypes.string_at(result)
_lib.c2pa_string_free(result)
return raw.decode('utf-8')
```

##### DO: convert

```python
# GOOD
return _convert_to_py_string(result)
```

##### DON'T: check the result by hand

```python
# BAD: untyped exception, no fallback when native set no error
result = _lib.c2pa_builder_set_remote_url(self._handle, url_bytes)
if result != 0:
    raise C2paError(f"Failed: {_read_native_error()}")
```

##### DO: check with the helper

```python
# GOOD: reads the error once, raises the typed subclass
_check_ffi_operation_result(
    result,
    Builder._ERROR_MESSAGES['url_error'],
    check=lambda r: r != 0)
```

##### DON'T: hold the lock across a callback-driving call

```python
# BAD: the stream callbacks run Python while _op_lock is held
with self._guarded_op(), Stream(stream) as stream_obj:
    self._ensure_valid_state()
    result = _lib.c2pa_reader_resource_to_stream(
        self._handle, uri_str, stream_obj._stream)
```

##### DO: reserve instead

```python
# GOOD: in-flight reservation, lock released during the call
with self._native_call(), Stream(stream) as stream_obj:
    result = _lib.c2pa_reader_resource_to_stream(
        self._handle, uri_str, stream_obj._stream)
```

##### DON'T: use the SDK inside a callback

```python
# BAD: re-enters the SDK while native is mid-call on the same object
def write_callback(ctx, data, length):
    reader.json()
    _lib.c2pa_reader_json(reader._handle)
    ...
```

##### DO: touch only the wrapped object

```python
# GOOD: Stream.__init__'s write_callback
def write_callback(ctx, data, length):
    s = _weak_self()
    if s is None:
        return -1
    if not s._initialized or s._closed:
        return -1
    try:
        if not data or length <= 0:
            return -1

        s._file_like_stream.write(ctypes.string_at(data, length))
        return length
    except Exception:
        return -1
```

##### DON'T: pass a string argument unchecked

```python
# BAD: "a\x00b" reaches native as "a"
uri_str = uri.encode('utf-8')
```

##### DO: check, then encode

```python
# GOOD
_check_cstr_arg("uri", uri)
uri_str = uri.encode('utf-8')
```

---

#### Helper reference

The [Methods to use with a `ManagedResource`](docs/native-resources-management.md#methods-to-use-with-a-managedresource)
table maps situations to creation and consumption helpers. Full list:

##### Creation and adoption

- `_create_and_activate(ffi_call, error_message, *, check=...)`: call a constructor, validate, take ownership; frees on failure
- `_activate(handle)`: take ownership of a validated handle (used by the helpers; rarely called directly)
- `_wrap_native_handle(handle)` (classmethod): new instance around a handle native already returned; skips `__init__`

##### Consumption

The consume helpers pass the handle into `ffi_call`, so it takes one argument:
`lambda h: _lib.c2pa_context_builder_build(h)`. Use `h`, the handle the helper passes in.

- `_consume_and_swap(ffi_call, error_message)`: native consumes the handle and returns a replacement for this object
- `_consume_into(ffi_call, error_message)`: native consumes the handle and returns another object's pointer; caller owns the result
- `_consume_no_replacement(ffi_call, error_message)`: native consumes the handle, returns a status code (0 = success)
- `_teardown(free_handle=False)`: mark consumed and closed without freeing
- `_release_handle()`: consuming call failed with ownership unknown; frees eagerly (guarded), then closes

##### Concurrency

- `_guarded_op(*, refuse_mut=True, exclusive=False)`: hold `_op_lock` for the block; caller checks state
- `_native_call()`: shared reservation; validates state
- `_exclusive_native_call()`: mutating reservation; validates state
- `_native_section()`: module-level native call plus result check
- `_ensure_valid_state()`: raises if closed or uninitialized; use inside `_guarded_op`

##### Argument checks

- `_check_cstr_arg(name, value)`: rejects `None` and embedded NUL
- `_check_handle_arg(name, handle)`: rejects a null handle argument
- `_check_bytes_arg(name, buffer)`: rejects `None` and empty buffers
- `_to_utf8_bytes(data, error_context)`: str or dict (JSON-serialized) to UTF-8 bytes

##### Results and errors

- `_check_ffi_operation_result(result, fallback_msg, *, check=...)`: raise typed `C2paError` on failure
- `_raise_typed_c2pa_error(error_str)`: map `"Variant: message"` to a `C2paError` subclass
- `_convert_to_py_string(ptr)`: decode and free a native string; `""` for NULL

##### Subclass hooks

- `_init_attrs()`: declare every instance attribute; call `super()._init_attrs()` first
- `_release()`: free class-specific resources; idempotent, never raises

---

#### Decision tree

##### "Native returns a new object pointer"

→ `self._create_and_activate(lambda: _lib.c2pa_x_new(...), "Failed to create X: {}")`

##### "Native consumes this handle"

1. Returns a replacement for this object? → `_consume_and_swap`
2. Returns a different object's pointer? → `_consume_into`; the new owner takes the result with `_activate` (as `Context.__init__` does with its `ContextBuilder`) or a new instance with `_wrap_native_handle`
3. Returns a status code? → `_consume_no_replacement`

##### "Native borrows this handle"

1. Runs caller-supplied Python (streams, signer callback)? → `_native_call()` or `_exclusive_native_call()`
2. Otherwise, mutates native state? → `_guarded_op(exclusive=True)` + `_ensure_valid_state()`, or `_exclusive_native_call()`
3. Otherwise, read-only? → `_native_call()`, or `_guarded_op()` + `_ensure_valid_state()`

##### "I need to check the result"

1. Pointer return? → `_check_ffi_operation_result(r, msg)` (default `not r`)
2. Status code, 0 = success? → `check=lambda r: r != 0`
3. Signed size or count, negative = error? → `check=lambda r: r < 0`

##### "Native returns memory to Python"

1. Object handle? → `ManagedResource` owns it
2. String? → `_convert_to_py_string`
3. String array? → read, then `c2pa_free_string_array(arr, count)` in `finally`
4. Byte buffer? → `ctypes.string_at(ptr, size)`, then `c2pa_manifest_bytes_free(ptr)` in `finally`

##### "I take a string from the caller"

→ type check, `_check_cstr_arg(name, value)`, then encode (`_to_utf8_bytes` for str-or-dict input)

---

#### Context and settings

`Context` is the configuration object passed to `Reader` and `Builder`. It carries a
`Settings` (verification, trust, builder, thumbnail options) and optionally a `Signer`.
Each `Context` is independent, so several configurations can coexist in one process. It
replaces the deprecated global `load_settings()`.

Rules for binding code:

- New constructors take a `context` argument typed as `ContextProvider`, and read
  configuration from it. They never read or write global settings.
- Use the context's pointer only inside `with _context_guard(context):`. For a
  `ManagedResource` context this takes a *shared* reservation (the same kind
  `Reader.json()` takes on a `Reader`), not exclusive: constructing a `Reader` or
  `Builder` does not mutate the `Context` itself, only reads its configuration, so
  several threads can each be mid-construction from the same `Context` at once. The
  reservation only stops a `close()` on that `Context` from freeing it while any of those
  constructions are still reading it. A third-party `ContextProvider` gets no such
  protection.
- `Context` and `Settings` are `ManagedResource` subclasses and follow every rule in this
  file.
- A `Signer` passed to a `Context` is consumed: the `Signer` closes and the `Context` owns
  the native signer. The signer's Python callback is copied onto the `Context` so it stays
  alive as long as native can call it.
- `Reader` and `Builder` constructed from a `Context` activate the native object first,
  then feed it data through a consuming call. See
  [Adopting a handle](docs/native-resources-management.md#adopting-a-handle).

See [docs/context-settings.md](docs/context-settings.md):
[Overview](docs/context-settings.md#overview),
[Using Context](docs/context-settings.md#using-context),
[Signer object on Context](docs/context-settings.md#signer-object-on-context),
[Context lifetime](docs/context-settings.md#context-lifetime),
[ContextProvider abstract base class](docs/context-settings.md#contextprovider-abstract-base-class).

---

#### Error handling pattern

Native errors are strings of the form `"VariantName: details"`, the cimpl convention.

- `_check_ffi_operation_result` reads the native error and passes it to
  `_raise_typed_c2pa_error`, which raises the matching `C2paError` subclass
  (`C2paError.ManifestNotFound`, `C2paError.Io`, ...) with the full string as message.
- With no native error, the fallback message is used. A message ending in `: {}` gets
  `"Unknown error"` filled in.
- Per-class fallback messages live in the class's `_ERROR_MESSAGES` dict. Add a key there
  for each new method.
- Errors raised on the Python side before reaching native use the same format as native,
  for example `C2paError(f"NullParameter: {name}")`.
- A new native error variant needs a `_C2pa<Variant>(C2paError)` class, its attribute on
  `C2paError`, and a branch in `_raise_typed_c2pa_error`.

---

## Final checklist

### Any change

- [ ] Every `Reader`, `Builder`, `Signer`, `Context` and `Settings` used in `with`, or
  explicitly `close()`d
- [ ] New tests run by name, their own result lines read
- [ ] `make test` passes
- [ ] `make check-format` passes
- [ ] All other existing unit tests still pass

### Public API change

- [ ] New public names in `__all__` (`src/c2pa/__init__.py`)
- [ ] Topic document in `docs/class-diagram.md` updated
- [ ] Version bumped in `pyproject.toml` and the `src/c2pa/c2pa.py` header

### Binding change (`src/c2pa/c2pa.py` internals)

- [ ] New native function: name in `_REQUIRED_FUNCTIONS`, `_setup_function` prototype (owned returns use `c_void_p`), fallback message in the class's `_ERROR_MESSAGES`
- [ ] Every native allocation freed by its matching free function, exactly once
- [ ] No Python memory passed to a native free; objects native keeps using referenced from an attribute
- [ ] Every handle use inside `_guarded_op`, `_native_call`, `_exclusive_native_call` or a consume helper
- [ ] No `_guarded_op` around a call that runs callbacks; `_ensure_valid_state()` inside every `_guarded_op` block
- [ ] No `_lib.*` and no SDK object use inside a callback body

---

## Key files

- `src/c2pa/c2pa.py`: public API, `ManagedResource`, binding helpers, `Reader.json` (binding reference example)
- `src/c2pa/__init__.py`: public exports
- `src/c2pa/lib.py`: native library loading
- `examples/`: runnable usage examples
- `tests/unit/`, `tests/test_unit_tests_threaded.py`: tests
- `Makefile`: every workflow command
- [docs/usage.md](docs/usage.md), [docs/context-settings.md](docs/context-settings.md), [docs/working-stores.md](docs/working-stores.md), [docs/intents.md](docs/intents.md): library usage
- [docs/native-resources-management.md](docs/native-resources-management.md): ownership, lifecycle, locking, streams, subclassing
