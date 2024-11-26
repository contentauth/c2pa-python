# Contributing to the project 

The information in this page is primarily for those who wish to contribute to the c2pa-python library project itself, rather than those who simply wish to use it in an application.  For general contribution guidelines, see [CONTRIBUTING.md](../CONTRIBUTING.md).

## Development

It is best to [set up a virtual environment](https://virtualenv.pypa.io/en/latest/installation.html) for development and testing.

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

Note: To peek at the Python code (uniffi generated and non-generated), run `maturin develop` and look in the c2pa folder.

## ManyLinux build

Build using [manylinux](https://github.com/pypa/manylinux) by using a Docker image as follows:

```bash
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

## Testing

We use [PyTest](https://docs.pytest.org/) and [unittest](https://docs.python.org/3/library/unittest.html) for testing.

Run tests by following these steps:

1. Activate the virtual environment: `source .venv/bin/activate`
2. (optional) Install dependencies: `pip install -r requirements.txt`
3. Setup the virtual environment with local changes: `maturin develop`
4. Run the tests: `pytest`
5. Deactivate the virtual environment: `deactivate`

For example:

```bash
source .venv/bin/activate
maturin develop
python3 tests/training.py
deactivate
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

