# SPDX-License-Identifier: LGPL-2.1-or-later
# Authors: alf and Claude (Anthropic)
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


def depth_for_radius(vbit: VBit, r: np.ndarray, depth_limit: float, min_depth: float = 0.0) -> np.ndarray:
    d = (np.asarray(r, float) - vbit.tip_radius) / math.tan(vbit.half_angle)
    return np.clip(d, min_depth, depth_limit)


def pass_depths(final: float, step: float) -> list:
    """Step-down depths ending at final; a last step shorter than 1e-6 is merged into final."""
    if step <= 0 or step >= final:
        return [final]
    n = int((final - 1e-6) // step)
    return [step * i for i in range(1, n + 1)] + [final]


def surface_gap(vbit: VBit, pocket_depth: float, glue_gap: float) -> float:
    """The plug's Surface Gap create_inlay sets: 1.5 mm, less where the cone is too short."""
    return min(1.5, vbit.cone_height - (pocket_depth - glue_gap))


def inlay_defaults(vbit: VBit) -> tuple:
    """(pocket depth P, glue gap G, surface gap S) that fit the bit's cone."""
    p = min(3.0, 0.6 * vbit.cone_height)
    return p, 0.2, surface_gap(vbit, p, 0.2)


def plug_errors(vbit: VBit, pocket_depth: float, glue_gap: float, surface_gap: float) -> list:
    errors = []
    if glue_gap <= 0 or glue_gap >= pocket_depth:
        errors.append(f"Glue Gap {glue_gap:g} mm must be above 0 and below the pocket depth {pocket_depth:g} mm.")
    excess = pocket_depth - glue_gap + surface_gap - vbit.cone_height
    if excess > 1e-9:
        errors.append(f"Plug depth (pocket depth - Glue Gap + Surface Gap) exceeds the V-bit cone height "
                      f"{vbit.cone_height:.2f} mm by {excess:.2f} mm.")
    return errors


def distances_to_segments(points: np.ndarray, segments: np.ndarray) -> np.ndarray:
    """Minimum distance from each of N points to any of M segments."""
    points, segments = np.asarray(points, float), np.asarray(segments, float)
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


def insert_crossings(xy: np.ndarray, r: np.ndarray, radius, levels) -> tuple:
    """Insert into the polyline xy (radii r = radius(xy)) the points where the radius crosses one of
    levels between two samples, found by bisection; returns (xy, r) with r = level there. The
    clipped depth has a kink at those radii, and the chord between the samples would cut it off."""
    xy, r = np.asarray(xy, float), np.asarray(r, float)
    hits = [(k, level) for level in levels for k in np.nonzero((r[:-1] - level) * (r[1:] - level) < 0)[0]]
    if not hits:
        return xy, r
    i, level = (np.array(v) for v in zip(*hits))
    a, ab, rising = xy[i], xy[i + 1] - xy[i], r[i + 1] > r[i]
    lo, hi = np.zeros(len(i)), np.ones(len(i))
    for _ in range(40):
        mid = (lo + hi) / 2
        past = (radius(a + mid[:, None] * ab) > level) == rising
        lo, hi = np.where(past, lo, mid), np.where(past, mid, hi)
    u = (lo + hi) / 2
    order = np.argsort(np.r_[np.arange(len(xy)), i + u], kind="stable")
    return np.vstack([xy, a + u[:, None] * ab])[order], np.r_[r, level][order]


def narrow_points(xy: np.ndarray, segments: np.ndarray, radius: float) -> np.ndarray:
    """Mask of the medial-axis points xy that lie in a gap narrower than 2*radius. A point on the
    bisector of a corner is not in a gap: the boundary tangents at its two footpoints meet at the
    corner, on the boundary. Across a gap they are parallel or meet away from it."""
    xy, segments = np.asarray(xy, float), np.asarray(segments, float)
    out = np.zeros(len(xy), bool)
    if not len(segments):
        return out
    a, ab = segments[:, 0], segments[:, 1] - segments[:, 0]
    len2 = np.einsum("mi,mi->m", ab, ab)
    inv = np.divide(1.0, len2, out=np.zeros_like(len2), where=len2 > 0)
    r = distances_to_segments(xy, segments)
    for i in np.nonzero(r < radius)[0]:
        foot = a + np.clip(np.einsum("mi,mi->m", xy[i] - a, ab) * inv, 0, 1)[:, None] * ab
        dist = np.hypot(*(foot - xy[i]).T)
        near = foot[dist <= r[i] * (1 + 1e-3) + 1e-6]
        f1 = foot[dist.argmin()]
        f2 = near[np.hypot(*(near - f1).T).argmax()]
        if np.hypot(*(f2 - f1)) < 1e-9:
            continue  # one footpoint: the axis ends on the boundary
        n = np.array([xy[i] - f1, xy[i] - f2])
        det = n[0, 0] * n[1, 1] - n[0, 1] * n[1, 0]
        if abs(det) < 1e-9 * r[i] ** 2:
            out[i] = True  # parallel walls
            continue
        corner = np.linalg.solve(n, np.einsum("ij,ij->i", n, [f1, f2]))
        out[i] = distances_to_segments(corner[None], segments)[0] > r[i]
    return out


def drop_collinear(loop: np.ndarray, eps: float) -> np.ndarray:
    """Closed 2D loop (last point not repeated) without points closer than eps to the chord of their
    neighbours. Collinear boundary points give Path.Voronoi degenerate parabolic edges."""
    loop = np.asarray(loop, float)
    a = np.roll(loop, -1, 0) - np.roll(loop, 1, 0)
    b = loop - np.roll(loop, 1, 0)
    cross = np.abs(a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0])
    keep = cross > eps * np.linalg.norm(a, axis=1)
    return loop[keep] if keep.sum() >= 3 else loop


def drop_floor_runs(path: np.ndarray, z_floor: float, eps: float = 1e-9) -> list:
    """Pieces of a 3D polyline without its segments lying on the floor z_floor."""
    on = path[:, 2] <= z_floor + eps
    return [p for p in np.split(path, np.flatnonzero(on[:-1] & on[1:]) + 1) if len(p) > 1]


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
