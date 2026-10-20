# SPDX-License-Identifier: LGPL-2.1-or-later
import os
import unittest

import FreeCAD as App


class IsolationTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get("FREECAD_USER_HOME"), "not run by tests/test_freecad.py")
    def test_user_home_is_isolated(self):
        home = os.path.realpath(os.environ["FREECAD_USER_HOME"])
        for path in (App.getUserAppDataDir(), App.getUserConfigDir()):
            self.assertTrue(os.path.realpath(path).startswith(home), path)
