# SPDX-License-Identifier: LGPL-2.1-or-later
# Authors: alf and Claude (Anthropic)
"""FreeCAD-version differences in tool descriptions (no FreeCAD import)."""
import os

_BIT_SHAPES = {"v-bit": "VBit", "endmill": "Endmill", "ballend": "Ballend"}


def tool_shape(tool) -> str:
    """Tool shape name: ShapeType (1.1+) or derived from BitShape (1.0)."""
    shape = getattr(tool, "ShapeType", "")
    if shape:
        return shape
    bit = getattr(tool, "BitShape", "")
    if not bit:
        return ""
    base = os.path.basename(bit)
    if base.lower().endswith(".fcstd"):
        base = base[:-6]
    return _BIT_SHAPES.get(base.lower(), base)
