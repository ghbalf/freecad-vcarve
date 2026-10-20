# SPDX-License-Identifier: LGPL-2.1-or-later
"""Selection gate for the V-carve ops: sketches (or Job clones of them) and their edges."""
from ..sketches import is_sketch_base


class SketchGate:
    def allow(self, doc, obj, sub):
        return is_sketch_base(obj) and (not sub or sub.startswith("Edge"))


def select():
    """Selection factory for the op task panels: installs the gate (CAM removes it on close)."""
    import FreeCADGui  # imported here so the gate can be used without a GUI

    FreeCADGui.Selection.addSelectionGate(SketchGate())
