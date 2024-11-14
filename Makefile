# For Python bindings ===========================================================

# Start from clean env: Delete `.venv`, then `python3 -m venv .venv`
# Pre-requisite: Python virtual environment is active (source .venv/bin/activate)
build-python:
	python3 -m venv .venv
	rm -rf c2pa/c2pa
	python3 -m pip uninstall maturin
	python3 -m pip uninstall uniffi
	python3 -m pip install -r requirements.txt
	maturin develop
