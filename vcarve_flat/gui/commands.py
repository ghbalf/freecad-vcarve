# SPDX-License-Identifier: LGPL-2.1-or-later
"""GUI commands creating the V-Carve ops and checking an inlay's fit, and their view providers.

PathOpGui.SetupOperation/Create hardcode CAM's own ViewProvider, so create() mirrors Create
with ours. The FreeCAD command names are registered by InitGui.py, which delegates here."""
import os

import FreeCAD as App
import FreeCADGui as Gui
import Path
import Path.Op.Base as PathOp
import Path.Op.Gui.Base as PathOpGui
import PathScripts.PathUtils as PathUtils
from PySide import QtCore, QtGui

from .. import fit_object, inlay, op_clearance, op_plug, op_vcarve  # noqa: F401  (op_plug: registers it with the setup sheet)
from ..compat import tool_shape
from ..sketches import is_sketch_base
from . import inlay_dialog, panels, selection

translate = App.Qt.translate
ICONS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "resources", "icons")
_ICON = {"VCarveOpPage": "vcarve_flat.svg", "ClearanceOpPage": "vcarve_clearance.svg",
         "PlugOpPage": "vcarve_plug.svg"}
_NO_TC = {"VCarveFlat": "Add a V-bit tool controller to the job",
          "VCarveClearance": "Add an end mill tool controller to the job",
          "VCarvePlug": "Add a V-bit tool controller to the job"}
RED, BLUE = (1.0, 0.0, 0.0), (0.0, 0.3, 1.0)  # no 4th value: transparency on 1.0, alpha on 1.1+


class ViewProvider(PathOpGui.ViewProvider):
    """CAM's op view provider with the addon's icons (looked up, so saved files stay relocatable)."""

    @property
    def OpIcon(self):
        return os.path.join(ICONS, _ICON[self.OpPageClass])

    @OpIcon.setter
    def OpIcon(self, value):  # assigned by the base class and loads(); the icon is derived
        pass

    def getIcon(self):
        return self.OpIcon if self.Object.Active else super().getIcon()

    def getSelectionFactory(self):  # only the V-carve op has base geometry to pick
        return selection.select if self.OpPageClass == "VCarveOpPage" else selection.free


def _warn(text):
    QtGui.QMessageBox.warning(Gui.getMainWindow(), translate("CAM_VCarve", "V-Carve"), text)


def _find_job():
    """The Job of the selection, else the document's only Job, else ask the user."""
    jobs = PathUtils.GetJobs()
    for sel in Gui.Selection.getSelection():
        for job in jobs:
            if selection.job_clone(job, sel) or PathUtils.findParentJob(sel) == job:
                return job
    if len(jobs) == 1:
        return jobs[0]
    return PathUtils.UserInput.chooseJob(jobs) if jobs else None


def _attach(obj, res, delete_on_reject=True):
    obj.ViewObject.Proxy = ViewProvider(obj.ViewObject, res)
    obj.ViewObject.Proxy.setDeleteObjectsOnReject(delete_on_reject)
    obj.ViewObject.Visibility = True


def create(res):
    """PathOpGui.Create with our view provider and op specific 'no tool controller' messages."""
    doc = App.ActiveDocument
    doc.openTransaction("Create %s" % res.name)
    try:
        obj = res.objFactory(res.name, obj=None, parentJob=res.job)
        _attach(obj, res)
        doc.commitTransaction()
        obj.ViewObject.Document.setEdit(obj.ViewObject, 0)  # the base page imports the selection
        return obj
    except (PathUtils.PathNoTCExistsException, PathOp.PathNoTCException):
        doc.abortTransaction()
        doc.recompute()
        _warn(translate("CAM_VCarve", _NO_TC[res.name]))
    return None


class _OpCommand(PathOpGui.CommandPathOp):
    def Activated(self):
        self.res.job = _find_job()
        return create(self.res) if self.res.job else None


def _add_selection(op, job):
    """Selected sketches go to BaseShapes, selected edges to Base, both as the Job's clones.
    Selected objects that are not sketches of the Job, and sketches with only vertices selected,
    are reported in one warning each."""
    shapes, skipped, no_edges = list(op.BaseShapes), [], []
    for sel in Gui.Selection.getSelectionEx():
        model = selection.job_clone(job, sel.Object)
        if model is None or not is_sketch_base(model):
            skipped.append(sel.Object.Label)
            continue
        edges = [s for s in sel.SubElementNames if s.startswith("Edge")]
        if sel.SubElementNames and not edges:
            no_edges.append(sel.Object.Label)
        for sub in edges:
            op.Proxy.addBase(op, model, sub)
        if not sel.SubElementNames and model not in shapes:
            shapes.append(model)
    op.BaseShapes = shapes
    if skipped:
        _warn(translate("CAM_VCarve", "Not a sketch of the Job {}, skipped: {}").format(
            job.Label, ", ".join(skipped)))
    if no_edges:
        _warn(translate("CAM_VCarve", "Only vertices selected, skipped: {}. Select edges or the whole "
                                      "sketch.").format(", ".join(no_edges)))


