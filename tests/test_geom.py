# SPDX-License-Identifier: LGPL-2.1-or-later
import math

import numpy as np
import pytest

from vcarve_flat.geom import (
    VBit, depth_for_radius, distances_to_segments, drop_collinear, drop_floor_runs, flat_radius, inlay_defaults, insert_crossings, narrow_points, limit_depth, order_paths,
    pass_depths, plug_errors, rest_stepover, simplify,
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


def test_depth_for_radius_min_depth():
    r = [0.0, 0.1, 2.1]
    assert depth_for_radius(V90, r, 1.0, min_depth=-0.5) == pytest.approx([-0.1, 0, 1.0])
    assert depth_for_radius(V90, r, 1.0) == pytest.approx([0, 0, 1.0])


def test_pass_depths():
    assert pass_depths(3, 0) == [3]
    assert pass_depths(3, 5) == [3]
    assert pass_depths(3, 1.5) == [1.5, 3]
    assert pass_depths(4, 1.5) == pytest.approx([1.5, 3, 4])
    assert pass_depths(3 + 1e-9, 1.5) == pytest.approx([1.5, 3])


def test_inlay_defaults():
    assert inlay_defaults(VBit(10, 90, 0.1)) == pytest.approx((2.97, 0.2, 1.5))
    p, g, s = inlay_defaults(VBit(10, 30, 0))
    assert (p, s) == pytest.approx((3, 1.5))
    assert inlay_defaults(VBit(4, 90, 0)) == pytest.approx((1.2, 0.2, 1.0))


def test_plug_errors():
    vb = VBit(10, 90, 0.1)
    p, g, s = inlay_defaults(vb)
    assert plug_errors(vb, p, g, s) == []
    assert any("Glue Gap" in m for m in plug_errors(vb, p, 0, s)) and len(plug_errors(vb, p, 0, s)) == 1
    assert len(plug_errors(vb, p, p, s)) == 1 and "Glue Gap" in plug_errors(vb, p, p, s)[0]
    errs = plug_errors(vb, p, g, vb.cone_height + 0.5 - (p - g))
    assert len(errs) == 1 and "0.5" in errs[0]


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


def test_insert_crossings():
    # radius |x| along y = 0; level 1.2 is crossed twice between samples, level 3 is hit by a sample
    xy = np.column_stack([np.arange(-2.0, 4.5, 1.0), np.zeros(7)])
    out, r = insert_crossings(xy, np.abs(xy[:, 0]), lambda p: np.abs(p[:, 0]), [1.2, 3.0])
    np.testing.assert_allclose(out[:, 0], [-2, -1.2, -1, 0, 1, 1.2, 2, 3, 4], atol=1e-9)
    np.testing.assert_allclose(r, np.abs(out[:, 0]), atol=1e-9)
    np.testing.assert_array_equal(insert_crossings(xy, np.abs(xy[:, 0]), None, [5.0])[0], xy)


def _loop_segments(pts):
    pts = np.asarray(pts, float)
    return np.stack([pts, np.roll(pts, -1, axis=0)], axis=1)


def test_narrow_points_gap_not_corners():
    strip = _loop_segments([(0, 0), (10, 0), (10, 0.3), (0, 0.3)])
    mid = np.column_stack([np.linspace(1, 9, 9), np.full(9, 0.15)])
    assert narrow_points(mid, strip, 0.5).all()
    assert not narrow_points(mid, strip, 0.1).any()  # 0.3 wide: not narrower than 0.2
    ends = np.array([(0.1, 0.1), (0.05, 0.05), (9.9, 0.2)])  # on the strip's corner bisectors
    assert not narrow_points(ends, strip, 0.5).any()


def test_narrow_points_sharp_and_square_corners():
    square = _loop_segments([(0, 0), (10, 0), (10, 10), (0, 10)])
    assert not narrow_points(np.array([(0.3, 0.3), (9.8, 9.8)]), square, 0.5).any()
    h = math.tan(math.radians(10))  # a 20 degree wedge with its tip at the origin
    wedge = _loop_segments([(0, 0), (10, -10 * h), (10, 10 * h)])
    assert not narrow_points(np.array([(1.0, 0), (2.0, 0)]), wedge, 0.5).any()
