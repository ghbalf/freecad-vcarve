# SPDX-License-Identifier: LGPL-2.1-or-later
# Authors: alf and Claude (Anthropic)
"""Reading a FreeCAD image plane: its pixels, and where it lies over the XY plane."""
import os
import tempfile
import unittest

import FreeCAD as App
import numpy as np

from vcarve_flat.image_plane import ImageError, plane_frame, read_rgba


def write_png(path, pixels):
    """pixels: HxWx3 uint8 rows from the top."""
    from PySide import QtGui
    h, w = pixels.shape[:2]
    img = QtGui.QImage(w, h, QtGui.QImage.Format_RGB32)
    for y in range(h):
        for x in range(w):
            img.setPixel(x, y, QtGui.qRgb(*map(int, pixels[y, x])))
    assert img.save(path)


def make_plane(doc, path, w, h, pixels=None, name="Photo"):
    """An Image::ImagePlane of w x h mm showing pixels (default: one white pixel)."""
    write_png(path, np.full((1, 1, 3), 255, np.uint8) if pixels is None else pixels)
    plane = doc.addObject("Image::ImagePlane", name)
    plane.ImageFile = path
    plane.XSize, plane.YSize = w, h
    doc.recompute()
    return plane


class ImagePlaneTest(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("ImagePlaneTest")
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def plane(self, w=20, h=10, pixels=None):
        return make_plane(self.doc, os.path.join(self.tmp, "img.png"), w, h, pixels)

    def test_read_rgba(self):
        px = np.zeros((2, 3, 3), np.uint8)
        px[0, 2] = (255, 0, 0)
        rgba = read_rgba(self.plane(pixels=px).ImageFile)
        self.assertEqual(rgba.shape, (2, 3, 4))
        self.assertEqual(tuple(rgba[0, 2]), (255, 0, 0, 255))
        self.assertEqual(tuple(rgba[1, 0]), (0, 0, 0, 255))

    def test_frame_identity(self):
        to_uv, bbox = plane_frame(self.plane())
        np.testing.assert_allclose(to_uv(np.array([[5.0, 2]])), [[5, 2]], atol=1e-9)
        np.testing.assert_allclose(bbox, (-10, -5, 10, 5), atol=1e-9)

    def test_frame_placed(self):
        p = self.plane()
        p.Placement = App.Placement(App.Vector(100, 50, 7), App.Rotation(App.Vector(0, 0, 1), 90))
        to_uv, bbox = plane_frame(p)
        np.testing.assert_allclose(to_uv(np.array([[100.0, 55]])), [[5, 0]], atol=1e-9)
        np.testing.assert_allclose(bbox, (95, 40, 105, 60), atol=1e-9)

    def test_frame_face_down(self):
        p = self.plane()
        p.Placement = App.Placement(App.Vector(), App.Rotation(App.Vector(1, 0, 0), 180))
        to_uv, _ = plane_frame(p)
        # World (5, 2) is local (5, -2); u is negated because local z points down, so the photo is
        # turned 180 degrees in the plane, never mirrored.
        np.testing.assert_allclose(to_uv(np.array([[5.0, 2]])), [[-5, -2]], atol=1e-9)

    def test_frame_tilted(self):
        p = self.plane()
        p.Placement = App.Placement(App.Vector(), App.Rotation(App.Vector(1, 0, 0), 30))
        with self.assertRaisesRegex(ImageError, "^Photo"):
            plane_frame(p)

    def test_missing_file(self):
        with self.assertRaises(ImageError):
            read_rgba(os.path.join(self.tmp, "nothing.png"))
        with self.assertRaises(ImageError):
            read_rgba("")
