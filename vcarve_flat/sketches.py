# SPDX-License-Identifier: LGPL-2.1-or-later
# Authors: alf and Claude (Anthropic)
"""Sketch (or Job clone of a sketch) -> closed loops -> planar faces."""
from typing import Sequence

import Part

_SKETCH = "Sketcher::SketchObject"


class SketchError(Exception):
    """Message always starts with the sketch label."""


def sketch_of(obj):
    if obj.TypeId == _SKETCH:
        return obj
    objs = getattr(obj, "Objects", None)
    if objs and objs[0].TypeId == _SKETCH:
        return objs[0]
    return None


def is_sketch_base(obj) -> bool:
    return sketch_of(obj) is not None


def sketch_label(obj) -> str:
    """Label of the sketch behind obj (the original sketch for a Job clone)."""
    return (sketch_of(obj) or obj).Label


def _wires(shape):
    return [Part.Wire(group) for group in Part.sortEdges(shape.Edges)]


def loops_for_base(obj, subs: Sequence[str] | None) -> list[Part.Wire]:
    label = sketch_label(obj)
    wires = _wires(obj.Shape)
    if not subs:
        if any(not w.isClosed() for w in wires):
            raise SketchError(f"{label}: sketch contains open wires")
        return wires
    out = []
    for sub in subs:
        if not sub.startswith("Edge"):
            continue
        try:
            edge = obj.Shape.getElement(sub)
        except Exception:
            raise SketchError(f"{label}: {sub} no longer exists") from None
        wire = next((w for w in wires if any(e.isSame(edge) for e in w.Edges)), None)
        if wire is None or not wire.isClosed():
            raise SketchError(f"{label}: {sub} is not part of a closed outline")
        if not any(wire.isSame(w) for w in out):
            out.append(wire)
    return out


def faces_from_loops(label: str, loops: list[Part.Wire]) -> list[Part.Face]:
    # Bullseye needs disjoint loops; crossing ones give overlapping or zero-area faces.
    for i, a in enumerate(loops):
        for b in loops[i + 1:]:
            if a.BoundBox.intersect(b.BoundBox) and a.distToShape(b)[0] < 1e-7:
                raise SketchError(f"{label}: outlines overlap or touch")
    try:
        faces = Part.makeFace(loops, "Part::FaceMakerBullseye").Faces
    except Exception as exc:
        raise SketchError(f"{label}: cannot build faces ({exc})") from None
    if not faces:
        raise SketchError(f"{label}: no faces could be built from the outlines")
    for face in faces:
        u, v = face.Surface.parameter(face.CenterOfMass)
        if abs(abs(face.normalAt(u, v).z) - 1) > 1e-6:
            raise SketchError(f"{label}: sketch is not parallel to the XY plane")
    return faces
