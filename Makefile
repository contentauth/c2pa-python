# For Python bindings ===========================================================

# Start from clean env: Delete `.venv`, then `python3 -m venv .venv`
# Pre-requisite: Python virtual environment is active (source .venv/bin/activate)
# Run Pytest tests in virtualenv: .venv/bin/pytest tests/test_unit_tests.py -v

clean:
	rm -rf artifacts/ build/ dist/

clean-c2pa-env: clean
	python3 -m pip uninstall -y c2pa
	python3 -m pip cache purge

install-deps:
	python3 -m pip install -r requirements.txt
	python3 -m pip install -r requirements-dev.txt
	pip install -e .

build-python:
	pip install -e .

rebuild: clean-c2pa-env install-deps download-native-artifacts build-python
	@echo "Development rebuild done!"

test:
	python3 ./tests/test_unit_tests.py

test-local-wheel-build:
	# Clean any existing builds
	rm -rf build/ dist/
	# Download artifacts and place them where they should go
	python scripts/download_artifacts.py c2pa-v0.55.0
	# Install Python
	python3 -m pip install -r requirements.txt
	python3 -m pip install -r requirements-dev.txt
	python setup.py bdist_wheel
	# Install local build in venv
	pip install $$(ls dist/*.whl)
	# Verify installation in local venv
	python -c "import c2pa; print('C2PA package installed at:', c2pa.__file__)"

verify-wheel-build:
	rm -rf build/ dist/ src/*.egg-info/
	python -m build
	twine check dist/*

publish: release
	python3 -m pip install twine
	python3 -m twine upload dist/*

format:
	autopep8 --aggressive --aggressive --in-place src/c2pa/*.py

download-native-artifacts:
	python3 scripts/download_artifacts.py c2pa-v0.55.0
