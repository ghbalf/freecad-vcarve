# SPDX-License-Identifier: LGPL-2.1-or-later
"""create_inlay: sets up a V-carve inlay, the pocket pair in a Job and the plug Job with its plug pair."""
import Path.Main.Job
import Path.Tool.Controller

from . import op_clearance, op_plug
from .compat import tool_shape
from .geom import surface_gap
from .op_vcarve import tool_vbit

_COPIED = ("ToolNumber", "HorizFeed", "VertFeed", "HorizRapid", "VertRapid", "SpindleSpeed", "SpindleDir")


def _check_tc(tc, shape, what):
    if tc is None or tool_shape(tc.Tool) != shape:
        raise ValueError(f"The {what} tool controller must use {'a V-bit' if shape == 'VBit' else 'an end mill'}")


def _copy_tc(doc, tc):
    new = Path.Tool.Controller.Create(tc.Label, tool=doc.copyObject(tc.Tool))
    for name in _COPIED:
        setattr(new, name, getattr(tc, name))
    return new


def _stepdown(op, value):
    op.setExpression("StepDown", None)  # else the setup sheet's expression wins on recompute
    op.StepDown = value


def create_inlay(job, sketch, vtc, etc, pocket_depth, glue_gap, boundary="Margin", ridge=True, stepdown=1.5):
    """Create the pocket pair in job and a plug Job "<sketch> Plug" with copies of vtc and etc and the
    plug pair. sketch is a sketch of job or its model clone. Returns (pocket_pair, plug_job, plug_pair),
    each pair being (clearance, V-carve or plug op)."""
    _check_tc(vtc, "VBit", "V-bit")
    _check_tc(etc, "Endmill", "end mill")
    clone = next((c for c in job.Model.Group if c is sketch or sketch in getattr(c, "Objects", ())), None)
    if clone is None:
        raise ValueError(f"The sketch {sketch.Label} is not in the Job {job.Label}")
    original = clone.Objects[0]
    doc = job.Document
    vbit = tool_vbit(vtc)

    pocket = op_clearance.create_pair(job, vtc, etc)
    pocket[1].BaseShapes = [clone]
    pocket[1].FlatDepth = pocket_depth

    pjob = Path.Main.Job.Create(f"{original.Label} Plug", [original], None)
    pjob.Label = f"{original.Label} Plug"
    for tc in list(pjob.Tools.Group):
        doc.removeObject(tc.Name)
    pjob.Stock.ExtZpos = 0
    doc.recompute()  # the ops take their stock heights when created
    ptcs = [_copy_tc(doc, tc) for tc in (vtc, etc)]
    for tc in ptcs:
        pjob.Proxy.addToolController(tc)
    plug_pair = op_clearance.create_pair(pjob, *ptcs, vcarve_create=op_plug.Create)
    clr, plug = plug_pair
    plug.PocketOp = pocket[1]
    plug.GlueGap = glue_gap
    plug.SurfaceGap = surface_gap(vbit, pocket_depth, glue_gap)
    plug.PlugBoundary = boundary
    plug.RidgePass = ridge
    clr.Proxy.opUpdateDepths(clr)
    for op in (*pocket, *plug_pair):
        _stepdown(op, stepdown)
    doc.recompute()
    return pocket, pjob, plug_pair
