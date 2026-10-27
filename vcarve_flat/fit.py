# SPDX-License-Identifier: LGPL-2.1-or-later
"""Inlay fit check: the flipped plug seated in the pocket, simulated from both Jobs' G1 moves."""
import hashlib
import math
from dataclasses import dataclass

import numpy as np
import Part

from . import op_vcarve, progress
from .clearing import offset_faces
from .compat import tool_shape

PIECE = 1.0  # mm: G1 moves are split into pieces at most this long
EDGE = 0.05  # mm: the bound is shrunk by this, so the clearing's arc re-fit along it is not a collision


@dataclass
class FitResult:
    points: np.ndarray  # (N, 2) board XY
    grid: float
    gap: np.ndarray  # seated gap; negative where the parts collide
    z: np.ndarray  # pocket cut height, 0 on the board surface
    collisions: np.ndarray
    voids: np.ndarray
    worst_collision: float  # the lowest gap among the collisions; 0 means none
    worst_void: float  # the widest gap among the voids; 0 means none
    ops: list
    error: str | None = None


def tool_profile(tc) -> tuple:
    """(radius R, tip radius r_t, slope t); an end mill is a V-bit with r_t = R and t = inf."""
    tool = tc.Tool
    radius = tool.Diameter.Value / 2
    if tool_shape(tool) == "Endmill":
        return radius, radius, math.inf
    half = math.radians(tool.CuttingEdgeAngle.Value / 2)
    return radius, tool.TipDiameter.Value / 2, math.tan(half)


def g1_segments(op, top=0.0) -> tuple:
    """The op's G1 moves as segment ends (a, b), XYZ with Z relative to top, split into pieces at most
    PIECE long (a piece of a line is a line, so this only narrows the search)."""
    pos, a, b = np.zeros(3), [], []
    for c in op.Path.Commands:
        if c.Name in ("G2", "G02", "G3", "G03"):
            raise ValueError(f"{op.Label}: arcs are not simulated")
        new = np.array([c.Parameters.get(k, v) for k, v in zip("XYZ", pos)])
        if c.Name in ("G1", "G01"):
            a.append(pos)
            b.append(new)
        pos = new
    if not a:
        return np.zeros((0, 3)), np.zeros((0, 3))
    a, b = np.array(a), np.array(b)
    n = np.maximum(1, np.ceil(np.linalg.norm(b - a, axis=1) / PIECE)).astype(int)
    seg = np.repeat(np.arange(len(a)), n)
    k = np.arange(n.sum()) - np.repeat(np.cumsum(n) - n, n)
    lo, hi = (k / n[seg])[:, None], ((k + 1) / n[seg])[:, None]
    return a[seg] + lo * (b - a)[seg] - [0, 0, top], a[seg] + hi * (b - a)[seg] - [0, 0, top]


def op_paths(*ops, top=0.0) -> list:
    return [(g1_segments(op, top), tool_profile(op.ToolController)) for op in ops]


def _lowest(q, a, b, radius, tip, slope) -> np.ndarray:
    """Lowest tool surface over each point of q (Q x 2) as the tool moves along each segment a -> b:
    (Q, S) array, inf where out of reach. Along a segment at offset h from the point and position s
    (nearest s0), the surface is z(s) + max(0, hypot(h, s - s0) - r_t)/t for hypot <= R; that is
    convex in s, so its minimum is at a stationary point, at a kink (hypot = r_t) or at an end of
    the reach."""
    d = b[:, :2] - a[:, :2]
    length = np.hypot(*d.T)
    plunge = length < 1e-9  # a vertical move: its lowest point counts, along any direction
    e = np.where(plunge[:, None], [1.0, 0.0], d / np.where(plunge, 1, length)[:, None])
    length = np.where(plunge, 0, length)
    w = q[:, None, :] - a[None, :, :2]
    s0 = (w * e).sum(-1)
    h = np.abs(w[..., 0] * e[:, 1] - w[..., 1] * e[:, 0])
    dz = np.where(plunge, 0, (b[:, 2] - a[:, 2]) / np.where(plunge, 1, length))
    z0 = np.where(plunge, np.minimum(a[:, 2], b[:, 2]), a[:, 2])
    half = np.sqrt(np.maximum(radius ** 2 - h ** 2, 0))
    lo, hi = np.maximum(0, s0 - half), np.minimum(length, s0 + half)
    kink = np.sqrt(np.maximum(tip ** 2 - h ** 2, 0))
    k = np.full_like(dz, np.nan) if math.isinf(slope) else -slope * dz  # f' = 0: (s - s0)/rho = k
    with np.errstate(invalid="ignore", divide="ignore"):
        stat = np.where(np.abs(k) < 1, s0 + k * h / np.sqrt(1 - k ** 2), s0)
    z = np.inf
    for c in (lo, hi, s0 - kink, s0 + kink, stat):
        c = np.clip(c, lo, hi)
        z = np.minimum(z, z0 + dz * c + np.maximum(0, np.hypot(h, c - s0) - tip) / slope)
    return np.where((h <= radius) & (lo <= hi), z, np.inf)


