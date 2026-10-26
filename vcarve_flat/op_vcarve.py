# SPDX-License-Identifier: LGPL-2.1-or-later
"""V-Carve (flat depth) CAM operation: listed sketches -> V-bit toolpaths."""
from dataclasses import dataclass

import FreeCAD as App
import numpy as np
import Path
import Path.Base.SetupSheet as PathSetupSheet
import Path.Op.Base as PathOp
import PathScripts.PathUtils as PathUtils

from .clearing import offset_faces, pocket_polylines, rest_faces
from .compat import tool_shape
from .geom import (VBit, distances_to_segments, flat_radius, limit_depth, order_paths, pass_depths,
                   rest_stepover)
from .medial import boundary_segments, carve_polylines, flat_boundary_loops
from .sketches import SketchError, faces_from_loops, is_sketch_base, loops_for_base, sketch_label
from .toolpath import paths_to_commands

_GROUP = "V-Carve"
MIN_REST_TOOL_RADIUS = 0.01  # mm; Path.Area rejects radius 0 and gets noisy far below this


def mm(value) -> App.Units.Quantity:
    """A length default: the setup sheet's op prototype stores it as given and must get a Quantity."""
    return App.Units.Quantity(value, App.Units.Length)


_PROPS = [  # (type, name, default, tooltip)
    ("App::PropertyLength", "FlatDepth", mm(0),
     "Depth of the flat floor below Start Depth (0 = carve as deep as the V-bit cone allows)"),
    ("App::PropertyFloat", "Discretize", 0.01, "Deflection used to discretize curves"),
    ("App::PropertyFloat", "Colinear", 10.0, "Angle (degrees) below which medial-axis segments count as colinear"),
    ("App::PropertyLength", "StepLength", mm(0.5), "Sampling distance along the medial axis"),
    ("App::PropertyLength", "Tolerance", mm(0.01), "Simplification tolerance of the toolpath"),
    ("App::PropertyLength", "RestScallop", mm(0.05),
     "Allowed scallop height where the V-bit clears floor the end mill cannot reach"),
]


@dataclass
class CarveSetup:
    vbit: VBit
    z_top: float
    depth: float
    r_flat: float
    capped: bool
    flat: bool
    min_depth: float = 0.0


def tool_vbit(tc) -> VBit:
    t = tc.Tool
    return VBit(t.Diameter.Value, t.CuttingEdgeAngle.Value, t.TipDiameter.Value)


def carve_setup(obj) -> CarveSetup:
    vbit = tool_vbit(obj.ToolController)
    flat = obj.FlatDepth.Value > 0
    depth, capped = limit_depth(vbit, obj.FlatDepth.Value)
    return CarveSetup(vbit, obj.StartDepth.Value, depth, flat_radius(vbit, depth) if flat else 0.0, capped, flat)


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
        if not is_sketch_base(base):
            out.append((label, SketchError(f"{label}: not a sketch, only sketches can be carved")))
            continue
        try:
            out.append((label, faces_from_loops(label, loops_for_base(base, subs))))
        except SketchError as err:
            out.append((label, err))
        except Exception as err:
            out.append((label, SketchError(f"{label}: {err}")))
    return out


def clearance_ops(obj) -> list:
    """The active clearance ops linked to obj (duck-typed on their VCarveOp property)."""
    job = PathUtils.findParentJob(obj)
    return [op for op in (job.Operations.Group if job else [])
            if getattr(op, "VCarveOp", None) == obj and getattr(op, "Active", True)]


def find_clearance_op(obj):
    """The first active clearance op linked to obj, or None."""
    return next(iter(clearance_ops(obj)), None)


def rest_clearance(cop) -> App.Vector:
    """(end mill radius, allowance, 0) that the V-bit rest area leaves to cop; zero without one."""
    if cop is None or cop.ToolController is None:
        return App.Vector()
    return App.Vector(cop.ToolController.Tool.Diameter.Value / 2, cop.Allowance.Value, 0)


def _rest_pocket(obj, cs, faces, rc):
    floor = obj.Proxy.floor(obj, cs, faces)
    if rc.x > 0:
        floor = rest_faces(floor, rc.x, rc.y)
    return pocket_polylines(floor, max(cs.vbit.tip_radius, MIN_REST_TOOL_RADIUS),
                            rest_stepover(cs.vbit, obj.RestScallop.Value), "Offset", 0,
                            cs.z_top - cs.depth, obj.Discretize)


