"""
tests/conftest.py

Shared pytest fixtures and configuration for the Asomien test suite.
"""

import os
import sys
from pathlib import Path

# Ensure the project root is on the Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Change working directory to project root so relative paths (e.g. personality_seed.json) resolve
os.chdir(project_root)
