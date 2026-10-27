# SPDX-License-Identifier: LGPL-2.1-or-later
# Authors: alf and Claude (Anthropic)
"""The V-Carve Inlay dialog: the few numbers that set up a pocket and its plug."""
import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtGui

from ..geom import inlay_defaults, plug_errors, surface_gap
from ..op_vcarve import tool_vbit

translate = App.Qt.translate
_BOUNDARY = [("Margin", "Saw the plug free inside a ring (Margin)"),
             ("Stock", "Clear the whole plug board, takes longer (Stock)")]


def _mm(low, high):
    box = QtGui.QDoubleSpinBox()
    box.setDecimals(2)
    box.setRange(low, high)
    box.setSingleStep(0.1)
    box.setSuffix(" mm")
    return box


class InlayDialog(QtGui.QDialog):
    def __init__(self, job, vtcs, etcs):
        super().__init__(Gui.getMainWindow())
        self.setWindowTitle(translate("CAM_VCarve", "V-Carve Inlay"))
        self.vtcs, self.etcs = list(vtcs), list(etcs)
        form = QtGui.QFormLayout(self)
        self.vbit, self.endmill = QtGui.QComboBox(), QtGui.QComboBox()
        self.vbit.addItems([tc.Label for tc in self.vtcs])
        self.endmill.addItems([tc.Label for tc in self.etcs])
        self.rest = QtGui.QComboBox()
        self.rest.addItem(translate("CAM_VCarve", "None"), None)
        for tc in self.etcs:
            self.rest.addItem(tc.Label, tc)
        self.pocket, self.glue = _mm(0.1, 100), _mm(0.01, 100)
        self.boundary = QtGui.QComboBox()
        for key, text in _BOUNDARY:
            self.boundary.addItem(translate("CAM_VCarve", text), key)
        self.ridge = QtGui.QCheckBox(translate("CAM_VCarve", "Ridge pass"))
        self.ridge.setChecked(True)
        self.error = QtGui.QLabel()
        self.error.setWordWrap(True)
        self.error.setStyleSheet("color: #cc0000")
        hint = QtGui.QLabel(translate("CAM_VCarve", "Advanced: edit the op properties afterwards"))
        self.buttons = QtGui.QDialogButtonBox(QtGui.QDialogButtonBox.Ok | QtGui.QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        for label, widget in (("V-bit", self.vbit), ("End mill", self.endmill), ("Rest end mill", self.rest), ("Pocket depth", self.pocket),
                              ("Glue gap", self.glue), ("Plug boundary", self.boundary)):
            form.addRow(translate("CAM_VCarve", label), widget)
        for widget in (self.ridge, self.error, hint, self.buttons):
            form.addRow(widget)
        self.vbit.currentIndexChanged.connect(self._reset)
        self.endmill.currentIndexChanged.connect(self._check)
        self.rest.currentIndexChanged.connect(self._check)
        self.pocket.valueChanged.connect(self._check)
        self.glue.valueChanged.connect(self._check)
        self._reset()

    def _vbit(self):
        return tool_vbit(self.vtcs[self.vbit.currentIndex()])

    def _reset(self):
        p, g, _ = inlay_defaults(self._vbit())
        self.pocket.setValue(p)
        self.glue.setValue(g)
        self._check()

    def _check(self):
        vbit, p, g = self._vbit(), self.pocket.value(), self.glue.value()
        errors = plug_errors(vbit, p, g, surface_gap(vbit, p, g))
        if p - g >= vbit.cone_height:
            errors.append(translate("CAM_VCarve", "Pocket depth - Glue Gap must stay below the V-bit cone height "
                                    "{:.2f} mm.").format(vbit.cone_height))
        rest = self.rest.currentData()
        if rest is not None and rest.Tool.Diameter >= self.etcs[self.endmill.currentIndex()].Tool.Diameter:
            errors.append(translate("CAM_VCarve", "The rest end mill must be smaller than the end mill"))
        self.error.setText("\n".join(errors))
        self.buttons.button(QtGui.QDialogButtonBox.Ok).setEnabled(not errors)

    def values(self):
        return dict(vtc=self.vtcs[self.vbit.currentIndex()], etc=self.etcs[self.endmill.currentIndex()],
                    pocket_depth=self.pocket.value(), glue_gap=self.glue.value(),
                    boundary=self.boundary.currentData(), ridge=self.ridge.isChecked(),
                    rest_etc=self.rest.currentData())
