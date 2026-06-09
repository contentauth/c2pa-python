# For Python bindings ===========================================================

# Version of C2PA to use
C2PA_VERSION := $(shell cat c2pa-native-version.txt)

# Python interpreter. Honors an active virtualenv ($VIRTUAL_ENV), then a local
# ./.venv, then falls back to python3 on PATH. Override with: make <target> PYTHON=...
ifndef PYTHON
  ifdef VIRTUAL_ENV
    PYTHON := $(VIRTUAL_ENV)/bin/python
  else ifneq ($(wildcard .venv/bin/python),)
    PYTHON := .venv/bin/python
    $(warning .venv exists but is not activated; using ./.venv/bin/python. Run 'source .venv/bin/activate' or override with PYTHON=...)
  else
    PYTHON := python3
  endif
endif

# Start from clean env: Delete `.venv`, then `python3 -m venv .venv`
# Pre-requisite: Python virtual environment is active (source .venv/bin/activate)
# Run Pytest tests in virtualenv: .venv/bin/pytest tests/test_unit_tests.py -v

# Creates the local virtualenv at the canonical ./.venv path if it does not exist.
# Activation must happen in shell independently:
# make create-venv && source .venv/bin/activate
create-venv:
	test -d .venv || python3 -m venv .venv
	@echo "Virtualenv ready at ./.venv -- activate with: source .venv/bin/activate"

# Removes build artifacts, distribution files, and other generated content
clean:
	rm -rf artifacts/ build/ dist/

# Performs a complete cleanup including uninstalling the c2pa package and clearing pip cache
clean-c2pa-env: clean
	$(PYTHON) -m pip uninstall -y c2pa
	$(PYTHON) -m pip cache purge

# Installs all required dependencies from requirements.txt and requirements-dev.txt
install-deps:
	$(PYTHON) -m pip install -r requirements.txt
	$(PYTHON) -m pip install -r requirements-dev.txt

# Installs the package in development mode
build-python:
	$(PYTHON) -m pip install -e .

# Performs a complete rebuild of the development environment
rebuild: clean-c2pa-env install-deps download-native-artifacts build-python
	@echo "Development rebuild done"

run-examples:
	$(PYTHON) ./examples/sign.py
	$(PYTHON) ./examples/sign_info.py
	$(PYTHON) ./examples/no_thumbnails.py
	$(PYTHON) ./examples/training.py
	rm -rf output/

# Runs the examples, then the unit tests
test:
	make run-examples
	$(PYTHON) ./tests/test_unit_tests.py
	$(PYTHON) ./tests/test_unit_tests_threaded.py

# Runs benchmarks in the venv
benchmark:
	$(PYTHON) -m pytest tests/benchmark.py -v

