# SPDX-License-Identifier: LGPL-2.1-or-later
# Authors: alf and Claude (Anthropic)
import os

import FreeCAD as App
import numpy as np
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


def add_clearance(doc, job, link, diameter, rest_only=False):
    """A V-Carve Clearance op at the end of job, linked to link, with a new end mill of diameter."""
    from vcarve_flat import op_clearance
    tc = Path.Tool.Controller.Create("EndMill", tool=_tool(doc, "5mm_Endmill"))
    tc.Tool.Diameter = diameter
    job.Proxy.addToolController(tc)
    op = op_clearance.Create("VCarveClearance", parentJob=job, tc=tc)
    op.VCarveOp = link
    op.RestOnly = rest_only
    op.Proxy.opUpdateDepths(op)
    doc.recompute()
    return op


def write_png(path, pixels):
    """Save HxWx3 uint8 pixels (row 0 on top) as a PNG."""
    from PySide import QtGui
    h, w = pixels.shape[:2]
    data = np.ascontiguousarray(pixels, np.uint8).tobytes()
    assert QtGui.QImage(data, w, h, 3 * w, QtGui.QImage.Format_RGB888).copy().save(path)


def make_plane(doc, path, w, h, pixels=None, name="Photo"):
    """An Image::ImagePlane of w x h mm showing pixels (default: one white pixel), saved to path."""
    write_png(path, np.full((1, 1, 3), 255, np.uint8) if pixels is None else pixels)
    plane = doc.addObject("Image::ImagePlane", name)
    plane.ImageFile = path
    plane.XSize, plane.YSize = w, h
    doc.recompute()
    return plane
