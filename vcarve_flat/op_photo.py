# SPDX-License-Identifier: LGPL-2.1-or-later
# Authors: alf and Claude (Anthropic)
"""V-Carve Photo CAM operation: V-grooves whose depth follows an image plane's darkness."""
import math

import FreeCAD as App
import numpy as np
import Part
import Path
import Path.Base.SetupSheet as PathSetupSheet
import Path.Op.Base as PathOp
import PathScripts.PathUtils as PathUtils

from . import photo, progress
from .compat import tool_shape
from .geom import limit_depth
from .image_plane import ImageError, plane_frame, read_rgba, size
from .op_vcarve import check_tool_controller, is_tool_controller, mm, tool_vbit
from .toolpath import paths_to_commands

_GROUP = "V-Carve Photo"
PATTERNS = ["Lines", "Hatch", "Custom"]

def _deg(value) -> App.Units.Quantity:
    return App.Units.Quantity(value, App.Units.Angle)  # a Quantity for the setup sheet, like mm()


_PROPS = [  # (type, name, default, tooltip)
    ("App::PropertyAngle", "Angle", _deg(45), "Direction of the lines, -90 to 90 degrees from the X axis"),
    ("App::PropertyAngle", "HatchAngle", _deg(135), "Direction of the second line set of the Hatch pattern"),
    ("App::PropertyLength", "MaxDepth", mm(2), "Depth of black, below Start Depth"),
    ("App::PropertyLength", "MinDepth", mm(0.05), "The bit lifts out where the depth is less than this"),
    ("App::PropertyLength", "LineSpacing", mm(2.5), "Distance between neighbouring lines"),
    ("App::PropertyLength", "SampleStep", mm(0.25), "Distance between depth samples along a line"),
    ("App::PropertyFloat", "Contrast", 100.0, "Contrast around mid-grey in percent (100 = unchanged)"),
    ("App::PropertyBool", "Invert", False, "Swap dark and light"),
    ("App::PropertyBool", "BandAverage", False, "Lines and Hatch: average the image across each line's band "
     "instead of reading it under the line; truer tone, but small highlights between lines fade"),
    ("App::PropertyLength", "Tolerance", mm(0.01), "Simplification tolerance of the toolpath"),
]


def groove_width(vbit, depth: float) -> float:
    return vbit.tip_diameter + 2 * depth * math.tan(vbit.half_angle)


def _is_vbit_tc(obj) -> bool:
    tc = getattr(obj, "ToolController", None)
    return is_tool_controller(tc) and tool_shape(tc.Tool) == "VBit"


def _follow_depth(obj):
    """Make LineSpacing the V-bit's groove width at MaxDepth plus 5 %, as an expression; a new V-bit sets it anew."""
    if _is_vbit_tc(obj):
        vbit = tool_vbit(obj.ToolController)
        obj.setExpression("LineSpacing", f"({vbit.tip_diameter:g} mm + 2 * min(MaxDepth; {vbit.cone_height:.6g} mm)"
                                         f" * tan({math.degrees(vbit.half_angle):g} deg)) * 1.05")


def _faced_below(obj) -> list:
    """The active MillFace ops before obj in its Job that face below obj's Start Depth."""
    from Path.Op.MillFace import ObjectFace
    job = PathUtils.findParentJob(obj)
    ops = list(job.Operations.Group) if job else []
    before = ops[:ops.index(obj)] if obj in ops else []
    return [o for o in before if isinstance(getattr(o, "Proxy", None), ObjectFace) and o.Active
            and o.FinalDepth.Value < obj.StartDepth.Value - 1e-6]


def _vector_lines(objs, deflection) -> list:
    """XY polylines of the edges of objs, chained where they meet."""
    lines = []
    for o in objs:
        for edges in Part.sortEdges(o.Shape.Edges):
            pts = Part.Wire(edges).discretize(Deflection=deflection)
            lines.append(np.array([(p.x, p.y) for p in pts]))
    return lines


