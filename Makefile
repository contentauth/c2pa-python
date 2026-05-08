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

# Installs the package in development mode
build-python:
	python3 -m pip install -e .

# Performs a complete rebuild of the development environment
rebuild: clean-c2pa-env install-deps download-native-artifacts build-python
	@echo "Development rebuild done"

run-examples:
	python3 ./examples/sign.py
	python3 ./examples/sign_info.py
	python3 ./examples/no_thumbnails.py
	python3 ./examples/training.py
	rm -rf output/

# Runs the examples, then the unit tests
test:
	make run-examples
	python3 ./tests/test_unit_tests.py
	python3 ./tests/test_unit_tests_threaded.py

# Runs benchmarks in the venv
benchmark:
	python3 -m pytest tests/benchmark.py -v

# Memory-profile benchmarks (peak traced, retained, RSS delta, alloc count)
benchmark-memory:
	mkdir -p .benchmarks
	python3 -m pytest tests/benchmark_memory.py -v --benchmark-only \
	  -m "not slow" \
	  --benchmark-json=.benchmarks/memory-latest.json

# Stress benchmarks (concurrency + scaling + leak detection); excludes slow tests
benchmark-stress:
	mkdir -p .benchmarks
	python3 -m pytest tests/benchmark_stress.py -v -p no:cacheprovider \
	  -m "not slow" \
	  --benchmark-json=.benchmarks/stress-latest.json

# Slow stress benchmarks (includes the 250MB fixture)
benchmark-stress-slow:
	mkdir -p .benchmarks
	python3 -m pytest tests/benchmark_stress.py -v -m slow \
	  -p no:cacheprovider \
	  --benchmark-json=.benchmarks/stress-slow-latest.json

# All non-slow benchmark suites
benchmark-all: benchmark benchmark-memory benchmark-stress

# Capture 5x main + 5x changes replicates of memory and stress suites
# and regenerate tests/BENCHMARK_RESULTS.md.
benchmark-compare:
	mkdir -p .benchmarks
	scripts/run_benchmark_comparison.sh

# Capture the leak suite (read + sign + mixed) once per side and append
# slope numbers into tests/BENCHMARK_RESULTS.md on next aggregation.
benchmark-compare-leak:
	mkdir -p .benchmarks
	scripts/run_benchmark_leak_comparison.sh

# Tests building and installing a local wheel package
# Downloads required artifacts, builds the wheel, installs it, and verifies the installation
test-local-wheel-build:
	# Clean any existing builds
	rm -rf build/ dist/
	# Download artifacts and place them where they should go
	python3 scripts/download_artifacts.py $(C2PA_VERSION)
	# Install Python
	python3 -m pip install -r requirements.txt
	python3 -m pip install -r requirements-dev.txt
	python3 -m build --wheel
	# Install local build in venv
	pip install $$(ls dist/*.whl)
	# Verify installation in local venv
	python3 -c "import c2pa; print('C2PA package installed at:', c2pa.__file__)"
	# Verify wheel structure
	twine check dist/*

# Tests building and installing a local source distribution package
# Downloads required artifacts, builds the sdist, installs it, and verifies the installation
test-local-sdist-build:
	# Clean any existing builds
	rm -rf build/ dist/
	# Download artifacts and place them where they should go
	python3 scripts/download_artifacts.py $(C2PA_VERSION)
	# Install Python
	python3 -m pip install -r requirements.txt
	python3 -m pip install -r requirements-dev.txt
	# Build sdist package
	python3 setup.py sdist
	# Install local build in venv
	pip install $$(ls dist/*.tar.gz)
	# Verify installation in local venv
	python3 -c "import c2pa; print('C2PA package installed at:', c2pa.__file__)"
	# Verify sdist structure
	twine check dist/*

# Verifies the wheel build process and checks the built package and its metadata
verify-wheel-build:
	rm -rf build/ dist/ src/*.egg-info/
	python3 -m build
	twine check dist/*

# Manually publishes the package to PyPI after creating a release
publish: release
	python3 -m pip install twine
	python3 -m twine upload dist/*

# Code analysis
check-format:
	python3 -m py_compile src/c2pa/c2pa.py
	flake8 src/c2pa/c2pa.py

# Formats Python source code using autopep8 with aggressive settings
format:
	autopep8 --aggressive --aggressive --in-place src/c2pa/c2pa.py

# Downloads the required native artifacts for the specified version
download-native-artifacts:
	python3 scripts/download_artifacts.py $(C2PA_VERSION)

# Build API documentation with Sphinx
docs:
	python3 scripts/generate_api_docs.py
