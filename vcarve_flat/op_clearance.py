# SPDX-License-Identifier: LGPL-2.1-or-later
"""V-Carve Clearance operation: clears the flat floor of a linked V-carve op with an end mill."""
import FreeCAD as App
import Path
import Path.Base.SetupSheet as PathSetupSheet
import Path.Op.Base as PathOp

from . import observer, op_vcarve, progress
from .clearing import pocket_polylines, rest_region
from .compat import tool_shape
from .geom import order_paths
from .sketches import SketchError
from .toolpath import paths_to_commands

_GROUP = "V-Carve"
_PROPS = [  # (type, name, default, tooltip)
    ("App::PropertyPercent", "StepOver", 40, "Stepover as a percentage of the tool diameter"),
    ("App::PropertyLength", "Allowance", op_vcarve.mm(0), "Distance kept from the floor boundary"),
    ("App::PropertyBool", "RestOnly", False,
     "Clear only what the clearance ops before this one (same V-carve op) could not reach"),
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
        return (PathOp.FeatureTool | PathOp.FeatureHeights | PathOp.FeatureDepths | PathOp.FeatureStepDown
                | PathOp.FeatureNoFinalDepth | PathOp.FeatureCoolant)

    def initOperation(self, obj):
        obj.addProperty("App::PropertyLink", "VCarveOp", _GROUP, "The V-Carve operation whose floor is cleared")
        obj.addProperty("App::PropertyEnumeration", "PocketPattern", _GROUP, "Clearing pattern")
        obj.PocketPattern = ["Offset", "ZigZag"]
        obj.PocketPattern = "Offset"
        self._add_properties(obj)
        obj.setEditorMode("StepDown", 2)  # unused: the levels come from the linked op

    def _add_properties(self, obj):
        """The _PROPS and RestChain that obj lacks (all when created, the newer ones in older documents)."""
        for typ, name, value, tip in _PROPS:
            if not hasattr(obj, name):
                obj.addProperty(typ, name, _GROUP, tip)
                setattr(obj, name, value)
        if not hasattr(obj, "RestChain"):
            obj.addProperty("App::PropertyString", "RestChain", _GROUP,
                            "End mills and allowances of the clearance ops before this one (internal)")
        obj.setEditorMode("RestChain", 2)

    def opSetDefaultValues(self, obj, job):
        self.opUpdateDepths(obj)

    def opUpdateDepths(self, obj):
        link = getattr(obj, "VCarveOp", None)
        if link is None or not op_vcarve._is_vbit_tc(link):
            return
        levels = link.Proxy.levels(link)
        if not levels:
            return
        obj.OpStartDepth = link.OpStartDepth.Value
        obj.OpFinalDepth = levels[-1].z_top - levels[-1].depth

    def opOnDocumentRestored(self, obj):
        self._prev_link = obj.VCarveOp.Name if obj.VCarveOp else None
        self._add_properties(obj)
        obj.setEditorMode("StepDown", 2)

    def opOnChanged(self, obj, prop):
        # Fires during creation and restore, before the properties exist. RestOnly is left out: it changes
        # neither the V-carve op's rest area nor the later ops' (see chain_key).
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
        with progress.op_task(self, obj):
            self._clear(obj)

    def _clear(self, obj):
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
        levels = link.Proxy.levels(link)
        if not levels:
            return  # the linked op logs why
        if not levels[-1].flat:
            Path.Log.info(f"{obj.Label}: the linked V-Carve operation has no Flat Depth, nothing to clear")
            return
        cops = op_vcarve.clearance_ops(link)
        i = cops.index(obj) if obj in cops else len(cops)
        before = cops[:i]
        if link.Active and link.RestChain != op_vcarve.chain_key(cops):
            # An end mill of the chain changed (e.g. its diameter) after the V-carve op computed its rest
            # area. Touched during a recompute, FreeCAD recomputes it (and this op) again in the same call.
            link.touch()
        for j in range(i + 1, len(cops)):  # the later ops' rest areas depend on this op's end mill
            if cops[j].RestChain != op_vcarve.chain_key(cops[:j]):
                cops[j].touch()
        key = op_vcarve.chain_key(before)
        if obj.RestChain != key:
            obj.RestChain = key
        tc = obj.ToolController
        diameter = tc.Tool.Diameter.Value
        error = link.Proxy.end_mill_error(link, diameter)
        if error:
            Path.Log.error(f"{obj.Label}: {error}")
            return
        radius = diameter / 2
        stepover = obj.StepOver / 100 * diameter
        tools = op_vcarve.chain_tools(before) if obj.RestOnly else []
        if obj.RestOnly and not tools:
            Path.Log.warning(f"{obj.Label}: Rest Only is set but there is no clearance op before it on "
                             f"{link.Label}, so it clears the whole floor")
        elif tools and radius >= min(r for r, _ in tools):
            Path.Log.warning(f"{obj.Label}: its end mill ({diameter:g} mm) is not smaller than every end mill "
                             f"before it on {link.Label}, so it clears little or nothing")
        by_level = [[] for _ in levels]
        for label, faces in link.Proxy.regions(link):
            if isinstance(faces, SketchError):
                continue  # the V-carve op logs it
            cut = []
            try:
                for cs in levels:
                    progress.step()
                    cut.append(pocket_polylines(rest_region(link.Proxy.floor(link, cs, faces), tools, radius,
                                                            obj.Allowance.Value),
                                                radius, stepover, obj.PocketPattern, obj.Allowance.Value,
                                                cs.z_top - cs.depth, link.Discretize))
            except progress.Cancelled:
                raise
            except Exception as exc:
                Path.Log.error(f"{label}: end mill floor clearing failed ({exc})")
                continue
            for paths, level in zip(by_level, cut):
                paths += level
        paths, pos = [], (0.0, 0.0)
        for level in by_level:
            level = order_paths(level, pos)
            if level:
                pos = level[-1][-1, :2]
            paths += level
        if not paths:
            Path.Log.warning(f"{obj.Label}: no floor reachable by the end mill")
            return
        self.commandlist.extend(paths_to_commands(paths, obj.SafeHeight.Value,
                                                  obj.ClearanceHeight.Value, tc.HorizFeed.Value,
                                                  tc.VertFeed.Value))


def SetupProperties():
    return ["StepOver", "PocketPattern", "Allowance", "RestOnly"]


def Create(name, obj=None, parentJob=None, tc=None):
    """Create(name) ... create and return a V-Carve Clearance operation."""
    if obj is None:
        obj = App.ActiveDocument.addObject("Path::FeaturePython", name)
    obj.Proxy = ObjectVCarveClearance(obj, name, parentJob, tc)
    if tc is not None and obj.ToolController != tc:  # ObjectOp starts with the previous op's controller
        obj.ToolController = tc
        obj.OpToolDiameter = tc.Tool.Diameter
    return obj


def _first_tc(job, shape, message):
    tc = next((t for t in job.Tools.Group if tool_shape(t.Tool) == shape), None)
    if tc is None:
        raise ValueError(message)
    return tc


def create_pair(job, vtc=None, etc=None, vcarve_create=op_vcarve.Create, name="VCarveFlat"):
    """Create (clearance op, V-carve op) in job, clearance first, linked. Adds no bases.
    vtc and etc default to the job's first V-bit and end mill controllers."""
    vtc = vtc or _first_tc(job, "VBit", "Add a V-bit tool controller to the job")
    etc = etc or _first_tc(job, "Endmill", "Add an end mill tool controller to the job")
    clearance = Create("VCarveClearance", parentJob=job, tc=etc)
    vcarve = vcarve_create(name, parentJob=job)
    vcarve.ToolController = vtc
    clearance.VCarveOp = vcarve
    clearance.Proxy.opUpdateDepths(clearance)
    return clearance, vcarve


PathSetupSheet.RegisterOperation("VCarveClearance", Create, SetupProperties)
observer.install()
