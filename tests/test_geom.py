# SPDX-License-Identifier: LGPL-2.1-or-later
import math

import numpy as np
import pytest

from vcarve_flat.geom import (
    VBit, depth_for_radius, distances_to_segments, flat_radius, limit_depth, rest_stepover,
)

V60 = VBit(10.0, 60.0, 0.0)
V90 = VBit(10.0, 90.0, 0.2)


def test_cone_height():
    assert V90.cone_height == pytest.approx(4.9)          # (5-0.1)/tan45
    assert V60.cone_height == pytest.approx(5/math.tan(math.radians(30)))


def test_limit_depth():
    assert limit_depth(V90, 0) == (pytest.approx(4.9), False)
    assert limit_depth(V90, 2.0) == (2.0, False)
    assert limit_depth(V90, 7.0) == (pytest.approx(4.9), True)


def test_flat_radius():
    assert flat_radius(V90, 2.0) == pytest.approx(2.1)


def test_depth_for_radius_clamps():
    r = np.array([0.0, 0.05, 1.1, 50.0])
    assert depth_for_radius(V90, r, 2.0) == pytest.approx([0, 0, 1.0, 2.0])


def test_distances_to_segments():
    seg = np.array([[[0, 0], [10, 0]], [[10, 0], [10, 10]]], float)
    pts = np.array([[5, 3], [12, 5], [-3, -4]], float)
    assert distances_to_segments(pts, seg) == pytest.approx([3, 2, 5])


def test_rest_stepover_sharp_tip():
    assert rest_stepover(VBit(10, 90, 0), 0.05) == pytest.approx(0.1)
