# SPDX-License-Identifier: LGPL-2.1-or-later
"""GUI commands creating the V-Carve ops, and their view provider.

PathOpGui.SetupOperation/Create hardcode CAM's own ViewProvider, so create() mirrors Create
with ours. The FreeCAD command names are registered by InitGui.py, which delegates here."""
import os

import FreeCAD as App
import FreeCADGui as Gui
import Path.Op.Base as PathOp
import Path.Op.Gui.Base as PathOpGui
import PathScripts.PathUtils as PathUtils
from PySide import QtCore, QtGui

from .. import op_clearance, op_vcarve
from ..sketches import is_sketch_base
from . import panels, selection

translate = App.Qt.translate
ICONS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "resources", "icons")
_ICON = {"VCarveOpPage": "vcarve_flat.svg", "ClearanceOpPage": "vcarve_clearance.svg"}
_NO_TC = {"VCarveFlat": "Add a V-bit tool controller to the job",
          "VCarveClearance": "Add an end mill tool controller to the job"}


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

    def getSelectionFactory(self):
        return selection.select


def _warn(text):
    QtGui.QMessageBox.warning(Gui.getMainWindow(), translate("CAM_VCarve", "V-Carve"), text)


def _find_job():
    """The Job of the selection, else the document's only Job, else ask the user."""
    jobs = PathUtils.GetJobs()
    for sel in Gui.Selection.getSelection():
        for job in jobs:
            if job.Proxy.resourceClone(job, sel) or PathUtils.findParentJob(sel) == job:
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
    """Selected sketches go to BaseShapes, selected edges to Base, both as the Job's clones."""
    shapes = list(op.BaseShapes)
    for sel in Gui.Selection.getSelectionEx():
        model = job.Proxy.resourceClone(job, sel.Object)
        if model is None or not is_sketch_base(model):
            continue
        for sub in (s for s in sel.SubElementNames if s.startswith("Edge")):
            op.Proxy.addBase(op, model, sub)
        if not sel.SubElementNames and model not in shapes:
            shapes.append(model)
    op.BaseShapes = shapes


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
        except ValueError as e:
            doc.abortTransaction()
            _warn(translate("CAM_VCarve", str(e)))
            return
        _add_selection(vcarve, job)
        # Cancel must not delete the V-carve op the clearance op links to (nor re-import the selection)
        _attach(clearance, self.clearance_res, False)
        _attach(vcarve, self.vcarve_res, False)
        doc.commitTransaction()
        doc.recompute()
        # Edit once the command returned: inside it, FreeCAD defers our commit and the panel would
        # join the creation transaction, so Cancel would undo the whole pair.
        QtCore.QTimer.singleShot(0, lambda: vcarve.ViewObject.Document.setEdit(vcarve.ViewObject, 0))


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
        _COMMANDS.update(CAM_VCarveFlat=_OpCommand(vcarve), CAM_VCarveClearance=_OpCommand(clearance),
                         CAM_VCarvePair=_PairCommand(vcarve, clearance))
    return _COMMANDS
