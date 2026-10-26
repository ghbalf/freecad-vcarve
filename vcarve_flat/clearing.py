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
    """Area an end mill of tool_radius can reach inside floor, keeping allowance from the walls.
    Path.Area, like the pocketing: OCC's outward makeOffset2D drops the outer wire of some faces
    with holes (font letters such as O and B) or fails on them."""
    if not floor:
        return []
    area = Path.Area()
    for face in floor:
        area.add(face)
    centres = area.makeOffset(offset=-(tool_radius + allowance))
    if not centres.Faces:
        return []
    return Path.Area().add(centres).makeOffset(offset=tool_radius).Faces


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


def area_offset(faces, distance: float) -> list:
    """Offset faces by distance (positive outward) with Path.Area, which copes with holes in both
    directions; a result that vanishes gives []."""
    if not faces or distance == 0:
        return list(faces)
    area = Path.Area()
    for face in faces:
        area.add(face)
    return area.makeOffset(offset=distance).Faces


def union(faces) -> list:
    if len(faces) < 2:  # fusing one shape logs "Boolean operation with only one shape input"
        return list(faces)
    return faces[0].fuse(faces[1:]).removeSplitter().Faces


def intersect(a, b) -> list:
    if not a or not b:
        return []
    return Part.makeCompound(a).common(Part.makeCompound(b)).Faces


def mirror_faces(faces, axis: str, center) -> list:
    """Mirror about the plane through center whose normal is X (left-right) or Y (front-back)."""
    normal = App.Vector(1, 0, 0) if axis == "X" else App.Vector(0, 1, 0)
    out = []
    for face in faces:
        # Rebuilt on a right-handed plane (Path.Area logs "left hand coordinate" for the mirrored one);
        # mirroring reversed the wires.
        plane = Part.Plane(App.Vector(0, 0, face.BoundBox.ZMin), App.Vector(0, 0, 1))
        out.append(Part.Face(plane, [w.reversed() for w in face.mirror(center, normal).Wires]))
    return out


def inside_loops(loops, faces) -> list:
    out = []
    for loop in loops:
        x, y = float(loop[0][0]), float(loop[0][1])
        if any(f.isInside(App.Vector(x, y, f.BoundBox.ZMin), 1e-6, True) for f in faces):
            out.append(loop)
    return out
