# SPDX-License-Identifier: LGPL-2.1-or-later
import unittest
from unittest import mock

import FreeCAD as App
import Part
import Path

from helpers import make_job, make_sketch
from test_op_vcarve import RECT
from vcarve_flat.compat import tool_shape
from vcarve_flat.inlay import create_inlay
from vcarve_flat.op_vcarve import tool_vbit


class InlayTests(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("inlay")
        for fn in ("warning", "error"):
            mock.patch.object(Path.Log, fn).start()
        self.addCleanup(mock.patch.stopall)
        self.sk = make_sketch(self.doc, "Letters", [RECT])
        self.job, self.tcs = make_job(self.doc, [self.sk])
        self.vtc, self.etc = self.tcs["60degree_Vbit"], self.tcs["5mm_Endmill"]

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def build(self, sketch=None, **kw):
        args = dict(pocket_depth=3.0, glue_gap=0.2)
        args.update(kw)
        res = create_inlay(self.job, sketch or self.sk, self.vtc, self.etc, **args)
        self.doc.recompute()
        return res

    def test_three_jobs(self):
        self.job.Stock.ExtXneg, self.job.Stock.ExtZpos = 7, 2
        ops, tools = list(self.job.Operations.Group), list(self.job.Tools.Group)
        qjob, (pclr, pvc), pjob, (clr, plug) = self.build()
        jobs = [o for o in self.doc.Objects if hasattr(o, "Operations")]
        self.assertEqual(len(jobs), 3)
        # Job.Create's default tool controller goes, and its tool bit with it
        self.assertEqual(sorted(o.Name for o in self.doc.Objects if not o.InList),
                         sorted(o.Name for o in jobs))
        self.assertEqual((list(self.job.Operations.Group), list(self.job.Tools.Group)), (ops, tools))
        self.assertEqual((qjob.Label, pjob.Label), ("Letters Pocket", "Letters Plug"))
        # the CAM simulators list only Jobs whose internal name starts with "Job"
        self.assertEqual(len(self.doc.findObjects("Path::FeaturePython", "Job.*")), 3)
        for job in (qjob, pjob):
            self.assertEqual(len(job.Tools.Group), 2)
            for src in (self.vtc, self.etc):
                tc = next(t for t in job.Tools.Group if tool_shape(t.Tool) == tool_shape(src.Tool))
                self.assertIsNot(tc.Tool, src.Tool)
                self.assertEqual(tc.Tool.Diameter, src.Tool.Diameter)
                self.assertEqual(tc.ToolNumber, src.ToolNumber)
                self.assertEqual(tc.HorizFeed, src.HorizFeed)
        self.assertEqual((qjob.Stock.ExtXneg.Value, qjob.Stock.ExtZpos.Value), (7, 2))
        self.assertEqual(qjob.Stock.Shape.BoundBox.XMin, self.job.Stock.Shape.BoundBox.XMin)
        self.assertEqual([o.Name for o in qjob.Operations.Group], [pclr.Name, pvc.Name])
        self.assertEqual([o.Name for o in pjob.Operations.Group], [clr.Name, plug.Name])
        self.assertEqual(clr.VCarveOp, plug)
        self.assertEqual(plug.PocketOp, pvc)
        self.assertEqual(pclr.VCarveOp, pvc)
        self.assertEqual(pvc.FlatDepth.Value, 3.0)
        self.assertEqual(list(pvc.BaseShapes), list(qjob.Model.Group))
        self.assertEqual(qjob.Model.Group[0].Objects[0], self.sk)
        for job in (qjob, pjob):
            for op in job.Operations.Group:
                self.assertIn(op.ToolController, job.Tools.Group)
        vt = next(t for t in pjob.Tools.Group if tool_shape(t.Tool) == "VBit")
        self.assertEqual(tool_vbit(vt), tool_vbit(self.vtc))
        self.assertEqual(pjob.Stock.ExtZpos.Value, 0)
        self.assertEqual(plug.PlugStock, pjob.Stock)
        self.assertEqual((plug.GlueGap.Value, plug.PlugBoundary, plug.RidgePass), (0.2, "Margin", True))
        self.assertAlmostEqual(plug.SurfaceGap.Value, min(1.5, tool_vbit(self.vtc).cone_height - 2.8))

    def test_box_stock_copied(self):
        import Path.Main.Stock as PathStock
        old = self.job.Stock
        place = App.Placement(App.Vector(-5, -6, -8), App.Rotation())
        self.job.Stock = PathStock.CreateBox(self.job, App.Vector(60, 40, 8), place)
        self.doc.removeObject(old.Name)
        qjob = self.build()[0]
        self.assertEqual((qjob.Stock.Length, qjob.Stock.Width, qjob.Stock.Height),
                         (self.job.Stock.Length, self.job.Stock.Width, self.job.Stock.Height))
        self.assertTrue(qjob.Stock.Placement.isSame(place, 1e-9))

    def test_options_and_clone(self):
        _, _, _, (_, plug) = self.build(self.job.Model.Group[0], boundary="Stock", ridge=False)
        self.assertEqual((plug.PlugBoundary, plug.RidgePass), ("Stock", False))

    def test_stepdown_set(self):
        _, pocket, _, plugs = self.build(stepdown=1.5)
        for op in (*pocket, *plugs):
            self.assertEqual(op.StepDown.Value, 1.5)
            self.assertNotIn("StepDown", [e[0] for e in op.ExpressionEngine])

    def test_sketch_edit_updates_plug(self):
        _, _, _, (_, plug) = self.build()
        before = plug.Path.BoundBox.XMax
        pts = [App.Vector(x, y, 0) for x, y in ((60, 0), (80, 0), (80, 20), (60, 20))]
        for a, b in zip(pts, pts[1:] + pts[:1]):
            self.sk.addGeometry(Part.LineSegment(a, b))
        self.doc.recompute()
        self.assertNotAlmostEqual(plug.Path.BoundBox.XMax, before)

    def test_pocket_depth_updates_plug(self):
        _, (_, pvc), _, (_, plug) = self.build()
        self.assertAlmostEqual(plug.PlugStartDepth.Value, 2.8)
        pvc.FlatDepth = 2.5
        self.doc.recompute()
        self.assertAlmostEqual(plug.PlugStartDepth.Value, 2.3)

    def test_sketch_outside_job(self):  # the Job only provides the tool controllers and the stock
        other = make_sketch(self.doc, "Other", [RECT])
        qjob, _, pjob, _ = self.build(other)
        self.assertEqual((qjob.Label, pjob.Label), ("Other Pocket", "Other Plug"))
        self.assertEqual(qjob.Model.Group[0].Objects[0], other)

    def test_not_a_sketch(self):
        box = self.doc.addObject("Part::Box", "Box")
        with self.assertRaises(ValueError):
            create_inlay(self.job, box, self.vtc, self.etc, 3.0, 0.2)
        self.assertEqual(len([o for o in self.doc.Objects if hasattr(o, "Operations")]), 1)

    def test_wrong_tool_shape(self):
        with self.assertRaises(ValueError):
            create_inlay(self.job, self.sk, self.etc, self.vtc, 3.0, 0.2)


if __name__ == "__main__":
    unittest.main()
