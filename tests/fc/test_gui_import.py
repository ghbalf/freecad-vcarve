# SPDX-License-Identifier: LGPL-2.1-or-later
import unittest

import FreeCAD as App

from helpers import make_job, make_sketch
from test_sketches import RECT


class GuiImportTests(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("gui")
        self.job, _ = make_job(self.doc, [make_sketch(self.doc, "S", [RECT])])
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
