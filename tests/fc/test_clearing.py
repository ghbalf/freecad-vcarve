# SPDX-License-Identifier: LGPL-2.1-or-later
import unittest
from unittest import mock

import FreeCAD as App
import numpy as np
import Part

from vcarve_flat.clearing import (area_offset, inside_loops, intersect, mirror_faces, pocket_polylines, rest_faces,
                                    rest_region, subtract, swept_faces, union)
from vcarve_flat.sketches import faces_from_loops

V = App.Vector


def rect(x0, y0, x1, y1):
    return Part.Face(Part.makePolygon([V(x, y, 0) for x, y in
                                       [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]]))


def area(faces):
    return sum(f.Area for f in faces)


def square_with_hole():
    outer = Part.makePolygon([V(x, y, 0) for x, y in [(0, 0), (20, 0), (20, 20), (0, 20), (0, 0)]])
    hole = Part.makePolygon([V(x, y, 0) for x, y in [(5, 5), (15, 5), (15, 15), (5, 15), (5, 5)]])
    return faces_from_loops("Sq", [outer, hole])


class TestAreaOffset(unittest.TestCase):
    def test_outward_and_inward_with_hole(self):
        faces = square_with_hole()
        self.assertAlmostEqual(area(area_offset(faces, 1)), 22 ** 2 - 8 ** 2, delta=1.0)
        self.assertAlmostEqual(area(area_offset(faces, -1)), 18 ** 2 - 12 ** 2, delta=1.0)
        self.assertEqual(area_offset(faces, 0), faces)

    def test_vanished(self):
        self.assertEqual(area_offset(square_with_hole(), -11), [])

    def test_planar_at_input_z(self):
        for f in area_offset(square_with_hole(), 1):
            self.assertAlmostEqual(f.BoundBox.ZMin, 0)
            self.assertAlmostEqual(f.BoundBox.ZMax, 0)


class TestMirror(unittest.TestCase):
    def setUp(self):
        pts = [(0, 0), (30, 0), (30, 8), (8, 8), (8, 30), (0, 30)]
        self.face = Part.Face(Part.makePolygon([V(x, y, 0) for x, y in pts + pts[:1]]))
        self.centre = self.face.BoundBox.Center

    def test_x_moves_foot_left_right(self):
        out = mirror_faces([self.face], "X", self.centre)
        bb = out[0].BoundBox
        self.assertAlmostEqual(bb.XMin, 0)
        self.assertAlmostEqual(bb.XMax, 30)
        self.assertAlmostEqual(out[0].Area, self.face.Area)
        self.assertTrue(out[0].isInside(V(28, 25, 0), 1e-6, True))
        self.assertTrue(out[0].isInside(V(2, 2, 0), 1e-6, True))
        self.assertFalse(out[0].isInside(V(2, 25, 0), 1e-6, True))

    def test_y_flips_front_back(self):
        out = mirror_faces([self.face], "Y", self.centre)
        self.assertTrue(out[0].isInside(V(25, 28, 0), 1e-6, True))
        self.assertFalse(out[0].isInside(V(25, 2, 0), 1e-6, True))
        self.assertGreater(out[0].Area, 0)

    def test_right_handed_plane(self):
        # A mirrored plane is left-handed (its surface normal points down); Path.Area logs about it.
        for face in mirror_faces(square_with_hole(), "X", V(10, 10, 0)):
            self.assertGreater(face.Surface.normal(0, 0).z, 0)
            self.assertGreater(face.normalAt(0, 0).z, 0)
            self.assertAlmostEqual(face.Area, 20 ** 2 - 10 ** 2)


class TestBooleans(unittest.TestCase):
    def test_union_intersect(self):
        a, b = [rect(0, 0, 10, 10)], [rect(5, 0, 15, 10)]
        self.assertAlmostEqual(area(union(a + b)), 150)
        self.assertAlmostEqual(area(intersect(a, b)), 50)
        self.assertEqual(union([]), [])

    def test_union_of_one_face_does_not_fuse(self):
        face = mock.Mock()  # fuse([]) logs "Boolean operation with only one shape input" on 1.1.4
        self.assertEqual(union([face]), [face])
        face.fuse.assert_not_called()


class TestInsideLoops(unittest.TestCase):
    def test_keeps_inside(self):
        faces = [rect(0, 0, 10, 10)]
        a = np.array([(1, 1, 0), (2, 1, 0), (2, 2, 0)], float)
        b = np.array([(20, 20), (21, 20), (21, 21)], float)
        out = inside_loops([a, b], faces)
        self.assertEqual(len(out), 1)
        self.assertIs(out[0], a)


class TestRestChain(unittest.TestCase):
    def setUp(self):
        pts = [(0, 0), (30, 0), (30, 8), (10, 8), (10, 20), (0, 20)]  # 30 x 20 with an L notch
        self.floor = [Part.Face(Part.makePolygon([V(x, y, 0) for x, y in pts + pts[:1]]))]

    def test_rest_faces_chain(self):
        big, both = rest_faces(self.floor, [(3, 0)]), rest_faces(self.floor, [(3, 0), (1, 0)])
        self.assertLess(area(both), area(big))
        self.assertGreater(area(both), 0)  # the corners keep their radius-1 arcs
        self.assertAlmostEqual(area(both), area(rest_faces(self.floor, [(1, 0), (3, 0)])), delta=1e-3)
        self.assertEqual(rest_faces(self.floor, []), self.floor)

    def test_rest_region_reaches_slivers(self):
        region = rest_region(self.floor, [(3, 0)], 1)
        self.assertTrue(pocket_polylines(region, 1, 0.8, "Offset", 0, 0, 0.01))
        want = area(subtract(rest_faces(self.floor, [(3, 0)]), rest_faces(self.floor, [(3, 0), (1, 0)])))
        got = area(intersect(swept_faces(region, 1, 0), rest_faces(self.floor, [(3, 0)])))
        self.assertGreaterEqual(got, 0.9 * want)

    def test_rest_region_with_allowance(self):
        # The V-bit counts the rest op's whole sweep as cleared, so the pocket of rest_region must cut all of it
        tools, r, a = [(3, 0)], 1, 0.5
        assumed = intersect(swept_faces(self.floor, r, a), rest_faces(self.floor, tools))
        cut = swept_faces(rest_region(self.floor, tools, r, a), r, a)
        # grown past Path.Area's arc re-fit (0.02 mm): without the allowance in the growth, 0.47 mm^2 stayed
        self.assertLess(area(subtract(assumed, area_offset(cut, 0.05))), 1e-4)

    def test_rest_region_empty(self):
        circle = [Part.Face(Part.Wire(Part.makeCircle(5)))]
        self.assertEqual(rest_region(circle, [(3, 0)], 1), [])
        self.assertEqual(rest_region(circle, [], 1), circle)
