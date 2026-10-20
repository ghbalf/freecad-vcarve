# SPDX-License-Identifier: LGPL-2.1-or-later
"""Task panel pages of the V-Carve Flat and V-Carve Clearance operations, built in code."""
import FreeCAD as App
import FreeCADGui as Gui
import Path.Base.Gui.Util as PathGuiUtil
import Path.Op.Gui.Base as PathOpGui
import Path.Op.Gui.Vcarve as PathVcarveGui
import PathScripts.PathUtils as PathUtils
from PySide import QtGui

from ..op_vcarve import ObjectVCarveFlat
from .selection import to_clones

translate = App.Qt.translate
# 26.3+: tool controller and coolant have a page of their own; 1.1: inline tool controller editor
_TC_PAGE = hasattr(PathOpGui, "TaskPanelToolControllerPage")
_TC_EDITOR = hasattr(PathOpGui.TaskPanelPage, "updateToolControllerEditorVisibility")


def _row(grid, label, widget):
    r = grid.rowCount()
    grid.addWidget(QtGui.QLabel(label), r, 0)
    grid.addWidget(widget, r, 1)
    return widget


def _double(decimals, low, high, step):
    box = QtGui.QDoubleSpinBox()
    box.setDecimals(decimals)
    box.setRange(low, high)
    box.setSingleStep(step)
    return box


class _Page(PathOpGui.TaskPanelPage):
    """Tool controller widgets (unless CAM has a page for them), then the fields of addFields()."""

    def getForm(self):
        form = QtGui.QWidget()
        grid = QtGui.QGridLayout(form)
        if not _TC_PAGE:
            box = QtGui.QGroupBox(translate("CAM_VCarve", "Tool Controller"))
            tc_grid = QtGui.QGridLayout(box)  # CAM appends the tool controller editor to this grid
            form.toolController = _row(tc_grid, translate("CAM_VCarve", "Tool Controller"), QtGui.QComboBox())
            form.coolantController = _row(tc_grid, translate("CAM_VCarve", "Coolant Mode"), QtGui.QComboBox())
            if _TC_EDITOR:
                form.editToolController = QtGui.QCheckBox(translate("CAM_VCarve", "Edit Tool Controller"))
                tc_grid.addWidget(form.editToolController, tc_grid.rowCount(), 0, 1, 2)
            grid.addWidget(box, grid.rowCount(), 0, 1, 2)
        self.quantities = []
        self.addFields(form, grid)
        return form

    def addFields(self, form, grid):
        """Add the page's own widgets as attributes of form, named after their properties."""

    def quantity(self, form, grid, prop, label):
        self.quantities.append(prop)
        setattr(form, prop, _row(grid, label, Gui.UiLoader().createWidget("Gui::QuantitySpinBox")))

    def initPage(self, obj):
        self.spins = [PathGuiUtil.QuantitySpinBox(getattr(self.form, p), obj, p) for p in self.quantities]

    def getFields(self, obj):
        for spin in self.spins:
            spin.updateProperty()
        if not _TC_PAGE:
            self.updateToolController(obj, self.form.toolController)
            self.updateCoolant(obj, self.form.coolantController)

    def setFields(self, obj):
        for spin in self.spins:
            (getattr(spin, "updateWidget", None) or spin.updateSpinBox)()  # 1.0: updateSpinBox
        if not _TC_PAGE:
            self.setupToolController(obj, self.form.toolController)
            self.setupCoolant(obj, self.form.coolantController)

    def getSignalsForUpdate(self, obj):
        signals = [getattr(self.form, p).editingFinished for p in self.quantities]
        if not _TC_PAGE:
            signals += [self.form.toolController.currentIndexChanged,
                        self.form.coolantController.currentIndexChanged]
        return signals


class BaseGeometryPage(PathVcarveGui.TaskPanelBaseGeometryPage):
    """CAM's Vcarve base page (BaseShapes for whole sketches, Base for edges), storing Job clones:
    26.3 stores the selected object itself, which may be the original sketch."""

    def addBaseGeometry(self, selection):
        added = super().addBaseGeometry(selection)
        shapes, base = to_clones(PathUtils.findParentJob(self.obj), self.obj.BaseShapes, self.obj.Base)
        if shapes != list(self.obj.BaseShapes):
            self.obj.BaseShapes = shapes
        if base != [(o, tuple(subs)) for o, subs in self.obj.Base]:
            self.obj.Base = base
        return added


