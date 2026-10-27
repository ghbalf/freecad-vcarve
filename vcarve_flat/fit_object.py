# SPDX-License-Identifier: LGPL-2.1-or-later
"""The Fit object: the marks of a Check Inlay Fit run, kept (never re-simulated) until the checked paths change."""
import FreeCAD as App
import numpy as np
import Part
import Path
import PathScripts.PathUtils as PathUtils

from . import fit, progress
from .op_plug import ObjectVCarvePlug
from .sketches import sketch_label

LIFT = 0.01  # mm: the marks lie just above the pocket's top, so the stock does not hide them
OUTDATED = "outdated: run Check Inlay Fit"
SEAM = 0.004  # of the grid: each square's overlap with its neighbours


def _squares(points, grid, z):
    """The union of grid-sized squares centred on points (on a grid), as a compound of faces at z."""
    if not len(points):
        return Part.makeCompound([])
    lo = points.min(axis=0)
    ij = np.round((points - lo) / grid).astype(int)
    ij = ij[np.lexsort(ij.T)]  # by row, then column; each run of a row becomes one rectangle
    starts = np.flatnonzero(np.r_[True, (np.diff(ij[:, 1]) != 0) | (np.diff(ij[:, 0]) != 1)])
    # Grown a little: squares touching only at a corner make Path.Area drop or invert whole regions
    e = SEAM * grid
    area = Path.Area()
    for s, last in zip(starts, np.r_[starts[1:], len(ij)] - 1):
        (i, j), width = ij[s], ij[last, 0] - ij[s, 0] + 1
        corner = App.Vector(lo[0] + (i - 0.5) * grid - e, lo[1] + (j - 0.5) * grid - e, z)
        area.add(Part.makePlane(width * grid + 2 * e, grid + 2 * e, corner))
    return Part.makeCompound(area.getShape().Faces)


class Fit:
    """Its links make FreeCAD recompute it after the checked ops; execute then only compares their paths."""

    def __init__(self, obj):
        for kind, name, tip in (
                ("App::PropertyLink", "PlugOp", "The checked plug op"),
                ("App::PropertyLink", "PocketOp", "Its pocket op"),
                ("App::PropertyLinkList", "ClearanceOps", "The checked clearance ops of both Jobs"),
                ("App::PropertyString", "Signature", "The checked paths' signature"),
                ("App::PropertyDistance", "WorstCollision", "The lowest seated gap where the plug hits the pocket"),
                ("App::PropertyDistance", "WorstVoid", "The widest seated gap where the plug leaves a void"),
                ("App::PropertyInteger", "Collisions", "Checked points where the plug hits the pocket (red)"),
                ("App::PropertyInteger", "Voids", "Checked points where the plug leaves a void (blue)")):
            obj.addProperty(kind, name, "Fit", tip)
        self._modes(obj)
        obj.Proxy = self

    @staticmethod
    def _modes(obj):
        obj.setEditorMode("Signature", 2)
        for name in ("WorstCollision", "WorstVoid", "Collisions", "Voids"):
            obj.setEditorMode(name, 1)

    def onDocumentRestored(self, obj):
        self._modes(obj)

    def execute(self, obj):
        ops = fit.chain(obj.PlugOp) if obj.PlugOp else []
        if not ops or fit.signature(ops) != obj.Signature:
            raise RuntimeError(OUTDATED)

    def dumps(self):
        return None

    def loads(self, state):
        return None


def create(doc, plug, result):
    """A Fit object "<sketch> Fit" showing result, the check of plug: red collision and blue void squares."""
    pocket = plug.PocketOp
    obj = doc.addObject("Part::FeaturePython", "Fit")
    Fit(obj)
    bases = [*pocket.BaseShapes, *(b for b, _ in pocket.Base)]
    obj.Label = f"{sketch_label(bases[0]) if bases else plug.Label} Fit"
    obj.PlugOp, obj.PocketOp = plug, pocket
    obj.ClearanceOps = [op for op in result.ops if op not in (plug, pocket)]
    obj.Signature = fit.signature(result.ops)
    obj.WorstCollision, obj.WorstVoid = result.worst_collision, result.worst_void
    obj.Collisions, obj.Voids = int(result.collisions.sum()), int(result.voids.sum())
    z = pocket.StartDepth.Value + LIFT
    obj.Shape = Part.makeCompound([_squares(result.points[m], result.grid, z)
                                   for m in (result.collisions, result.voids)])
    return obj


def summary(obj) -> str:
    parts = []
    if obj.Collisions:
        parts.append(f"worst collision {obj.WorstCollision.Value:.2f} mm at {obj.Collisions} spots")
    if obj.Voids:
        parts.append(f"worst void {obj.WorstVoid.Value:.2f} mm")
    return f"{obj.Label}: {', '.join(parts) or 'fits'}"


def plug_of(objs):
    """The plug op of the V-Carve Inlay that one of objs (its plug or pocket op or Job) belongs to, or None."""
    for obj in objs:
        for plug in obj.Document.Objects:
            if isinstance(getattr(plug, "Proxy", None), ObjectVCarvePlug) and plug.PocketOp is not None:
                if obj in (plug, plug.PocketOp, PathUtils.findParentJob(plug), PathUtils.findParentJob(plug.PocketOp)):
                    return plug
    return None


def run(plug, attach=None):
    """Checks plug's inlay with a progress indicator and, as one undo step, replaces its Fit object by a new
    one, then attach(it); logs the summary. On Cancel or a refused check the old one stays and None is returned."""
    try:
        with progress.task("Check Inlay Fit"):
            result = fit.check(plug)
    except progress.Cancelled:
        Path.Log.notice("Check Inlay Fit cancelled")
        return None
    if result.error:
        Path.Log.error(result.error)
        return None
    doc = plug.Document
    doc.openTransaction("Check Inlay Fit")
    try:
        for old in [o for o in doc.Objects if isinstance(getattr(o, "Proxy", None), Fit) and o.PlugOp == plug]:
            doc.removeObject(old.Name)
        obj = create(doc, plug, result)
        doc.recompute([obj])
        if attach:
            attach(obj)
    except Exception:
        doc.abortTransaction()
        raise
    doc.commitTransaction()
    (App.Console.PrintWarning if obj.Collisions or obj.Voids else App.Console.PrintMessage)(summary(obj) + "\n")
    return obj
