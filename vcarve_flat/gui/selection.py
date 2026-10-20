# SPDX-License-Identifier: LGPL-2.1-or-later
"""Selection gate for the V-carve ops: sketches (or Job clones of them) and their edges."""
from ..sketches import is_sketch_base


class SketchGate:
    def allow(self, doc, obj, sub):
        return is_sketch_base(obj) and (not sub or sub.startswith("Edge"))


def to_clones(job, shapes, base):
    """Map BaseShapes and Base entries to the Job's clones without carving a loop twice:
    shapes are deduplicated, edge lists merged per clone, and edges of a whole shape dropped."""
    def clone(o):
        return job.Proxy.resourceClone(job, o) or o

    out_shapes, merged = [], {}
    for o in map(clone, shapes):
        if o not in out_shapes:
            out_shapes.append(o)
    for o, subs in base:
        o = clone(o)
        if o not in out_shapes:
            edges = merged.setdefault(o, [])
            edges.extend(s for s in subs if s not in edges)
    return out_shapes, [(o, tuple(subs)) for o, subs in merged.items()]


def select():
    """Selection factory for the op task panels: installs the gate (CAM removes it on close)."""
    import FreeCADGui  # imported here so the gate can be used without a GUI

    FreeCADGui.Selection.addSelectionGate(SketchGate())


def free():
    """Selection factory for ops without base geometry: no gate, any selection."""
    import FreeCADGui

    FreeCADGui.Selection.removeSelectionGate()
