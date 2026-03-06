import sys
import os

# Add tests directory to sys.path so that bare imports like
# `from test_common import ...` work with both pytest and unittest discover.
sys.path.insert(0, os.path.dirname(__file__))
