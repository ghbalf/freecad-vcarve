# SPDX-License-Identifier: LGPL-2.1-or-later
import math
import unittest

import FreeCAD as App
import Part

from helpers import make_job, make_sketch
from vcarve_flat.sketches import SketchError, faces_from_loops, is_sketch_base, loops_for_base

RECT = [(0, 0), (40, 0), (40, 20), (0, 20)]
SQUARE = [(50, 0), (55, 0), (55, 5), (50, 5)]


class SketchTests(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("t")
        self.sk = make_sketch(self.doc, "Sk", [RECT, SQUARE], circles=[(10, 10, 4)])
        self.job, _ = make_job(self.doc, [self.sk])
        self.base = self.job.Model.Group[0]

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def edge_of(self, pred):
        for i, e in enumerate(self.base.Shape.Edges, 1):
            if pred(e.CenterOfMass if hasattr(e, "CenterOfMass") else e.BoundBox.Center):
                return f"Edge{i}"
        self.fail("edge not found")

    def rect_edge(self):
        return self.edge_of(lambda c: abs(c.x - 20) < 1e-6 and abs(c.y) < 1e-6)

    def circle_edge(self):
        return self.edge_of(lambda c: abs(c.x - 10) < 1e-6 and abs(c.y - 10) < 1e-6)

    def test_whole_sketch(self):
        loops = loops_for_base(self.base, None)
        self.assertEqual(len(loops), 3)
        faces = faces_from_loops("Sk", loops)
        self.assertEqual(len(faces), 2)
        big = max(faces, key=lambda f: f.Area)
        self.assertEqual(len(big.Wires), 2)
        self.assertAlmostEqual(big.Area, 800 - math.pi * 16, places=3)

    def test_edge_picks_loop(self):
        loops = loops_for_base(self.base, [self.rect_edge()])
        self.assertEqual(len(loops), 1)
        faces = faces_from_loops("Sk", loops)
        self.assertEqual(len(faces), 1)
        self.assertEqual(len(faces[0].Wires), 1)
        self.assertAlmostEqual(faces[0].Area, 800, places=3)

    def test_edge_picks_loop_and_hole(self):
        loops = loops_for_base(self.base, [self.rect_edge(), self.circle_edge()])
        faces = faces_from_loops("Sk", loops)
        self.assertEqual(len(faces), 1)
        self.assertEqual(len(faces[0].Wires), 2)

    def test_same_loop_twice(self):
        # the rectangle was added first, so Edge1 and Edge2 are two of its sides
        self.assertEqual(len(loops_for_base(self.base, ["Edge1", "Edge2"])), 1)

    def test_stale_edge(self):
        with self.assertRaises(SketchError) as cm:
            loops_for_base(self.base, ["Edge99"])
        self.assertIn("Edge99", str(cm.exception))
        self.assertTrue(str(cm.exception).startswith(self.sk.Label))

    def test_vertex_ignored(self):
        self.assertEqual(len(loops_for_base(self.base, ["Vertex1", self.rect_edge()])), 1)

    def test_open_wire(self):
        sk = make_sketch(self.doc, "Open", [RECT])
        sk.addGeometry(Part.LineSegment(App.Vector(60, 0, 0), App.Vector(70, 5, 0)))
        self.doc.recompute()
        with self.assertRaises(SketchError) as cm:
            loops_for_base(sk, None)
        self.assertIn("Open", str(cm.exception))

    def test_overlapping_loops(self):
        sk = make_sketch(self.doc, "Ov", [[(0, 0), (20, 0), (20, 10), (0, 10)],
                                          [(10, 5), (30, 5), (30, 15), (10, 15)]])
        with self.assertRaises(SketchError) as cm:
            faces_from_loops("Ov", loops_for_base(sk, None))
        self.assertIn("Ov", str(cm.exception))

    def test_edge_on_open_wire(self):
        sk = make_sketch(self.doc, "Open", [RECT])
        sk.addGeometry(Part.LineSegment(App.Vector(60, 0, 0), App.Vector(70, 5, 0)))
        self.doc.recompute()
        with self.assertRaises(SketchError) as cm:
            loops_for_base(sk, [f"Edge{len(sk.Shape.Edges)}"])
        self.assertIn("not part of a closed outline", str(cm.exception))

    def test_not_xy(self):
        sk = make_sketch(self.doc, "Tilted", [RECT])
        sk.Placement = App.Placement(App.Vector(), App.Rotation(App.Vector(1, 0, 0), 90))
        self.doc.recompute()
        with self.assertRaises(SketchError) as cm:
            faces_from_loops("Tilted", loops_for_base(sk, None))
        self.assertIn("parallel", str(cm.exception))

    def test_clone_is_sketch_base(self):
        self.assertTrue(is_sketch_base(self.base))
        self.assertTrue(is_sketch_base(self.sk))
        box = self.doc.addObject("Part::Feature", "Box")
        box.Shape = Part.makeBox(1, 1, 1)
        self.assertFalse(is_sketch_base(box))
