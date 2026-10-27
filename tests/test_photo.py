# SPDX-License-Identifier: LGPL-2.1-or-later
# Authors: alf and Claude (Anthropic)
import numpy as np
import pytest

from vcarve_flat.photo import Raster, cut_runs, darkness, hatch_share, line_set, resample


def rgb(*pixels):
    """One row of RGB(A) pixels."""
    return np.array([pixels], np.uint8)


def test_darkness_black_white_grey():
    rho = darkness(rgb((0, 0, 0), (255, 255, 255), (128, 128, 128)), 100, False)[0]
    assert rho[0] == pytest.approx(1)
    assert rho[1] == pytest.approx(0)
    assert rho[2] == pytest.approx(1 - 0.2158, abs=1e-3)  # sRGB 128 is 0.2158 in linear light


def test_darkness_weights():
    red, green, blue = darkness(rgb((255, 0, 0), (0, 255, 0), (0, 0, 255)), 100, False)[0]
    assert green < red < blue


def test_darkness_alpha_is_white():
    assert darkness(rgb((0, 0, 0, 0), (0, 0, 0, 255)), 100, False)[0] == pytest.approx([0, 1])


def test_darkness_invert():
    assert darkness(rgb((0, 0, 0), (255, 255, 255)), 100, True)[0] == pytest.approx([0, 1])


def test_darkness_contrast():
    grey = rgb((63, 63, 63))
    assert darkness(grey, 200, False)[0, 0] == pytest.approx(1)  # 0.5 + (63/255 - 0.5)·2 < 0: black
    assert darkness(grey, 100, False)[0, 0] == pytest.approx(1 - ((63 / 255 + 0.055) / 1.055) ** 2.4)


def test_raster_orientation():
    rho = np.array([[1.0, 0.0], [0.0, 0.0]])  # the top-left pixel black
    r = Raster(rho, 10, 10)
    assert r.sample(np.array([[-2.5, 2.5], [2.5, -2.5], [20, 0]])) == pytest.approx([1, 0, 0])


def test_raster_bilinear():
    r = Raster(np.array([[1.0, 0.0]]), 10, 5)
    assert r.sample(np.array([[0.0, 0.0]]))[0] == pytest.approx(0.5)


def test_line_set_horizontal():
    lines = line_set((0, 0, 10, 10), 0, 2.5)
    assert [ln[0, 1] for ln in lines] == pytest.approx([1.25, 3.75, 6.25, 8.75])
    assert all(ln[:, 1] == pytest.approx([ln[0, 1]] * 2) for ln in lines)
    assert [ln[:, 0].tolist() for ln in lines] == [[0, 10], [10, 0], [0, 10], [10, 0]]  # serpentine


def test_line_set_angles():
    assert all(ln[0, 0] == pytest.approx(ln[1, 0]) for ln in line_set((0, 0, 10, 10), 90, 2.5))
    diag = line_set((0, 0, 10, 10), 45, 1)
    assert diag and all(((ln >= -1e-9) & (ln <= 10 + 1e-9)).all() for ln in diag)
    for ln in diag:
        d = (ln[1] - ln[0]) / np.linalg.norm(ln[1] - ln[0])
        assert abs(d[0]) == pytest.approx(np.sqrt(0.5)) and d[0] * d[1] > 0
    as_set = lambda lines: sorted(tuple(sorted(map(tuple, np.round(ln, 9)))) for ln in lines)
    assert as_set(line_set((0, 0, 10, 10), -90, 2.5)) == as_set(line_set((0, 0, 10, 10), 90, 2.5))


def test_resample():
    assert len(resample(np.array([[0.0, 0], [1, 0]]), 0.25)) == 5
    ell = resample(np.array([[0.0, 0], [1, 0], [1, 1]]), 0.3)
    assert any(np.allclose(p, [1, 0]) for p in ell)
    assert np.allclose(ell[[0, -1]], [[0, 0], [1, 1]])
    assert np.linalg.norm(np.diff(ell, axis=0), axis=1).max() <= 0.3 + 1e-12


def test_hatch_share():
    assert hatch_share(np.array([0, 1, 0.75])) == pytest.approx([0, 1, 0.5])


def test_cut_runs_lift_over_white():
    xy = np.column_stack([np.arange(5.0), np.zeros(5)])
    runs = cut_runs(xy, np.array([1, 1, 0, 0, 1.0]), 0.05, 10, 0.01)
    assert [len(r) for r in runs] == [2, 1]
    assert all((r[:, 2] == 9).all() for r in runs)


def test_eye_fixture():
    """A pupil (black disk, r 10 mm) with a catchlight (white dot, r 1.5 mm): the cut reaches the full
    depth on the pupil and lifts out over the catchlight."""
    c = (np.arange(300) + 0.5) * 0.1 - 15
    x, y = np.meshgrid(c, -c)
    r = np.hypot(x, y)
    eye = Raster(((r < 10) & (r > 1.5)).astype(float), 30, 30)
    xy = resample(np.array([[-15.0, 0], [15, 0]]), 0.25)
    runs = cut_runs(xy, eye.sample(xy) * 2, 0.05, 0, 0.01)
    assert len(runs) == 2
    assert [r[:, 2].min() for r in runs] == pytest.approx([-2, -2], abs=1e-6)
    assert 2.5 <= runs[1][0, 0] - runs[0][-1, 0] <= 3.5
