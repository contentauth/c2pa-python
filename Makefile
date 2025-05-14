# For Python bindings ===========================================================

# Start from clean env: Delete `.venv`, then `python3 -m venv .venv`
# Pre-requisite: Python virtual environment is active (source .venv/bin/activate)

clean-c2pa-env:
	python3 -m pip uninstall -y c2pa
	python3 -m pip cache purge

build-python:
	python3 -m pip install -r requirements.txt
	python3 -m pip install -r requirements-dev.txt
	pip install -e .

test:
	python3 ./tests/test_unit_tests.py

test-local-wheel-build:
	# Clean any existing builds
	rm -rf build/ dist/
	python3 -m pip install -r requirements.txt
	python3 -m pip install -r requirements-dev.txt
	python setup.py bdist_wheel
	# Install local build in venv
	pip install $$(ls dist/*.whl)
	# Verify installation in local venv
	python -c "import c2pa; print('C2PA package installed at:', c2pa.__file__)"

publish: release
	python3 -m pip install twine
	python3 -m twine upload dist/*