class ObjectVCarvePhoto(PathOp.ObjectOp):
    def opFeatures(self, obj):
        return (PathOp.FeatureTool | PathOp.FeatureHeights | PathOp.FeatureDepths | PathOp.FeatureNoFinalDepth
                | PathOp.FeatureCoolant)

    def initOperation(self, obj):
        obj.addProperty("App::PropertyLink", "ImagePlane", _GROUP, "The image plane to carve")
        obj.addProperty("App::PropertyEnumeration", "Pattern", _GROUP, "Lines, two crossed line sets, or the "
                        "Vectors objects' edges")
        obj.Pattern = PATTERNS
        obj.Pattern = PATTERNS[0]
        obj.addProperty("App::PropertyLinkList", "Vectors", _GROUP,
                        "Sketches or imported SVG paths to carve along (Custom pattern)")
        for typ, name, value, tip in _PROPS:
            obj.addProperty(typ, name, _GROUP, tip)
            setattr(obj, name, value)

    def opSetDefaultValues(self, obj, job):
        planes = [o for o in obj.Document.Objects if o.TypeId == "Image::ImagePlane"]
        if App.GuiUp:
            import FreeCADGui as Gui
            chosen = [o for o in Gui.Selection.getSelection() if o in planes]
            planes = chosen or planes
        if len(planes) == 1:
            obj.ImagePlane = planes[0]
        _follow_depth(obj)

    def opOnChanged(self, obj, prop):
        if prop == "ToolController" and "Restore" not in obj.State:
            check_tool_controller(obj)
            _follow_depth(obj)

    def isToolSupported(self, obj, tool):
        return tool_shape(tool) == "VBit"

    def opExecute(self, obj):
        with progress.op_task(self, obj):
            self.carve(obj)

    def carve(self, obj):
        if not _is_vbit_tc(obj):
            Path.Log.error(f"{obj.Label}: the tool controller must use a V-bit")
            return
        for face in _faced_below(obj):
            Path.Log.warning(f"{obj.Label}: {face.Label} faces the stock down to {face.FinalDepth.Value:g} mm, below "
                             f"Start Depth {obj.StartDepth.Value:g} mm; set Start Depth to the faced surface")
        plane = obj.ImagePlane
        if plane is None:
            Path.Log.error(f"{obj.Label}: no image plane selected")
            return
        try:
            to_uv, bbox = plane_frame(plane)
            rgba = read_rgba(plane.ImageFile)
        except ImageError as exc:
            Path.Log.error(f"{obj.Label}: {exc}")
            return
        raster = photo.Raster(photo.darkness(rgba, max(obj.Contrast, 0.0), obj.Invert), *size(plane),
                              cell=obj.SampleStep.Value)
        vbit = tool_vbit(obj.ToolController)
        depth, capped = limit_depth(vbit, obj.MaxDepth.Value)
        if capped:
            Path.Log.warning(f"{obj.Label}: Max Depth {obj.MaxDepth.Value:g} mm is deeper than the V-bit "
                             f"cone, using {depth:.3f} mm")
        if obj.Pattern == "Custom":
            sets = [(_vector_lines(obj.Vectors, obj.Tolerance.Value), False, None)]
        else:
            rect = self.clip_rect(obj, bbox)
            if rect is None:
                return
            if groove_width(vbit, depth) > obj.LineSpacing.Value:
                Path.Log.warning(f"{obj.Label}: the groove at Max Depth ({groove_width(vbit, depth):.2f} mm) "
                                 f"is wider than Line Spacing, so neighbouring grooves merge in the darkest areas")
            angles = [obj.Angle.Value] + ([obj.HatchAngle.Value] if obj.Pattern == "Hatch" else [])
            sets = [(photo.line_set(rect, a, obj.LineSpacing.Value), obj.Pattern == "Hatch",
                     np.array([-math.sin(math.radians(a)), math.cos(math.radians(a))]) if obj.BandAverage else None)
                    for a in angles]
        paths = []
        step = obj.SampleStep.Value
        for lines, hatch, normal in sets:
            for line in lines:
                progress.step()
                xy = photo.resample(line, step)
                rho = (raster.sample(to_uv(xy)) if normal is None
                       else photo.band_sample(raster, to_uv, xy, normal, obj.LineSpacing.Value, step))
                d = (photo.hatch_share(rho) if hatch else rho) * depth
                paths += photo.cut_runs(xy, d, obj.MinDepth.Value, obj.StartDepth.Value, obj.Tolerance.Value)
        if not paths:
            Path.Log.notice(f"{obj.Label}: nothing dark enough to cut (deeper than Min Depth)")
            return
        tc = obj.ToolController
        self.commandlist.extend(paths_to_commands(paths, obj.SafeHeight.Value, obj.ClearanceHeight.Value,
                                                  tc.HorizFeed.Value, tc.VertFeed.Value))

    def clip_rect(self, obj, bbox):
        """The image rectangle's XY extent clipped to the stock, warning if it reaches outside it."""
        job = PathUtils.findParentJob(obj)
        if not (job and job.Stock):
            return bbox
        sb = job.Stock.Shape.BoundBox
        rect = (max(bbox[0], sb.XMin), max(bbox[1], sb.YMin), min(bbox[2], sb.XMax), min(bbox[3], sb.YMax))
        if rect != tuple(bbox):
            Path.Log.warning(f"{obj.Label}: the image reaches outside the stock; carving only over the stock")
        if rect[0] >= rect[2] or rect[1] >= rect[3]:
            Path.Log.error(f"{obj.Label}: the image plane does not lie over the stock")
            return None
        return rect


def SetupProperties():
    return ["Pattern"] + [name for _, name, _, _ in _PROPS]


def Create(name, obj=None, parentJob=None):
    """Create(name) ... create and return a V-Carve Photo operation."""
    if obj is None:
        obj = App.ActiveDocument.addObject("Path::FeaturePython", name)
    obj.Proxy = ObjectVCarvePhoto(obj, name, parentJob)
    return obj


PathSetupSheet.RegisterOperation("VCarvePhoto", Create, SetupProperties)
