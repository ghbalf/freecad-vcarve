# SPDX-License-Identifier: LGPL-2.1-or-later
"""V-Carve (flat depth) CAM operation: listed sketches -> V-bit toolpaths."""
from dataclasses import dataclass

import FreeCAD as App
import numpy as np
import Path
import Path.Op.Base as PathOp
import PathScripts.PathUtils as PathUtils

from .clearing import offset_faces, pocket_polylines, subtract, swept_faces
from .compat import tool_shape
from .geom import VBit, distances_to_segments, flat_radius, limit_depth, order_paths, rest_stepover
from .medial import boundary_segments, carve_polylines, flat_boundary_loops
from .sketches import SketchError, faces_from_loops, is_sketch_base, loops_for_base, sketch_label
from .toolpath import paths_to_commands

_GROUP = "V-Carve"
MIN_REST_TOOL_RADIUS = 0.01  # mm; Path.Area rejects radius 0 and gets noisy far below this
_PROPS = [  # (type, name, default, tooltip)
    ("App::PropertyLength", "FlatDepth", 0.0,
     "Depth of the flat floor below Start Depth (0 = carve as deep as the V-bit cone allows)"),
    ("App::PropertyFloat", "Discretize", 0.01, "Deflection used to discretize curves"),
    ("App::PropertyFloat", "Colinear", 10.0, "Angle (degrees) below which medial-axis segments count as colinear"),
    ("App::PropertyLength", "StepLength", 0.5, "Sampling distance along the medial axis"),
    ("App::PropertyLength", "Tolerance", 0.01, "Simplification tolerance of the toolpath"),
    ("App::PropertyLength", "RestScallop", 0.05,
     "Allowed scallop height where the V-bit clears floor the end mill cannot reach"),
]


@dataclass
class CarveSetup:
    vbit: VBit
    z_top: float
    depth: float
    r_flat: float
    capped: bool


def carve_setup(obj) -> CarveSetup:
    t = obj.ToolController.Tool
    vbit = VBit(t.Diameter.Value, t.CuttingEdgeAngle.Value, t.TipDiameter.Value)
    flat = obj.FlatDepth.Value
    depth, capped = limit_depth(vbit, flat)
    return CarveSetup(vbit, obj.StartDepth.Value, depth, flat_radius(vbit, depth) if flat > 0 else 0.0, capped)


def region_sets(obj) -> list:
    """[(sketch label, faces | SketchError)] for each BaseShapes sketch and each Base sketch."""
    entries = [(b, None) for b in obj.BaseShapes]
    whole = {b.Name for b in obj.BaseShapes}
    grouped = {}
    for base, subs in obj.Base:
        if base.Name not in whole:  # a whole sketch already covers its edge selections
            grouped.setdefault(base.Name, (base, []))[1].extend(subs)
    out = []
    for base, subs in entries + list(grouped.values()):
        label = sketch_label(base)
        try:
            out.append((label, faces_from_loops(label, loops_for_base(base, subs))))
        except SketchError as err:
            out.append((label, err))
        except Exception as err:
            out.append((label, SketchError(f"{label}: {err}")))
    return out


def find_clearance_op(obj):
    """The clearance op linked to obj (duck-typed on its VCarveOp property), or None."""
    job = PathUtils.findParentJob(obj)
    return next((op for op in (job.Operations.Group if job else [])
                 if getattr(op, "VCarveOp", None) == obj), None)


def _rest_pocket(obj, cs, faces, cop):
    floor = offset_faces(faces, -cs.r_flat)
    if cop:
        floor = subtract(floor, swept_faces(floor, cop.ToolController.Tool.Diameter.Value / 2,
                                            cop.Allowance.Value))
    return pocket_polylines(floor, max(cs.vbit.tip_radius, MIN_REST_TOOL_RADIUS),
                            rest_stepover(cs.vbit, obj.RestScallop.Value), "Offset", 0,
                            cs.z_top - cs.depth, obj.Discretize)


def _carve(obj, cs, label, faces, cop):
    """(rest pocket, medial, boundary loops, wider-than-bit) polylines for one sketch's faces.
    A rest-pocket failure is logged and does not drop the medial and boundary paths."""
    deflection, tol = obj.Discretize, obj.Tolerance.Value
    medial, loops, wide = [], [], False
    for face in faces:
        paths = carve_polylines(face, cs.vbit, cs.z_top, cs.depth, deflection=deflection,
                                colinear_deg=obj.Colinear, step=obj.StepLength.Value, tol=tol,
                                boundary_pass=False)
        medial += paths
        if cs.r_flat > 0:
            loops += flat_boundary_loops(face, cs.vbit, cs.z_top, cs.depth, deflection=deflection, tol=tol)
        elif paths:
            dist = distances_to_segments(np.vstack(paths)[:, :2], boundary_segments(face, deflection))
            wide = wide or dist.max() > cs.vbit.radius
    rest = []
    if cs.r_flat > 0:
        try:
            rest = _rest_pocket(obj, cs, faces, cop)
        except Exception as exc:
            Path.Log.error(f"{label}: V-bit floor clearing failed ({exc})")
    return rest, medial, loops, wide


