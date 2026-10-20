# SPDX-License-Identifier: LGPL-2.1-or-later
import unittest
from unittest import mock

import FreeCAD as App
import numpy as np
import Path
import Path.Tool.Controller

from helpers import _tool, make_job, make_sketch
from test_op_vcarve import RECT, cut_points
from vcarve_flat import op_clearance, op_vcarve
from vcarve_flat.compat import tool_shape

NECK = [(0, 0), (20, 0), (20, 7), (30, 7), (30, 0), (50, 0), (50, 20), (30, 20), (30, 13),
        (20, 13), (20, 20), (0, 20)]  # two 20 mm lobes joined by a 6 mm neck


class ClearanceTests(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("clr")
        mock.patch.object(Path.Log, "warning").start()
        mock.patch.object(Path.Log, "error").start()
        self.addCleanup(mock.patch.stopall)

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def pair(self, loops, flat=1.0):
        sk = make_sketch(self.doc, "S", loops)
        self.job, tcs = make_job(self.doc, [sk])
        self.vtc, self.etc = tcs["60degree_Vbit"], tcs["5mm_Endmill"]
        self.clr, self.vc = op_clearance.create_pair(self.job)
        self.vc.BaseShapes = list(self.job.Model.Group)
        self.vc.FlatDepth = flat
        self.doc.recompute()
        return self.clr, self.vc

    def test_clears_floor(self):
        clr, vc = self.pair([RECT])
        self.assertAlmostEqual(clr.Path.BoundBox.ZMin, -1.0, delta=0.05)
        cs = op_vcarve.carve_setup(vc)
        m = cs.r_flat + self.etc.Tool.Diameter.Value / 2 - 0.01
        pts = cut_points(clr)
        self.assertTrue(len(pts))
        self.assertTrue(np.all((pts[:, 0] >= m) & (pts[:, 0] <= 40 - m) & (pts[:, 1] >= m) & (pts[:, 1] <= 20 - m)))

    def test_no_flat_depth(self):
        clr, vc = self.pair([RECT], flat=0)
        self.assertEqual(len(cut_points(clr)), 0)
        self.assertNotIn("Invalid", clr.State)

    def test_too_narrow(self):
        clr, _ = self.pair([[(0, 0), (30, 0), (30, 1.5), (0, 1.5)]])
        self.assertEqual(len(cut_points(clr)), 0)
        self.assertNotIn("Invalid", clr.State)

    def test_rest_shrinks_with_clearance(self):
        clr, vc = self.pair([NECK])
        cs = op_vcarve.carve_setup(vc)
        (_, faces), = op_vcarve.region_sets(vc)
        with_c = op_vcarve._rest_pocket(vc, cs, faces, clr)
        without = op_vcarve._rest_pocket(vc, cs, faces, None)
        n = lambda ps: sum(len(p) for p in ps)
        self.assertLess(n(with_c), n(without))
        pts = np.vstack(with_c)
        # The neck is too narrow for the end mill, so it still gets rest clearing; the lobes' interiors don't.
        self.assertTrue(np.any((pts[:, 0] > 22) & (pts[:, 0] < 28)))
        lobe_core = (np.abs(pts[:, 0] - 10) < 5) & (np.abs(pts[:, 1] - 10) < 5)
        self.assertFalse(lobe_core.any())

    def test_create_pair_order(self):
        clr, vc = self.pair([RECT])
        ops = self.job.Operations.Group
        self.assertEqual([o.Name for o in ops], [clr.Name, vc.Name])
        self.assertIs(clr.VCarveOp, vc)
        first_mill = next(t for t in self.job.Tools.Group if tool_shape(t.Tool) == "Endmill")
        self.assertIs(clr.ToolController, first_mill)
        self.assertEqual(tool_shape(clr.ToolController.Tool), "Endmill")
        self.assertEqual(tool_shape(vc.ToolController.Tool), "VBit")

    def test_create_pair_missing_vbit(self):
        sk = make_sketch(self.doc, "S", [RECT])
        job, _ = make_job(self.doc, [sk], bits=("5mm_Endmill",))
        with self.assertRaisesRegex(ValueError, "V-bit"):
            op_clearance.create_pair(job)

    def test_toolchange_retouches(self):
        clr, vc = self.pair([RECT])
        other = Path.Tool.Controller.Create("Other", tool=_tool(self.doc, "5mm_Endmill"))
        self.job.Proxy.addToolController(other)
        self.doc.recompute()
        self.assertNotIn("Touched", vc.State)
        clr.ToolController = other
        self.assertIn("Touched", vc.State)