# Tests building and installing a local wheel package
# Downloads required artifacts, builds the wheel, installs it, and verifies the installation
test-local-wheel-build:
	# Clean any existing builds
	rm -rf build/ dist/
	# Download artifacts and place them where they should go
	$(PYTHON) scripts/download_artifacts.py $(C2PA_VERSION)
	# Install Python
	$(PYTHON) -m pip install -r requirements.txt
	$(PYTHON) -m pip install -r requirements-dev.txt
	$(PYTHON) -m build --wheel
	# Install local build in venv
	$(PYTHON) -m pip install $$(ls dist/*.whl)
	# Verify installation in local venv
	$(PYTHON) -c "import c2pa; print('C2PA package installed at:', c2pa.__file__)"
	# Verify wheel structure
	$(PYTHON) -m twine check dist/*

# Tests building and installing a local source distribution package
# Downloads required artifacts, builds the sdist, installs it, and verifies the installation
test-local-sdist-build:
	# Clean any existing builds
	rm -rf build/ dist/
	# Download artifacts and place them where they should go
	$(PYTHON) scripts/download_artifacts.py $(C2PA_VERSION)
	# Install Python
	$(PYTHON) -m pip install -r requirements.txt
	$(PYTHON) -m pip install -r requirements-dev.txt
	# Build sdist package
	$(PYTHON) setup.py sdist
	# Install local build in venv
	$(PYTHON) -m pip install $$(ls dist/*.tar.gz)
	# Verify installation in local venv
	$(PYTHON) -c "import c2pa; print('C2PA package installed at:', c2pa.__file__)"
	# Verify sdist structure
	$(PYTHON) -m twine check dist/*

# Verifies the wheel build process and checks the built package and its metadata
verify-wheel-build:
	rm -rf build/ dist/ src/*.egg-info/
	$(PYTHON) -m build
	$(PYTHON) -m twine check dist/*

# Manually publishes the package to PyPI after creating a release
publish: release
	$(PYTHON) -m pip install twine
	$(PYTHON) -m twine upload dist/*

# Code analysis
check-format:
	$(PYTHON) -m py_compile src/c2pa/c2pa.py
	$(PYTHON) -m flake8 --extend-ignore=E501 src/c2pa/c2pa.py

# Formats Python source code using autopep8 with aggressive settings
format:
	$(PYTHON) -m autopep8 --aggressive --aggressive --in-place src/c2pa/c2pa.py

# Downloads the required native artifacts for the specified version
download-native-artifacts:
	$(PYTHON) scripts/download_artifacts.py $(C2PA_VERSION)

# Builds the native library from local c2pa-rs checkout and install it.
# Requires C2PA_RS_PATH to point at the c2pa-rs sources and a working Rust toolchain.
# Replaces the prebuilt artifacts from download-native-artifacts.
# --clean forces a full `cargo clean`, drop it for faster incremental rebuilds.
# Pass EXTRA_BUILD_ARGS="--debug" to build the debug profile (release is the default).
# Usage: make build-from-source C2PA_RS_PATH=/path/to/c2pa-rs
build-from-source:
	$(PYTHON) scripts/build_local_artifacts.py --clean $(EXTRA_BUILD_ARGS)
	$(PYTHON) -m pip install -e .

# Build API documentation with Sphinx
docs:
	python3 scripts/generate_api_docs.py

# Memory profiling with memray (runs in Docker, reports go to tests/perf/reports/)
# More details for usage are in tests/perf/README.md
PERF_ENV ?= python-3.12-slim
MEMRAY_ITERATIONS ?= 100
MEMRAY_THRESHOLD ?= 1.1
SCENARIO ?=
SCENARIO_ARG := $(if $(SCENARIO),--scenario $(SCENARIO),)
# In CI, use en vars to write the report to the job run
GH_SUMMARY_MOUNT := $(if $(GITHUB_STEP_SUMMARY),-v $(GITHUB_STEP_SUMMARY):$(GITHUB_STEP_SUMMARY),)
.PHONY: memory-use-bench
memory-use-bench:
	docker build -f tests/perf/Dockerfiles/$(PERF_ENV)-perf-Dockerfile -t c2pa-memray-$(PERF_ENV) .
	docker run --rm -v $(PWD):/workspace $(GH_SUMMARY_MOUNT) -e PYTHONPATH=/workspace/src -e PERF_ENV=$(PERF_ENV) -e MEMRAY_ITERATIONS=$(MEMRAY_ITERATIONS) -e MEMRAY_THRESHOLD=$(MEMRAY_THRESHOLD) -e GITHUB_TOKEN -e GITHUB_STEP_SUMMARY c2pa-memray-$(PERF_ENV) python -m tests.perf.run_profile $(SCENARIO_ARG) $(PERF_ARGS)
	@echo ""
	@echo "Reports written to tests/perf/reports/"
	@echo "Open tests/perf/reports/<scenario>-{peak,leaks,temporary}.html in a browser"

.PHONY: clean-memory-perf-reports
clean-memory-perf-reports:
	rm -f tests/perf/reports/*.html tests/perf/reports/*.bin
	@echo "Cleared tests/perf/reports/"