def _is_vbit_tc(obj) -> bool:
    return bool(obj.ToolController) and tool_shape(obj.ToolController.Tool) == "VBit"


class ObjectVCarveFlat(PathOp.ObjectOp):
    def opFeatures(self, obj):
        return (PathOp.FeatureTool | PathOp.FeatureHeights | PathOp.FeatureDepths
                | PathOp.FeatureNoFinalDepth | PathOp.FeatureBaseEdges | PathOp.FeatureCoolant)

    def initOperation(self, obj):
        obj.addProperty("App::PropertyLinkList", "BaseShapes", _GROUP, "Whole sketches to carve")
        for typ, name, value, tip in _PROPS:
            obj.addProperty(typ, name, _GROUP, tip)
            setattr(obj, name, value)
        self.opOnDocumentRestored(obj)

    def opOnDocumentRestored(self, obj):
        obj.setEditorMode("BaseShapes", 2)  # hidden; edited through the base list

    def opSetDefaultValues(self, obj, job):
        if job and job.Model.Group:
            obj.OpStartDepth = job.Proxy.modelBoundBox(job).ZMax
        self.opUpdateDepths(obj)

    def opUpdateDepths(self, obj):
        # The base class resets OpStartDepth to the stock top; carving starts at the model top.
        job = PathUtils.findParentJob(obj)
        if job and job.Model.Group:
            obj.OpStartDepth = job.Proxy.modelBoundBox(job).ZMax
        if _is_vbit_tc(obj):
            obj.OpFinalDepth = obj.OpStartDepth.Value - carve_setup(obj).depth  # display only

    def opRejectAddBase(self, obj, base, sub):
        return not is_sketch_base(base)

    def isToolSupported(self, obj, tool):
        return tool_shape(tool) == "VBit"

    def opExecute(self, obj):
        if not _is_vbit_tc(obj):
            Path.Log.error(f"{obj.Label}: the tool controller must use a V-bit")
            return
        sets = region_sets(obj)
        if not sets:
            Path.Log.warning(f"{obj.Label}: no sketches selected, nothing to cut")
            return
        cs = carve_setup(obj)
        if cs.capped:
            Path.Log.warning(f"{obj.Label}: Flat Depth {obj.FlatDepth.Value:g} mm is deeper than the "
                             f"V-bit cone, using {cs.depth:.3f} mm")
        cop = find_clearance_op(obj) if cs.r_flat > 0 else None
        groups = [[], [], []]  # rest pocket, medial axis, flat-boundary loops
        for label, faces in sets:
            if isinstance(faces, SketchError):
                Path.Log.error(str(faces))
                continue
            try:
                *parts, wide = _carve(obj, cs, label, faces, cop)
            except Exception as exc:
                Path.Log.error(f"{label}: carving failed ({exc})")
                continue
            for group, paths in zip(groups, parts):
                group += paths
            if wide:
                Path.Log.warning(f"{label}: areas wider than the V-bit; set Flat Depth to clear them")
        if groups[0] and cop is None:
            Path.Log.warning(f"{obj.Label}: no V-Carve Clearance op, so the V-bit is clearing the whole "
                             "floor (slow); add a V-Carve Clearance op with an end mill")
        ordered, pos = [], (0.0, 0.0)
        for group in groups:
            group = order_paths(group, pos)
            if group:
                pos = group[-1][-1, :2]
            ordered += group
        tc = obj.ToolController
        self.commandlist.extend(paths_to_commands(ordered, obj.SafeHeight.Value, obj.ClearanceHeight.Value,
                                                  tc.HorizFeed.Value, tc.VertFeed.Value))


def SetupProperties():
    return [name for _, name, _, _ in _PROPS]


def Create(name, obj=None, parentJob=None):
    """Create(name) ... create and return a V-Carve (flat depth) operation."""
    if obj is None:
        obj = App.ActiveDocument.addObject("Path::FeaturePython", name)
    obj.Proxy = ObjectVCarveFlat(obj, name, parentJob)
    return obj
