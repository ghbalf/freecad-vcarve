# SPDX-License-Identifier: LGPL-2.1-or-later
# Authors: alf and Claude (Anthropic)
"""Photo V-carve without FreeCAD: image darkness, sampling it in mm, lines over it and the cuts along them."""
import numpy as np

_LUMA = np.array([0.299, 0.587, 0.114])


def darkness(rgba: np.ndarray, contrast: float, invert: bool) -> np.ndarray:
    """Darkness 0 (white) .. 1 (black) of an HxWx3 or HxWx4 uint8 image. Transparent pixels are white;
    contrast (%) stretches the encoded grey around mid-grey, then the grey is turned into linear light,
    because the grooves darken the surface by the share of it they cover."""
    px = np.asarray(rgba, float) / 255
    grey = px[..., :3] @ _LUMA
    if px.shape[-1] == 4:
        grey = grey * px[..., 3] + (1 - px[..., 3])
    grey = np.clip(0.5 + (grey - 0.5) * contrast / 100, 0, 1)
    light = np.where(grey <= 0.04045, grey / 12.92, ((grey + 0.055) / 1.055) ** 2.4)
    return light if invert else 1 - light


class Raster:
    """Darkness rho (HxW, row 0 on top) over a width x height mm rectangle centred on the origin."""

    def __init__(self, rho: np.ndarray, width: float, height: float):
        self.rho = np.asarray(rho, float)
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
