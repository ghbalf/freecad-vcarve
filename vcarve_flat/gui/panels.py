# SPDX-License-Identifier: LGPL-2.1-or-later
# Authors: alf and Claude (Anthropic)
"""Task panel pages of the V-Carve operations, built in code."""
import FreeCAD as App
import FreeCADGui as Gui
import Path.Base.Gui.Util as PathGuiUtil
import Path.Op.Gui.Base as PathOpGui
import Path.Op.Gui.Vcarve as PathVcarveGui
import PathScripts.PathUtils as PathUtils
from PySide import QtCore, QtGui

from ..op_vcarve import ObjectVCarveFlat
from .selection import to_clones

translate = App.Qt.translate
# 26.3+: tool controller and coolant have a page of their own; 1.1: inline tool controller editor
_TC_PAGE = hasattr(PathOpGui, "TaskPanelToolControllerPage")
_TC_EDITOR = hasattr(PathOpGui.TaskPanelPage, "updateToolControllerEditorVisibility")
_DEPTHS_PAGE = hasattr(PathOpGui, "TaskPanelDepthsPage")  # 26.3+: the depths are on the heights page


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


class _NoStepDownPage(PathOpGui.TaskPanelDepthsPage if _DEPTHS_PAGE else PathOpGui.TaskPanelHeightsPage):
    """The depths page without Step Down: the clearance op steps down with its linked op."""

    def haveStepDown(self):
        return False


class ClearanceOpPage(_Page):
    if _DEPTHS_PAGE:
        def taskPanelDepthsPage(self, obj, features):
            return _NoStepDownPage(obj, features)
    else:
        def taskPanelHeightsPage(self, obj, features):
            return _NoStepDownPage(obj, features)

    def addFields(self, form, grid):
        form.VCarveOp = _row(grid, translate("CAM_VCarve", "V-Carve Operation"), QtGui.QComboBox())
        form.StepOver = _row(grid, translate("CAM_VCarve", "Step Over"), QtGui.QSpinBox())
        form.StepOver.setRange(1, 100)
        form.StepOver.setSuffix(" %")
        form.PocketPattern = _row(grid, translate("CAM_VCarve", "Pattern"), QtGui.QComboBox())
        self.quantity(form, grid, "Allowance", translate("CAM_VCarve", "Allowance"))
        form.RestOnly = _row(grid, translate("CAM_VCarve", "Rest only"), QtGui.QCheckBox())

    def _vcarve_ops(self):
        ops = self.job.Operations.Group if self.job else []
        return [op for op in ops if isinstance(getattr(op, "Proxy", None), ObjectVCarveFlat)]

    def getFields(self, obj):
        super().getFields(obj)
        # An empty or unknown combo value (e.g. while the combo is being refilled) is never written.
        name = self.form.VCarveOp.currentData()
        link = obj.Document.getObject(name) if name else None
        if link is not None and obj.VCarveOp != link:
            obj.VCarveOp = link
        if obj.StepOver != self.form.StepOver.value():
            obj.StepOver = self.form.StepOver.value()
        pattern = self.form.PocketPattern.currentText()
        if pattern in obj.getEnumerationsOfProperty("PocketPattern") and obj.PocketPattern != pattern:
            obj.PocketPattern = pattern
        if obj.RestOnly != self.form.RestOnly.isChecked():
            obj.RestOnly = self.form.RestOnly.isChecked()

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
        self.form.RestOnly.setChecked(obj.RestOnly)

    def getSignalsForUpdate(self, obj):
        return super().getSignalsForUpdate(obj) + [
            self.form.VCarveOp.currentIndexChanged, self.form.StepOver.editingFinished,
            self.form.PocketPattern.currentIndexChanged, self.form.RestOnly.stateChanged]


