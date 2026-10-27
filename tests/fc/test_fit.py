# SPDX-License-Identifier: LGPL-2.1-or-later
"""Inlay fit: the flipped plug seated in the pocket, simulated from both Jobs' paths on cross-sections."""
import math
import os
import tempfile
import unittest
from unittest import mock

import FreeCAD as App
import numpy as np
import Path

from fit import make_inlay, seated
from helpers import add_clearance
from test_op_vcarve import L_SHAPE, RECT, RING
from vcarve_flat import fit as fitcheck
from vcarve_flat import fit_object, progress
from vcarve_flat.fit import cut_height

BAR3 = [(0, 24), (30, 24), (30, 27), (0, 27)]
LETTERS = [[(34, 24), (44, 24), (44, 34), (34, 34)], [(44.3, 24), (54.3, 24), (54.3, 34), (44.3, 34)]]
THIN = [(58, 22), (80, 22), (80, 22.8), (58, 22.8)]
LOOPS = [RECT, BAR3, *LETTERS, THIN]
GAPS = [((44, 24), (44.3, 34))]  # between the letters: narrower than a 1 mm tip (the plug op warns)
CENTRE = (40, 17)  # the design bbox (0..80, 0..34) centre, the plug's mirror centre
LINES = {"wide": 5, "counter": 10, "bar": 25.5, "thin bar": 22.4, "letter gap": 29}
TOL = 0.02


def dist_to_segments(pts, a, b):
    ab = b - a
    u = np.clip(((pts[:, None] - a) * ab).sum(-1) / (ab * ab).sum(-1), 0, 1)
    return np.hypot(*(pts[:, None] - a - u[..., None] * ab).transpose(2, 0, 1)).min(axis=1)


def corner_strips(n):
    """Strips along the bisectors of the design's (all convex, 90 degree) corners where the ridge pass
    leaves the spec's corner void (R13). Half-angle h, s = sin h, c = cos h: the pocket's tip centres
    lie on the bisector at depth (r - r_t) / t, and the ridge pass cuts the seated plug with the same
    tip from the same centres, so on the bisector the plug lies 2 r_t s / t (1.22 mm) above the pocket.
    At w from the bisector the ridge cone from a centre e behind lifts the plug above the V wall while
    e s + 2 r_t - hypot(e, w) > w c; the best e = w tan h gives w < r_t / c. The wall rule (R8) holds
    where the pocket is shallower than start, which for such w is within (r_t + start t) / s of the
    corner."""
    r_t, h = n.vbit.tip_radius, math.pi / 4
    length = (r_t + n.start * n.t) / math.sin(h)
    a, b = [], []
    for loop in LOOPS:
        c = np.array(loop, float)
        u = np.roll(c, 1, axis=0) - c
        v = np.roll(c, -1, axis=0) - c
        bis = u / np.hypot(*u.T)[:, None] + v / np.hypot(*v.T)[:, None]
        a.append(c)
        b.append(c + length * bis / np.hypot(*bis.T)[:, None])
    return np.vstack(a), np.vstack(b), r_t / math.cos(h)


def line(y):
    x = np.arange(0, 80 + 1e-9, 0.05)
    return np.column_stack([x, np.full_like(x, y)])


class CutHeightTests(unittest.TestCase):
    def test_exact_between_samples(self):
        # Path points 0.05 mm apart read a pointed V up to 0.025/t = 0.043 mm too shallow between them
        t = math.tan(math.radians(30))
        q = np.array([(5.025, 0.0), (5.0, 1.0), (7.31, -0.4), (0.2, 0.9)])
        for (a, b), tool in [(((0, 0, -1), (10, 0, -1)), (3, 0, t)), (((0, 0, -2), (10, 0, 0)), (3, 0, t)),
                             (((0, 0, -2), (10, 0, 0)), (3, 0.5, t)), (((0, 0, -2), (10, 0, 0)), (2.5, 2.5, math.inf))]:
            a, b = np.array([a], float), np.array([b], float)
            u = np.linspace(0, 1, 200001)[:, None]
            c = a + u * (b - a)
            radius, tip, slope = tool
            rho = np.hypot(q[:, None, 0] - c[None, :, 0], q[:, None, 1] - c[None, :, 1])
            z = np.where(rho <= radius, c[None, :, 2] + np.maximum(0, rho - tip) / slope, np.inf).min(axis=1)
            np.testing.assert_allclose(cut_height([((a, b), tool)], q), np.minimum(z, 0), atol=1e-4)
        # a plunge cuts only around its axis
        plunge = (np.array([(5.0, 0, 0)]), np.array([(5.0, 0, -1)]))
        np.testing.assert_allclose(cut_height([(plunge, (3, 0, t))], np.array([(5, 0), (5, 0.3), (9, 0)])),
                                   [-1, -1 + 0.3 / t, 0], atol=1e-9)


