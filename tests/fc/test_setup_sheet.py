# SPDX-License-Identifier: LGPL-2.1-or-later
import unittest

import FreeCAD as App
import Path.Base.SetupSheet as PathSetupSheet

from helpers import make_job, make_sketch
from test_sketches import RECT
from vcarve_flat import op_clearance, op_vcarve  # noqa: F401  (importing registers the ops)

OPS = {"VCarveFlat": op_vcarve, "VCarveClearance": op_clearance}


class SetupSheetTests(unittest.TestCase):
    def tearDown(self):
        for doc in list(App.listDocuments()):
            App.closeDocument(doc)

    def test_ops_registered(self):
        for name, mod in OPS.items():
            self.assertIn(name, PathSetupSheet._RegisteredOps)
            op = PathSetupSheet._RegisteredOps[name]
            self.assertEqual(op.properties(), mod.SetupProperties())
            # the setup sheet editor builds a prototype of each registered op
            ptt = op.prototype(name)
            self.assertIn("FlatDepth" if mod is op_vcarve else "StepOver", ptt.properties)

    def test_pair_uses_setup_sheet_defaults(self):
        doc = App.newDocument("ss")
        job, _ = make_job(doc, [make_sketch(doc, "S", [RECT])])
        sheet = job.SetupSheet
        for op, prop, value in (("VCarveFlat", "FlatDepth", 1.5), ("VCarveClearance", "StepOver", 25)):
            name = PathSetupSheet.OpPropertyName(op, prop)
            sheet.addProperty("App::PropertyDistance" if prop == "FlatDepth" else "App::PropertyPercent", name)
            setattr(sheet, name, value)
        clearance, vcarve = op_clearance.create_pair(job)
        self.assertAlmostEqual(vcarve.FlatDepth.Value, 1.5)
        self.assertEqual(clearance.StepOver, 25)