def _carve(obj, cs, label, faces, rc):
    """(rest pocket, medial, boundary loops, wider-than-bit) polylines for one sketch's faces.
    A rest-pocket failure is logged and does not drop the medial and boundary paths."""
    deflection, tol = obj.Discretize, obj.Tolerance.Value
    medial, loops, wide = [], [], False
    for face in faces:
        paths = carve_polylines(face, cs.vbit, cs.z_top, cs.depth, deflection=deflection,
                                colinear_deg=obj.Colinear, step=obj.StepLength.Value, tol=tol,
                                drop_floor=cs.flat, min_depth=cs.min_depth)
        medial += paths
        if cs.flat:
            loops += obj.Proxy.wall_loops(obj, cs, face)
        elif paths:
            dist = distances_to_segments(np.vstack(paths)[:, :2], boundary_segments(face, deflection))
            wide = wide or dist.max() > cs.vbit.radius
    rest = []
    if cs.flat:
        try:
            rest = _rest_pocket(obj, cs, faces, rc)
        except Exception as exc:
            Path.Log.error(f"{label}: V-bit floor clearing failed ({exc})")
    return rest, medial, loops, wide


def _carve_levels(obj, levels, label, faces, rc) -> list:
    """_carve at each level; without a flat floor, stops after the first level that clamps nothing
    (the deeper ones would repeat it)."""
    out = []
    for cs in levels:
        out.append(_carve(obj, cs, label, faces, rc))
        if not cs.flat and not any(p[:, 2].min() <= cs.z_top - cs.depth + 1e-6 for p in out[-1][1]):
            break
    return out


def is_tool_controller(tc) -> bool:
    # The property editor lets ToolController link any object, e.g. the tool bit itself.
    return hasattr(tc, "Tool") and hasattr(tc, "ToolNumber")


def check_tool_controller(obj):
    """Log an error, naming the right TC when there is one, if ToolController is not a tool controller."""
    tc = obj.ToolController
    if tc is None or is_tool_controller(tc):
        return
    job = PathUtils.findParentJob(obj)
    owner = next((t for t in (job.Tools.Group if job else []) if getattr(t, "Tool", None) == tc), None)
    hint = f"pick its tool controller {owner.Label}" if owner else "pick a tool controller"
    Path.Log.error(f"{obj.Label}: {tc.Label} is not a tool controller, {hint}")


def _is_vbit_tc(obj) -> bool:
    tc = getattr(obj, "ToolController", None)  # None too for a VCarveOp link to a non-op object
    return is_tool_controller(tc) and tool_shape(tc.Tool) == "VBit"


