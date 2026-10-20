# SPDX-License-Identifier: LGPL-2.1-or-later
import unittest

import FreeCAD as App

from helpers import make_job, make_sketch
from test_sketches import RECT


class GuiImportTests(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("gui")
        self.sketches = [make_sketch(self.doc, n, [RECT]) for n in ("S", "T")]
        self.job, _ = make_job(self.doc, self.sketches)
        self.clone = self.job.Model.Group[0]

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def test_sketch_gate(self):
        from vcarve_flat.gui.selection import SketchGate
        gate = SketchGate()
        box = self.doc.addObject("Part::Box", "Box")
        self.assertTrue(gate.allow(self.doc, self.clone, "Edge1"))
        self.assertTrue(gate.allow(self.doc, self.clone, ""))
        self.assertFalse(gate.allow(self.doc, self.clone, "Vertex1"))
        self.assertFalse(gate.allow(self.doc, box, ""))
        self.assertFalse(gate.allow(self.doc, box, "Edge1"))

    def test_to_clones_merges_and_drops_covered_edges(self):
        from vcarve_flat.gui.selection import to_clones
        (s, t), (cs, ct) = self.sketches, self.job.Model.Group
        shapes, base = to_clones(self.job, [s, cs], [(s, ("Edge1",)), (t, ("Edge1", "Edge2")),
                                                     (ct, ("Edge2", "Edge3"))])
        self.assertEqual(shapes, [cs])  # originals map to clones, no duplicates
        # edges of a whole-shape entry are dropped (no loop carved twice), subs merged per clone
        self.assertEqual(base, [(ct, ("Edge1", "Edge2", "Edge3"))])