class VCarveOpPage(_Page):
    _FLOATS = ("Discretize", "Colinear")

    def addFields(self, form, grid):
        self.quantity(form, grid, "FlatDepth", translate("CAM_VCarve", "Flat Depth"))
        self.quantity(form, grid, "RestScallop", translate("CAM_VCarve", "Rest Scallop"))
        self.quantity(form, grid, "StepLength", translate("CAM_VCarve", "Step Length"))
        self.quantity(form, grid, "Tolerance", translate("CAM_VCarve", "Tolerance"))
        form.Discretize = _row(grid, translate("CAM_VCarve", "Discretize"), _double(4, 0.0001, 10, 0.001))
        form.Colinear = _row(grid, translate("CAM_VCarve", "Colinear Angle"), _double(1, 0, 180, 1))

    def getFields(self, obj):
        super().getFields(obj)
        for prop in self._FLOATS:
            value = getattr(self.form, prop).value()
            if getattr(obj, prop) != value:
                setattr(obj, prop, value)

    def setFields(self, obj):
        super().setFields(obj)
        for prop in self._FLOATS:
            getattr(self.form, prop).setValue(getattr(obj, prop))

    def getSignalsForUpdate(self, obj):
        return super().getSignalsForUpdate(obj) + [getattr(self.form, p).editingFinished for p in self._FLOATS]

    def taskPanelBaseGeometryPage(self, obj, features):
        return BaseGeometryPage(obj, features)


class ClearanceOpPage(_Page):
    def addFields(self, form, grid):
        form.VCarveOp = _row(grid, translate("CAM_VCarve", "V-Carve Operation"), QtGui.QComboBox())
        form.StepOver = _row(grid, translate("CAM_VCarve", "Step Over"), QtGui.QSpinBox())
        form.StepOver.setRange(1, 100)
        form.StepOver.setSuffix(" %")
        form.PocketPattern = _row(grid, translate("CAM_VCarve", "Pattern"), QtGui.QComboBox())
        self.quantity(form, grid, "Allowance", translate("CAM_VCarve", "Allowance"))

    def _vcarve_ops(self):
        ops = self.job.Operations.Group if self.job else []
        return [op for op in ops if isinstance(getattr(op, "Proxy", None), ObjectVCarveFlat)]

    def getFields(self, obj):
        super().getFields(obj)
        name = self.form.VCarveOp.currentData()
        link = obj.Document.getObject(name) if name else None
        if obj.VCarveOp != link:
            obj.VCarveOp = link
        if obj.StepOver != self.form.StepOver.value():
            obj.StepOver = self.form.StepOver.value()
        if obj.PocketPattern != self.form.PocketPattern.currentText():
            obj.PocketPattern = self.form.PocketPattern.currentText()

    def setFields(self, obj):
        super().setFields(obj)
        combo = self.form.VCarveOp
        combo.blockSignals(True)
        combo.clear()
        ops, link = self._vcarve_ops(), obj.VCarveOp
        if link not in ops:  # keep an unlisted (or empty) link instead of rewriting it
            ops.insert(0, link)
        for op in ops:
            combo.addItem(op.Label if op else "", op.Name if op else "")
        combo.setCurrentIndex(ops.index(link))
        combo.blockSignals(False)
        self.form.StepOver.setValue(obj.StepOver)
        pattern = self.form.PocketPattern
        pattern.blockSignals(True)
        pattern.clear()
        pattern.addItems(obj.getEnumerationsOfProperty("PocketPattern"))
        pattern.setCurrentText(obj.PocketPattern)
        pattern.blockSignals(False)

    def getSignalsForUpdate(self, obj):
        return super().getSignalsForUpdate(obj) + [
            self.form.VCarveOp.currentIndexChanged, self.form.StepOver.editingFinished,
            self.form.PocketPattern.currentIndexChanged]
