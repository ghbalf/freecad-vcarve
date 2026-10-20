# SPDX-License-Identifier: LGPL-2.1-or-later
import os

import FreeCAD as App
import Part
import Path
import Path.Main.Job
import Path.Tool.Controller
import Sketcher


def make_sketch(doc, name, loops, circles=()):
    sk = doc.addObject("Sketcher::SketchObject", name)
    V = App.Vector
    for pts in loops:
        for a, b in zip(pts, pts[1:] + pts[:1]):
            sk.addGeometry(Part.LineSegment(V(*a, 0), V(*b, 0)))
    for x, y, r in circles:
        sk.addGeometry(Part.Circle(V(x, y, 0), V(0, 0, 1), r))
    doc.recompute()
    return sk


def _tool(doc, bit):
    try:
        from CAMTests.PathTestUtils import PathTestWithAssets
    except ImportError:  # 1.0.x: no asset manager
        import Path.Tool.Bit
        mod = os.path.dirname(os.path.dirname(Path.__file__))
        return Path.Tool.Bit.Factory.CreateFrom(os.path.join(mod, "Tools", "Bit", bit + ".fctb"), bit)
    case = PathTestWithAssets()
    case.setUp()
    return case.assets.get(f"toolbit://{bit}").attach_to_doc(doc=doc)


def make_job(doc, sketches, bits=("60degree_Vbit", "5mm_Endmill")):
    job = Path.Main.Job.Create("Job", list(sketches), None)
    tcs = {}
    for bit in bits:
        tc = Path.Tool.Controller.Create(bit, tool=_tool(doc, bit))
        job.Proxy.addToolController(tc)
        tcs[bit] = tc
    doc.recompute()
    return job, tcs
