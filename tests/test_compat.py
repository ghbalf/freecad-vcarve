# SPDX-License-Identifier: LGPL-2.1-or-later
# Authors: alf and Claude (Anthropic)
from types import SimpleNamespace as NS

from vcarve_flat.compat import tool_shape


def test_shape_type():
    assert tool_shape(NS(ShapeType="VBit")) == "VBit"


def test_bitshape_vbit():
    assert tool_shape(NS(BitShape="/x/Tools/Shape/v-bit.fcstd")) == "VBit"


def test_bitshape_endmill():
    assert tool_shape(NS(BitShape="endmill.fcstd")) == "Endmill"


def test_neither():
    assert tool_shape(NS()) == ""
