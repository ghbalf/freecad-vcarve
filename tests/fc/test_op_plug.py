# SPDX-License-Identifier: LGPL-2.1-or-later
import math
import unittest
from unittest import mock

import FreeCAD as App
import numpy as np
import Path
import Part
import Path.Main.Job
import Path.Tool.Controller

from helpers import _tool, make_job, make_sketch
from test_op_vcarve import RECT, RING, cut_points
from vcarve_flat import op_clearance, op_plug
from vcarve_flat.clearing import area_offset
from vcarve_flat.geom import VBit, flat_radius, inlay_defaults, pass_depths

BAR = [(0, 0), (30, 0), (30, 2), (0, 2)]


class PlugTests(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("plug")
        self.warn = mock.patch.object(Path.Log, "warning").start()
        self.err = mock.patch.object(Path.Log, "error").start()
        self.addCleanup(mock.patch.stopall)

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def logged(self, mock_fn, *texts):
        return any(all(t in str(c.args[0]) for t in texts) for c in mock_fn.call_args_list if c.args)

    def inlay(self, loops=(RECT,), circles=RING, tip=None, stock=None, **props):
        """Pocket pair (Flat Depth P) and plug pair on the same sketch; returns the plug op."""
        sk = make_sketch(self.doc, "S", list(loops), circles)
        job, tcs = make_job(self.doc, [sk])
        if tip is not None:
            tcs["60degree_Vbit"].Tool.TipDiameter = tip
        self.pocket_clr, self.vc = op_clearance.create_pair(job)
        self.vc.BaseShapes = list(job.Model.Group)
        t = tcs["60degree_Vbit"].Tool
        self.vbit = VBit(t.Diameter.Value, t.CuttingEdgeAngle.Value, t.TipDiameter.Value)
        self.P, self.G, self.S = inlay_defaults(self.vbit)
        self.start = self.P - self.G
        self.t = math.tan(self.vbit.half_angle)
        self.vc.FlatDepth = self.P
        self.pjob = Path.Main.Job.Create("Plug", [sk], None)
        for tc in list(self.pjob.Tools.Group):
            self.doc.removeObject(tc.Name)
        self.pjob.Stock.ExtZpos = 0
        self.pjob.Stock.ExtZneg = 10
        for k, v in (stock or {}).items():
            setattr(self.pjob.Stock, k, v)
        self.doc.recompute()  # ops take their stock heights when created
        self.vtc, self.etc = (Path.Tool.Controller.Create(b, tool=_tool(self.doc, b))
                              for b in ("60degree_Vbit", "5mm_Endmill"))
        for tc in (self.vtc, self.etc):
            self.pjob.Proxy.addToolController(tc)
        if tip is not None:
            self.vtc.Tool.TipDiameter = tip
        self.clr = op_clearance.Create("VCarveClearance", parentJob=self.pjob, tc=self.etc)
        self.plug = op_plug.Create("VCarvePlug", parentJob=self.pjob)
        self.plug.ToolController = self.vtc
        self.plug.PocketOp = self.vc
        self.clr.VCarveOp = self.plug
        if "StepDown" in props:
            self.plug.setExpression("StepDown", None)
        for k, v in props.items():
            setattr(self.plug, k, v)
        self.doc.recompute()
        return self.plug

    def recompute(self, **props):
        for k, v in props.items():
            setattr(self.plug, k, v)
        self.doc.recompute()
        return cut_points(self.plug)

    def z_v(self):
        return self.plug.StartDepth.Value - self.start

    def assert_error(self):
        self.assertEqual(len(cut_points(self.plug)), 0)
        self.assertTrue(self.logged(self.err, self.plug.Label), self.err.call_args_list)

    def test_mirror_and_depths(self):
        plug = self.inlay()
        pts = cut_points(plug)
        self.assertAlmostEqual(pts[:, 2].min(), -(self.start + self.S), delta=1e-3)
        self.assertAlmostEqual(plug.PlugStartDepth.Value, self.start)
        self.assertIn("ReadOnly", plug.getEditorMode("PlugStartDepth"))
        self.assertIn("Hidden", plug.getEditorMode("FlatDepth"))
        g = self.S * self.t
        cx = 40  # the design bbox centre: RECT 0..40, RING 60..80
        xs = 2 * cx - pts[:, 0]
        self.assertLessEqual(xs.min(), 0 - g)
        self.assertGreaterEqual(xs.max(), 80 + g)
        self.assertLessEqual(pts[:, 1].min(), 0 - g)
        self.assertGreaterEqual(pts[:, 1].max(), 20 + g)
        for op in (plug, self.clr):  # (75, 10) lies inside the mirrored RECT
            p = cut_points(op)
            self.assertTrue(len(p))
            self.assertGreater(np.hypot(p[:, 0] - 75, p[:, 1] - 10).min(), 0.5)
        top = self.pjob.Stock.Shape.BoundBox.ZMax
        self.assertGreater(plug.SafeHeight.Value, top)
        self.assertGreater(plug.ClearanceHeight.Value, top)

    def test_follows_pocket(self):
        self.inlay()
        self.vc.FlatDepth = self.P - 0.5
        self.doc.recompute()
        self.assertAlmostEqual(self.plug.PlugStartDepth.Value, self.start - 0.5)
        self.assertAlmostEqual(cut_points(self.plug)[:, 2].min(), -(self.start - 0.5 + self.S), delta=1e-3)

    def test_counter_is_island(self):
        self.inlay()
        pts = cut_points(self.plug)
        z = pts[np.abs(pts[:, 2] - (self.z_v() - self.S)) < 1e-6]
        r = np.hypot(z[:, 0] - 10, z[:, 1] - 10)  # the ring's centre (70, 10) mirrored
        self.assertLess(np.abs(r - (4 - flat_radius(self.vbit, self.S))).min(), 0.05)

    def test_margin_ring(self):
        plug = self.inlay()
        pts = cut_points(self.clr)
        self.assertTrue(len(pts))
        width = self.S * self.t + plug.PlugMargin.Value
        radius = self.etc.Tool.Diameter.Value / 2
        design = [Part.Face(Part.makePolygon([App.Vector(x, y, 0) for x, y in
                                              [(40, 0), (80, 0), (80, 20), (40, 20), (40, 0)]])),
                  Part.Face(Part.Wire(Part.makeCircle(10, App.Vector(10, 10, 0))))]  # RECT and RING mirrored
        (ring,) = area_offset(design, width)
        for p in pts:  # the end mill stays inside the ring
            v = Part.Vertex(App.Vector(*p[:2], 0))
            self.assertTrue(ring.isInside(v.Point, 1e-6, True), p)
            self.assertGreaterEqual(v.distToShape(ring.OuterWire)[0], radius - 0.05, p)
        lo, hi = pts.min(axis=0), pts.max(axis=0)  # and reaches its outer edge
        for got, edge in ((-lo[0], width), (hi[0], 80 + width), (-lo[1], width), (hi[1], 20 + width)):
            self.assertAlmostEqual(got, edge - radius, delta=0.05)

    def test_stock_mode(self):
        self.inlay(PlugBoundary="Stock", stock={f"Ext{a}{s}": 10 for a in "XY" for s in ("neg", "pos")})
        pts = cut_points(self.clr)
        bb = self.pjob.Stock.Shape.BoundBox
        r = self.etc.Tool.Diameter.Value / 2
        for got, edge in ((pts[:, 0].min(), bb.XMin), (pts[:, 1].min(), bb.YMin),
                          (-pts[:, 0].max(), -bb.XMax), (-pts[:, 1].max(), -bb.YMax)):
            self.assertLessEqual(got - r, edge + 0.05)
            self.assertGreaterEqual(got, edge - r - 0.05)
        self.assertFalse(self.logged(self.warn, "cover"))

    def test_margin_too_small(self):
        self.inlay(PlugMargin=2)
        self.assertEqual(len(cut_points(self.clr)), 0)
        self.assertTrue(self.logged(self.err, self.clr.Label, "Plug Margin"), self.err.call_args_list)

    def test_pocket_without_flat_depth(self):
        self.inlay()
        self.vc.FlatDepth = 0
        self.doc.recompute()
        self.assert_error()
        self.assertTrue(self.logged(self.err, self.vc.Label, "Flat Depth"), self.err.call_args_list)

    def test_different_vbit(self):
        self.inlay()
        self.vtc.Tool.TipDiameter = self.vbit.tip_diameter + 0.5
        self.doc.recompute()
        self.assert_error()

    def test_glue_gap_range(self):
        self.inlay()
        for gap in (0, self.P):
            self.err.reset_mock()
            self.recompute(GlueGap=gap)
            self.assert_error()
            self.assertTrue(self.logged(self.err, "Glue Gap"))

    def test_too_deep(self):
        self.inlay()
        self.recompute(SurfaceGap=self.vbit.cone_height)
        self.assert_error()

    def test_not_a_pocket_op(self):
        self.inlay()
        self.recompute(PocketOp=self.pocket_clr)
        self.assert_error()

    def test_thin_stock_warning(self):
        self.inlay(stock={"ExtZneg": 1})
        self.assertTrue(self.logged(self.warn, self.plug.Label, "thinner"), self.warn.call_args_list)
        self.assertTrue(len(cut_points(self.plug)))

    def test_no_check_log_on_depth_update(self):
        self.inlay(GlueGap=0)
        self.err.reset_mock()
        self.plug.Proxy.opUpdateDepths(self.plug)
        self.assertFalse(self.err.called)

    def test_stepdown_plug(self):
        self.inlay()
        one = cut_points(self.plug)[:, 2].min()
        self.plug.setExpression("StepDown", None)
        z = self.recompute(StepDown=1)[:, 2]
        z_v = self.z_v()
        levels = [s - self.start for s in pass_depths(self.start + self.S, 1)]
        self.assertTrue(any(d < 0 for d in levels))
        for d in levels:
            self.assertLess(np.abs(z - (z_v - d)).min(), 1e-6, d)
        self.assertAlmostEqual(z.min(), one, delta=1e-6)
        self.assertGreater(len(set(np.round(cut_points(self.clr)[:, 2], 6))), 1)

    def bar_centre_above(self, pts):
        on = (np.abs(pts[:, 1] - 1) < 0.01) & (pts[:, 0] > 0.5) & (pts[:, 0] < 29.5)
        return on & (pts[:, 2] > self.z_v() + 0.1)

    def test_ridge_pass(self):
        self.inlay([BAR], (), tip=1.0)
        on = cut_points(self.plug)
        self.assertTrue(self.bar_centre_above(on).any())
        off = self.recompute(RidgePass=False)
        self.assertFalse(self.bar_centre_above(off).any())
        for tc in (self.vtc, self.vc.ToolController):
            tc.Tool.TipDiameter = 0
        sharp_off = self.recompute()
        sharp_on = self.recompute(RidgePass=True)
        np.testing.assert_allclose(sharp_on, sharp_off)

    def test_never_above_top(self):
        self.inlay(tip=1.0, StepDown=1)
        pts = cut_points(self.plug)
        self.assertTrue(len(pts))
        self.assertLessEqual(pts[:, 2].max(), self.plug.StartDepth.Value + 1e-6)
        self.assertGreater(pts[:, 2].max(), self.z_v())


if __name__ == "__main__":
    unittest.main()
