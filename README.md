# C2PA Python library

The [c2pa-python](https://github.com/contentauth/c2pa-python) repository provides a Python library that can:

- Read and validate C2PA manifest data from media files in supported formats.
- Create and sign manifest data, and attach it to media files in supported formats.

Features:

- Create and sign C2PA manifests using various signing algorithms.
- Verify C2PA manifests and extract metadata.
- Add assertions and ingredients to assets.
- Examples and unit tests to demonstrate usage.

<div style={{display: 'none'}}>

For the best experience, read the docs on the [CAI Open Source SDK documentation website](https://opensource.contentauthenticity.org/docs/c2pa-c).

If you want to view the documentation in GitHub, see:
- [Using the Python library](docs/usage.md)
- [Supported formats](https://github.com/contentauth/c2pa-rs/blob/main/docs/supported-formats.md)
- [Configuring the SDK using `Context` and `Settings`](docs/context-settings.md)
- [Using Builder intents](docs/intents.md) to ensure spec-compliant manifests
- Using [working stores and archvies](docs/working-stores.md)
- Selectively constructing manifests by [filtering actions and ingredients](docs/selective-manifests.md)
- [Diagram of public classes in the Python library and their relationships](docs/class-diagram.md)
- [Release notes](docs/release-notes.md)

</div>

## Prerequisites

This library requires Python version 3.10+.

## Package installation

Install the c2pa-python package from PyPI by running:

```bash
pip install c2pa-python
```

To use the module in Python code, import the module like this:

```python
import c2pa
```

## Building from local c2pa-rs sources

### Build steps

By default the build downloads a prebuilt native library from a [c2pa-rs](https://github.com/contentauth/c2pa-rs) release. To test the Python bindings against a local, unreleased c2pa-rs checkout, you can instead build the native library from source.

Prerequisites:

- A local clone of [c2pa-rs](https://github.com/contentauth/c2pa-rs).
- The [Rust toolchain](https://rust-lang.org/tools/install/) (`cargo` on your `PATH`).

Point `C2PA_RS_PATH` at your c2pa-rs checkout and run the `build-from-source` target:

```sh
export C2PA_RS_PATH=/path/to/c2pa-rs
make build-from-source C2PA_RS_PATH=$C2PA_RS_PATH
```

This does a clean release build of the `c2pa-c-ffi` crate (with the `file_io` feature, which the Python wrapper requires), stages the resulting library under both `artifacts/` and `src/c2pa/libs/`, and installs the package in editable mode, replacing any prebuilt artifacts from `make download-native-artifacts`.

### Note on targets for macOS

On macOS this produces a universal (arm64+x86_64) library by default, which requires both Rust targets:

```sh
rustup target add aarch64-apple-darwin x86_64-apple-darwin
```

To build a single-architecture library instead, set `C2PA_LIBS_PLATFORM` to a specific platform (for example `aarch64-apple-darwin`).

## Examples

See the [`examples` directory](https://github.com/contentauth/c2pa-python/tree/main/examples) for some helpful examples:

- `examples/read.py` shows how to read and verify an asset with a C2PA manifest.
- `examples/sign.py` shows how to sign and verify an asset with a C2PA manifest.
- `examples/training.py` demonstrates how to add a "Do Not Train" assertion to an asset and verify it.

## API reference documentation

Documentation is published at [github.io/c2pa-python/api/c2pa](https://contentauth.github.io/c2pa-python/api/c2pa/index.html).

To build documentation locally, refer to [this section in Contributing to the project](https://github.com/contentauth/c2pa-python/blob/main/docs/project-contributions.md#api-reference-documentation).

## Contributing

Contributions are welcome!  For more information, see [Contributing to the project](https://github.com/contentauth/c2pa-python/blob/main/docs/project-contributions.md).

## License

This project is licensed under the Apache License 2.0 and the MIT License. See the [LICENSE-MIT](https://github.com/contentauth/c2pa-python/blob/main/LICENSE-MIT) and [LICENSE-APACHE](https://github.com/contentauth/c2pa-python/blob/main/LICENSE-APACHE) files for details.