def cut_height(paths_by_tool, points, chunk=256) -> np.ndarray:
    """The lowest Z the tools reach at each XY point (0 where none reaches, the uncut top).
    A V-bit's lower surface at distance rho from its axis at z_c is z_c + max(0, rho - r_t)/t
    for rho <= R."""
    q = np.asarray(points, float)[:, :2]
    out = np.zeros(len(q))
    for (a, b), (radius, tip, slope) in paths_by_tool:
        keep = np.minimum(a[:, 2], b[:, 2]) < 0  # segments at or above the top cut nothing
        a, b = a[keep], b[keep]
        if not len(a):
            continue
        # beyond its reach a tool's surface is above the top; a piece's points lie within PIECE/2 of its middle
        reach = np.minimum(radius, tip - np.minimum(a[:, 2], b[:, 2]) * slope) + PIECE / 2
        mid = (a[:, :2] + b[:, :2]) / 2
        order = np.argsort(mid[:, 0])
        a, b, mid, reach = a[order], b[order], mid[order], reach[order]
        rmax = reach.max()
        for i in range(0, len(q), chunk):
            progress.step()
            c = q[i:i + chunk]
            lo, hi = np.searchsorted(mid[:, 0], [c[:, 0].min() - rmax, c[:, 0].max() + rmax])
            m = np.arange(lo, hi)
            m = m[(mid[m, 1] >= c[:, 1].min() - rmax) & (mid[m, 1] <= c[:, 1].max() + rmax)]
            if not len(m):
                continue
            out[i:i + chunk] = np.minimum(out[i:i + chunk], _lowest(c, a[m], b[m], radius, tip, slope).min(axis=1))
    return out


def chain(plug) -> list:
    """The ops a check of plug simulates: the pocket op and its Job's active clearance ops, then the plug
    op and its Job's; [] without a pocket op."""
    pocket = plug.PocketOp
    if pocket is None:
        return []
    return [pocket, *op_vcarve.clearance_ops(pocket), plug, *op_vcarve.clearance_ops(plug)]


def signature(ops) -> str:
    h = hashlib.sha1()
    for op in ops:
        h.update(op.Name.encode())
        h.update(op.Path.toGCode().encode())
    return h.hexdigest()


def _inside(q, faces, deflection=0.01) -> np.ndarray:
    """Whether each point of q (Q x 2) lies inside faces (even-odd over all their wires)."""
    a = []
    for face in faces:
        for wire in face.Wires:
            p = np.array([(v.x, v.y) for v in wire.discretize(Deflection=deflection)])
            a.append(np.column_stack([p, np.roll(p, -1, axis=0)]))
    x0, y0, x1, y1 = np.vstack(a).T
    out = np.zeros(len(q), bool)
    chunk = max(1, 2 ** 21 // len(x0))
    for i in range(0, len(q), chunk):
        progress.step()
        x, y = q[i:i + chunk, 0, None], q[i:i + chunk, 1, None]
        crosses = (y0 > y) != (y1 > y)
        with np.errstate(invalid="ignore", divide="ignore"):
            out[i:i + chunk] = (crosses & (x < x0 + (y - y0) * (x1 - x0) / (y1 - y0))).sum(axis=1) % 2 == 1
    return out


def check(plug, grid=0.25, tol=0.02) -> FitResult:
    """Seats the plug op's plug in its pocket on a grid over the plug's bound, mirrored to the board."""
    def refuse(error):
        return FitResult(np.zeros((0, 2)), grid, np.zeros(0), np.zeros(0), np.zeros(0, bool), np.zeros(0, bool),
                         0.0, 0.0, ops, error)

    pocket, ops = plug.PocketOp, chain(plug) or [plug]
    if pocket is None:
        return refuse(f"{plug.Label}: no pocket op linked")
    n, paths = ops.index(plug), []
    for i, op in enumerate(ops):
        try:
            a, b = g1_segments(op, (pocket if i < n else plug).StartDepth.Value)
        except ValueError as err:
            return refuse(str(err))
        if "Invalid" in op.State or "Error" in op.State or not len(a):
            return refuse(f"{op.Label}: no toolpath, recompute it first")
        if "Touched" in op.State:
            return refuse(f"{op.Label}: out of date, recompute it first")
        paths.append(((a, b), tool_profile(op.ToolController)))
    design = plug.Proxy._design(plug)
    bounds = plug.Proxy._bounds(plug, design, op_vcarve.tool_vbit(plug.ToolController)) if design else []
    if not bounds:
        return refuse(f"{plug.Label}: no design")
    centre = Part.makeCompound(design).BoundBox.Center
    bb = Part.makeCompound(bounds).BoundBox
    x, y = np.meshgrid(np.arange(bb.XMin, bb.XMax + grid / 2, grid), np.arange(bb.YMin, bb.YMax + grid / 2, grid))
    m = np.column_stack([x.ravel(), y.ravel()])
    m = m[_inside(m, offset_faces(bounds, -EDGE))]
    q = m.copy()
    axis = 0 if plug.MirrorAxis == "X" else 1
    q[:, axis] = 2 * centre[axis] - m[:, axis]
    z = cut_height(paths[:n], q)
    s = -cut_height(paths[n:], m)
    G = plug.GlueGap.Value
    gap = (-pocket.FlatDepth.Value + G + s) - z
    collisions = gap < -tol
    in_pocket = z < -1e-3
    voids = in_pocket & (gap > G + max(tol, 0.1))
    return FitResult(q, grid, gap, z, collisions, voids, float(gap[collisions].min(initial=0)),
                     float(gap[voids].max(initial=0)), ops)
