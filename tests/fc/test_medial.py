# SPDX-License-Identifier: LGPL-2.1-or-later
import math
import unittest

import FreeCAD as App
import numpy as np
import Part

from vcarve_flat.clearing import offset_faces, pocket_polylines, subtract, swept_faces
from vcarve_flat.geom import VBit, depth_for_radius, distances_to_segments
from vcarve_flat.medial import boundary_segments, carve_polylines, flat_boundary_loops
from vcarve_flat.sketches import faces_from_loops

V = App.Vector
KW = dict(deflection=0.01, colinear_deg=10.0, step=0.5, tol=0.005)


def poly_face(pts):
    return Part.Face(Part.makePolygon([V(x, y, 0) for x, y in pts + pts[:1]]))


def ring_face():  # Task 3 fixture: 40x20 rectangle with a r=4 hole at (10, 10)
    outer = Part.makePolygon([V(x, y, 0) for x, y in [(0, 0), (40, 0), (40, 20), (0, 20), (0, 0)]])
    hole = Part.Wire(Part.makeCircle(4, V(10, 10, 0)))
    return faces_from_loops("Ring", [outer, hole])[0]


RECT = poly_face([(0, 0), (40, 0), (40, 20), (0, 20)])
L_FACE = poly_face([(0, 0), (30, 0), (30, 8), (8, 8), (8, 30), (0, 30)])
# Letter "A" of DejaVu Sans Bold 50 mm from a user's Draft ShapeString -> sketch (FreeCAD 1.1.4): the
# hole's left edge is split into collinear pieces, which gave a degenerate Voronoi parabola
A_OUTER = [(50.564671391287, 39.965727300281), (70.720921391287, 39.965727300281),
           (73.868242819858, 30.822870157424), (86.825832105573, 30.822870157424),
           (68.310207105573, 80.822870157424), (52.941903534144, 80.822870157424),
           (34.426278534144, 30.822870157424), (47.383867819858, 30.822870157424)]
A_HOLE = [(67.473153534144, 49.251441585995), (53.778957105573, 49.251441585995),
          (53.792363041677, 49.290242506754), (53.805768977782, 49.329043427513),
          (53.832580849992, 49.406645269031), (53.886204594412, 49.561848952067),
          (53.993452083251, 49.872256318138), (54.20794706093, 50.493071050281),
          (54.636937016287, 51.734700514567), (55.494916927001, 54.217959443138),
          (57.21087674843, 59.184477300281), (60.642796391287, 69.117513014567)]


