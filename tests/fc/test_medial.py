# SPDX-License-Identifier: LGPL-2.1-or-later
# Authors: alf and Claude (Anthropic)
import math
import os
import unittest
from unittest import mock

import FreeCAD as App
import numpy as np
import Part
import Path

from vcarve_flat import clearing, medial
from vcarve_flat.clearing import area_subtract, offset_faces, pocket_polylines, rest_faces, subtract
from vcarve_flat.geom import VBit, depth_for_radius, distances_to_segments
from vcarve_flat.medial import (boundary_segments, cap_grooves, carve_polylines, flat_boundary_loops,
                                ridge_polylines)
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


def centre_z(paths, y, x):
    """z at (x, y) interpolated along the path segment that passes through it."""
    for p in paths:
        for a, b in zip(p[:-1], p[1:]):
            if abs(a[1] - y) < 1e-6 and abs(b[1] - y) < 1e-6 and min(a[0], b[0]) <= x <= max(a[0], b[0]) and a[0] != b[0]:
                return float(np.interp(x, [a[0], b[0]], [a[2], b[2]]))
    raise AssertionError(f"no path through x={x}, y={y}")


class MedialTests(unittest.TestCase):
    def test_collinear_boundary_points(self):
        wires = [Part.makePolygon([V(x, y, 0) for x, y in pts + pts[:1]]) for pts in (A_OUTER, A_HOLE)]
        face, = faces_from_loops("A", wires)
        paths = carve_polylines(face, VBit(10, 90, 0.1), 0.0, 1.0, **KW)
        self.assertTrue(paths)

    def test_medial_keeps_parabolas(self):
        # FreeCAD's discretized parabolic Voronoi edges miss their vertices by up to 0.05 mm: taking
        # those as broken (the 26.3 fault is 43 mm) put chords up to 0.078 mm off the medial axis
        def octagon(r):
            return [V(r * math.cos(k * math.pi / 4 + 0.3), r * math.sin(k * math.pi / 4 + 0.3), 0) for k in range(8)]
        a1 = Part.Arc(V(20, -2, 0), V(22, 0, 0), V(20, 2, 0)).toShape()
        a2 = Part.Arc(V(0, 2, 0), V(-2, 0, 0), V(0, -2, 0)).toShape()
        slot = Part.Wire([Part.makeLine(V(0, -2, 0), V(20, -2, 0)), a1, Part.makeLine(V(20, 2, 0), V(0, 2, 0)), a2])
        shapes = {"O": [Part.makePolygon(octagon(r) + octagon(r)[:1]) for r in (10, 6)],
                  "slot": [Part.makePolygon([V(-5, -5, 0), V(25, -5, 0), V(25, 5, 0), V(-5, 5, 0), V(-5, -5, 0)]),
                           slot]}
        for name, wires in shapes.items():
            face, = faces_from_loops(name, wires)
            with mock.patch.object(medial, "_chord", wraps=medial._chord) as chord:
                self.assertTrue(medial.medial_polylines(face, boundary_segments(face, 0.01), 10.0, 0.5))
            self.assertFalse(chord.called, name)

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

    def test_cap_grooves(self):
        """The A's counter tip mitred through the top edge's floor offset: one groove each side, from the floor's
        corner up to the mitre's centre line, where both end at the same point and depth."""
        wires = [Part.makePolygon([V(x / 2, y / 2, 0) for x, y in pts + pts[:1]]) for pts in (A_OUTER, A_HOLE)]
        faces = faces_from_loops("A", wires)
        vbit = VBit(10, 60, 0.1)
        floor = offset_faces(faces, -(0.05 + 3 * math.tan(vbit.half_angle)), sharp=True)
        a, b = sorted(cap_grooves(faces, floor, vbit, 0.0, 3.0), key=lambda g: g[0, 0])
        np.testing.assert_allclose([a[0, 2], b[0, 2]], -3.0)
        np.testing.assert_allclose(a[1], b[1], atol=1e-3)
        np.testing.assert_allclose(a[1], (30.325, 38.973, -2.405), atol=1e-3)
        self.assertEqual(cap_grooves([L_FACE], offset_faces([L_FACE], -2.0, sharp=True), VBit(10, 90, 0), 0.0, 2.0), [])

    def test_clamp_kink_not_cut_off(self):
        # Samples StepLength apart skipped the point where the depth reaches the clamp; the chord
        # across that kink was up to 0.03 mm shallower than the V surface (the plug collided there)
        vbit, sq = VBit(10, 60, 0), poly_face([(0, 0), (10, 0), (10, 10), (0, 10)])
        segs = boundary_segments(sq, KW["deflection"])
        for p in carve_polylines(sq, vbit, 0.0, 3.0, **KW):
            u = np.linspace(0, 1, 11)[:, None, None]
            pts = (p[:-1] + u * (p[1:] - p[:-1])).reshape(-1, 3)
            true = -depth_for_radius(vbit, distances_to_segments(pts[:, :2], segs), 3.0)
            self.assertLessEqual((pts[:, 2] - true).max(), KW["tol"] + 1e-6)

    def test_carve_min_depth(self):
        bar = poly_face([(0, 0), (40, 0), (40, 2), (0, 2)])
        paths = carve_polylines(bar, VBit(10, 90, 3.0), 0.0, 2.0, min_depth=-1, **KW)
        self.assertAlmostEqual(centre_z(paths, 1.0, 20.0), 0.5, delta=1e-3)

    def test_ridge_polylines(self):
        vbit = VBit(10, 90, 1.0)
        bar2 = poly_face([(0, 0), (40, 0), (40, 2), (0, 2)])
        paths = ridge_polylines(bar2, vbit, 0.0, 2.0, **KW)
        for x in (10.0, 20.0, 30.0):
            self.assertAlmostEqual(centre_z(paths, 1.0, x), 0.5, delta=1e-3)
        # r = 3 on the centre line gives z = 2.5 > height: the middle run at the plug top is dropped
        bar6 = poly_face([(0, 0), (40, 0), (40, 6), (0, 6)])
        pts = np.vstack(ridge_polylines(bar6, vbit, 0.0, 2.0, **KW) or [np.empty((0, 3))])
        on_axis = pts[np.abs(pts[:, 1] - 3) < 1e-6]
        self.assertFalse(np.any((on_axis[:, 0] > 3.5) & (on_axis[:, 0] < 36.5)))
        self.assertEqual(ridge_polylines(bar2, VBit(10, 90, 0), 0.0, 2.0, **KW), [])

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

    def test_offset_keeps_circles(self):
        # OCC mishandled faces with full circles, and Path.Area re-fits arcs up to 0.023 mm off: the
        # thin-bar end of the plug collided by 0.026 mm (its complement holds the ring's circle)
        face = subtract([poly_face([(-5, -5), (45, -5), (45, 25), (-5, 25)])],
                        [poly_face([(20, 0), (40, 0), (40, 20), (20, 20)]),
                         Part.Face(Part.Wire(Part.makeCircle(4, V(10, 10, 0))))])
        hole = App.BoundBox(5, 5, -1, 15, 15, 1)
        for d in (-0.3, 0.5):
            pts = [p for f in offset_faces(face, d) for e in f.Edges if hole.isInside(e.BoundBox)
                   for p in e.discretize(50)]
            self.assertTrue(pts, d)
            err = max(abs(math.hypot(p.x - 10, p.y - 10) - (4 - d)) for p in pts)
            self.assertLess(err, 1e-6, d)

    def test_offset_keeps_occ_whole_face(self):
        # Offsetting wire by wire gave other loop orders and start points than OCC's whole-face offset,
        # which changed v1 paths where that offset was right
        def octagon(r):
            return [(r * math.cos(k * math.pi / 4 + 0.3), r * math.sin(k * math.pi / 4 + 0.3)) for k in range(8)]
        cases = {"frame": [[(0, 0), (20, 0), (20, 20), (0, 20)], [(3, 3), (17, 3), (17, 17), (3, 17)]],
                 "nested": [[(0, 0), (40, 0), (40, 40), (0, 40)], [(6, 6), (34, 6), (34, 34), (6, 34)],
                            [(12, 12), (28, 12), (28, 28), (12, 28)]],
                 "O": [octagon(10), octagon(6)]}
        checked = 0
        for name, loops in cases.items():
            wires = [Part.makePolygon([V(x, y, 0) for x, y in pts + pts[:1]]) for pts in loops]
            faces = faces_from_loops(name, wires)
            for d in (-1.2, -0.3, 0.6):
                whole = [g for f in faces for g in f.makeOffset2D(d, join=0).Faces]
                area = Path.Area()
                for f in faces:
                    area.add(f)
                ref = area.makeOffset(offset=d).Faces
                if sorted(len(f.Wires) for f in whole) != sorted(len(f.Wires) for f in ref) \
                        or abs(sum(f.Area for f in whole) - sum(f.Area for f in ref)) > 0.05:
                    continue  # this FreeCAD's makeOffset2D is wrong here (1.0)
                checked += 1
                got = offset_faces(faces, d)
                self.assertEqual([[v.Point for w in f.Wires for v in w.OrderedVertexes] for f in got],
                                 [[v.Point for w in f.Wires for v in w.OrderedVertexes] for f in whole], (name, d))
        if not checked:
            self.skipTest("makeOffset2D is wrong for faces with holes in this FreeCAD")

    def test_offset_zero(self):
        self.assertEqual(offset_faces([RECT], 0), [RECT])

    def test_rest_area(self):
        floor = [poly_face([(0, 0), (30, 0), (30, 4), (40, 4), (40, 6), (30, 6), (30, 10), (0, 10)])]
        rest = rest_faces(floor, [(1.5, 0)])
        self.assertTrue(rest)
        self.assertTrue(any(f.isInside(V(35, 5, 0), 1e-6, True) for f in rest))

    def test_rest_area_ring(self):
        # An "O": OCC's outward makeOffset2D dropped the outer wire of such faces (or failed), so the
        # end mill seemed to clear almost nothing and the V-bit re-cleared the whole floor
        floor = Part.Face(Part.Wire(Part.makeCircle(20))).cut(Part.Face(Part.Wire(Part.makeCircle(12)))).Faces
        rest = rest_faces(floor, [(1.5875, 0)])
        self.assertLess(sum(f.Area for f in rest), 0.01 * floor[0].Area)

    def test_area_subtract_near_outlines(self):
        # The plug floor around "AOB" (DejaVu Sans Bold, 50 mm) and the area a 3.175 mm end mill sweeps
        # in it: their outlines lie within 0.01 mm, and OCC's cut kept the whole 5355 mm² floor, so the
        # V-bit re-cleared the ring the clearance op had cleared
        floor, swept = Part.read(os.path.join(os.path.dirname(__file__), "data", "aob_floor_swept.brep")).Faces
        self.assertLess(sum(f.Area for f in area_subtract([floor], [swept])), 0.01 * floor.Area)

    def test_rest_area_when_cut_fails(self):
        floor = Part.Face(Part.Wire(Part.makeCircle(20))).cut(Part.Face(Part.Wire(Part.makeCircle(12)))).Faces
        with mock.patch.object(clearing, "subtract", lambda a, b: list(a)):  # OCC's cut keeping the floor
            rest = rest_faces(floor, [(1.5875, 0)])
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
