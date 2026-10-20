# SPDX-License-Identifier: LGPL-2.1-or-later
import math

import numpy as np
import pytest

from vcarve_flat.geom import (
    VBit, depth_for_radius, distances_to_segments, drop_collinear, drop_floor_runs, flat_radius, limit_depth, order_paths, rest_stepover,
    simplify,
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


def test_distances_to_segments_int_input():
    seg = np.array([[[0, 0], [10, 0]], [[10, 0], [10, 10]]])
    assert distances_to_segments(np.array([[5, 3], [12, 5], [-3, -4]]), seg) == pytest.approx([3, 2, 5])


def test_rest_stepover_sharp_tip():
    assert rest_stepover(VBit(10, 90, 0), 0.05) == pytest.approx(0.1)


def test_simplify_collinear():
    pts = np.array([[i, 0, 0] for i in range(11)], float)
    assert len(simplify(pts, 0.01)) == 2


def test_simplify_keeps_corner():
    pts = np.array([[0, 0, 0], [5, 0, 0], [10, 0, 0], [10, 5, 0], [10, 10, 0]], float)
    assert simplify(pts, 0.01).tolist() == [[0, 0, 0], [10, 0, 0], [10, 10, 0]]


def test_simplify_respects_z():
    pts = np.array([[0, 0, 0], [5, 0, -1.0], [10, 0, 0]], float)
    assert len(simplify(pts, 0.1)) == 3


def test_order_paths_reverses():
    a = np.array([[0, 0, 0], [10, 0, 0]], float)
    b = np.array([[20, 0, 0], [11, 0, 0]], float)
    out = order_paths([b, a])
    assert out[0] is a or np.array_equal(out[0], a)
    assert out[1][0].tolist() == [11, 0, 0]
    assert np.array_equal(out[1], b[::-1])


def test_order_closed_rotates():
    a = np.array([[-5, 0, 0], [0, 0, 0]], float)
    sq = np.array([[10, 10, 0], [0, 10, 0], [0, 0, 0], [10, 0, 0], [10, 10, 0]], float)
    out = order_paths([sq, a], start=(-6, 0))
    assert out[0] is a
    assert out[1][0].tolist() == [0, 0, 0]
    assert np.array_equal(out[1][0], out[1][-1]) and len(out[1]) == 5


def test_simplify_closed_square():
    t = np.linspace(0, 10, 11)
    z = np.zeros(11)
    sq = np.vstack([np.c_[t, z, z], np.c_[z + 10, t, z][1:], np.c_[10 - t, z + 10, z][1:],
                    np.c_[z, 10 - t, z][1:]])
    out = simplify(sq, 0.01)
    assert len(out) == 5 and np.array_equal(out[0], out[-1])


@pytest.mark.parametrize("n", [0, 1, 2])
def test_simplify_short_unchanged(n):
    pts = np.arange(n * 3, dtype=float).reshape(n, 3)
    assert np.array_equal(simplify(pts, 0.1), pts)


def test_drop_collinear():
    # closed loop (last point not repeated): square with collinear points on two sides and at a corner seam
    loop = np.array([(0, 0), (1, 0), (2, 0), (4, 0), (4, 4), (0, 4), (0, 2)], dtype=float)
    assert drop_collinear(loop, 1e-7).tolist() == [[0, 0], [4, 0], [4, 4], [0, 4]]
    tri = np.array([(0, 0), (1, 0), (0.5, 1e-3)])  # 1e-3 off the chord: a real corner, kept
    assert len(drop_collinear(tri, 1e-7)) == 3


def test_drop_floor_runs():
    z = [0, -0.5, -1, -1, -1, -0.5, -1, -0.2, -1, -1]
    path = np.column_stack([np.arange(len(z)), np.zeros(len(z)), z]).astype(float)
    parts = drop_floor_runs(path, -1.0)
    # the slopes keep the floor point they reach; runs along the floor and lone floor points go
    assert [p[:, 0].tolist() for p in parts] == [[0, 1, 2], [4, 5, 6, 7, 8]]
    assert drop_floor_runs(path[2:5], -1.0) == []
