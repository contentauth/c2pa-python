# Agent Guidelines

Before working in this repository, read the applicable sections of
[AI_WORKFLOW.md](AI_WORKFLOW.md) and follow its guidance.

- SDK developers: For library behavior or implementation changes, read all of Part 1:
  Using the library and Part 2: Developing c2pa-python. For tooling-only changes, read
  Part 2 and relevant Part 1 sections.
- SDK users: Read Part 1: Using the library when writing applications, scripts, or examples.
- Testers: Read Part 2 and relevant Part 1 sections. When writing code that uses the
  library, read all of Part 1.
- Documentation writers: Read Part 2 and relevant Part 1 sections.
- Use a Python virtual environment for development. Create and activate the local
  environment with `make create-venv && source .venv/bin/activate`. Make uses the active
  environment, then `./.venv`, then `python3`; override with `make <target> PYTHON=...`.
- For changes to the binding layer, follow the binding-layer rules and decision tree in AI_WORKFLOW.md.
- Before finishing code changes, run `make test` and `make check-format`. If prerequisites prevent a check from running, report the blocker and the results of checks that did run.
- Bump the Python package version only for release-ready changes, and ask the user for confirmation before changing it.

## Repository map

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
| `tests/unit/` | Unit tests, one module per area; shared constants, helpers and `TestContextAPIs` in `_support.py` |
| `tests/test_unit_tests_threaded.py` | Concurrency tests |
| `tests/fixtures/` | Test assets, certificates and keys |
| `tests/perf/` | Memory and thread-safety harnesses, run in Docker |
| `examples/` | Runnable examples, also run by `make test` |
| `docs/` | User and developer documentation |
| `api-docs/` | Sphinx configuration and output |
| `.github/workflows/` | Build and test workflows, wheels, benchmarks, c2pa-rs source build, documentation publishing, and issue-label automation |
