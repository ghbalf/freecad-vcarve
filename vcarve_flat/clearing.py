# SPDX-License-Identifier: LGPL-2.1-or-later
"""Face offset / subtract helpers and Path.Area pocketing for the clearing passes."""
import FreeCAD as App
import numpy as np
import Part
import Path

_POCKET_MODE = {"ZigZag": 4, "Offset": 2}  # Path.Area: 4 = ZigZagOffset (zigzag plus a contour pass)


def _split_circles(wire):
    """wire with each full circle split into two arcs: OCC's makeOffset2D mishandles full circles."""
    edges = []
    for e in wire.Edges:
        if e.isClosed():
            a, b = e.ParameterRange
            halves = [Part.Edge(e.Curve, a, (a + b) / 2), Part.Edge(e.Curve, (a + b) / 2, b)]
            edges += [h.reversed() for h in halves] if e.Orientation == "Reversed" else halves
        else:
            edges.append(e)
    return Part.Wire(Part.__sortEdges__(edges))


def _occ_offset(face, distance: float) -> list:
    """OCC offset of face. makeOffset2D gets some faces with holes wrong (1.0 drops or shrinks the
    holes, 1.1 returns a circular hole as a face of its own), so it is checked against the offset done
    one wire at a time: the outer region offset by distance, minus the holes offset by -distance. The
    whole-face result is kept where they agree (its loop order and start points are v1's)."""
    if not isinstance(face, Part.Face):
        return face.makeOffset2D(distance, join=0).Faces

    def offset(f, d):
        try:
            return f.makeOffset2D(d, join=0).Faces
        except App.Base.CADKernelError as exc:
            if "no wires" in str(exc):
                return []  # vanished
            raise

    try:
        whole = offset(face, distance)
    except (App.Base.CADKernelError, ValueError):
        whole = None
    try:
        outer = offset(Part.Face(_split_circles(face.OuterWire)), distance)
        holes = [g for w in face.Wires if not w.isSame(face.OuterWire)
                 for g in offset(Part.Face(_split_circles(w)), -distance)]
        per_wire = subtract(outer, holes)
    except (App.Base.CADKernelError, ValueError):
        if whole is None:
            raise
        return whole
    if whole is not None and sorted(len(f.Wires) for f in whole) == sorted(len(f.Wires) for f in per_wire) \
            and abs(sum(f.Area for f in whole) - sum(f.Area for f in per_wire)) <= 1e-3 * face.Length:
        return whole
    return per_wire


def offset_faces(faces, distance: float) -> list:
    """Offset faces by distance (positive outward); a feature that vanishes (too narrow) yields no
    face. OCC's makeOffset2D keeps arcs exact (see _occ_offset for its faults) but fails on some
    faces ("Wire is not closed"); Path.Area gets those right but re-fits arcs up to 0.02 mm off.
    So the OCC result is used when it agrees with Path.Area (same face count, area within 0.05 mm
    times the input perimeter), else the Path.Area one. When both fail the OCC error propagates,
    so the caller reports it with the sketch's name."""
    if not faces or distance == 0:
        return list(faces)
    occ, occ_error = [], None
    for face in faces:
        try:
            occ += _occ_offset(face, distance)
        except App.Base.CADKernelError as exc:
            if "no wires" not in str(exc):
                occ_error = exc
        except ValueError as exc:
            occ_error = exc
    try:
        area = Path.Area()
        for face in faces:
            area.add(face)
        ref = area.makeOffset(offset=distance).Faces
    except Exception:
        if occ_error:
            raise occ_error from None
        return occ
    if occ_error:
        return ref
    tol = 0.05 * sum(face.Length for face in faces)
    if len(occ) == len(ref) and abs(sum(f.Area for f in occ) - sum(f.Area for f in ref)) <= tol:
        return occ
    return ref


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


area_offset = offset_faces  # the plug ops' name for it


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
