# SPDX-License-Identifier: LGPL-2.1-or-later
"""V-Carve Clearance operation: clears the flat floor of a linked V-carve op with an end mill."""
import FreeCAD as App
import Path
import Path.Base.SetupSheet as PathSetupSheet
import Path.Op.Base as PathOp

from . import op_vcarve
from .clearing import offset_faces, pocket_polylines
from .compat import tool_shape
from .geom import order_paths
from .sketches import SketchError
from .toolpath import paths_to_commands

_GROUP = "V-Carve"
_PROPS = [  # (type, name, default, tooltip)
    ("App::PropertyPercent", "StepOver", 40, "Stepover as a percentage of the tool diameter"),
    ("App::PropertyLength", "Allowance", op_vcarve.mm(0), "Distance kept from the floor boundary"),
]


def _is_endmill_tc(obj) -> bool:
    tc = obj.ToolController
    return op_vcarve.is_tool_controller(tc) and tool_shape(tc.Tool) == "Endmill"


class ObjectVCarveClearance(PathOp.ObjectOp):
    # Class defaults: a restored document rebuilds the proxy without __init__.
    _only_tc = None
    _prev_link = None  # name of the V-carve op linked before the last VCarveOp change

    def __init__(self, obj, name, parentJob=None, tc=None):
        # While set, only tc counts as supported, so creation does not ask FreeCAD to pick among
        # several end mills (a prompt in the GUI, an UnboundLocalError headless).
        self._only_tc = tc
        super().__init__(obj, name, parentJob)
        self._only_tc = None

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

    def opOnDocumentRestored(self, obj):
        self._prev_link = obj.VCarveOp.Name if obj.VCarveOp else None

    def opOnChanged(self, obj, prop):
        # Fires during creation and restore, before the properties exist.
        if prop not in ("ToolController", "Allowance", "VCarveOp", "Active") or "Restore" in obj.State:
            return
        if prop == "ToolController":
            op_vcarve.check_tool_controller(obj)
        link = getattr(obj, "VCarveOp", None)
        if prop == "VCarveOp":  # the previous V-carve op lost its clearance op: its rest area grows
            old = obj.Document.getObject(self._prev_link) if self._prev_link else None
            if old is not None and old != link:
                old.touch()
            self._prev_link = link.Name if link else None
        if link is not None:
            link.touch()

    def isToolSupported(self, obj, tool):
        if self._only_tc is not None:
            return tool is self._only_tc.Tool
        return tool_shape(tool) == "Endmill"

    def opExecute(self, obj):
        link = obj.VCarveOp
        if link is None:
            Path.Log.info(f"{obj.Label}: no V-Carve operation linked yet")
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
        if link.Active and op_vcarve.find_clearance_op(link) == obj \
                and link.RestClearance != op_vcarve.rest_clearance(obj):
            # The end mill changed (e.g. its diameter) after the V-carve op computed its rest area.
            # Touched during a recompute, FreeCAD recomputes it (and this op) again in the same call.
            link.touch()
        cs = op_vcarve.carve_setup(link)
        tc = obj.ToolController
        radius = tc.Tool.Diameter.Value / 2
        stepover = obj.StepOver / 100 * 2 * radius
        paths = []
        for label, faces in op_vcarve.region_sets(link):
            if isinstance(faces, SketchError):
                continue  # the V-carve op logs it
            try:
                floor = offset_faces(faces, -cs.r_flat)
                paths += pocket_polylines(floor, radius, stepover, obj.PocketPattern, obj.Allowance.Value,
                                          cs.z_top - cs.depth, link.Discretize)
            except Exception as exc:
                Path.Log.error(f"{label}: end mill floor clearing failed ({exc})")
        if not paths:
            Path.Log.info(f"{obj.Label}: no floor reachable by the end mill")
            return
        self.commandlist.extend(paths_to_commands(order_paths(paths, (0.0, 0.0)), obj.SafeHeight.Value,
                                                  obj.ClearanceHeight.Value, tc.HorizFeed.Value,
                                                  tc.VertFeed.Value))


def SetupProperties():
    return ["StepOver", "PocketPattern", "Allowance"]


def Create(name, obj=None, parentJob=None, tc=None):
    """Create(name) ... create and return a V-Carve Clearance operation."""
    if obj is None:
        obj = App.ActiveDocument.addObject("Path::FeaturePython", name)
    obj.Proxy = ObjectVCarveClearance(obj, name, parentJob, tc)
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
    clearance = Create("VCarveClearance", parentJob=job, tc=etc)
    vcarve = op_vcarve.Create("VCarveFlat", parentJob=job)
    vcarve.ToolController = vtc
    clearance.VCarveOp = vcarve
    clearance.Proxy.opUpdateDepths(clearance)
    return clearance, vcarve


PathSetupSheet.RegisterOperation("VCarveClearance", Create, SetupProperties)
