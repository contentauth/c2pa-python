# For Python bindings ===========================================================

# Start from clean env: Delete `.venv`, then `python3 -m venv .venv`
# Pre-requisite: Python virtual environment is active (source .venv/bin/activate)
build-python: release
	python3 -m venv .venv
	python3 -m pip install -r requirements.txt
	python3 -m pip install -r requirements-dev.txt
	python3 -m pip install -U c2pa-python
	cargo run --features=uniffi/cli --bin uniffi-bindgen generate src/adobe_api.udl -n --language python -o target/python
	maturin develop
	python3 ./tests/test_api.py

# Pre-requisite: Python virtual environment is active (source .venv/bin/activate)
python-redeploy: release
	maturin develop

# Pre-requisite: Python virtual environment is active (source .venv/bin/activate)
python-test:
	python3 -m pip install -r requirements-dev.txt
	python3 -m pip install -U c2pa-python
	python3 ./tests/test_api.py