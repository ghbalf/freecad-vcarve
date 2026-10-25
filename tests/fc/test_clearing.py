# SPDX-License-Identifier: LGPL-2.1-or-later
import unittest

import FreeCAD as App
import numpy as np
import Part

from vcarve_flat.clearing import area_offset, inside_loops, intersect, mirror_faces, union
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


class TestBooleans(unittest.TestCase):
    def test_union_intersect(self):
        a, b = [rect(0, 0, 10, 10)], [rect(5, 0, 15, 10)]
        self.assertAlmostEqual(area(union(a + b)), 150)
        self.assertAlmostEqual(area(intersect(a, b)), 50)
        self.assertEqual(union([]), [])


class TestInsideLoops(unittest.TestCase):
    def test_keeps_inside(self):
        faces = [rect(0, 0, 10, 10)]
        a = np.array([(1, 1, 0), (2, 1, 0), (2, 2, 0)], float)
        b = np.array([(20, 20), (21, 20), (21, 21)], float)
        out = inside_loops([a, b], faces)
        self.assertEqual(len(out), 1)
        self.assertIs(out[0], a)
