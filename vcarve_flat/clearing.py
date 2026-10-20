# SPDX-License-Identifier: LGPL-2.1-or-later
"""Face offset / subtract helpers and Path.Area pocketing for the clearing passes."""
import FreeCAD as App
import numpy as np
import Part
import Path

_POCKET_MODE = {"ZigZag": 4, "Offset": 2}  # Path.Area: 4 = ZigZagOffset (zigzag plus a contour pass)


def offset_faces(faces, distance: float) -> list:
    """Offset each face; a feature that vanishes (too narrow) yields no face. Other offset
    failures propagate, so the caller reports them with the sketch's name."""
    if distance == 0:
        return faces
    out = []
    for face in faces:
        try:
            out += face.makeOffset2D(distance, join=0).Faces
        except App.Base.CADKernelError as exc:
            if "no wires" not in str(exc):
                raise
    return out


def swept_faces(floor, tool_radius: float, allowance: float) -> list:
    """Area an end mill of tool_radius can reach inside floor, keeping allowance from the walls."""
    return offset_faces(offset_faces(floor, -(tool_radius + allowance)), tool_radius)


def subtract(a, b) -> list:
    if not a:
        return []
    if not b:
        return a
    return Part.makeCompound(a).cut(Part.makeCompound(b)).Faces


def pocket_polylines(faces, tool_radius, stepover, pattern, extra_offset, z, deflection) -> list:
    if not faces:
        return []
    area = Path.Area()
    for face in faces:
        area.add(face)
    # makePocket's own keyword defaults override setParams(), so pass the values here.
    pocket = area.makePocket(mode=_POCKET_MODE[pattern], tool_radius=tool_radius,
                             stepover=stepover, extra_offset=extra_offset)
    out = []
    for wire in pocket.Wires:
        pts = np.array([(p.x, p.y, z) for p in wire.discretize(QuasiDeflection=deflection)])
        if len(pts) > 1:
            out.append(pts)
    return out
