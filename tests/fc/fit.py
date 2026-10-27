# SPDX-License-Identifier: LGPL-2.1-or-later
"""Inlay test helpers: build a pocket Job and a plug Job, and seat the plug on given points."""
import math
from types import SimpleNamespace

import numpy as np
import Path
import Path.Main.Job
import Path.Tool.Controller

from helpers import _tool, make_job, make_sketch
from vcarve_flat import op_clearance, op_plug
from vcarve_flat.fit import cut_height, op_paths
from vcarve_flat.geom import VBit, inlay_defaults


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
