# SPDX-License-Identifier: LGPL-2.1-or-later
import unittest
from unittest import mock

import FreeCAD as App
import numpy as np
import Part
import Path

from helpers import make_job, make_sketch
from vcarve_flat import op_vcarve
from vcarve_flat.geom import VBit, flat_radius
from vcarve_flat.toolpath import paths_to_commands

RECT = [(0, 0), (40, 0), (40, 20), (0, 20)]
RING = [(70, 10, 10), (70, 10, 4)]


def cut_points(op):
    """XYZ of every G1 move (tracking modal position)."""
    pos, out = {"X": 0.0, "Y": 0.0, "Z": 0.0}, []
    for c in op.Path.Commands:
        pos.update({k: v for k, v in c.Parameters.items() if k in pos})
        if c.Name in ("G1", "G01"):
            out.append((pos["X"], pos["Y"], pos["Z"]))
    return np.array(out).reshape(-1, 3)


class OpVCarveTests(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("op")
        self.warn = mock.patch.object(Path.Log, "warning").start()
        self.err = mock.patch.object(Path.Log, "error").start()
        self.addCleanup(mock.patch.stopall)

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def job_with(self, *sketches):
        self.job, tcs = make_job(self.doc, sketches)
        self.tc = tcs["60degree_Vbit"]
        t = self.tc.Tool
        self.vbit = VBit(t.Diameter.Value, t.CuttingEdgeAngle.Value, t.TipDiameter.Value)
        return list(self.job.Model.Group)

    def make_op(self, bases=(), **props):
        op = op_vcarve.Create("VCarve", parentJob=self.job)
        op.ToolController = self.tc
        op.BaseShapes = list(bases)
        for k, v in props.items():
            setattr(op, k, v)
        self.doc.recompute()
        return op

    def logged(self, mock_fn, text):
        return any(text in str(c.args[0]) for c in mock_fn.call_args_list if c.args)

    def assert_inside(self, pts, x0, y0, x1, y1, tol=1e-3):
        self.assertTrue(len(pts))
        self.assertTrue(np.all((pts[:, 0] >= x0 - tol) & (pts[:, 0] <= x1 + tol)
                               & (pts[:, 1] >= y0 - tol) & (pts[:, 1] <= y1 + tol)))

    def test_execute_full_cone(self):
        (clone,) = self.job_with(make_sketch(self.doc, "Rect", [RECT]))
        op = self.make_op([clone])
        self.assertAlmostEqual(op.Path.BoundBox.ZMin, -self.vbit.cone_height, delta=0.05)
        self.assert_inside(cut_points(op), 0, 0, 40, 20)

    def test_execute_flat(self):
        (clone,) = self.job_with(make_sketch(self.doc, "Rect", [RECT]))
        op = self.make_op([clone], FlatDepth=1.0)
        self.assertAlmostEqual(op.Path.BoundBox.ZMin, -1.0, delta=0.05)
        pts = cut_points(op)
        self.assert_inside(pts, 0, 0, 40, 20)
        r = flat_radius(self.vbit, 1.0)
        flat = pts[np.abs(pts[:, 2] + 1.0) < 1e-6]
        on_left = flat[(np.abs(flat[:, 0] - r) < 0.01) & (np.abs(flat[:, 1] - 10) <= 10 - r + 0.01)]
        self.assertTrue(len(on_left), r)

    def test_depth_capped(self):
        (clone,) = self.job_with(make_sketch(self.doc, "Rect", [RECT]))
        op = self.make_op([clone], FlatDepth=100.0)
        self.assertAlmostEqual(op.Path.BoundBox.ZMin, -self.vbit.cone_height, delta=0.05)
        self.assertTrue(self.logged(self.warn, "100"), self.warn.call_args_list)

    def test_only_listed(self):
        _, ring = self.job_with(make_sketch(self.doc, "Rect", [RECT]),
                                make_sketch(self.doc, "Ring", [], circles=RING))
        op = self.make_op([ring])
        self.assert_inside(cut_points(op), 60, 0, 80, 20)

    def test_empty_bases(self):
        self.job_with(make_sketch(self.doc, "Rect", [RECT]))
        op = self.make_op()
        self.assertEqual(len(cut_points(op)), 0)
        self.assertTrue(self.logged(self.warn, "no sketches selected"), self.warn.call_args_list)

    def test_partial_failure(self):
        bad = self.doc.addObject("Sketcher::SketchObject", "Open")
        bad.addGeometry(Part.LineSegment(App.Vector(50, 0, 0), App.Vector(60, 5, 0)))
        bad.Label = "OpenSketch"
        self.doc.recompute()
        rect, open_ = self.job_with(make_sketch(self.doc, "Rect", [RECT]), bad)
        op = self.make_op([rect, open_])
        self.assert_inside(cut_points(op), 0, 0, 40, 20)
        self.assertTrue(self.logged(self.err, "OpenSketch"), self.err.call_args_list)

    def test_overlapping_loops(self):
        sk = make_sketch(self.doc, "Overlap",
                         [[(0, 0), (20, 0), (20, 10), (0, 10)], [(10, 5), (30, 5), (30, 15), (10, 15)]])
        (clone,) = self.job_with(sk)
        op = self.make_op([clone])
        self.assertNotIn("Invalid", op.State)
        if not self.logged(self.err, sk.Label):
            ((_, faces),) = op_vcarve.region_sets(op)
            self.assertIsInstance(faces, list)
            self.assertAlmostEqual(sum(f.Area for f in faces), 350, delta=0.1)
            for x, y in [(5, 2), (25, 12), (15, 7)]:
                self.assertTrue(any(f.isInside(App.Vector(x, y, 0), 1e-6, True) for f in faces))

    def test_wide_area_warning(self):
        sq = make_sketch(self.doc, "Square", [[(0, 0), (60, 0), (60, 60), (0, 60)]])
        (clone,) = self.job_with(sq)
        self.assertAlmostEqual(self.vbit.diameter, 10)
        self.make_op([clone])
        self.assertTrue(self.logged(self.warn, "wider than the V-bit"), self.warn.call_args_list)

    def test_edge_base(self):
        (clone,) = self.job_with(make_sketch(self.doc, "Rect", [RECT]))
        whole = self.make_op([clone], FlatDepth=1.0)
        edge = self.make_op(FlatDepth=1.0)
        edge.Proxy.addBase(edge, clone, "Edge1")
        self.doc.recompute()
        self.assertEqual(len(edge.Base), 1)
        self.assertAlmostEqual(edge.Path.BoundBox.ZMin, whole.Path.BoundBox.ZMin, delta=1e-6)
        a, b = cut_points(whole), cut_points(edge)
        np.testing.assert_allclose(a.min(axis=0), b.min(axis=0), atol=0.01)
        np.testing.assert_allclose(a.max(axis=0), b.max(axis=0), atol=0.01)

    def test_sharp_bit_flat(self):
        (clone,) = self.job_with(make_sketch(self.doc, "Rect", [RECT]))
        self.tc.Tool.TipDiameter = 0
        self.doc.recompute()
        op = self.make_op([clone], FlatDepth=1.0)
        pts = cut_points(op)
        self.assertAlmostEqual(pts[:, 2].min(), -1.0, delta=1e-6)
        self.assertEqual(self.err.call_args_list, [])

    def test_rest_pocket_failure_keeps_carve(self):
        (clone,) = self.job_with(make_sketch(self.doc, "Rect", [RECT]))
        with mock.patch.object(op_vcarve, "pocket_polylines", side_effect=RuntimeError("boom")):
            op = self.make_op([clone], FlatDepth=1.0)
        self.assertAlmostEqual(cut_points(op)[:, 2].min(), -1.0, delta=1e-6)
        self.assertTrue(self.logged(self.err, "Rect"), self.err.call_args_list)

    def test_region_sets_unexpected_error(self):
        rect, ring = self.job_with(make_sketch(self.doc, "Rect", [RECT]),
                                   make_sketch(self.doc, "Ring", [], circles=RING))
        real = op_vcarve.loops_for_base

        def loops(base, subs):
            if base == ring:
                raise RuntimeError("kaputt")
            return real(base, subs)
        with mock.patch.object(op_vcarve, "loops_for_base", side_effect=loops):
            op = self.make_op([rect, ring])
        self.assertNotIn("Invalid", op.State)
        self.assert_inside(cut_points(op), 0, 0, 40, 20)
        self.assertTrue(self.logged(self.err, "Ring: kaputt"), self.err.call_args_list)

    def test_whole_floor_warning_once(self):
        rect, ring = self.job_with(make_sketch(self.doc, "Rect", [RECT]),
                                   make_sketch(self.doc, "Ring", [], circles=RING))
        self.make_op([rect, ring], FlatDepth=1.0)
        hits = [c for c in self.warn.call_args_list if c.args and "whole floor" in str(c.args[0])]
        self.assertEqual(len(hits), 1, self.warn.call_args_list)
        self.assertIn("Clearance", str(hits[0].args[0]))

    def test_non_sketch_base(self):
        (clone,) = self.job_with(make_sketch(self.doc, "Rect", [RECT]))
        box = self.doc.addObject("Part::Box", "Box")
        box.Label = "MyBox"
        op = self.make_op([clone, box], FlatDepth=1.0)
        self.assert_inside(cut_points(op), 0, 0, 40, 20)
        self.assertTrue(self.logged(self.err, "MyBox: not a sketch"), self.err.call_args_list)

    def test_rest_clearance_hidden_and_restored(self):
        (clone,) = self.job_with(make_sketch(self.doc, "Rect", [RECT]))
        op = self.make_op([clone], FlatDepth=1.0)
        self.assertIn("Hidden", op.getEditorMode("RestClearance"))
        op.removeProperty("RestClearance")
        op.Proxy.opOnDocumentRestored(op)  # a document saved before the property existed
        self.assertIn("Hidden", op.getEditorMode("RestClearance"))

    def test_no_double_carve(self):
        (clone,) = self.job_with(make_sketch(self.doc, "Rect", [RECT]))
        whole = self.make_op([clone])
        both = self.make_op([clone])
        both.Proxy.addBase(both, clone, "Edge1")
        self.doc.recompute()
        self.assertEqual(len(op_vcarve.region_sets(both)), 1)
        self.assertEqual(len(cut_points(both)), len(cut_points(whole)))

    def test_tool_bit_linked_as_tool_controller(self):
        # The property editor offers every object, so the bit itself can be picked instead of its TC.
        (clone,) = self.job_with(make_sketch(self.doc, "Rect", [RECT]))
        op = self.make_op([clone])
        op.ToolController = self.tc.Tool
        self.assertFalse(op_vcarve._is_vbit_tc(op))
        op.Proxy.opUpdateDepths(op)  # must not raise
        self.assertTrue(self.logged(self.err, f"pick its tool controller {self.tc.Label}"),
                        self.err.call_args_list)


class ToolpathTests(unittest.TestCase):
    def test_sequence(self):
        paths = [np.array([(0, 0, -1), (1, 0, -1)]), np.array([(5, 5, -2), (6, 5, -2)])]
        cmds = paths_to_commands(paths, 3.0, 5.0, 10.0, 2.0)
        got = [(c.Name, dict(c.Parameters)) for c in cmds]
        self.assertEqual(got, [
            ("G0", {"Z": 5.0}), ("G0", {"X": 0.0, "Y": 0.0}), ("G0", {"Z": 3.0}),
            ("G1", {"Z": -1.0, "F": 2.0}), ("G1", {"X": 1.0, "Y": 0.0, "Z": -1.0, "F": 10.0}),
            ("G0", {"Z": 3.0}), ("G0", {"X": 5.0, "Y": 5.0}), ("G0", {"Z": 3.0}),
            ("G1", {"Z": -2.0, "F": 2.0}), ("G1", {"X": 6.0, "Y": 5.0, "Z": -2.0, "F": 10.0}),
            ("G0", {"Z": 5.0})])
        self.assertEqual(paths_to_commands([], 3.0, 5.0, 10.0, 2.0), [])


if __name__ == "__main__":
    unittest.main()
