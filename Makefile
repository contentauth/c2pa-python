# For Python bindings ===========================================================

# Version of C2PA to use
C2PA_VERSION := $(shell cat c2pa-native-version.txt)

# Start from clean env: Delete `.venv`, then `python3 -m venv .venv`
# Pre-requisite: Python virtual environment is active (source .venv/bin/activate)
# Run Pytest tests in virtualenv: .venv/bin/pytest tests/test_unit_tests.py -v

# Removes build artifacts, distribution files, and other generated content
clean:
	rm -rf artifacts/ build/ dist/

# Performs a complete cleanup including uninstalling the c2pa package and clearing pip cache
clean-c2pa-env: clean
	python3 -m pip uninstall -y c2pa
	python3 -m pip cache purge

# Installs all required dependencies from requirements.txt and requirements-dev.txt
install-deps:
	python3 -m pip install -r requirements.txt
	python3 -m pip install -r requirements-dev.txt
	pip install -e .

# Installs the package in development mode
build-python:
	pip install -e .

# Performs a complete rebuild of the development environment
rebuild: clean-c2pa-env install-deps download-native-artifacts build-python
	@echo "Development rebuild done!"

# Runs the unit tests
test:
	python3 ./tests/test_unit_tests.py

# Tests building and installing a local wheel package
# Downloads required artifacts, builds the wheel, installs it, and verifies the installation
test-local-wheel-build:
	# Clean any existing builds
	rm -rf build/ dist/
	# Download artifacts and place them where they should go
	python scripts/download_artifacts.py $(C2PA_VERSION)
	# Install Python
	python3 -m pip install -r requirements.txt
	python3 -m pip install -r requirements-dev.txt
	python -m build --wheel
	# Install local build in venv
	pip install $$(ls dist/*.whl)
	# Verify installation in local venv
	python -c "import c2pa; print('C2PA package installed at:', c2pa.__file__)"
	# Verify wheel structure
	twine check dist/*

# Tests building and installing a local source distribution package
# Downloads required artifacts, builds the sdist, installs it, and verifies the installation
test-local-sdist-build:
	# Clean any existing builds
	rm -rf build/ dist/
	# Download artifacts and place them where they should go
	python scripts/download_artifacts.py $(C2PA_VERSION)
	# Install Python
	python3 -m pip install -r requirements.txt
	python3 -m pip install -r requirements-dev.txt
	# Build sdist package
	python -m build --sdist
	# Install local build in venv
	pip install $$(ls dist/*.tar.gz)
	# Verify installation in local venv
	python -c "import c2pa; print('C2PA package installed at:', c2pa.__file__)"
	# Verify sdist structure
	twine check dist/*

# Verifies the wheel build process and checks the built package and its metadata
verify-wheel-build:
	rm -rf build/ dist/ src/*.egg-info/
	python -m build
	twine check dist/*

# Manually publishes the package to PyPI after creating a release
publish: release
	python3 -m pip install twine
	python3 -m twine upload dist/*

# Formats Python source code using autopep8 with aggressive settings
format:
	autopep8 --aggressive --aggressive --in-place src/c2pa/*.py

# Downloads the required native artifacts for the specified version
download-native-artifacts:
	python3 scripts/download_artifacts.py $(C2PA_VERSION)