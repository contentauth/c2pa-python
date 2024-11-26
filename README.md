# C2PA Python library

The [c2pa-python](https://github.com/contentauth/c2pa-python) repository implements Python bindings for the Content Authenticity Initiative (CAI) SDK.
It enables you to read and validate C2PA manifest data from and add signed manifests to media files in supported formats.

**NOTE**: Starting with version 0.5.0, this package has a completely different API from version 0.4.0. See [Release notes](docs/release-notes.md) for more information.

**WARNING**: This is an prerelease version of this library.  There may be bugs and unimplemented features, and the API is subject to change.

<div style={{display: 'none'}}>

Additional documentation:
- [Using the Python library](docs/usage.md)
- [Release notes](docs/release-notes.md)
- [Contributing to the project](docs/project-contributions.md)

</div>

## Installation

Install from PyPI by entering this command:

```bash
pip install -U c2pa-python
```

This is a platform wheel built with Rust that works on Windows, macOS, and most Linux distributions (using [manylinux](https://github.com/pypa/manylinux)). If you need to run on another platform, see [Project contributions - Development](docs/project-contributions.md#development) for information on how to build from source.

### Updating

Determine what version you've got by entering this command:

```bash
pip list | grep c2pa-python
```

If the version shown is lower than the most recent version, then update by [reinstalling](#installation).

### Reinstalling

If you tried unsuccessfully to install this package before the [0.40 release](https://github.com/contentauth/c2pa-python/releases/tag/v0.4), then use this command to reinstall:

```bash
pip install --upgrade --force-reinstall c2pa-python
```

## Supported formats

The Python library [supports the same media file formats](https://github.com/contentauth/c2pa-rs/blob/main/docs/supported-formats.md) as the Rust library. 

## License

This package is distributed under the terms of both the [MIT license](https://github.com/contentauth/c2pa-python/blob/main/LICENSE-MIT) and the [Apache License (Version 2.0)](https://github.com/contentauth/c2pa-python/blob/main/LICENSE-APACHE).

Note that some components and dependent crates are licensed under different terms; please check the license terms for each crate and component for details.

### Contributions and feedback

We welcome contributions to this project.  For information on contributing, providing feedback, and about ongoing work, see [Contributing](https://github.com/contentauth/c2pa-python/blob/main/CONTRIBUTING.md).