class MedialTests(unittest.TestCase):
    def test_collinear_boundary_points(self):
        wires = [Part.makePolygon([V(x, y, 0) for x, y in pts + pts[:1]]) for pts in (A_OUTER, A_HOLE)]
        face, = faces_from_loops("A", wires)
        paths = carve_polylines(face, VBit(10, 90, 0.1), 0.0, 1.0, **KW)
        self.assertTrue(paths)

    def test_rectangle_depth(self):
        vbit = VBit(10, 90, 0)
        paths = carve_polylines(RECT, vbit, 0.0, 5.0, **KW)
        self.assertTrue(paths)
        z = np.concatenate([p[:, 2] for p in paths])
        self.assertAlmostEqual(z.min(), -5.0, delta=0.05)
        corners = [(0, 0), (40, 0), (40, 20), (0, 20)]
        ends = [e for p in paths for e in (p[0], p[-1])
                if min(math.dist(e[:2], c) for c in corners) < 1e-3]
        self.assertEqual(len(ends), 4)
        for e in ends:
            self.assertAlmostEqual(e[2], 0.0, delta=1e-3)

    def test_containment(self):
        vbit = VBit(6, 60, 0.2)
        for face in (L_FACE, ring_face()):
            segs = boundary_segments(face, KW["deflection"])
            paths = carve_polylines(face, vbit, 0.0, vbit.cone_height, **KW)
            self.assertTrue(paths)
            pts = np.vstack(paths)
            depth = -pts[:, 2]
            dist = distances_to_segments(pts[:, :2], segs)
            self.assertTrue(np.all(dist >= depth * math.tan(vbit.half_angle) - 1e-3))
            for x, y, _ in pts:
                self.assertTrue(face.isInside(V(x, y, 0), 1e-6, True), (x, y))

    def test_flat_clamp_and_boundary(self):
        vbit = VBit(10, 90, 0)
        paths = carve_polylines(RECT, vbit, 0.0, 2.0, **KW)
        paths += flat_boundary_loops(RECT, vbit, 0.0, 2.0, deflection=KW["deflection"], tol=KW["tol"])
        self.assertGreaterEqual(min(p[:, 2].min() for p in paths), -2.0 - 1e-9)
        loops = [p for p in paths if np.allclose(p[:, 2], -2.0) and np.allclose(p[0], p[-1])
                 and len(p) > 3]
        boxes = [(p[:, 0].min(), p[:, 1].min(), p[:, 0].max(), p[:, 1].max()) for p in loops]
        self.assertTrue(any(np.allclose(b, (2, 2, 38, 18), atol=0.01) for b in boxes), boxes)

    def test_no_medial_run_on_floor(self):
        # The end mill and the rest pocket clear the floor; a medial pass along it only marks it
        paths = carve_polylines(RECT, VBit(10, 90, 0), 0.0, 2.0, drop_floor=True, **KW)
        self.assertTrue(paths)
        for p in paths:
            self.assertFalse(np.any(np.isclose(p[:-1, 2], -2.0) & np.isclose(p[1:, 2], -2.0)), p)

    def test_depth_matches_distance(self):
        vbit = VBit(10, 90, 0)
        segs = boundary_segments(RECT, KW["deflection"])
        for p in carve_polylines(RECT, vbit, 0.0, 5.0, **KW):
            want = -depth_for_radius(vbit, distances_to_segments(p[:, :2], segs), 5.0)
            np.testing.assert_allclose(p[:, 2], want, atol=1e-6)


class ClearingTests(unittest.TestCase):
    def test_offset_empty(self):
        self.assertEqual(offset_faces([poly_face([(0, 0), (5, 0), (5, 5), (0, 5)])], -3), [])

    def test_offset_error_propagates(self):
        class Failing:
            def makeOffset2D(self, *args, **kw):
                raise Part.OCCError("BRep_API: command not done")
        with self.assertRaises(Part.OCCError):
            offset_faces([Failing()], -1)

    def test_offset_zero(self):
        self.assertEqual(offset_faces([RECT], 0), [RECT])

    def test_rest_area(self):
        floor = [poly_face([(0, 0), (30, 0), (30, 4), (40, 4), (40, 6), (30, 6), (30, 10), (0, 10)])]
        rest = subtract(floor, swept_faces(floor, 1.5, 0))
        self.assertTrue(rest)
        self.assertTrue(any(f.isInside(V(35, 5, 0), 1e-6, True) for f in rest))

    def test_rest_area_ring(self):
        # An "O": OCC's outward makeOffset2D dropped the outer wire of such faces (or failed), so the
        # end mill seemed to clear almost nothing and the V-bit re-cleared the whole floor
        floor = Part.Face(Part.Wire(Part.makeCircle(20))).cut(Part.Face(Part.Wire(Part.makeCircle(12)))).Faces
        rest = subtract(floor, swept_faces(floor, 1.5875, 0))
        self.assertLess(sum(f.Area for f in rest), 0.01 * floor[0].Area)

    def test_subtract_empty(self):
        self.assertEqual(subtract([RECT], []), [RECT])
        self.assertEqual(subtract([], [RECT]), [])

    def test_pocket_polylines(self):
        square = poly_face([(0, 0), (20, 0), (20, 20), (0, 20)])
        paths = pocket_polylines([square], 1.5, 1.2, "Offset", 0.0, -3.0, 0.01)
        self.assertTrue(paths)
        pts = np.vstack(paths)
        self.assertTrue(np.all((pts[:, :2] >= 1.5 - 1e-6) & (pts[:, :2] <= 18.5 + 1e-6)))
        self.assertTrue(np.all(pts[:, 2] == -3.0))
        zz = pocket_polylines([square], 1.5, 1.2, "ZigZag", 0.0, -3.0, 0.01)
        self.assertTrue(zz)
        self.assertEqual(pocket_polylines([], 1.5, 1.2, "Offset", 0.0, -3.0, 0.01), [])
