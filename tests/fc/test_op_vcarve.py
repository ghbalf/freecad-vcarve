# SPDX-License-Identifier: LGPL-2.1-or-later
import unittest
from unittest import mock

import FreeCAD as App
import numpy as np
import Part
import Path

from helpers import add_clearance, make_job, make_sketch
from vcarve_flat import op_vcarve
from vcarve_flat.geom import VBit, flat_radius
from vcarve_flat.toolpath import paths_to_commands

RECT = [(0, 0), (40, 0), (40, 20), (0, 20)]
RING = [(70, 10, 10), (70, 10, 4)]
L_SHAPE = [(0, 0), (40, 0), (40, 10), (10, 10), (10, 30), (0, 30)]
L_FAR = [(x + 50, y) for x, y in L_SHAPE]


def cut_points(op):
    """XYZ of every G1 move (tracking modal position)."""
    pos, out = {"X": 0.0, "Y": 0.0, "Z": 0.0}, []
    for c in op.Path.Commands:
        pos.update({k: v for k, v in c.Parameters.items() if k in pos})
        if c.Name in ("G1", "G01"):
            out.append((pos["X"], pos["Y"], pos["Z"]))
    return np.array(out).reshape(-1, 3)


def g1_segments(op):
    """(start, end) XYZ arrays of the G1 moves that change XY."""
    pos, out = np.zeros(3), []
    for c in op.Path.Commands:
        new = np.array([c.Parameters.get(k, v) for k, v in zip("XYZ", pos)])
        if c.Name in ("G1", "G01") and np.hypot(*(new - pos)[:2]) > 0:
            out.append((pos, new))
        pos = new
    return np.array([a for a, _ in out]), np.array([b for _, b in out])


def g1_length(op, z=None) -> float:
    """XY length of the G1 moves, only those at height z if given."""
    a, b = g1_segments(op)
    if not len(a):
        return 0.0
    keep = np.ones(len(a), bool) if z is None else (np.abs(a[:, 2] - z) < 1e-6) & (np.abs(b[:, 2] - z) < 1e-6)
    return float(np.hypot(*(b - a)[keep, :2].T).sum())