class PlugOpPage(_Page):
    """The plug op's own properties; PocketOp is set by the Inlay command and left alone here."""
    _ENUMS = ("PlugBoundary", "MirrorAxis")

    def addFields(self, form, grid):
        self.quantity(form, grid, "GlueGap", translate("CAM_VCarve", "Glue Gap"))
        self.quantity(form, grid, "SurfaceGap", translate("CAM_VCarve", "Surface Gap"))
        self.quantity(form, grid, "PlugMargin", translate("CAM_VCarve", "Plug Margin"))
        form.PlugBoundary = _row(grid, translate("CAM_VCarve", "Plug Boundary"), QtGui.QComboBox())
        form.MirrorAxis = _row(grid, translate("CAM_VCarve", "Mirror Axis"), QtGui.QComboBox())
        form.RidgePass = _row(grid, translate("CAM_VCarve", "Ridge Pass"), QtGui.QCheckBox())
        self.quantity(form, grid, "RestScallop", translate("CAM_VCarve", "Rest Scallop"))
        self.quantity(form, grid, "StepLength", translate("CAM_VCarve", "Step Length"))
        self.quantity(form, grid, "Tolerance", translate("CAM_VCarve", "Tolerance"))

    def getFields(self, obj):
        super().getFields(obj)
        for prop in self._ENUMS:
            value = getattr(self.form, prop).currentText()
            if value in obj.getEnumerationsOfProperty(prop) and getattr(obj, prop) != value:
                setattr(obj, prop, value)
        if obj.RidgePass != self.form.RidgePass.isChecked():
            obj.RidgePass = self.form.RidgePass.isChecked()

    def setFields(self, obj):
        super().setFields(obj)
        for prop in self._ENUMS:
            combo = getattr(self.form, prop)
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(obj.getEnumerationsOfProperty(prop))
            combo.setCurrentText(getattr(obj, prop))
            combo.blockSignals(False)
        self.form.RidgePass.setChecked(obj.RidgePass)

    def getSignalsForUpdate(self, obj):
        return super().getSignalsForUpdate(obj) + [
            getattr(self.form, p).currentIndexChanged for p in self._ENUMS] + [self.form.RidgePass.stateChanged]


