# SPDX-License-Identifier: LGPL-2.1-or-later
"""V-Carve Plug operation: carves the mirrored design of a V-Carve Flat pocket op as a raised inlay plug.

The plug is v1's carving applied to the complement of the mirrored letters, from a virtual carve
surface Z_v = StartDepth - (P - G) down to the Surface Gap below it."""
import math

import FreeCAD as App
import Part
import Path
import Path.Base.SetupSheet as PathSetupSheet
import Path.Op.Base as PathOp
import PathScripts.PathUtils as PathUtils

from . import op_vcarve
from .clearing import area_offset, inside_loops, intersect, mirror_faces, subtract, union
from .geom import flat_radius, pass_depths, plug_errors
from .medial import corner_valleys, face_loops, has_narrow_gap, ridge_polylines
from .sketches import SketchError

_GROUP = "V-Carve Plug"
mm = op_vcarve.mm
_PROPS = [  # (type, name, default, tooltip)
    ("App::PropertyLength", "GlueGap", mm(0.2), "Gap between plug top and pocket floor when seated"),
    ("App::PropertyLength", "SurfaceGap", mm(1.5),
     "Gap between the plug board and the board surface when seated: the plug's flat depth below "
     "Plug Start Depth"),
    ("App::PropertyBool", "RidgePass", True,
     "Flatten the plug's ridges where they are narrower than the V-bit tip, to match the pocket "
     "grooves (no path for a pointed V-bit)"),
    ("App::PropertyLength", "PlugMargin", mm(10),
     "Margin mode: width of the flat ring cleared around the plug's footprint at the floor; less the V-bit "
     "tip radius, at least the end mill diameter"),
]
_ENUMS = [  # (name, values, tooltip); the first value is the default
    ("PlugBoundary", ["Margin", "Stock"],
     "Margin: clear a ring around the plug (saw it free there); Stock: clear the whole stock of the plug Job"),
    ("MirrorAxis", ["X", "Y"], "X: flip left-right; Y: flip front-back, about the design's bounding-box centre"),
]


def _describe(vbit) -> str:
    return f"{vbit.diameter:g} mm, {vbit.angle_deg:g}°, tip {vbit.tip_diameter:g} mm"


