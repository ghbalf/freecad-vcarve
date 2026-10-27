# SPDX-License-Identifier: LGPL-2.1-or-later
# Authors: alf and Claude (Anthropic)
"""A FreeCAD Image::ImagePlane as photo V-carve input: its pixels, and the map from world XY onto it."""
import numpy as np

import FreeCAD as App


class ImageError(Exception):
    pass


def read_rgba(path: str) -> np.ndarray:
    """The image file's pixels as an HxWx4 uint8 RGBA array, row 0 on top."""
    from PySide import QtGui
    img = QtGui.QImage(path) if path else QtGui.QImage()
    if img.isNull():
        raise ImageError(f"cannot read the image file '{path}'")
    img = img.convertToFormat(QtGui.QImage.Format_RGBA8888)
    w, h, stride = img.width(), img.height(), img.bytesPerLine()
    raw = np.frombuffer(bytes(img.constBits())[:stride * h], np.uint8).reshape(h, stride)
    return raw[:, :w * 4].reshape(h, w, 4).copy()


def size(plane) -> tuple:
    """The plane's (XSize, YSize) in mm."""
    return tuple(float(getattr(v, "Value", v)) for v in (plane.XSize, plane.YSize))


def plane_frame(plane):
    """(to_uv, bbox): to_uv maps (N, 2) world XY, projected straight down onto the plane, to image
    coordinates in mm (centred, v towards the image's top row); bbox is the image's world XY extent.
    A plane facing down is carved as the top view shows it."""
    pl = plane.Placement
    normal = pl.Rotation.multVec(App.Vector(0, 0, 1))
    if abs(normal.z) < 1 - 1e-6:
        raise ImageError(f"{plane.Label}: the image plane must be parallel to the XY plane")
    m = pl.inverse().Matrix
    a = np.array([[m.A11, m.A12], [m.A21, m.A22]])
    t = np.array([m.A14, m.A24])

    def to_uv(xy):
        return np.asarray(xy, float) @ a.T + t

    w, h = size(plane)
    corners = np.array([[c.x, c.y] for c in (pl.multVec(App.Vector(sx * w / 2, sy * h / 2, 0))
                                               for sx in (-1, 1) for sy in (-1, 1))])
    return to_uv, (*corners.min(axis=0), *corners.max(axis=0))
