# SPDX-License-Identifier: LGPL-2.1-or-later
"""Inlay test helpers: build a pocket Job and a plug Job, and simulate their cut surfaces from the paths."""
import math
from types import SimpleNamespace

import numpy as np
import Path
import Path.Main.Job
import Path.Tool.Controller

from helpers import _tool, make_job, make_sketch
from vcarve_flat import op_clearance, op_plug
from vcarve_flat.compat import tool_shape
from vcarve_flat.geom import VBit, inlay_defaults

PIECE = 1.0  # mm: G1 moves are split into pieces at most this long


def _set_stepdown(op, value):
    op.setExpression("StepDown", None)  # else the setup sheet's expression wins on recompute
    op.StepDown = value


def make_inlay(doc, loops, circles=(), tip=None, stepdown=None, ridge=True, stock=None, **props):
    """Pocket pair (Flat Depth P) and plug pair on one sketch. stepdown goes to all four ops, props to
    the plug op. Returns a namespace of the objects and the depths P, G, S, start, t."""
    sk = make_sketch(doc, "S", list(loops), circles)
    job, tcs = make_job(doc, [sk])
    if tip is not None:
        tcs["60degree_Vbit"].Tool.TipDiameter = tip
    n = SimpleNamespace(job=job)
    n.pocket_clr, n.vc = op_clearance.create_pair(job)
    n.vc.BaseShapes = list(job.Model.Group)
    t = tcs["60degree_Vbit"].Tool
    n.vbit = VBit(t.Diameter.Value, t.CuttingEdgeAngle.Value, t.TipDiameter.Value)
    n.P, n.G, n.S = inlay_defaults(n.vbit)
    n.start = n.P - n.G
    n.t = math.tan(n.vbit.half_angle)
    n.vc.FlatDepth = n.P
    n.pjob = Path.Main.Job.Create("Plug", [sk], None)
    for tc in list(n.pjob.Tools.Group):
        doc.removeObject(tc.Name)
    n.pjob.Stock.ExtZpos = 0
    n.pjob.Stock.ExtZneg = 10
    for k, v in (stock or {}).items():
        setattr(n.pjob.Stock, k, v)
    doc.recompute()  # ops take their stock heights when created
    n.vtc, n.etc = (Path.Tool.Controller.Create(b, tool=_tool(doc, b)) for b in ("60degree_Vbit", "5mm_Endmill"))
    for tc in (n.vtc, n.etc):
        n.pjob.Proxy.addToolController(tc)
    if tip is not None:
        n.vtc.Tool.TipDiameter = tip
    n.clr = op_clearance.Create("VCarveClearance", parentJob=n.pjob, tc=n.etc)
    n.plug = op_plug.Create("VCarvePlug", parentJob=n.pjob)
    n.plug.ToolController = n.vtc
    n.plug.PocketOp = n.vc
    n.clr.VCarveOp = n.plug
    n.plug.RidgePass = ridge
    if stepdown is not None:
        for op in (n.pocket_clr, n.vc, n.clr, n.plug):
            _set_stepdown(op, stepdown)
    if "StepDown" in props:
        n.plug.setExpression("StepDown", None)
    for k, v in props.items():
        setattr(n.plug, k, v)
    doc.recompute()
    return n


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
            raise AssertionError(f"{op.Label}: arcs are not simulated")
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
            c = q[i:i + chunk]
            lo, hi = np.searchsorted(mid[:, 0], [c[:, 0].min() - rmax, c[:, 0].max() + rmax])
            m = np.arange(lo, hi)
            m = m[(mid[m, 1] >= c[:, 1].min() - rmax) & (mid[m, 1] <= c[:, 1].max() + rmax)]
            if not len(m):
                continue
            out[i:i + chunk] = np.minimum(out[i:i + chunk], _lowest(c, a[m], b[m], radius, tip, slope).min(axis=1))
    return out


def seated(n, points, centre) -> SimpleNamespace:
    """Pocket z, plug depth s at the mirrored point, and the seated gap at each board point.
    gap = (-P + G + s(q')) - z_pocket(q); negative means the parts collide."""
    q = np.asarray(points, float)
    m = q.copy()
    axis = 0 if n.plug.MirrorAxis == "X" else 1
    m[:, axis] = 2 * centre[axis] - q[:, axis]
    z = cut_height(op_paths(n.vc, n.pocket_clr, top=n.vc.StartDepth.Value), q)
    s = -cut_height(op_paths(n.plug, n.clr, top=n.plug.StartDepth.Value), m)
    return SimpleNamespace(z=z, s=s, gap=(-n.P + n.G + s) - z)
