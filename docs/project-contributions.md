# Contributing to the project

The information in this page is primarily for those who wish to contribute to the c2pa-python library project itself, rather than those who simply wish to use it in an application. For general contribution guidelines, see [CONTRIBUTING.md](../CONTRIBUTING.md).

## Setup

It is best to [set up a virtual environment](https://virtualenv.pypa.io/en/latest/installation.html) for development and testing:

```bash
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

Download [c2pa-rs library artifacts](https://github.com/contentauth/c2pa-rs/tags) for the release selected in `c2pa-native-version.txt`:

```bash
make download-native-artifacts
```

Without `make`, pass the tag from `c2pa-native-version.txt` directly to
`python scripts/download_artifacts.py` (currently `c2pa-v0.91.7`).

Install the package in development mode:

```bash
pip install -e .
```

This command:

- Copies the appropriate libraries for your platform from `artifacts/` to `src/c2pa/libs/`
- Installs the package in development mode, so you can make changes to the Python code without reinstalling.

## Building wheels

Build the wheel for your platform (from the root of the repository):

```bash
source .venv/bin/activate
pip install -r requirements.txt
python3 -m pip install build
pip install -U pytest

python3 -m build --wheel
```

To test the local wheel build, enter this command:

```bash
make test-local-wheel-build
```

To verify the builds, enter this command:

```bash
make verify-wheel-build
```

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

The project uses [pytest](https://docs.pytest.org/) and [unittest](https://docs.python.org/3/library/unittest.html) for testing.

Run tests by following these steps:

1. Activate the virtual environment: `source .venv/bin/activate`
2. (optional) Install dependencies: `pip install -r requirements.txt`
3. Run the tests:
    ```bash
    make test
    ```
4. Alternatively, install `pytest` (if not already installed) and run it:
    ```bash
    pip install pytest
    pytest
    ```

    > [!WARNING]
    > Using `pytest` can lead to issues if you often switch between virtual environments.

### Testing during bindings development

While developing bindings locally, we use [unittest](https://docs.python.org/3/library/unittest.html), since [pytest](https://docs.pytest.org/) can get confused by virtual environment re-deployments (especially if you bump the version number).

To run tests while developing bindings, enter this command:

```sh
make test
```

To rebuild and test, enter these commands:

```sh
make build-python
make test
```

## API reference documentation

We use Sphinx autodoc to generate API docs.

Install development dependencies:

```
cd c2pa-python
python3 -m pip install -r requirements-dev.txt
```

Build docs for your working tree by entering `make docs` or:

```
python3 scripts/generate_api_docs.py
```

View the output by loading `api-docs/_build/html/index.html` in a web browser.

This uses `sphinx-autoapi` to parse `src/c2pa` directly, avoiding imports of native libs.
- Entry script: `scripts/generate_api_docs.py`
- Config: `api-docs/conf.py`; index: `api-docs/index.rst`

### Versioned release documentation

Edit [api-docs/versions.json](../api-docs/versions.json) to choose the exact
GitHub release tags shown in the sidebar dropdown. Entries must be unique
tags such as `v0.38.0`. The first entry is the default served at the existing
documentation URL; new releases are not automatically added to the list.

Fetch the release tags and build the complete site:

```sh
git fetch origin --tags
make docs-versioned
```

The builder verifies that every tag has a published release in
`contentauth/c2pa-python` and fails if a release or local tag is missing.
It needs network access to the GitHub API; optionally set `GITHUB_TOKEN`
to avoid unauthenticated rate limits.

Each version uses the Python sources from its exact tag with the current
documentation configuration, templates, and build dependencies. It parses
sources without importing the package or executing scripts from old releases.
Builds run in temporary directories and leave the working tree's generated
API pages untouched.

The complete site is written to `api-docs/_build/versioned/`:

- The default version is also served at the root, preserving existing API URLs.
- Each selected release has a stable URL under `versions/<tag>/`.
- Switching versions opens that release's documentation home page.
- A regular `make docs` build remains an unversioned working-tree preview.

The publishing workflow always checks out `main` for the release list and
build tooling, including when triggered by a release. It rebuilds all selected
versions when a release is published, when relevant documentation files change
on `main`, or when manually dispatched. Publish changes to the list on `main`
to add, remove, or reorder dropdown entries.
