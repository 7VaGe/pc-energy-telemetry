# conftest.py
# Adds the exporter root to sys.path and pre-imports hardware_profile so that
# test_hardware_profile.py always gets the real module, regardless of the
# order in which pytest collects and imports test files.

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Pre-import before any stub can shadow it
import collectors.hardware_profile  # noqa: F401
