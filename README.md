# Python API for C2PA

This project provides a Python API for working with [C2PA](https://c2pa.org/) (Coalition for Content Provenance and Authenticity) manifests. It includes functionality for creating, signing, and verifying C2PA manifests, as well as working with assets and assertions.

## Features

- Create and sign C2PA manifests using various signing algorithms.
- Verify C2PA manifests and extract metadata.
- Add assertions and ingredients to assets.
- Examples and unit tests to demonstrate usage.

## Project Structure

```bash
.
├── .github/                  # GitHub configuration files
├── artifacts/                # Platform-specific libraries for building (per subfolder)
│   └── your_target_platform/ # Platform-specific artifacts
├── docs/                     # Project documentation
├── examples/                 # Example scripts demonstrating usage
├── scripts/                  # Utility scripts (eg. artifacts download)
├── src/                      # Source code
│   └── c2pa/                 # Main package directory
│       └── libs/             # Platform-specific libraries
├── tests/                    # Unit tests and benchmarks
├── .gitignore                # Git ignore rules
├── Makefile                  # Build and development commands
├── pyproject.toml            # Python project configuration
├── requirements.txt          # Python dependencies
├── requirements-dev.txt      # Development dependencies
└── setup.py                  # Package setup script
```

## Package installation

The c2pa-python package is published to PyPI. You can install it from there by running:

```bash
pip install c2pa-python
```

To use the module in your Python code, import like this:

```python
import c2pa
```

## Examples

### Adding a "Do Not Train" Assertion

The `examples/training.py` script demonstrates how to add a "Do Not Train" assertion to an asset and verify it.

### Signing and Verifying Assets

The `examples/sign.py` script shows how to sign an asset with a C2PA manifest and verify it.

## Development Setup

1. Create and activate a virtual environment with native dependencies:

```bash
# Create virtual environment
python -m venv .venv

# Activate virtual environment
# On Windows:
.venv\Scripts\activate
# On macOS/Linux:
source .venv/bin/activate

# load project dependencies
pip install -r requirements.txt
pip install -r requirements-dev.txt

# download library artifacts for the current version you want, eg v0.55.0
python scripts/download_artifacts.py c2pa-v0.55.0
```

2. Install the package in development mode:

```bash
pip install -e .
```

This will:

- Copy the appropriate libraries for your platform from `artifacts/` to `src/c2pa/libs/`
- Install the package in development mode, allowing you to make changes to the Python code without reinstalling

## Building Wheels

To build wheels for all platforms that have libraries in the `artifacts/` directory:

```bash
python setup.py bdist_wheel
```

You can use `twine` to verify the wheels have correct metadata:

```bash
twine check dist/*
```

This will create platform-specific wheels in the `dist/` directory.

## Running Tests

Run the tests:

```bash
make test
```

Alternatively, install pytest (if not already installed):

```bash
pip install pytest
```

And run:

```bash
pytest
```

## Contributing

Contributions are welcome! Please fork the repository and submit a pull request.

## License

This project is licensed under the Apache License 2.0 or the MIT License. See the LICENSE-MIT and LICENSE-APACHE files for details.
