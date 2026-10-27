# SPDX-License-Identifier: LGPL-2.1-or-later
# Authors: alf and Claude (Anthropic)
"""The V-Carve Photo op: depth along lines, hatch and custom vectors follows an image plane's darkness."""
import math
import os
import shutil
import tempfile
import time
import unittest
from unittest import mock

import FreeCAD as App
import numpy as np
import Part
import Path

from helpers import make_job, make_plane, make_sketch
from test_op_vcarve import cut_points
from vcarve_flat import op_photo
from vcarve_flat.op_vcarve import tool_vbit


def halves(w, h):
    """w x h px, the left half black and the right half white."""
    px = np.full((h, w, 3), 255, np.uint8)
    px[:, :w // 2] = 0
    return px


def eye(px=300, mm=30.0, cy=1.25):
    """The eye fixture: a black disk (r 10 mm) with a white dot (r 1.5 mm) at its centre, which is cy
    above the image centre (on a line at the default 2.5 mm spacing)."""
    c = (np.arange(px) + 0.5) * mm / px - mm / 2
    x, y = np.meshgrid(c, -c)
    r = np.hypot(x, y - cy)
    return np.where(((r < 10) & (r > 1.5))[..., None], 0, 255).astype(np.uint8).repeat(3, axis=2)


def runs(op):
    """The cut runs: the G1 points between rapids, as (N, 3) arrays."""
    pos, out, cur = {"X": 0.0, "Y": 0.0, "Z": 0.0}, [], []
    for c in op.Path.Commands:
        pos.update({k: v for k, v in c.Parameters.items() if k in pos})
        if c.Name in ("G1", "G01"):
            cur.append((pos["X"], pos["Y"], pos["Z"]))
        elif cur:
            out.append(np.array(cur))
            cur = []
    return out


class OpPhotoTests(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("photo")
        self.tmp = tempfile.mkdtemp()
        self.warn = mock.patch.object(Path.Log, "warning").start()
        self.err = mock.patch.object(Path.Log, "error").start()
        self.notice = mock.patch.object(Path.Log, "notice").start()
        self.addCleanup(mock.patch.stopall)

    def tearDown(self):
        App.closeDocument(self.doc.Name)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def job_over(self, w=60, h=40):
        """A Job on a w x h x 10 mm box centred on the origin."""
        box = self.doc.addObject("Part::Box", "Box")
        box.Length, box.Width, box.Height = w, h, 10
        box.Placement.Base = App.Vector(-w / 2, -h / 2, 0)
        self.doc.recompute()
        self.job, tcs = make_job(self.doc, [box])
        self.tc, self.mill = tcs["60degree_Vbit"], tcs["5mm_Endmill"]
        self.vbit = tool_vbit(self.tc)
        self.top = self.job.Stock.Shape.BoundBox.ZMax

    def plane(self, w, h, pixels, name="Photo"):
        return make_plane(self.doc, os.path.join(self.tmp, name + ".png"), w, h, pixels, name)

    def make_op(self, plane=None, **props):
        op = op_photo.Create("Photo", parentJob=self.job)
        op.ToolController = self.tc
        op.ImagePlane = plane
        for k, v in props.items():
            setattr(op, k, v)
        self.doc.recompute()
        return op

    def logged(self, mock_fn, text):
        return any(text in str(c.args[0]) for c in mock_fn.call_args_list if c.args)

    def test_lines_depth_follows_darkness(self):
        self.job_over()
        op = self.make_op(self.plane(40, 20, halves(40, 20)), Angle=0, LineSpacing=2.5)
        pts = cut_points(op)
        left = pts[pts[:, 0] < -1]
        self.assertTrue(len(left))
        np.testing.assert_allclose(left[:, 2], self.top - 2, atol=1e-6)
        self.assertFalse((pts[:, 0] > 1).any())
        self.assertEqual(len(runs(op)), 8)
        self.assertFalse(self.err.called)

    def test_image_top_is_plus_y(self):
        px = np.full((20, 40, 3), 255, np.uint8)
        px[:10] = 0  # the top half black
        self.job_over()
        pts = cut_points(self.make_op(self.plane(40, 20, px), Angle=0, LineSpacing=2.5))
        self.assertTrue(len(pts))
        self.assertTrue((pts[:, 1] > 0).all())

    def test_default_spacing_keeps_grooves_apart(self):
        self.job_over()
        op = self.make_op(self.plane(40, 20, halves(40, 20)))
        width = self.vbit.tip_diameter + 2 * 2 * math.tan(self.vbit.half_angle)
        self.assertGreater(op.LineSpacing.Value, width)
        self.assertLessEqual(op.LineSpacing.Value, width * 1.05 + 0.1 + 1e-9)
        self.assertFalse(self.logged(self.warn, "merge"))

    def test_hatch_reaches_full_depth(self):
        self.job_over()
        op = self.make_op(self.plane(40, 20, np.zeros((20, 40, 3), np.uint8)), Pattern="Hatch",
                          Angle=0, HatchAngle=90, LineSpacing=2.5)
        self.assertAlmostEqual(cut_points(op)[:, 2].min(), self.top - 2, places=6)
        dirs = {("x" if abs(r[-1, 0] - r[0, 0]) > 1 else "y") for r in runs(op)}
        self.assertEqual(dirs, {"x", "y"})

    def test_custom_vectors(self):
        self.job_over()
        plane = self.plane(40, 20, halves(40, 20))
        sk = make_sketch(self.doc, "Stroke", [])
        sk.addGeometry(Part.LineSegment(App.Vector(-15, 0, 0), App.Vector(15, 0, 0)))
        line = self.doc.addObject("Part::Feature", "SvgPath")
        line.Shape = Part.makeLine(App.Vector(-15, 5, 0), App.Vector(15, 5, 0))
        op = self.make_op(plane, Pattern="Custom", Vectors=[sk, line])
        pts = cut_points(op)
        self.assertEqual(set(np.round(pts[:, 1], 6)), {0.0, 5.0})
        np.testing.assert_allclose(pts[pts[:, 0] < -1, 2], self.top - 2, atol=1e-6)
        self.assertFalse((pts[:, 0] > 1).any())

    def test_eye(self):
        """The wince test: the pupil reaches full depth, the catchlight stays uncut."""
        self.job_over()
        op = self.make_op(self.plane(30, 30, eye()), Angle=0, LineSpacing=2.5)
        centre = [r for r in runs(op) if abs(r[0, 1] - 1.25) < 1e-6]
        self.assertEqual(len(centre), 2)  # the line through the dot: lifted over it
        for r in centre:
            self.assertAlmostEqual(r[:, 2].min(), self.top - 2, places=6)
        self.assertTrue(2.5 <= abs(centre[1][0, 0] - centre[0][-1, 0]) <= 3.5)

    def test_merge_warning(self):
        self.job_over()
        self.make_op(self.plane(40, 20, halves(40, 20)), LineSpacing=1)
        self.assertTrue(self.logged(self.warn, "merge"))

    def test_clamp_warning(self):
        self.job_over()
        op = self.make_op(self.plane(40, 20, halves(40, 20)), MaxDepth=50)
        self.assertTrue(self.logged(self.warn, "cone"))
        self.assertAlmostEqual(cut_points(op)[:, 2].min(), self.top - self.vbit.cone_height, places=6)

    def test_clip_warning(self):
        self.job_over(20, 20)
        op = self.make_op(self.plane(40, 40, np.zeros((4, 4, 3), np.uint8)))
        self.assertTrue(self.logged(self.warn, "outside the stock"))
        bb, pts = self.job.Stock.Shape.BoundBox, cut_points(op)
        self.assertTrue(((pts[:, 0] >= bb.XMin - 1e-6) & (pts[:, 0] <= bb.XMax + 1e-6)
                         & (pts[:, 1] >= bb.YMin - 1e-6) & (pts[:, 1] <= bb.YMax + 1e-6)).all())

    def test_errors(self):
        self.job_over()
        op = self.make_op()
        self.assertTrue(self.logged(self.err, "image plane"))
        self.assertEqual(runs(op), [])
        tilted = self.plane(40, 20, halves(40, 20), "Tilted")
        tilted.Placement = App.Placement(App.Vector(), App.Rotation(App.Vector(1, 0, 0), 30))
        op.ImagePlane = tilted
        self.doc.recompute()
        self.assertTrue(self.logged(self.err, "Tilted"))
        self.assertEqual(runs(op), [])
        self.err.reset_mock()
        op.ImagePlane = self.plane(40, 20, halves(40, 20))
        op.ToolController = self.mill
        self.doc.recompute()
        self.assertTrue(self.logged(self.err, "V-bit"))
        self.assertEqual(runs(op), [])

    def test_white_image_notice(self):
        self.job_over()
        op = self.make_op(self.plane(40, 20, np.full((2, 2, 3), 255, np.uint8)))
        self.assertEqual(runs(op), [])
        self.assertFalse(self.err.called)
        self.assertTrue(self.logged(self.notice, "nothing"))

    def test_min_depth_above_max_depth(self):
        self.job_over()
        op = self.make_op(self.plane(40, 20, halves(40, 20)), MinDepth=3, MaxDepth=2)
        self.assertEqual(runs(op), [])
        self.assertFalse(self.err.called)
        self.assertTrue(self.logged(self.notice, "nothing"))

    def test_plane_move_touches_op(self):
        self.job_over()
        plane = self.plane(40, 20, halves(40, 20))
        op = self.make_op(plane, Angle=0)
        x0 = runs(op)[0][:, 0].min()
        plane.Placement.Base = App.Vector(5, 0, 0)
        self.doc.recompute()
        self.assertAlmostEqual(runs(op)[0][:, 0].min(), x0 + 5, places=6)

    def test_setup_sheet_prototype(self):
        # The Job panel builds a prototype of every registered op; it knows only some property types.
        import Path.Base.SetupSheet as PathSetupSheet
        proto = PathSetupSheet._RegisteredOps["VCarvePhoto"].prototype("VCarvePhoto")
        for name in op_photo.SetupProperties():
            proto.getProperty(name).displayString()  # quantities need Quantity defaults, not floats

    def test_reopen(self):
        self.job_over()
        op = self.make_op(self.plane(40, 20, halves(40, 20)))
        before, name = op.Path.toGCode(), op.Name
        path = os.path.join(self.tmp, "photo.FCStd")
        self.doc.saveAs(path)
        App.closeDocument(self.doc.Name)
        os.remove(os.path.join(self.tmp, "Photo.png"))  # the image now lives only in the document
        self.doc = App.openDocument(path)
        op = self.doc.getObject(name)
        op.touch()
        self.doc.recompute()
        self.assertEqual(op.Path.toGCode(), before)
        self.assertFalse(self.err.called)

    def test_large_image_time(self):
        self.job_over(400, 400)
        ramp = np.linspace(0, 255, 2000).astype(np.uint8)
        px = np.repeat(np.tile(ramp, (2000, 1))[..., None], 3, axis=2)
        plane = self.plane(400, 400, px)
        t = time.monotonic()
        op = self.make_op(plane, LineSpacing=2.5)
        self.assertLess(time.monotonic() - t, 30)
        self.assertGreater(len(op.Path.Commands), 1000)
