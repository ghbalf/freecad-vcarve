# SPDX-License-Identifier: LGPL-2.1-or-later
# Authors: alf and Claude (Anthropic)
"""Integration entry point: freecadcmd tests/fc/run.py"""
import os
import sys
import unittest

import Path

here = os.path.dirname(os.path.abspath(__file__))
for p in (here, os.path.dirname(os.path.dirname(here)), os.path.dirname(os.path.dirname(Path.__file__))):
    if p not in sys.path:
        sys.path.insert(0, p)

result = unittest.TextTestRunner(verbosity=2).run(
    unittest.defaultTestLoader.discover(here, pattern="test_*.py"))
if not result.wasSuccessful():
    sys.exit(1)
print("FC-TESTS-OK")
