# SPDX-License-Identifier: LGPL-2.1-or-later
"""V-Carve Clearance operation: clears the flat floor of a linked V-carve op with an end mill."""
from unittest import mock

import FreeCAD as App
import Path
import Path.Op.Base as PathOp
import PathScripts.PathUtils as PathUtils

from . import op_vcarve
from .clearing import offset_faces, pocket_polylines
from .compat import tool_shape
from .geom import order_paths
from .sketches import SketchError
from .toolpath import paths_to_commands

_GROUP = "V-Carve"
_PROPS = [  # (type, name, default, tooltip)
    ("App::PropertyPercent", "StepOver", 40, "Stepover as a percentage of the tool diameter"),
    ("App::PropertyLength", "Allowance", 0.0, "Distance kept from the floor boundary"),
]


def _is_endmill_tc(obj) -> bool:
    return bool(obj.ToolController) and tool_shape(obj.ToolController.Tool) == "Endmill"


class ObjectVCarveClearance(PathOp.ObjectOp):
    def opFeatures(self, obj):
        return (PathOp.FeatureTool | PathOp.FeatureHeights | PathOp.FeatureDepths
                | PathOp.FeatureNoFinalDepth | PathOp.FeatureCoolant)

    def initOperation(self, obj):
        obj.addProperty("App::PropertyLink", "VCarveOp", _GROUP, "The V-Carve operation whose floor is cleared")
        obj.addProperty("App::PropertyEnumeration", "PocketPattern", _GROUP, "Clearing pattern")
        obj.PocketPattern = ["Offset", "ZigZag"]
        obj.PocketPattern = "Offset"
        for typ, name, value, tip in _PROPS:
            obj.addProperty(typ, name, _GROUP, tip)
            setattr(obj, name, value)

    def opSetDefaultValues(self, obj, job):
        self.opUpdateDepths(obj)

    def opUpdateDepths(self, obj):
        link = getattr(obj, "VCarveOp", None)
        if link is None or not op_vcarve._is_vbit_tc(link):
            return
        obj.OpStartDepth = link.OpStartDepth.Value
        obj.OpFinalDepth = link.OpStartDepth.Value - op_vcarve.carve_setup(link).depth

    def onChanged(self, obj, prop):
        # Fires during creation and restore, before the properties exist.
        if prop in ("ToolController", "Allowance", "VCarveOp") and "Restore" not in obj.State \
                and getattr(obj, "VCarveOp", None) is not None:
            obj.VCarveOp.touch()

    def isToolSupported(self, obj, tool):
        return tool_shape(tool) == "Endmill"

    def opExecute(self, obj):
        link = obj.VCarveOp
        if link is None:
            Path.Log.error(f"{obj.Label}: no V-Carve operation linked")
            return
        if not _is_endmill_tc(obj):
            Path.Log.error(f"{obj.Label}: the tool controller must use an end mill")
            return
        if not op_vcarve._is_vbit_tc(link):
            Path.Log.error(f"{obj.Label}: the linked V-Carve operation has no V-bit tool controller")
            return
        if link.FlatDepth.Value == 0:
            Path.Log.info(f"{obj.Label}: the linked V-Carve operation has no Flat Depth, nothing to clear")
            return
        cs = op_vcarve.carve_setup(link)
        tc = obj.ToolController
        radius = tc.Tool.Diameter.Value / 2
        stepover = obj.StepOver / 100 * 2 * radius
        paths = []
        for _, faces in op_vcarve.region_sets(link):
            if isinstance(faces, SketchError):
                continue  # the V-carve op logs it
            floor = offset_faces(faces, -cs.r_flat)
            paths += pocket_polylines(floor, radius, stepover, obj.PocketPattern, obj.Allowance.Value,
                                      cs.z_top - cs.depth, link.Discretize)
        if not paths:
            Path.Log.info(f"{obj.Label}: no floor reachable by the end mill")
            return
        self.commandlist.extend(paths_to_commands(order_paths(paths, (0.0, 0.0)), obj.SafeHeight.Value,
                                                  obj.ClearanceHeight.Value, tc.HorizFeed.Value,
                                                  tc.VertFeed.Value))


def SetupProperties():
    return ["VCarveOp", "StepOver", "PocketPattern", "Allowance"]


def Create(name, obj=None, parentJob=None):
    """Create(name) ... create and return a V-Carve Clearance operation."""
    if obj is None:
        obj = App.ActiveDocument.addObject("Path::FeaturePython", name)
    obj.Proxy = ObjectVCarveClearance(obj, name, parentJob)
    return obj


def _first_tc(job, shape, message):
    tc = next((t for t in job.Tools.Group if tool_shape(t.Tool) == shape), None)
    if tc is None:
        raise ValueError(message)
    return tc


def create_pair(job):
    """Create (clearance op, V-carve op) in job, clearance first, linked. Adds no bases."""
    vtc = _first_tc(job, "VBit", "Add a V-bit tool controller to the job")
    etc = _first_tc(job, "Endmill", "Add an end mill tool controller to the job")
    # Creation asks FreeCAD for a default TC, which prompts (GUI) or fails (headless) when the job
    # has several supported ones; hand it the TC chosen here instead.
    with mock.patch.object(PathUtils, "findToolController", lambda *_a, **_k: etc):
        clearance = Create("VCarveClearance", parentJob=job)
    clearance.ToolController = etc
    vcarve = op_vcarve.Create("VCarve", parentJob=job)
    vcarve.ToolController = vtc
    clearance.VCarveOp = vcarve
    clearance.Proxy.opUpdateDepths(clearance)
    return clearance, vcarve
