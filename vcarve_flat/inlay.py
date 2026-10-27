# SPDX-License-Identifier: LGPL-2.1-or-later
"""create_inlay: sets up a V-carve inlay, a pocket Job and a plug Job, each with its pair."""
import Path.Main.Job
import Path.Main.Stock as PathStock
import Path.Tool.Controller

from . import op_clearance, op_plug
from .compat import tool_shape
from .geom import surface_gap
from .op_vcarve import tool_vbit
from .sketches import sketch_of

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


def _new_job(src, sketch, label, tcs):
    """A Job for sketch with copies of tcs; returns it and the copies."""
    doc = src.Document
    job = Path.Main.Job.Create("Job", [sketch], None)  # the CAM simulators list only names Job*
    job.Label = label
    for tc in list(job.Tools.Group):  # the default one; onDelete removes its tool bit, as the GUI does
        tc.Proxy.onDelete(tc)
        doc.removeObject(tc.Name)
    copies = [_copy_tc(doc, tc) for tc in tcs]
    for tc in copies:
        job.Proxy.addToolController(tc)
    return job, copies


def _add_rest(job, pair, tc):
    """A RestOnly clearance op for pair's V-carve op, right after its clearance op."""
    clr, carve = pair
    rest = op_clearance.Create("VCarveClearance", parentJob=job, tc=tc)
    rest.VCarveOp, rest.RestOnly = carve, True
    rest.Proxy.opUpdateDepths(rest)
    ops = [o for o in job.Operations.Group if o != rest]
    ops.insert(ops.index(clr) + 1, rest)
    job.Operations.Group = ops
    return rest


def create_inlay(job, sketch, vtc, etc, pocket_depth, glue_gap, boundary="Margin", ridge=True, stepdown=1.5,
                 rest_etc=None):
    """Create a pocket Job "<sketch> Pocket" with the stock of job and a plug Job "<sketch> Plug", each with
    copies of vtc and etc and its pair; job itself is left as it is. sketch is a sketch or a Job's clone of
    one. With rest_etc, a smaller end mill, each Job also gets a RestOnly clearance op with a copy of it, right
    after the first clearance op. Returns (pocket_job, pocket_pair, plug_job, plug_pair), each pair being (clearance, V-carve or plug op)."""
    _check_tc(vtc, "VBit", "V-bit")
    _check_tc(etc, "Endmill", "end mill")
    if rest_etc is not None:
        _check_tc(rest_etc, "Endmill", "rest end mill")
        if rest_etc.Tool.Diameter >= etc.Tool.Diameter:
            raise ValueError("The rest end mill must be smaller than the end mill")
    original = sketch_of(sketch)
    if original is None:
        raise ValueError(f"'{sketch.Label}' is not a sketch")
    doc = job.Document
    rests = [rest_etc] if rest_etc else []
    vbit = tool_vbit(vtc)

    qjob, qtcs = _new_job(job, original, f"{original.Label} Pocket", (vtc, etc, *rests))
    whole_base = PathStock.StockType.FromStock(job.Stock) == PathStock.StockType.FromBase
    stock = qjob.Stock  # a model-based stock follows the model; the placement only matters for the others
    qjob.Stock = PathStock.CreateFromTemplate(qjob, PathStock.TemplateAttributes(job.Stock, includePlacement=not whole_base))
    doc.removeObject(stock.Name)
    pjob, ptcs = _new_job(job, original, f"{original.Label} Plug", (vtc, etc, *rests))
    pjob.Stock.ExtZpos = 0
    doc.recompute()  # the ops take their stock heights when created

    pocket = op_clearance.create_pair(qjob, *qtcs[:2])
    pocket[1].BaseShapes = list(qjob.Model.Group)
    pocket[1].FlatDepth = pocket_depth
    plug_pair = op_clearance.create_pair(pjob, *ptcs[:2], vcarve_create=op_plug.Create, name="VCarvePlug")
    clr, plug = plug_pair
    plug.PocketOp = pocket[1]
    plug.GlueGap = glue_gap
    plug.SurfaceGap = surface_gap(vbit, pocket_depth, glue_gap)
    plug.PlugBoundary = boundary
    plug.RidgePass = ridge
    clr.Proxy.opUpdateDepths(clr)
    rest_ops = [_add_rest(j, pair, tcs[2]) for j, pair, tcs in ((qjob, pocket, qtcs), (pjob, plug_pair, ptcs)) if rests]
    for op in (*pocket, *plug_pair, *rest_ops):
        _stepdown(op, stepdown)
    doc.recompute()
    # the board's thickness, but deep enough for the plug (Job.Create leaves 1 mm below the sketch)
    floor = min(op.FinalDepth.Value for op in plug_pair)
    pjob.Stock.ExtZneg = max(job.Stock.Shape.BoundBox.ZLength, pjob.Stock.Shape.BoundBox.ZMax - floor + 1)
    doc.recompute()
    return qjob, pocket, pjob, plug_pair
