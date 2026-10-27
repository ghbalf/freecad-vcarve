# SPDX-License-Identifier: LGPL-2.1-or-later
# Authors: alf and Claude (Anthropic)
import numpy as np
import pytest

from vcarve_flat.photo import Raster, darkness


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
