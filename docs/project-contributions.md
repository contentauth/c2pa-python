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

[api-docs/versions.json](../api-docs/versions.json) is the publication policy:
`versions` selects one exact stable `vX.Y.Z` tag per retained major/minor line,
sorted numerically descending. The highest line is the root default. `aliases`
maps historical exact tags to unprefixed `X.Y` lines; every selected tag must
have an alias. `retiredLines` records lines automation must never restore.
The validator rejects empty selections, duplicate lines, prereleases, invalid
aliases, and active/retired overlap.

On stable release publication, the standard-library-only promoter verifies
the release tag, event release ID, published timestamp and stable/draft flags.
It reconciles all published stable releases: retained lines advance to their
highest patch, and new lines are admitted only above every active or retired
line. It never backfills unlisted historical lines or regresses a patch/default.
Migration consolidates only the previously listed lines and preserves their
exact-tag aliases; it does not discover additional historical lines.

To retire a line, submit a human PR removing its selected tag and every alias
targeting it, and add its unprefixed `X.Y` to `retiredLines`. Keep at least one
active line. To deliberately restore or backfill a historical line, use a human
PR with an exact published tag and matching aliases (remove its retirement
entry if applicable). Do not manually add a future, unpublished release tag.

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
- Each line has a canonical URL under `versions/X.Y/`; the sidebar displays
  `X.Y` and the page identifies its exact source patch.
- Historical `versions/vX.Y.Z/` HTML URLs redirect to equivalent canonical
  pages, preserving nested suffixes, query strings and fragments. Removed pages
  without an equivalent are not redirected to an unrelated API.
- Switching lines opens that line's documentation home page.
- A regular `make docs` build remains an unversioned working-tree preview.

The workflow uses current `main` tooling, never release-supplied scripts.
Promotion is an isolated job with no dependency installation or docs build.
Its only remote write is a Contents API compare-and-swap on the exact allowlisted
path `api-docs/versions.json` on `main`. Five bounded retries reread and recompute
against concurrent edits, without force pushes or lost unrelated main changes.
There is no promotion concurrency group to silently discard burst events;
release reconciliation also converges when releases arrive out of order.

Organization administrators can share the documentation App across the SDK
repositories using the Actions organization variable `C2PA_DOCS_APP_ID` and
organization secret `C2PA_DOCS_APP_PRIVATE_KEY`. Grant both selected-repository
access to this repository; workflows read them as `vars.C2PA_DOCS_APP_ID` and
`secrets.C2PA_DOCS_APP_PRIVATE_KEY`. Repository-level values override organization
values, so remove stale repository overrides when adopting the shared credentials.
Install the App on each participating repository with Contents write permission,
and separately authorize it under each repository's applicable main
protection/ruleset. Configuring credentials alone does not grant installation
access or protection bypass. The workflow mints a short-lived,
repository-scoped installation token and fails explicitly if setup is absent.
It never falls back to the ordinary workflow token for protected-branch writes.
App permissions are repository-level, not path-level; the writer's fixed API
endpoint enforces its manifest-only allowlist. Do not expose this credential to
builds, dependency installation, pull requests or release source code.

The separate `Deploy API docs` workflow starts explicitly on successful
completion of `Build and publish docs` (`workflow_run`); it does not depend on
the App push retriggering workflows. Relevant pushes to `main` and manual dispatch
still publish; App-push and workflow-completion publications may coalesce.
The complete build/deploy workflow is serialized, but checks out current `main`
only after admission, so coalescing pending publication events cannot discard
manifest updates. Failed upstream runs use isolated concurrency groups so they
cannot displace successful pending publications. Publishing never writes to the
repository, so it cannot create a push loop. The build remains read-only; only the separate deployment
job gets Pages write and OIDC permissions. Deployment rejects artifacts whose
source SHA no longer matches current `main`; rerun publication manually if an
unrelated main change superseded the latest build. No live deployment or
App/protection provisioning is part of local validation.

Run the policy, promotion and generator tests with:

```sh
python -m unittest tests.test_docs_versions tests.test_versioned_docs -v
```
