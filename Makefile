# For Python bindings ===========================================================

# Start from clean env: Delete `.venv`, then `python3 -m venv .venv`
# Pre-requisite: Python virtual environment is active (source .venv/bin/activate)

release:
	cargo build --release

build-python:
	rm -rf c2pa/c2pa
	python3 -m pip uninstall -y maturin
	python3 -m pip uninstall -y uniffi
	python3 -m pip install -r requirements.txt
	maturin develop

test:
	python3 ./tests/test_unit_tests.py
	python3 ./tests/test_api.py

publish: release
	python3 -m pip install twine
	python3 -m twine upload dist/*
