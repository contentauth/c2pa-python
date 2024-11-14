# For Python bindings ===========================================================

# Start from clean env: Delete `.venv`, then `python3 -m venv .venv`
# Pre-requisite: Python virtual environment is active (source .venv/bin/activate)
build-python: release
	python3 -m venv .venv
	source .venv/bin/activate
	python3 -m pip install -r requirements.txt
	python3 -m pip install -r requirements-dev.txt
	maturin develop

# Pre-requisite: Python virtual environment is active (source .venv/bin/activate)
python-redeploy: release
	maturin develop

# Pre-requisite: Python virtual environment is active (source .venv/bin/activate)
python-test:
	python3 -m pip install -r requirements-dev.txt
	python3 -m pip install -U c2pa-python
	python3 ./tests/test_api.py