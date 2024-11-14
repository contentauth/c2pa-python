# For Python bindings ===========================================================

# Start from clean env: Delete `.venv`, then `python3 -m venv .venv`
# Pre-requisite: Python virtual environment is active (source .venv/bin/activate)
build-python: release
  python3 -m venv .venv
  source .venv/bin/activate
  python3 -m pip install -r requirements.txt
  maturin develop
