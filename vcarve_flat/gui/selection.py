# SPDX-License-Identifier: LGPL-2.1-or-later
"""Selection gate for the V-carve ops: sketches (or Job clones of them) and their edges."""
from ..sketches import is_sketch_base


class SketchGate:
    def allow(self, doc, obj, sub):
        return is_sketch_base(obj) and (not sub or sub.startswith("Edge"))


def job_clone(job, obj):
    """obj's clone in job's Model, obj itself if it is one, else None. FreeCAD's resourceClone
    also returns another Job's clone as it is."""
    clone = job.Proxy.resourceClone(job, obj)
    return clone if clone in job.Model.Group else None


def to_clones(job, shapes, base):
    """Map BaseShapes and Base entries to the Job's clones without carving a loop twice:
    shapes are deduplicated, edge lists merged per clone, and edges of a whole shape dropped."""
    def clone(o):
        return job_clone(job, o) or o

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