def z_on_path(points, segments):
    """For each point, the lowest Z of the path points nearest to it in XY."""
    a, b = segments
    ab = (b - a)[None, :, :2]
    t = np.clip((((points[:, None, :2] - a[None, :, :2]) * ab).sum(axis=2) / (ab ** 2).sum(axis=2)), 0, 1)
    q = a[None] + t[..., None] * (b - a)[None]
    d2 = ((q[..., :2] - points[:, None, :2]) ** 2).sum(axis=2)
    return np.where(d2 <= d2.min(axis=1, keepdims=True) + 1e-9, q[..., 2], np.inf).min(axis=1)


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
        if "StepDown" in props:
            op.setExpression("StepDown", None)  # else the setup sheet's expression wins on recompute
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

    def test_ring_of_circles(self):
        """OCC's inward offset of an annulus of full circles returns the counter (1.1) or shrinks the hole
        (1.0); the walls and the floor must still be the annulus."""
        (ring,) = self.job_with(make_sketch(self.doc, "Ring", [], circles=RING))
        op = self.make_op([ring], FlatDepth=1.0)
        pts = cut_points(op)
        r = np.hypot(pts[:, 0] - 70, pts[:, 1] - 10)
        self.assertGreater(r.min(), 4 - 1e-6)  # the counter stays uncut
        self.assertLess(r.max(), 10 + 1e-6)
        rr = r[np.abs(pts[:, 2] + 1) < 1e-6]
        rf = flat_radius(self.vbit, 1.0)
        self.assertLess(np.abs(rr - (10 - rf)).min(), 0.02)  # the outer wall loop
        self.assertLess(np.abs(rr - (4 + rf)).min(), 0.02)  # the inner wall loop
        self.assertTrue(((rr > 4 + rf + 0.5) & (rr < 10 - rf - 0.5)).any())  # the floor

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

    def test_sharp_inner_corner(self):
        # L with an inner corner at (10, 10): the wood kept is x > 10, y > 10, and at depth h its
        # edge lies h*t further out with a sharp corner, so no cone and no floor may reach into it
        (clone,) = self.job_with(make_sketch(self.doc, "L", [L_SHAPE]))
        op = self.make_op([clone], FlatDepth=3.0)
        t = np.tan(self.vbit.half_angle)
        pts = cut_points(op)
        for h in (0.5, 1.5, 2.5):
            q = 10 - h * t
            below = pts[pts[:, 2] < -h]
            radius = self.vbit.tip_radius + (-h - below[:, 2]) * t
            dist = np.hypot(np.maximum(q - below[:, 0], 0), np.maximum(q - below[:, 1], 0))
            self.assertTrue(np.all(dist >= radius - 0.01), (h, (radius - dist).max()))
        cs = op.Proxy.levels(op)[-1]
        (faces,) = [fs for _, fs in op.Proxy.regions(op)]
        r = 10 - cs.r_flat * 0.9  # just inside the round corner the floor had
        self.assertFalse(any(f.isInside(App.Vector(r, r, f.BoundBox.ZMin), 1e-6, True)
                             for f in op.Proxy.floor(op, cs, faces)))

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

    def test_rest_chain_hidden_and_restored(self):
        (clone,) = self.job_with(make_sketch(self.doc, "Rect", [RECT]))
        op = self.make_op([clone], FlatDepth=1.0)
        self.assertIn("Hidden", op.getEditorMode("RestChain"))
        op.removeProperty("RestChain")
        op.Proxy.opOnDocumentRestored(op)  # a document saved before the property existed
        self.assertIn("Hidden", op.getEditorMode("RestChain"))

    def test_vbit_rest_shrinks_with_rest_op(self):
        (clone,) = self.job_with(make_sketch(self.doc, "Design", [RECT, L_FAR]))
        self.tc.Tool.TipDiameter = 0  # 1.0's V-bit has a 1 mm tip, too wide for the rest corners
        op = self.make_op([clone], FlatDepth=2.0)
        add_clearance(self.doc, self.job, op, 5.0)
        one = g1_length(op, -2.0)
        add_clearance(self.doc, self.job, op, 1.0, rest_only=True)
        self.assertEqual(op.RestChain, "2.5,0;0.5,0")
        self.assertLess(g1_length(op, -2.0), one)
        self.assertFalse(self.logged(self.warn, "several"), self.warn.call_args_list)

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

    def test_stepdown_passes(self):
        (clone,) = self.job_with(make_sketch(self.doc, "Rect", [RECT]))
        one = self.make_op([clone], FlatDepth=3.0, StepDown=0)
        multi = self.make_op([clone], FlatDepth=3.0, StepDown=1.0)
        pts, ref = cut_points(multi), cut_points(one)
        zs = np.round(pts[:, 2], 6)
        for z in (-1, -2, -3):
            self.assertIn(z, zs)
        self.assertAlmostEqual(pts[:, 2].min(), ref[:, 2].min(), delta=1e-6)
        self.assert_inside(pts, *ref[:, :2].min(axis=0), *ref[:, :2].max(axis=0))
        segments = g1_segments(one)
        for chunk in np.array_split(pts, max(1, len(pts) // 100)):
            self.assertTrue(np.all(chunk[:, 2] >= z_on_path(chunk, segments) - 0.01))

    def test_stepdown_zero_is_one_pass(self):
        (clone,) = self.job_with(make_sketch(self.doc, "Rect", [RECT]))
        a = self.make_op([clone], FlatDepth=3.0, StepDown=0)
        b = self.make_op([clone], FlatDepth=3.0, StepDown=100.0)
        np.testing.assert_array_equal(cut_points(a), cut_points(b))

    def test_stepdown_no_flat_stops_when_unclamped(self):
        # A slot carved 1.5 deep in full: levels 1 and 2 cut, level 2 clamps nothing, and the levels
        # down to the cone height (8.66) would repeat it.
        self.job_with(make_sketch(self.doc, "Rect", [RECT]))
        w = 2 * flat_radius(self.vbit, 1.5)  # from the bit: its tip differs between FreeCAD versions
        slot = make_sketch(self.doc, "Slot", [[(0, 0), (30, 0), (30, w), (0, w)]])
        one = self.make_op([slot], StepDown=0)
        multi = self.make_op([slot], StepDown=1.0)
        plunges = lambda op: sum(1 for c in op.Path.Commands
                                 if c.Name in ("G1", "G01") and set(c.Parameters) <= {"Z", "F"})
        self.assertEqual(plunges(multi), 2 * plunges(one))
        self.assertIn(-1, np.round(cut_points(multi)[:, 2], 6))
        self.assertAlmostEqual(cut_points(multi)[:, 2].min(), cut_points(one)[:, 2].min(), delta=1e-6)
        self.assertAlmostEqual(cut_points(one)[:, 2].min(), -1.5, delta=0.01)

    def test_restored_without_stepdown(self):
        (clone,) = self.job_with(make_sketch(self.doc, "Rect", [RECT]))
        ref = self.make_op([clone], FlatDepth=3.0, StepDown=0)
        op = self.make_op([clone], FlatDepth=3.0, StepDown=1.0)
        op.removeProperty("StepDown")
        op.Proxy.onDocumentRestored(op)  # a v1 document
        self.assertEqual(op.StepDown.Value, 0)
        op.recompute()
        np.testing.assert_array_equal(cut_points(op), cut_points(ref))


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
