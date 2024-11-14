# For Python bindings ===========================================================

# Start from clean env: Delete `.venv`, then `python3 -m venv .venv`
# Pre-requisite: Python virtual environment is active (source .venv/bin/activate)
build-python:
	rm -rf c2pa/c2pa
	python3 -m pip uninstall -y maturin
	python3 -m pip uninstall -y uniffi
	python3 -m pip install -r requirements.txt
	maturin develop
