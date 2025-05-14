# Python API for C2PA

This project provides a Python API for working with [C2PA](https://c2pa.org/) (Coalition for Content Provenance and Authenticity) manifests. It includes functionality for creating, signing, and verifying C2PA manifests, as well as working with assets and assertions.

## Features

- Create and sign C2PA manifests using various signing algorithms.
- Verify C2PA manifests and extract metadata.
- Add assertions and ingredients to assets.
- Examples and unit tests to demonstrate usage.

## Project Structure

```bash
python_api/ 
    ├── examples/        # Example scripts demonstrating usage
    ├── src/            # Source code for the C2PA Python API
    │   └── c2pa/      # Main package directory
    │       └── libs/  # Platform-specific libraries
    ├── tests/          # Unit tests and benchmarks
    ├── artifacts/      # Platform-specific libraries for building
    │   ├── win_amd64/     # Windows x64 libraries
    │   ├── win_arm64/     # Windows ARM64 libraries
    │   ├── macosx_x86_64/ # macOS x64 libraries
    │   ├── macosx_arm64/  # macOS ARM64 libraries
    │   ├── linux_x86_64/  # Linux x64 libraries
    │   └── linux_aarch64/ # Linux ARM64 libraries
    ├── requirements.txt # Python dependencies
    └── README.md       # Project documentation
```

## Development Setup

1. Create and activate a virtual environment:
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

# download library artifacts for the current version you want
python scripts/download_artifacts.py c2pa-v0.49.5
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

This will create platform-specific wheels in the `dist/` directory.

## Running Tests

Install pytest (if not already installed):
```bash
pip install pytest
```

Run the tests:
```bash
pytest
```

## Examples

### Adding a "Do Not Train" Assertion
The `examples/training.py` script demonstrates how to add a "Do Not Train" assertion to an asset and verify it.

### Signing and Verifying Assets
The `examples/test.py` script shows how to sign an asset with a C2PA manifest and verify it.

## Contributing

Contributions are welcome! Please fork the repository and submit a pull request.

## License

This project is licensed under the Apache License 2.0 or the MIT License. See the LICENSE-MIT and LICENSE-APACHE files for details.