class PhotoOpPage(_Page):
    """The photo op's image, pattern and tone fields; the line fields follow the pattern."""
    _LINES = ("Angle", "LineSpacing")  # shown for Lines and Hatch

    def addFields(self, form, grid):
        def labelled(prop):  # the label of the row just added
            self.labels[prop] = grid.itemAtPosition(grid.rowCount() - 1, 0).widget()

        self.labels = {}
        form.ImagePlane = _row(grid, translate("CAM_VCarve", "Image Plane"), QtGui.QComboBox())
        form.Pattern = _row(grid, translate("CAM_VCarve", "Pattern"), QtGui.QComboBox())
        for prop, label in (("Angle", "Angle"), ("HatchAngle", "Hatch Angle"), ("LineSpacing", "Line Spacing")):
            self.quantity(form, grid, prop, translate("CAM_VCarve", label))
            labelled(prop)
        box = QtGui.QWidget()
        lay = QtGui.QGridLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        form.Vectors = QtGui.QListWidget()
        form.Vectors.setSelectionMode(QtGui.QAbstractItemView.ExtendedSelection)
        form.addVectors = QtGui.QPushButton(translate("CAM_VCarve", "Add selected"))
        form.removeVectors = QtGui.QPushButton(translate("CAM_VCarve", "Remove"))
        lay.addWidget(form.Vectors, 0, 0, 1, 2)
        lay.addWidget(form.addVectors, 1, 0)
        lay.addWidget(form.removeVectors, 1, 1)
        form.VectorsBox = _row(grid, translate("CAM_VCarve", "Vectors"), box)
        labelled("VectorsBox")
        for prop, label in (("MaxDepth", "Max Depth"), ("MinDepth", "Min Depth"), ("SampleStep", "Sample Step"),
                            ("Tolerance", "Tolerance")):
            self.quantity(form, grid, prop, translate("CAM_VCarve", label))
        form.Contrast = _row(grid, translate("CAM_VCarve", "Contrast"), _double(0, 0, 1000, 10))
        form.Contrast.setSuffix(" %")
        form.Invert = _row(grid, translate("CAM_VCarve", "Invert"), QtGui.QCheckBox())
        form.BandAverage = _row(grid, translate("CAM_VCarve", "Band Average"), QtGui.QCheckBox())
        labelled("BandAverage")

    def _show_pattern(self, *_):
        pattern = self.form.Pattern.currentText()
        shown = {"Angle": pattern != "Custom", "LineSpacing": pattern != "Custom",
                 "HatchAngle": pattern == "Hatch", "VectorsBox": pattern == "Custom",
                 "BandAverage": pattern != "Custom"}
        for prop, on in shown.items():
            getattr(self.form, prop).setHidden(not on)
            self.labels[prop].setHidden(not on)

    def _vector_names(self):
        vectors = self.form.Vectors
        return [vectors.item(i).data(QtCore.Qt.UserRole) for i in range(vectors.count())]

    def _add_vectors(self):
        names = self._vector_names()
        for o in Gui.Selection.getSelection():
            shape = getattr(o, "Shape", None)
            if shape is not None and shape.Edges and o.Name not in names:
                item = QtGui.QListWidgetItem(o.Label)
                item.setData(QtCore.Qt.UserRole, o.Name)
                self.form.Vectors.addItem(item)
                names.append(o.Name)
        self.pageGetFields()

    def _remove_vectors(self):
        for item in self.form.Vectors.selectedItems():
            self.form.Vectors.takeItem(self.form.Vectors.row(item))
        self.pageGetFields()

    def getFields(self, obj):
        super().getFields(obj)
        name = self.form.ImagePlane.currentData()
        link = obj.Document.getObject(name) if name else None
        if link is not None and obj.ImagePlane != link:
            obj.ImagePlane = link
        pattern = self.form.Pattern.currentText()
        if pattern in obj.getEnumerationsOfProperty("Pattern") and obj.Pattern != pattern:
            obj.Pattern = pattern
        vectors = [o for o in map(obj.Document.getObject, self._vector_names()) if o is not None]
        if vectors != list(obj.Vectors):
            obj.Vectors = vectors
        if obj.Contrast != self.form.Contrast.value():
            obj.Contrast = self.form.Contrast.value()
        for prop in ("Invert", "BandAverage"):
            if getattr(obj, prop) != getattr(self.form, prop).isChecked():
                setattr(obj, prop, getattr(self.form, prop).isChecked())

    def setFields(self, obj):
        super().setFields(obj)
        combo, link = self.form.ImagePlane, obj.ImagePlane
        planes = [o for o in obj.Document.Objects if o.TypeId == "Image::ImagePlane"]
        if link not in planes:  # keep an unlisted (or empty) link instead of rewriting it
            planes.insert(0, link)
        combo.blockSignals(True)
        combo.clear()
        for plane in planes:
            combo.addItem(plane.Label if plane else "", plane.Name if plane else "")
        combo.setCurrentIndex(planes.index(link))
        combo.blockSignals(False)
        pattern = self.form.Pattern
        pattern.blockSignals(True)
        pattern.clear()
        pattern.addItems(obj.getEnumerationsOfProperty("Pattern"))
        pattern.setCurrentText(obj.Pattern)
        pattern.blockSignals(False)
        self.form.Vectors.clear()
        for o in obj.Vectors:
            item = QtGui.QListWidgetItem(o.Label)
            item.setData(QtCore.Qt.UserRole, o.Name)
            self.form.Vectors.addItem(item)
        self.form.Contrast.setValue(obj.Contrast)
        self.form.Invert.setChecked(obj.Invert)
        self.form.BandAverage.setChecked(obj.BandAverage)
        self._show_pattern()

    def getSignalsForUpdate(self, obj):
        return super().getSignalsForUpdate(obj) + [
            self.form.ImagePlane.currentIndexChanged, self.form.Pattern.currentIndexChanged,
            self.form.Contrast.editingFinished, self.form.Invert.stateChanged, self.form.BandAverage.stateChanged]

    def registerSignalHandlers(self, obj):
        self.form.Pattern.currentIndexChanged.connect(self._show_pattern)
        self.form.addVectors.clicked.connect(self._add_vectors)
        self.form.removeVectors.clicked.connect(self._remove_vectors)
