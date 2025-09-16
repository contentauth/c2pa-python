# C2PA Python library

The [c2pa-python](https://github.com/contentauth/c2pa-python) repository provides a Python library that can:

- Read and validate C2PA manifest data from media files in supported formats.
- Create and sign manifest data, and attach it to media files in supported formats.

Features:

- Create and sign C2PA manifests using various signing algorithms.
- Verify C2PA manifests and extract metadata.
- Add assertions and ingredients to assets.
- Examples and unit tests to demonstrate usage.

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

## Examples

See the [`examples` directory](https://github.com/contentauth/c2pa-python/tree/main/examples) for some helpful examples:
- `examples/sign.py` shows how to sign and verify an asset with a C2PA manifest.
- `examples/training.py` demonstrates how to add a "Do Not Train" assertion to an asset and verify it.

## API reference documentation

You can generate API docs with one command. How to use:

Install dev deps:
```
cd c2pa-python
python3 -m pip install -r requirements-dev.txt
```

Build docs:

```
make -C docs
```

Output:

```
Open docs/build/html/index.html
```

This uses `sphinx-autoapi` to parse `src/c2pa` directly, avoiding imports of native libs.
- Entry script: `scripts/generate_api_docs.py`
- Config: `docs/conf.py`; index: `docs/index.rst`

Sphinx config is in `docs/conf.py`, an `index.rst`, added `scripts/generate_api_docs.py`, updated `requirements-dev.txt` with `Sphinx/AutoAPI/Myst/Furo`, and added a docs Makefile target.


## Contributing

Contributions are welcome!  For more information, see [Contributing to the project](https://github.com/contentauth/c2pa-python/blob/main/docs/project-contributions.md).

## License

This project is licensed under the Apache License 2.0 and the MIT License. See the [LICENSE-MIT](https://github.com/contentauth/c2pa-python/blob/main/LICENSE-MIT) and [LICENSE-APACHE](https://github.com/contentauth/c2pa-python/blob/main/LICENSE-APACHE) files for details.