class ObjectVCarveFlat(PathOp.ObjectOp):
    # The interface the clearance op and opExecute get their geometry through; the plug op overrides it.
    def regions(self, obj) -> list:
        return region_sets(obj)

    def levels(self, obj) -> list:
        """One CarveSetup per step-down pass, shallowest first; only the last one may be capped."""
        cs = carve_setup(obj)
        depths = pass_depths(cs.depth, obj.StepDown.Value)
        return [CarveSetup(cs.vbit, cs.z_top, d, flat_radius(cs.vbit, d) if cs.flat else 0.0,
                           cs.capped and i == len(depths) - 1, cs.flat) for i, d in enumerate(depths)]

    def floor(self, obj, cs, faces) -> list:
        """The V-bit tool-centre floor of level cs."""
        return offset_faces(faces, -cs.r_flat)

    def wall_loops(self, obj, cs, face) -> list:
        return flat_boundary_loops(face, cs.vbit, cs.z_top, cs.depth, deflection=obj.Discretize,
                                   tol=obj.Tolerance.Value)

    def extra_paths(self, obj) -> list:
        """V-bit paths cut after all levels."""
        return []

    def end_mill_error(self, obj, diameter):
        """Why an end mill of this diameter cannot clear the floor, or None."""
        return None

    def opFeatures(self, obj):
        return (PathOp.FeatureTool | PathOp.FeatureHeights | PathOp.FeatureDepths | PathOp.FeatureStepDown
                | PathOp.FeatureNoFinalDepth | PathOp.FeatureBaseEdges | PathOp.FeatureCoolant)

    def initOperation(self, obj):
        obj.addProperty("App::PropertyLinkList", "BaseShapes", _GROUP, "Whole sketches to carve")
        for typ, name, value, tip in _PROPS:
            obj.addProperty(typ, name, _GROUP, tip)
            setattr(obj, name, value)
        self.opOnDocumentRestored(obj)

    def opOnDocumentRestored(self, obj):
        if not hasattr(obj, "RestClearance"):  # documents saved before it existed
            obj.addProperty("App::PropertyVectorDistance", "RestClearance", _GROUP,
                            "End mill radius and allowance the rest area was computed for (internal)")
        obj.setEditorMode("BaseShapes", 2)  # hidden; edited through the base list
        obj.setEditorMode("RestClearance", 2)

    def opSetDefaultValues(self, obj, job):
        if job and job.Model.Group:
            obj.OpStartDepth = job.Proxy.modelBoundBox(job).ZMax
        self.opUpdateDepths(obj)

    def opUpdateDepths(self, obj):
        # The base class resets OpStartDepth to the stock top; carving starts at the model top.
        job = PathUtils.findParentJob(obj)
        if job and job.Model.Group:
            obj.OpStartDepth = job.Proxy.modelBoundBox(job).ZMax
        levels = self.levels(obj) if _is_vbit_tc(obj) else []
        if levels:
            obj.OpFinalDepth = levels[-1].z_top - levels[-1].depth  # display only

    def opOnChanged(self, obj, prop):
        if prop == "ToolController" and "Restore" not in obj.State:
            check_tool_controller(obj)

    def opRejectAddBase(self, obj, base, sub):
        return not is_sketch_base(base)

    def isToolSupported(self, obj, tool):
        return tool_shape(tool) == "VBit"

    def opExecute(self, obj):
        if not _is_vbit_tc(obj):
            Path.Log.error(f"{obj.Label}: the tool controller must use a V-bit")
            return
        levels = self.levels(obj)
        if not levels:
            return
        last = levels[-1]
        # Stored before any early return: the clearance op compares it with its own tool and
        # touches this op on a mismatch (it has no other way to know the end mill changed).
        cops = clearance_ops(obj) if last.flat else []
        cop = cops[0] if cops else None
        if len(cops) > 1:
            Path.Log.warning(f"{obj.Label}: several active V-Carve Clearance ops link this op; the V-bit "
                             f"rest area is computed for {cop.Label} only")
        rc = rest_clearance(cop)
        if obj.RestClearance != rc:
            obj.RestClearance = rc
        sets = self.regions(obj)
        if not sets:
            Path.Log.warning(f"{obj.Label}: no sketches selected, nothing to cut")
            return
        if last.capped:
            Path.Log.warning(f"{obj.Label}: Flat Depth {obj.FlatDepth.Value:g} mm is deeper than the "
                             f"V-bit cone, using {last.depth:.3f} mm")
        groups = [[[], [], []] for _ in levels]  # per level: rest pocket, medial axis, flat-boundary loops
        for label, faces in sets:
            if isinstance(faces, SketchError):
                Path.Log.error(str(faces))
                continue
            try:
                carved = _carve_levels(obj, levels, label, faces, rc)
            except Exception as exc:
                Path.Log.error(f"{label}: carving failed ({exc})")
                continue
            for level, (*parts, _) in zip(groups, carved):
                for group, paths in zip(level, parts):
                    group += paths
            if any(wide for *_, wide in carved):
                Path.Log.warning(f"{label}: areas wider than the V-bit; set Flat Depth to clear them")
        if any(level[0] for level in groups) and cop is None:
            Path.Log.warning(f"{obj.Label}: no V-Carve Clearance op, so the V-bit is clearing the whole "
                             "floor (slow); add a V-Carve Clearance op with an end mill")
        ordered, pos = [], (0.0, 0.0)
        for group in [g for level in groups for g in level] + [self.extra_paths(obj)]:
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


PathSetupSheet.RegisterOperation("VCarveFlat", Create, SetupProperties)