class ObjectVCarvePlug(op_vcarve.ObjectVCarveFlat):
    _last = None  # (C_v, B) of the last regions() call; floor() and wall_loops() clip to B

    def _checks(self, obj):
        """(errors naming this op, V-bit, start = P - G); V-bit and start are None while unknown."""
        pocket = getattr(obj, "PocketOp", None)
        if pocket is None:
            return [f"{obj.Label}: no Pocket Op linked"], None, None
        if not isinstance(getattr(pocket, "Proxy", None), op_vcarve.ObjectVCarveFlat) \
                or isinstance(pocket.Proxy, ObjectVCarvePlug):
            return [f"{obj.Label}: Pocket Op {pocket.Label} is not a V-Carve Flat operation"], None, None
        if not op_vcarve._is_vbit_tc(pocket):
            return [f"{obj.Label}: the pocket op {pocket.Label} has no V-bit tool controller"], None, None
        if pocket.FlatDepth.Value <= 0:
            return [f"{obj.Label}: the pocket op {pocket.Label} has no Flat Depth, so the pocket depth "
                    "is undefined"], None, None
        cs = op_vcarve.carve_setup(pocket)
        start = cs.depth - obj.GlueGap.Value
        if not op_vcarve._is_vbit_tc(obj):
            return [f"{obj.Label}: the tool controller must use a V-bit"], None, start
        vbit = op_vcarve.tool_vbit(obj.ToolController)
        if vbit != cs.vbit:
            return [f"{obj.Label}: its V-bit ({_describe(vbit)}) differs from the V-bit of the pocket op "
                    f"{pocket.Label} ({_describe(cs.vbit)}), so the plug would not fit"], vbit, start
        errors = plug_errors(vbit, cs.depth, obj.GlueGap.Value, obj.SurfaceGap.Value)
        return [f"{obj.Label}: {e}" for e in errors], vbit, start

    def _design(self, obj) -> list:
        """L: the pocket op's faces, united and mirrored about their bounding-box centre."""
        faces = union([f for _, fs in op_vcarve.region_sets(obj.PocketOp)
                       if not isinstance(fs, SketchError) for f in fs])
        if not faces:
            return []
        return mirror_faces(faces, obj.MirrorAxis, Part.makeCompound(faces).BoundBox.Center)

    def _bounds(self, obj, design, vbit) -> list:
        """B, the floor limit."""
        if obj.PlugBoundary == "Stock":
            bb = PathUtils.findParentJob(obj).Stock.Shape.BoundBox
            r = op_vcarve.rest_clearance(op_vcarve.find_clearance_op(obj)).x
            return [Part.makePlane(bb.XLength + 2 * r, bb.YLength + 2 * r,
                                   App.Vector(bb.XMin - r, bb.YMin - r, design[0].BoundBox.ZMin))]
        ring = area_offset(design, obj.SurfaceGap.Value * math.tan(vbit.half_angle) + obj.PlugMargin.Value)
        return union([Part.Face(f.OuterWire) for f in ring])  # a counter is the plug's, however wide

    def _limit(self, obj, faces) -> list:
        if self._last is None or not all(any(f is c for c in self._last[0]) for f in faces):
            self.regions(obj)
        return self._last[1] if self._last else []

    def regions(self, obj) -> list:
        self._last = None
        errors, vbit, _ = self._checks(obj)
        if errors:
            return []
        label = f"{obj.PocketOp.Label} plug"
        design = self._design(obj)
        if not design:
            return [(label, SketchError(f"{obj.Label}: the pocket op {obj.PocketOp.Label} has no sketch "
                                        "faces to mirror"))]
        bounds = self._bounds(obj, design, vbit)
        # Grown far enough that the outer edge's medial axis is all floor and its loops lie outside B.
        complement = subtract(area_offset(bounds, 2 * vbit.radius + 1), design)
        self._last = (complement, bounds)
        return [(label, complement)]

    def levels(self, obj) -> list:
        """Levels counted from the plug top; depths relative to Z_v, negative above it."""
        errors, vbit, start = self._checks(obj)
        if errors:
            return []
        z_v = obj.StartDepth.Value - start
        return [op_vcarve.CarveSetup(vbit, z_v, s - start, flat_radius(vbit, s - start), False, True, -start)
                for s in pass_depths(start + obj.SurfaceGap.Value, obj.StepDown.Value)]

    def floor(self, obj, cs, faces) -> list:
        return intersect(area_offset(faces, -cs.r_flat, sharp=True), self._limit(obj, faces))

    def wall_loops(self, obj, cs, face) -> list:
        loops = face_loops(area_offset([face], -cs.r_flat, sharp=True), cs.z_top - cs.depth,
                           deflection=obj.Discretize, tol=obj.Tolerance.Value)
        return inside_loops(loops, self._limit(obj, [face]))

    def extra_paths(self, obj) -> list:
        errors, vbit, start = self._checks(obj)
        if errors:
            return []
        z_v = obj.StartDepth.Value - start
        try:
            design = self._design(obj)
            paths = corner_valleys(design, vbit, z_v, start)
            if obj.RidgePass:
                paths += [p for f in design
                          for p in ridge_polylines(f, vbit, z_v, start, deflection=obj.Discretize,
                                                   colinear_deg=obj.Colinear, step=obj.StepLength.Value,
                                                   tol=obj.Tolerance.Value)]
            return paths
        except Exception as exc:
            Path.Log.error(f"{obj.Label}: ridge pass failed ({exc})")
            return []

    def end_mill_error(self, obj, diameter):
        ring = obj.PlugMargin.Value - op_vcarve.tool_vbit(obj.ToolController).tip_radius  # floor starts r_t out
        if obj.PlugBoundary == "Margin" and ring < diameter:
            return (f"Plug Margin {obj.PlugMargin.Value:g} mm of {obj.Label}, less the V-bit tip radius, is "
                    f"narrower than the end mill diameter {diameter:g} mm")
        return None

    def opFeatures(self, obj):
        return super().opFeatures(obj) & ~PathOp.FeatureBaseEdges

    def initOperation(self, obj):
        super().initOperation(obj)
        obj.addProperty("App::PropertyLink", "PocketOp", _GROUP, "The pocket's V-Carve Flat operation")
        for typ, name, value, tip in _PROPS:
            obj.addProperty(typ, name, _GROUP, tip)
            setattr(obj, name, value)
        for name, values, tip in _ENUMS:
            obj.addProperty("App::PropertyEnumeration", name, _GROUP, tip)
            setattr(obj, name, values)
            setattr(obj, name, values[0])
        obj.addProperty("App::PropertyLength", "PlugStartDepth", _GROUP,
                        "Plug Start Depth: pocket depth - Glue Gap, below the plug board's top (derived)")
        self.opOnDocumentRestored(obj)

    def _link_stock(self, obj):
        """PlugStock links the Job's stock, so editing the stock recomputes the plug."""
        if not hasattr(obj, "PlugStock"):
            obj.addProperty("App::PropertyLink", "PlugStock", _GROUP, "The plug Job's stock (internal)")
            obj.setEditorMode("PlugStock", 2)
        job = PathUtils.findParentJob(obj)
        if job and job.Stock and obj.PlugStock != job.Stock:
            obj.PlugStock = job.Stock

    def opOnDocumentRestored(self, obj):
        super().opOnDocumentRestored(obj)
        if hasattr(obj, "PlugStartDepth"):  # run by the base initOperation before it exists
            obj.setEditorMode("FlatDepth", 2)  # unused: the plug's depths come from the pocket op
            obj.setEditorMode("PlugStartDepth", 1)
            self._link_stock(obj)

    def opSetDefaultValues(self, obj, job):
        super().opSetDefaultValues(obj, job)
        self._link_stock(obj)

    def opUpdateDepths(self, obj):
        super().opUpdateDepths(obj)
        errors, _, start = self._checks(obj)
        if not errors and abs(obj.PlugStartDepth.Value - start) > 1e-9:
            obj.PlugStartDepth = start

    def opRejectAddBase(self, obj, base, sub):
        return True

    def opExecute(self, obj):
        errors, vbit, start = self._checks(obj)
        for error in errors:
            Path.Log.error(error)
        if errors:
            return
        stock = PathUtils.findParentJob(obj).Stock.Shape.BoundBox
        depth = start + obj.SurfaceGap.Value
        if stock.ZLength < depth - 1e-6:
            Path.Log.warning(f"{obj.Label}: the plug Job's stock ({stock.ZLength:g} mm) is thinner than the "
                             f"plug depth {depth:g} mm (pocket depth - Glue Gap + Surface Gap)")
        design = self._design(obj) if obj.PlugBoundary == "Stock" else []
        if design:
            bb = Part.makeCompound(design).BoundBox
            if bb.XMin < stock.XMin - 1e-6 or bb.YMin < stock.YMin - 1e-6 \
                    or bb.XMax > stock.XMax + 1e-6 or bb.YMax > stock.YMax + 1e-6:
                Path.Log.warning(f"{obj.Label}: the plug Job's stock does not cover the mirrored design")
            rc = op_vcarve.rest_clearance(op_vcarve.find_clearance_op(obj))
            grown = Part.makeCompound(area_offset(design, flat_radius(vbit, obj.SurfaceGap.Value)))
            edge = Part.makePlane(stock.XLength, stock.YLength,
                                  App.Vector(stock.XMin, stock.YMin, grown.BoundBox.ZMin)).OuterWire
            if rc.x and grown.distToShape(edge)[0] < 2 * rc.x:
                Path.Log.warning(f"{obj.Label}: the stock margin beyond the plug is narrower than the end mill "
                                 f"diameter {2 * rc.x:g} mm, so the clearance op may not clear it fully and the "
                                 "V-bit clears the rest. Set the plug Job's stock to the real board size")
        super().opExecute(obj)
        complement = self._last[0] if self._last else []
        if vbit.tip_radius > 0 and any(
                has_narrow_gap(f, vbit.tip_radius, deflection=obj.Discretize, colinear_deg=obj.Colinear,
                               step=obj.StepLength.Value) for f in complement):
            Path.Log.warning(f"{obj.Label}: the design has gaps narrower than the V-bit tip "
                             f"({vbit.tip_diameter:g} mm); the plug will not seat there. Use a pointed "
                             "V-bit or widen the gaps")


def SetupProperties():
    return ([n for n in op_vcarve.SetupProperties() if n != "FlatDepth"]
            + [name for _, name, _, _ in _PROPS] + [name for name, _, _ in _ENUMS])


def Create(name, obj=None, parentJob=None):
    """Create(name) ... create and return a V-Carve Plug operation."""
    if obj is None:
        obj = App.ActiveDocument.addObject("Path::FeaturePython", name)
    obj.Proxy = ObjectVCarvePlug(obj, name, parentJob)
    return obj


PathSetupSheet.RegisterOperation("VCarvePlug", Create, SetupProperties)
