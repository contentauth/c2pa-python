# Usage examples

## Examples

### Adding a "Do Not Train" Assertion

The `examples/training.py` script demonstrates how to add a "Do Not Train" assertion to an asset and verify it.

### Signing and Verifying Assets

The `examples/sign.py` script shows how to sign an asset with a C2PA manifest and verify it.

## Running the Examples

To run the examples, make sure you have the c2pa-python package installed and you're in the root directory of the project. We recommend working using virtual environments (venv).

Then you can run the examples with the following commands:

```bash
# Run the "Do Not Train" assertion example
python examples/training.py

# Run the signing and verification example
python examples/sign.py
```

The examples will use test files from the `tests/fixtures` directory and output the results to the temporary `output` directory. Read manifest store data will be shown in the console you run the examples from.
