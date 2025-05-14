import os
import sys
import pytest

@pytest.fixture
def fixtures_dir():
    """Provide the path to the fixtures directory."""
    return os.path.join(os.path.dirname(__file__), "fixtures")

pytest.fixture(scope="session", autouse=True)
def setup_c2pa_library():
    """Ensure the src/c2pa library path is added to sys.path."""
    c2pa_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../src/c2pa"))
    if c2pa_path not in sys.path:
        sys.path.insert(0, c2pa_path)