"""Pytest configuration and shared fixtures."""

import sys
import os

# Ensure the project root is on the path so tests can import core modules
# without requiring an editable install.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
