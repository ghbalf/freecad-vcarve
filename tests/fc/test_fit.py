# SPDX-License-Identifier: LGPL-2.1-or-later
"""Inlay fit: the flipped plug seated in the pocket, simulated from both Jobs' paths on cross-sections."""
import math
import unittest
from unittest import mock

import FreeCAD as App
import numpy as np
import Path

from fit import cut_height, make_inlay, seated
from test_op_vcarve import RECT, RING

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


if __name__ == "__main__":
    unittest.main()