class _PairCommand:
    def __init__(self, vcarve_res, clearance_res):
        self.vcarve_res, self.clearance_res = vcarve_res, clearance_res

    def Activated(self):
        job = _find_job()
        if job is None:
            return
        doc = App.ActiveDocument
        doc.openTransaction("Create V-Carve pair")
        try:
            clearance, vcarve = op_clearance.create_pair(job)
            _add_selection(vcarve, job)
            # Cancel must not delete the V-carve op the clearance op links to (nor re-import the selection)
            _attach(clearance, self.clearance_res, False)
            _attach(vcarve, self.vcarve_res, False)
        except ValueError as e:
            doc.abortTransaction()
            _warn(translate("CAM_VCarve", str(e)))
            return
        except Exception:
            doc.abortTransaction()
            raise
        doc.commitTransaction()
        doc.recompute()
        # Edit once the command returned: inside it, FreeCAD defers our commit and the panel would
        # join the creation transaction, so Cancel would undo the whole pair.
        QtCore.QTimer.singleShot(0, lambda: vcarve.ViewObject.Document.setEdit(vcarve.ViewObject, 0))


class _InlayCommand:
    def __init__(self, vcarve_res, clearance_res, plug_res):
        self.res = vcarve_res, clearance_res, plug_res

    def Activated(self):
        job = _find_job()
        if job is None:
            return
        selected = Gui.Selection.getSelection()
        if len(selected) != 1 or not is_sketch_base(selected[0]):
            _warn(translate("CAM_VCarve", "Select exactly one sketch"))
            return
        tcs = job.Tools.Group
        vtcs = [tc for tc in tcs if tool_shape(tc.Tool) == "VBit"]
        etcs = [tc for tc in tcs if tool_shape(tc.Tool) == "Endmill"]
        if not vtcs or not etcs:
            _warn(translate("CAM_VCarve", "The Job needs a V-bit and an end mill tool controller"))
            return
        dialog = inlay_dialog.InlayDialog(job, vtcs, etcs)
        if not dialog.exec_():
            return
        def attach(made):  # inside the creation's transaction
            _, pocket, _, plug = made
            vcarve_res, clearance_res, plug_res = self.res
            for (clearance, carve), carve_res in ((pocket, vcarve_res), (plug, plug_res)):
                _attach(clearance, clearance_res, False)
                _attach(carve, carve_res, False)

        try:
            if inlay.run_inlay(job, selected[0], dialog.values(), attach):
                job.Document.recompute()
        except ValueError as e:
            job.Document.recompute()
            _warn(str(e))


class FitViewProvider:
    """The Fit object's view provider: its icon (the colours are the view object's own, saved with it)."""

    def __init__(self, vobj):
        vobj.Proxy = self

    def getIcon(self):
        return os.path.join(ICONS, "vcarve_fit.svg")

    def dumps(self):
        return None

    def loads(self, state):
        return None


def _show_fit(obj):
    """Collision squares red, void squares blue, opaque (DiffuseColor sets ShapeAppearance on 1.1+ too)."""
    vobj = obj.ViewObject
    FitViewProvider(vobj)
    vobj.Transparency = 0
    hits = len(obj.Shape.SubShapes[0].Faces)
    vobj.DiffuseColor = [RED] * hits + [BLUE] * (len(obj.Shape.Faces) - hits)


class _FitCommand:
    def Activated(self):
        plug = fit_object.plug_of(Gui.Selection.getSelection())
        if plug is None:
            Path.Log.error(translate("CAM_VCarve", "Select the plug or pocket op or Job of a V-Carve Inlay"))
            return
        fit_object.run(plug, _show_fit)


_COMMANDS = {}


def register():
    """Build (once) and return {command name: command object with Activated()}."""
    if not _COMMANDS:
        def res(name, factory, page, pixmap, menu, tip):
            return PathOpGui.CommandResources(name, factory, page, pixmap, menu, None, tip)

        vcarve = res("VCarveFlat", op_vcarve.Create, panels.VCarveOpPage, "vcarve_flat",
                     "V-Carve Flat", "V-carve sketches with a flat floor")
        clearance = res("VCarveClearance", op_clearance.Create, panels.ClearanceOpPage,
                        "vcarve_clearance", "V-Carve Clearance", "Clear the flat floor of a V-carve op")
        plug = res("VCarvePlug", op_plug.Create, panels.PlugOpPage, "vcarve_plug",
                   "V-Carve Plug", "Carve the plug of a V-carve inlay")
        _COMMANDS.update(CAM_VCarveFlat=_OpCommand(vcarve), CAM_VCarveClearance=_OpCommand(clearance),
                         CAM_VCarvePair=_PairCommand(vcarve, clearance), CAM_VCarvePlug=_OpCommand(plug),
                         CAM_VCarveInlay=_InlayCommand(vcarve, clearance, plug), CAM_VCarveFit=_FitCommand())
    return _COMMANDS
