# SPDX-License-Identifier: LGPL-2.1-or-later
# Authors: alf and Claude (Anthropic)
"""Photo V-carve without FreeCAD: image darkness, sampling it in mm, lines over it and the cuts along them."""
import numpy as np

from .geom import simplify

_LUMA = np.array([0.299, 0.587, 0.114])


def darkness(rgba: np.ndarray, contrast: float, invert: bool) -> np.ndarray:
    """Darkness 0 (white) .. 1 (black) of an HxWx3 or HxWx4 uint8 image. Transparent pixels are uncut;
    contrast (%) stretches the encoded grey around mid-grey, then the grey is turned into linear light,
    because the grooves darken the surface by the share of it they cover."""
    px = np.asarray(rgba, float) / 255
    grey = px[..., :3] @ _LUMA
    grey = np.clip(0.5 + (grey - 0.5) * contrast / 100, 0, 1)
    light = np.where(grey <= 0.04045, grey / 12.92, ((grey + 0.055) / 1.055) ** 2.4)
    rho = light if invert else 1 - light
    return rho * px[..., 3] if px.shape[-1] == 4 else rho  # transparent stays uncut, inverted or not


def _block_mean(a: np.ndarray, factor: int, axis: int) -> np.ndarray:
    """a averaged over blocks of about factor entries along axis, spread evenly over its length."""
    size = a.shape[axis]
    starts = np.arange(max(1, size // factor)) * size // max(1, size // factor)
    counts = np.diff(np.append(starts, size))
    return np.add.reduceat(a, starts, axis=axis) / np.expand_dims(counts, 1 - axis)


class Raster:
    """Darkness rho (HxW, row 0 on top) over a width x height mm rectangle centred on the origin;
    with cell (mm), pixels finer than it are averaged into blocks of at most cell, so sampling at that
    step sees every pixel instead of aliasing fur and grain into depth noise."""

    def __init__(self, rho: np.ndarray, width: float, height: float, cell: float = 0):
        self.rho = np.asarray(rho, float)
        for axis, extent in enumerate((height, width)):
            factor = int(cell * self.rho.shape[axis] / extent + 1e-9) if cell > 0 else 1
            if factor > 1:
                self.rho = _block_mean(self.rho, factor, axis)
        self.width, self.height = width, height

    def sample(self, uv: np.ndarray) -> np.ndarray:
        """Bilinear darkness at the (N, 2) points uv (mm, v up); 0 outside the image."""
        uv = np.asarray(uv, float)
        h, w = self.rho.shape
        col = np.clip((uv[:, 0] / self.width + 0.5) * w - 0.5, 0, w - 1)
        row = np.clip((0.5 - uv[:, 1] / self.height) * h - 0.5, 0, h - 1)
        c0, r0 = np.minimum(col.astype(int), max(w - 2, 0)), np.minimum(row.astype(int), max(h - 2, 0))
        c1, r1 = np.minimum(c0 + 1, w - 1), np.minimum(r0 + 1, h - 1)
        fc, fr = col - c0, row - r0
        top = self.rho[r0, c0] * (1 - fc) + self.rho[r0, c1] * fc
        bottom = self.rho[r1, c0] * (1 - fc) + self.rho[r1, c1] * fc
        inside = (np.abs(uv[:, 0]) <= self.width / 2) & (np.abs(uv[:, 1]) <= self.height / 2)
        return np.where(inside, top * (1 - fr) + bottom * fr, 0.0)


def band_sample(raster: Raster, to_uv, xy: np.ndarray, normal: np.ndarray, width: float, step: float):
    """Darkness at the points xy averaged across a band width wide along normal, sampled at most step apart."""
    n = max(1, int(np.ceil(width / step - 1e-9)))
    return np.mean([raster.sample(to_uv(xy + off * normal)) for off in ((np.arange(n) + 0.5) / n - 0.5) * width],
                   axis=0)


def line_set(rect, angle: float, spacing: float) -> list:
    """Parallel lines at angle degrees from +X, spacing apart and symmetric about the centre of rect
    (xmin, ymin, xmax, ymax), each clipped to rect as a 2x2 array, in offset order with every second
    one reversed (serpentine)."""
    x0, y0, x1, y1 = rect
    a = np.radians(angle)
    d, n = np.array([np.cos(a), np.sin(a)]), np.array([-np.sin(a), np.cos(a)])
    c = np.array([(x0 + x1) / 2, (y0 + y1) / 2])
    reach = np.hypot(x1 - x0, y1 - y0) / 2
    k = int(reach // spacing) + 1
    lines = []
    for off in (np.arange(-k, k) + 0.5) * spacing:
        p = c + off * n
        lo, hi = -np.inf, np.inf
        for axis, (a0, a1) in enumerate(((x0, x1), (y0, y1))):
            if abs(d[axis]) < 1e-12:
                if not a0 <= p[axis] <= a1:
                    lo, hi = 1, 0
                continue
            t0, t1 = sorted(((a0 - p[axis]) / d[axis], (a1 - p[axis]) / d[axis]))
            lo, hi = max(lo, t0), min(hi, t1)
        if hi - lo > 1e-9:
            seg = np.array([p + lo * d, p + hi * d])
            lines.append(seg[::-1] if len(lines) % 2 else seg)
    return lines


def resample(poly: np.ndarray, step: float) -> np.ndarray:
    """The polyline with points at most step apart, keeping its vertices."""
    poly = np.asarray(poly, float)
    out = [poly[:1]]
    for a, b in zip(poly[:-1], poly[1:]):
        n = max(1, int(np.ceil(np.linalg.norm(b - a) / step - 1e-9)))
        out.append(a + (b - a) * (np.arange(1, n + 1) / n)[:, None])
    return np.concatenate(out)


def hatch_share(rho: np.ndarray) -> np.ndarray:
    """The darkness each of two crossed line sets carries so together they cover rho: 1 - (1 - c)^2 = rho."""
    return 1 - np.sqrt(1 - np.asarray(rho, float))


def cut_runs(xy: np.ndarray, depth: np.ndarray, min_depth: float, z_top: float, tol: float) -> list:
    """The stretches of xy where depth >= min_depth, as (M, 3) paths at z_top - depth, simplified within tol."""
    cut = np.asarray(depth) >= min_depth
    edges = np.flatnonzero(np.diff(np.concatenate([[0], cut.astype(np.int8), [0]])))
    pts = np.column_stack([xy, z_top - np.asarray(depth, float)])
    return [simplify(pts[i:j], tol) for i, j in zip(edges[::2], edges[1::2])]
