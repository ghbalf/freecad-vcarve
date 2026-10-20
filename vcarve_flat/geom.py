# SPDX-License-Identifier: LGPL-2.1-or-later
"""V-bit depth math and distance helpers (numpy only, no FreeCAD)."""
import math
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class VBit:
    diameter: float
    angle_deg: float
    tip_diameter: float

    @property
    def radius(self) -> float:
        return self.diameter / 2

    @property
    def tip_radius(self) -> float:
        return self.tip_diameter / 2

    @property
    def half_angle(self) -> float:
        return math.radians(self.angle_deg / 2)

    @property
    def cone_height(self) -> float:
        return (self.radius - self.tip_radius) / math.tan(self.half_angle)


def limit_depth(vbit: VBit, flat_depth: float) -> tuple[float, bool]:
    """Return (depth_limit, capped); flat_depth <= 0 means the full cone."""
    if flat_depth <= 0:
        return vbit.cone_height, False
    if flat_depth > vbit.cone_height:
        return vbit.cone_height, True
    return flat_depth, False


def flat_radius(vbit: VBit, depth: float) -> float:
    return vbit.tip_radius + depth * math.tan(vbit.half_angle)


def depth_for_radius(vbit: VBit, r: np.ndarray, depth_limit: float) -> np.ndarray:
    d = (np.asarray(r, float) - vbit.tip_radius) / math.tan(vbit.half_angle)
    return np.clip(d, 0, depth_limit)


def distances_to_segments(points: np.ndarray, segments: np.ndarray) -> np.ndarray:
    """Minimum distance from each of N points to any of M segments."""
    a = segments[:, 0, :]
    ab = segments[:, 1, :] - a
    len2 = np.einsum("mi,mi->m", ab, ab)
    inv = np.divide(1.0, len2, out=np.zeros_like(len2), where=len2 > 0)
    out = np.empty(len(points))
    for i in range(0, len(points), 2048):
        p = points[i:i + 2048, None, :]
        t = np.clip(np.einsum("nmi,mi->nm", p - a, ab) * inv, 0, 1)
        d = p - (a + t[..., None] * ab)
        out[i:i + 2048] = np.sqrt(np.einsum("nmi,nmi->nm", d, d).min(axis=1))
    return out


def rest_stepover(vbit: VBit, scallop: float) -> float:
    return vbit.tip_diameter + 2 * scallop * math.tan(vbit.half_angle)


def simplify(points, tol):
    """Douglas-Peucker on 3D distance (iterative). Keeps first and last points."""
    pts = np.asarray(points, float)
    n = len(pts)
    if n < 3:
        return pts.copy()
    keep = np.zeros(n, bool)
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        i, j = stack.pop()
        if j - i < 2:
            continue
        seg = pts[j] - pts[i]
        rel = pts[i + 1:j] - pts[i]
        L2 = float(seg @ seg)
        t = np.clip(rel @ seg / L2, 0.0, 1.0) if L2 > 0 else np.zeros(len(rel))
        d = np.linalg.norm(rel - t[:, None] * seg, axis=1)
        k = int(np.argmax(d))
        if d[k] > tol:
            m = i + 1 + k
            keep[m] = True
            stack += [(i, m), (m, j)]
    return pts[keep]


def order_paths(paths, start=(0.0, 0.0)):
    """Greedy nearest-neighbor ordering on XY; reverses open paths and rotates closed ones."""
    remaining = list(paths)
    pos = np.asarray(start, float)[:2]
    out = []
    while remaining:
        best = None
        for idx, p in enumerate(remaining):
            if len(p) > 2 and np.array_equal(p[0], p[-1]):
                d = np.linalg.norm(p[:-1, :2] - pos, axis=1)
                k = int(np.argmin(d))
                cand = (float(d[k]), idx, k, False)
            else:
                d0 = float(np.linalg.norm(p[0, :2] - pos))
                d1 = float(np.linalg.norm(p[-1, :2] - pos))
                cand = (d0, idx, 0, False) if d0 <= d1 else (d1, idx, 0, True)
            if best is None or cand[0] < best[0]:
                best = cand
        _, idx, k, rev = best
        p = remaining.pop(idx)
        if k:
            p = np.vstack([p[k:-1], p[:k], p[k:k + 1]])
        elif rev:
            p = p[::-1]
        out.append(p)
        pos = p[-1, :2]
    return out
