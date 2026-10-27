# SPDX-License-Identifier: LGPL-2.1-or-later
# Authors: alf and Claude (Anthropic)
"""Core invariant: V-bit rest area + end-mill swept area = the whole flat floor."""
import math
import unittest
from unittest import mock

import FreeCAD as App
import numpy as np
import Path

from helpers import make_job, make_sketch
from test_op_clearance import NECK
from vcarve_flat import op_clearance, op_vcarve
from vcarve_flat.clearing import offset_faces
from vcarve_flat.geom import distances_to_segments

# Discretization noise of the cut paths (curve deflection, simplify tolerance, Path.Area arc
# approximation) measured at 0.03-0.04 mm on these shapes; a real uncut band is >= 0.4 mm wide.
EPS = 0.05
GRID = 0.25  # mm between floor samples
# The library 60 degree V-bit has a 0.1 mm tip from 1.1 on but 1.0 mm in 1.0.2; pin it so every
# version checks the same geometry. (Wider tips leave small rest-pocket gaps, see README limitations.)
TIP = 0.1


def flat_segments(op, z):
    """XY segments of the G1 moves of op that run at height z."""
    pos, out = {"X": 0.0, "Y": 0.0, "Z": 0.0}, []
    for c in op.Path.Commands:
        new = dict(pos, **{k: v for k, v in c.Parameters.items() if k in pos})
        if c.Name in ("G1", "G01") and abs(pos["Z"] - z) < 1e-6 and abs(new["Z"] - z) < 1e-6:
            out.append(((pos["X"], pos["Y"]), (new["X"], new["Y"])))
        pos = new
    return np.array(out, float).reshape(-1, 2, 2)


class FloorCoverageTests(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("cov")
        mock.patch.object(Path.Log, "warning").start()
        self.err = mock.patch.object(Path.Log, "error").start()
        self.addCleanup(mock.patch.stopall)

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def uncovered(self, pattern, loops):
        job, _ = make_job(self.doc, [make_sketch(self.doc, "S", loops)])
        clr, vc = op_clearance.create_pair(job)
        vc.ToolController.Tool.TipDiameter = TIP
        vc.BaseShapes = list(job.Model.Group)
        vc.FlatDepth = 1.0
        clr.PocketPattern = pattern
        self.doc.recompute()
        self.assertEqual(self.err.call_args_list, [])
        cs = op_vcarve.carve_setup(vc)
        z = cs.z_top - cs.depth
        (_, faces), = op_vcarve.region_sets(vc)
        floor = offset_faces(faces, -cs.r_flat)
        bb = floor[0].BoundBox
        xs, ys = np.meshgrid(np.arange(bb.XMin, bb.XMax, GRID), np.arange(bb.YMin, bb.YMax, GRID))
        pts = np.array([(x, y) for x, y in zip(xs.ravel(), ys.ravel())
                        if any(f.isInside(App.Vector(x, y, bb.ZMin), 1e-6, True) for f in floor)])
        mill, vbit = flat_segments(clr, z), flat_segments(vc, z)
        self.assertTrue(len(pts) and len(mill) and len(vbit))
        r_mill = clr.ToolController.Tool.Diameter.Value / 2
        r_vbit = cs.vbit.tip_radius + vc.RestScallop.Value * math.tan(cs.vbit.half_angle)
        gap = np.minimum(distances_to_segments(pts, mill) - r_mill, distances_to_segments(pts, vbit) - r_vbit)
        return pts[gap > EPS], gap.max()

    def check(self, pattern):
        bad, worst = self.uncovered(pattern, [NECK])
        self.assertEqual(len(bad), 0, f"{pattern}: {len(bad)} floor samples uncut, worst gap {worst:.3f} mm, "
                                      f"e.g. {bad[:5].round(2).tolist()}")

    def test_offset(self):
        self.check("Offset")

    def test_zigzag(self):
        self.check("ZigZag")


if __name__ == "__main__":
    unittest.main()