class FitTests(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("fit")
        mock.patch.object(Path.Log, "warning").start()
        self.err = mock.patch.object(Path.Log, "error").start()
        self.addCleanup(mock.patch.stopall)

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def fit(self, tip, ridge=True, stepdown=None):
        self.n = make_inlay(self.doc, LOOPS, RING, tip, stepdown, ridge)
        self.assertFalse(self.err.called, self.err.call_args_list)
        return {name: (line(y), seated(self.n, line(y), CENTRE)) for name, y in LINES.items()}

    def assert_fit(self, cuts, tipped=False):
        P, G = self.n.P, self.n.G
        floor = wall = 0
        for name, (pts, f) in cuts.items():
            ok = np.ones(len(pts), bool)
            if tipped:  # the documented tipped-bit effects
                a, b, half_width = corner_strips(self.n)
                ok &= dist_to_segments(pts, a, b) >= half_width
                ga, gb = (np.array(g, float) for g in zip(*GAPS))
                lo, hi = np.minimum(ga, gb), np.maximum(ga, gb)
                ok &= np.hypot(*np.maximum(0, np.maximum(lo - pts[:, None], pts[:, None] - hi)).transpose(2, 0, 1)
                               ).min(axis=1) >= self.n.vbit.tip_radius
            gap, z, s = f.gap[ok], f.z[ok], f.s[ok]
            msg = lambda m: f"{name}: at x={pts[ok][m][:, 0]} gap={gap[m]}"  # noqa: E731
            bad = gap < -TOL
            self.assertFalse(bad.any(), msg(bad))
            at_floor = (np.abs(z + P) < 1e-3) & (np.abs(s) < 1e-3)
            bad = at_floor & (np.abs(gap - G) > TOL)
            self.assertFalse(bad.any(), msg(bad))
            on_wall = (z > -P + G + 0.01) & (z < -0.01)  # R8: both sides on their walls
            bad = on_wall & (gap > TOL)
            self.assertFalse(bad.any(), msg(bad))
            band = (z > -P + 0.01) & (z <= -P + G + 0.01)  # the plug's top faces the wall's foot
            bad = band & (gap > G + TOL)
            self.assertFalse(bad.any(), msg(bad))
            floor += at_floor.sum()
            wall += on_wall.sum()
        self.assertGreater(floor, 100)
        self.assertGreater(wall, 100)

    def test_fit_sharp(self):
        self.assert_fit(self.fit(tip=0))

    def test_fit_tipped_ridge(self):
        self.assert_fit(self.fit(tip=1), tipped=True)

    def test_fit_tipped_no_ridge(self):
        cuts = self.fit(tip=1, ridge=False)
        vbit = self.n.vbit
        self.assertLess(cuts["bar"][1].gap.min(), -0.5 * vbit.tip_radius / self.n.t)

    def test_fit_stepdown(self):
        self.assert_fit(self.fit(tip=0, stepdown=1))

    def test_fit_inner_corner(self):
        """The plug's walls above Z_v keep the letter's inner corner sharp, like the pocket's."""
        n = make_inlay(self.doc, [L_SHAPE], tip=0)
        self.assertFalse(self.err.called, self.err.call_args_list)
        x, y = np.meshgrid(np.arange(6, 14, 0.1), np.arange(6, 14, 0.1))
        pts = np.column_stack([x.ravel(), y.ravel()])
        gap = seated(n, pts, (20, 15)).gap
        self.assertGreater(gap.min(), -TOL, pts[gap.argmin()])

    def test_fit_wide_counter(self):
        """A counter wider than the plug's margin ring is cleared all over, not left as waste."""
        n = make_inlay(self.doc, [RECT], [(70, 10, 15), (70, 10, 13)], tip=0)  # PlugMargin 10
        self.assertFalse(self.err.called, self.err.call_args_list)
        x, y = np.meshgrid(np.arange(57.5, 82.5, 0.5), np.arange(-2.5, 22.5, 0.5))
        pts = np.column_stack([x.ravel(), y.ravel()])
        pts = pts[np.hypot(pts[:, 0] - 70, pts[:, 1] - 10) < 12.5]
        gap = seated(n, pts, (42.5, 10)).gap  # the design bbox x 0..85
        self.assertGreater(gap.min(), -TOL, pts[gap.argmin()])


class CheckTests(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("check")
        mock.patch.object(Path.Log, "warning").start()
        mock.patch.object(Path.Log, "error").start()
        self.addCleanup(mock.patch.stopall)

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def test_check_fits(self):
        n = make_inlay(self.doc, LOOPS, tip=0)
        r = fitcheck.check(n.plug)
        self.assertIsNone(r.error)
        self.assertEqual(r.grid, 0.25)
        self.assertEqual(r.points.shape, (len(r.gap), 2))
        self.assertGreater(len(r.gap), 10000)
        self.assertEqual({o.Name for o in r.ops}, {o.Name for o in (n.vc, n.pocket_clr, n.plug, n.clr)})
        self.assertFalse(r.collisions.any(), r.points[r.collisions])
        self.assertEqual(r.worst_collision, 0)
        self.assertEqual(r.worst_void, r.gap[r.voids].max(initial=0))
        # the points are the mirrors of the plug's bound: none lies far outside the design bbox (0..80, 0..34)
        self.assertLess(np.abs(r.points - CENTRE).max(axis=0)[0], 40 + 15)

    def test_check_finds_collision(self):
        n = make_inlay(self.doc, LOOPS, tip=1, ridge=False)
        r = fitcheck.check(n.plug)
        self.assertIsNone(r.error)
        self.assertTrue(r.collisions.any())
        self.assertLess(r.worst_collision, -0.1)
        self.assertEqual(r.worst_collision, r.gap.min())
        np.testing.assert_array_equal(r.collisions, r.gap < -0.02)

    def test_check_ring(self):
        """An island left in the margin ring rests on the board around the pocket."""
        n = make_inlay(self.doc, LOOPS, tip=0)
        n.clr.Path = Path.Path(n.clr.Path.Commands[:len(n.clr.Path.Commands) // 2])
        n.clr.purgeTouched()
        r = fitcheck.check(n.plug)
        self.assertIsNone(r.error)
        self.assertTrue((r.collisions & (r.z == 0)).any())

    def test_check_refuses_touched(self):
        n = make_inlay(self.doc, LOOPS, tip=0)
        n.clr.Active = False
        r = fitcheck.check(n.plug, grid=1)
        self.assertRegex(r.error, ": out of date, recompute it first$")
        self.assertEqual(len(r.points), 0)
        self.doc.recompute()
        r = fitcheck.check(n.plug, grid=1)
        self.assertIsNone(r.error)
        self.assertNotIn(n.clr, r.ops)
        self.assertFalse((r.collisions & (r.z == 0)).any())

    def test_check_guards(self):
        n = make_inlay(self.doc, LOOPS, tip=0)
        with mock.patch.object(n.plug.Proxy, "_design", return_value=[]):
            self.assertEqual(fitcheck.check(n.plug).error, f"{n.plug.Label}: no design")
        n.plug.PocketOp = None
        self.assertEqual(fitcheck.check(n.plug).error, f"{n.plug.Label}: no pocket op linked")

    def test_check_refuses_empty_paths(self):
        n = make_inlay(self.doc, LOOPS, tip=0)
        n.plug.Active = False
        self.doc.recompute()
        r = fitcheck.check(n.plug)
        self.assertEqual(r.error, f"{n.plug.Label}: no toolpath, recompute it first")
        self.assertEqual(len(r.points), 0)

    def test_signature_changes(self):
        n = make_inlay(self.doc, LOOPS, tip=0)
        ops = fitcheck.check(n.plug, grid=2).ops
        before = fitcheck.signature(ops)
        self.assertEqual(fitcheck.signature(ops), before)
        n.plug.GlueGap = 0.3
        self.doc.recompute()
        self.assertNotEqual(fitcheck.signature(ops), before)


def assert_squares(case, shape, points, mask, grid):
    """shape covers the squares around points[mask] and none of the others' centres."""
    np.testing.assert_array_equal(fitcheck._inside(points, shape.Faces), mask)
    case.assertAlmostEqual(shape.Area, mask.sum() * grid ** 2, delta=0.02 * mask.sum() * grid ** 2)


class SquaresTests(unittest.TestCase):
    def test_squares(self):
        """Squares that touch only at a corner (Path.Area drops or inverts whole regions of them)."""
        x, y = np.meshgrid(np.arange(30) * 0.25 + 0.1, np.arange(30) * 0.25 - 3)
        points = np.column_stack([x.ravel(), y.ravel()])
        for mask in (np.random.default_rng(1).random(len(points)) < 0.5, (np.arange(len(points)) % 31) % 2 == 0):
            assert_squares(self, fit_object._squares(points[mask], 0.25, 0), points, mask, 0.25)


class FitObjectTests(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("fitobj")
        mock.patch.object(Path.Log, "warning").start()
        self.err = mock.patch.object(Path.Log, "error").start()
        self.addCleanup(mock.patch.stopall)
        self.n = make_inlay(self.doc, LOOPS, tip=1, ridge=False)  # collides
        self.result = fitcheck.check(self.n.plug, grid=1)
        self.assertIsNone(self.result.error)
        r = self.result
        r.voids = ~r.collisions & (np.arange(len(r.gap)) % 5 == 0)  # the inlay has none to show
        r.worst_void = r.gap[r.voids].max()

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def assert_valid(self, obj):
        obj.touch()
        self.doc.recompute()
        self.assertFalse({"Invalid", "Error", "Touched"} & set(obj.State), obj.State)

    def assert_outdated(self, obj, area):
        self.doc.recompute()
        self.assertIn("Invalid", obj.State)
        self.assertIn("outdated: run Check Inlay Fit", obj.getStatusString())
        self.assertAlmostEqual(obj.Shape.Area, area, 6)

    def test_fit_object(self):
        n, r = self.n, self.result
        obj = fit_object.create(self.doc, n.plug, r)
        self.assertEqual(obj.Label, "S Fit")
        self.assertEqual((obj.PlugOp, obj.PocketOp, list(obj.ClearanceOps)), (n.plug, n.vc, [n.pocket_clr, n.clr]))
        self.assertEqual(obj.Signature, fitcheck.signature(r.ops))
        self.assertEqual((obj.Collisions, obj.Voids), (r.collisions.sum(), r.voids.sum()))
        self.assertGreater(obj.Collisions, 0)
        self.assertGreater(obj.Voids, 0)
        self.assertAlmostEqual(obj.WorstCollision.Value, r.worst_collision, 6)
        self.assertAlmostEqual(obj.WorstVoid.Value, r.worst_void, 6)
        hits, voids = obj.Shape.SubShapes
        for part, mask in ((hits, r.collisions), (voids, r.voids)):
            assert_squares(self, part, r.points, mask, r.grid)
            bb = part.BoundBox
            self.assertAlmostEqual(bb.ZMin, n.vc.StartDepth.Value + 0.01, 6)
            self.assertAlmostEqual(bb.ZMax, bb.ZMin, 6)
            self.assertAlmostEqual(bb.XMin, r.points[mask, 0].min() - r.grid / 2, 2)
            self.assertAlmostEqual(bb.YMax, r.points[mask, 1].max() + r.grid / 2, 2)
        self.assert_valid(obj)
        area = obj.Shape.Area
        n.plug.GlueGap = 0.3
        self.assert_outdated(obj, area)

    def test_fit_object_chain_changes(self):
        """A clearance op deactivated or added later makes it outdated, like a changed path."""
        n = self.n
        obj = fit_object.create(self.doc, n.plug, self.result)
        self.assert_valid(obj)
        area = obj.Shape.Area
        n.clr.Active = False
        self.assert_outdated(obj, area)
        n.clr.Active = True
        self.assert_valid(obj)
        add_clearance(self.doc, n.job, n.vc, 1, rest_only=True)
        obj.touch()
        self.assert_outdated(obj, area)
        n.plug.PocketOp = None
        obj.touch()
        self.assert_outdated(obj, area)

    def test_fit_object_restore(self):
        obj = fit_object.create(self.doc, self.n.plug, self.result)
        self.doc.recompute()
        name, area, faces, signature = obj.Name, obj.Shape.Area, len(obj.Shape.Faces), obj.Signature
        path = os.path.join(tempfile.mkdtemp(), "fit.FCStd")
        self.doc.saveAs(path)
        App.closeDocument(self.doc.Name)
        self.doc = App.openDocument(path)
        obj = self.doc.getObject(name)
        self.assertIsInstance(obj.Proxy, fit_object.Fit)
        self.assertEqual((obj.Signature, len(obj.Shape.Faces), len(obj.Shape.SubShapes)), (signature, faces, 2))
        self.assertAlmostEqual(obj.Shape.Area, area, 6)
        self.assert_valid(obj)

    def fits(self):
        return [o for o in self.doc.Objects if isinstance(getattr(o, "Proxy", None), fit_object.Fit)]

    def test_run_replaces(self):
        n, attached = self.n, []
        self.doc.UndoMode = 1
        with mock.patch.object(fitcheck, "check", return_value=self.result), \
                mock.patch.object(App.Console, "PrintWarning") as warn:
            for _ in range(2):
                fit_object.run(n.plug, lambda obj: attached.append(obj.Name))
        second = self.doc.getObject(attached[1])
        self.assertEqual((self.fits(), len(attached)), ([second], 2))
        self.assertFalse({"Invalid", "Touched"} & set(second.State), second.State)
        r = self.result
        warn.assert_called_with(f"S Fit: worst collision {r.worst_collision:.2f} mm at {r.collisions.sum()} spots, "
                                f"worst void {r.worst_void:.2f} mm\n")
        self.assertEqual(self.doc.UndoNames[:2], ["Check Inlay Fit"] * 2)

    def test_run_keeps_old_on_error_or_cancel(self):
        n = self.n
        with mock.patch.object(fitcheck, "check", return_value=self.result), \
                mock.patch.object(App.Console, "PrintWarning"):
            old = fit_object.run(n.plug)
        failed = fitcheck.FitResult(*([None] * 9), error="S: out of date, recompute it first")

        def cancel(plug):
            raise progress.Cancelled

        for check in (mock.Mock(return_value=failed), cancel):
            with mock.patch.object(fitcheck, "check", check):
                self.assertIsNone(fit_object.run(n.plug))
            self.assertEqual(self.fits(), [old])
        self.err.assert_called_once_with("S: out of date, recompute it first")

    def test_summary(self):
        r = self.result
        r.collisions[:], r.voids[:], r.worst_collision, r.worst_void = False, False, 0.0, 0.0
        obj = fit_object.create(self.doc, self.n.plug, r)
        self.assertEqual(fit_object.summary(obj), "S Fit: fits")
        obj.Voids, obj.WorstVoid = 3, 0.123
        self.assertEqual(fit_object.summary(obj), "S Fit: worst void 0.12 mm")

    def test_plug_of(self):
        n = self.n
        for sel in (n.plug, n.pjob, n.vc, n.job):
            self.assertEqual(fit_object.plug_of([n.etc, sel]), n.plug)
        self.assertIsNone(fit_object.plug_of([n.etc]))
        self.assertIsNone(fit_object.plug_of([]))


if __name__ == "__main__":
    unittest.main()
