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

SAMPLE = 0.05  # mm between resampled path points


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


def g1_points(op, top=0.0) -> np.ndarray:
    """The op's G1 moves resampled to at most SAMPLE apart, XYZ with Z relative to top."""
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
        return np.zeros((0, 3))
    a, b = np.array(a), np.array(b)
    n = np.maximum(1, np.ceil(np.linalg.norm(b - a, axis=1) / SAMPLE)).astype(int)
    seg = np.repeat(np.arange(len(a)), n)
    frac = (np.arange(n.sum()) - np.repeat(np.cumsum(n) - n, n)) / n[seg]
    pts = np.vstack([a[seg] + frac[:, None] * (b - a)[seg], b])
    return pts - [0, 0, top]


def op_paths(*ops, top=0.0) -> list:
    return [(g1_points(op, top), tool_profile(op.ToolController)) for op in ops]


def cut_height(paths_by_tool, points, chunk=256) -> np.ndarray:
    """The lowest Z the tools reach at each XY point (0 where none reaches, the uncut top).
    A V-bit's lower surface at distance rho from a path point at z_c is z_c + max(0, rho - r_t)/t
    for rho <= R."""
    q = np.asarray(points, float)[:, :2]
    out = np.zeros(len(q))
    for path, (radius, tip, slope) in paths_by_tool:
        p = path[path[:, 2] < 0]  # path points at or above the top cut nothing
        if not len(p):
            continue
        reach = np.minimum(radius, tip - p[:, 2] * slope)  # beyond it the surface is above the top
        order = np.argsort(p[:, 0])
        p, reach = p[order], reach[order]
        rmax = reach.max()
        for i in range(0, len(q), chunk):
            c = q[i:i + chunk]
            lo, hi = np.searchsorted(p[:, 0], [c[:, 0].min() - rmax, c[:, 0].max() + rmax])
            s = p[lo:hi]
            s = s[(s[:, 1] >= c[:, 1].min() - rmax) & (s[:, 1] <= c[:, 1].max() + rmax)]
            if not len(s):
                continue
            rho = np.hypot(c[:, None, 0] - s[None, :, 0], c[:, None, 1] - s[None, :, 1])
            z = np.where(rho <= radius, s[None, :, 2] + np.maximum(0, rho - tip) / slope, np.inf)
            out[i:i + chunk] = np.minimum(out[i:i + chunk], z.min(axis=1))
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
