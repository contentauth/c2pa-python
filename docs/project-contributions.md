# Contributing to the project 

The information in this page is primarily for those who wish to contribute to the c2pa-python library project itself, rather than those who simply wish to use it in an application.  For general contribution guidelines, see [CONTRIBUTING.md](../CONTRIBUTING.md).

## Setup

It is best to [set up a virtual environment](https://virtualenv.pypa.io/en/latest/installation.html) for development and testing:

```bash
# Create virtual environment
python -m venv .venv
```

Activate the virtual environment.

- On Windows:
    ```bash
    .venv\Scripts\activate
    ```
- On macOS/Linux:
    ```bash
    source .venv/bin/activate
    ```

Load project dependencies:

```bash
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

Download library artifacts for the current version you want, (for example, as shown below for v0.55.0):

```bash
python scripts/download_artifacts.py c2pa-v0.55.0
```

Install the package in development mode:

```bash
pip install -e .
```

This command:

- Copies the appropriate libraries for your platform from `artifacts/` to `src/c2pa/libs/`
- Installs the package in development mode, so you can make changes to the Python code without reinstalling.

## Build from source

To build from source on Linux, install `curl` and `rustup` then set up Python.

First update `apt` then (if needed) install `curl`:

```bash
apt update
apt install curl
```

Install Rust:

```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
source "$HOME/.cargo/env"
```

Install Python, `pip`, and `venv`:

```bash
apt install python3
apt install pip
apt install python3.11-venv
python3 -m venv .venv
```

Build the wheel for your platform (from the root of the repository):

```bash
source .venv/bin/activate
pip install -r requirements.txt
python3 -m pip install build
pip install -U pytest

python3 -m build --wheel
```

## Building wheels

To build wheels for all platforms that have libraries in the `artifacts/` directory:

```bash
python setup.py bdist_wheel
```

You can use `twine` to verify the wheels have correct metadata:

```bash
twine check dist/*
```

This will create platform-specific wheels in the `dist/` directory.

## Project structure

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

## Testing

The project uses [PyTest](https://docs.pytest.org/) and [unittest](https://docs.python.org/3/library/unittest.html) for testing.

Run tests by following these steps:

1. Activate the virtual environment: `source .venv/bin/activate`
2. (optional) Install dependencies: `pip install -r requirements.txt`
4. Run the tests:
    ```bash
    make test
    ```
5. Alternatively, install pytest (if not already installed) and run it:
    ```bash
    pip install pytest
    pytest
    ```

### Testing during bindings development

While developing bindings locally, we use [unittest](https://docs.python.org/3/library/unittest.html), since [PyTest](https://docs.pytest.org/) can get confused by virtual environment re-deployments (especially if you bump the version number).

To run tests while developing bindings, enter this command:

```sh
make test
```

To rebuild and test, enter these commands:

```sh
make build-python
make test
```
