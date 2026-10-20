# SPDX-License-Identifier: LGPL-2.1-or-later
"""Offscreen GUI check, run as: freecad tests/gui/check_gui.py (see tests/test_gui.py).
Prints GUI-CHECK-OK and exits 0 on success; prints the traceback and exits 1 otherwise."""
import os
import sys
import tempfile
import traceback

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui

# The addon link made by tests/test_gui.py; gives the test helpers without relying on __file__.
sys.path.insert(0, os.path.join(os.environ["FREECAD_USER_HOME"], "Mod", "freecad-vcarve", "tests", "fc"))
NAMES = ["CAM_VCarveFlat", "CAM_VCarveClearance", "CAM_VCarvePair"]


def toolbar_entries(title):
    bars = [b for b in Gui.getMainWindow().findChildren(QtGui.QToolBar) if b.objectName() == title]
    assert bars, f"no toolbar {title!r}"
    return {str(v) for a in bars[0].actions() for v in (a.objectName(), a.data(), a.text()) if v}


def check_icons(ops):
    for op in ops:
        path = op.ViewObject.Proxy.getIcon()
        assert os.path.isfile(path), f"{op.Label}: icon {path!r} missing"


def edit(op):
    op.ViewObject.Document.setEdit(op.ViewObject, 0)
    assert Gui.Control.activeDialog(), f"{op.Label}: no task panel"
    Gui.Control.closeDialog()
    Gui.ActiveDocument.resetEdit()
    QtGui.QApplication.processEvents()  # let the closed panel go before the next one opens


def main():
    home = os.path.realpath(os.environ["FREECAD_USER_HOME"])
    data = os.path.realpath(App.getUserAppDataDir())
    assert data.startswith(home), f"FREECAD_USER_HOME not honored: user data dir is {data}"

    Gui.activateWorkbench("CAMWorkbench")
    QtGui.QApplication.processEvents()
    missing = [n for n in NAMES if n not in Gui.listCommands()]
    assert not missing, f"commands not registered: {missing}"
    entries = toolbar_entries("New Operations")
    for name in NAMES:
        text = Gui.Command.get(name).getInfo()["menuText"]
        assert name in entries or text in entries, f"{name} not in toolbar: {sorted(entries)}"

    import Path.Main.Gui.Job as JobGui
    import Path.Tool.Controller as Controller
    import PathScripts.PathUtils as PathUtils
    from helpers import _tool, make_sketch

    doc = App.newDocument("guicheck")
    sk = make_sketch(doc, "Letters", [[(0, 0), (40, 0), (40, 20), (0, 20)]])
    job = JobGui.Create([sk], None, False)
    for bit in ("60degree_Vbit", "5mm_Endmill"):
        job.Proxy.addToolController(Controller.Create(bit, tool=_tool(doc, bit)))
    doc.recompute()
    clone = job.Model.Group[0]
    inactive = [n for n in NAMES if not Gui.Command.get(n).isActive()]
    assert not inactive, f"commands inactive with a Job: {inactive}"

    from vcarve_flat.gui import commands
    warnings = []
    commands._warn = warnings.append  # record instead of a modal message box
    stray = make_sketch(doc, "Stray", [[(50, 0), (60, 0), (60, 10), (50, 10)]])  # not in the Job
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(sk)
    Gui.Selection.addSelection(stray)
    Gui.runCommand("CAM_VCarvePair")
    QtGui.QApplication.processEvents()
    assert len(warnings) == 1 and "Stray" in warnings[0] and "Letters" not in warnings[0], warnings
    ops = list(job.Operations.Group)
    assert len(ops) == 2, f"expected 2 ops, got {[o.Label for o in ops]}"
    clr, vc = ops
    assert getattr(clr, "VCarveOp", None) == vc, "clearance op is not first or not linked"
    assert list(vc.BaseShapes) == [clone], f"BaseShapes {[o.Label for o in vc.BaseShapes]}"
    assert Gui.Control.activeDialog(), "no task panel for the V-carve op"
    check_icons(ops)
    Gui.Control.closeDialog()
    Gui.ActiveDocument.resetEdit()
    edit(clr)  # clearance page

    def accept_clearance():
        clr.ViewObject.Document.setEdit(clr.ViewObject, 0)
        panel = clr.ViewObject.Proxy.panel
        for page in panel.featurePages:  # as after editing any field: OK writes every page back
            page.setDirty()
        panel.accept()
        QtGui.QApplication.processEvents()  # let the closed panel go before the next one opens

    clr.ViewObject.Document.setEdit(clr.ViewObject, 0)  # no base geometry: no selection gate
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(job.Stock)
    assert Gui.Selection.getSelection() == [job.Stock], "clearance panel gates the selection"
    clr.ViewObject.Proxy.panel.reject()
    QtGui.QApplication.processEvents()
    for link in (None, stray):  # a link the combo does not list must survive OK
        clr.VCarveOp = link
        accept_clearance()
        assert clr.VCarveOp == link, f"VCarveOp {link and link.Name} rewritten to {clr.VCarveOp.Name}"
    clr.VCarveOp = vc
    accept_clearance()
    assert clr.VCarveOp == vc

    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(sk, "Vertex1")
    base, warnings[:] = list(vc.Base), []
    commands._add_selection(vc, job)
    assert list(vc.Base) == base and len(warnings) == 1 and "vertices" in warnings[0], warnings

    count, objects = len(job.Operations.Group), len(doc.Objects)
    commands._add_selection = lambda op, job: 1 / 0
    try:
        commands.register()["CAM_VCarvePair"].Activated()
        raise AssertionError("pair command swallowed the error")
    except ZeroDivisionError:
        pass
    assert len(job.Operations.Group) == count and len(doc.Objects) == objects, \
        f"failed pair creation left objects: {[o.Name for o in doc.Objects]}"

    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(clone, "Edge1")
    Gui.runCommand("CAM_VCarveFlat")
    QtGui.QApplication.processEvents()
    single = job.Operations.Group[-1]
    assert len(job.Operations.Group) == 3 and single.Base and single.Base[0][0] == clone, \
        f"CAM_VCarveFlat base: {single.Base}"
    single.ViewObject.Proxy.panel.accept()  # OK keeps the op (Cancel deletes a new one)

    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(sk)  # the original sketch must be mapped to the Job's clone
    Gui.runCommand("CAM_VCarveFlat")
    QtGui.QApplication.processEvents()
    whole = job.Operations.Group[-1]
    assert len(job.Operations.Group) == 4 and list(whole.BaseShapes) == [clone], \
        f"CAM_VCarveFlat BaseShapes: {[o.Name for o in whole.BaseShapes]}"
    whole.ViewObject.Proxy.panel.accept()

    path = os.path.join(tempfile.mkdtemp(), "guicheck.FCStd")
    doc.saveAs(path)
    App.closeDocument(doc.Name)
    doc = App.openDocument(path)
    ops = list(PathUtils.GetJobs()[0].Operations.Group)
    check_icons(ops)
    for op in ops:
        edit(op)

    job = PathUtils.GetJobs()[0]  # last: after its panel, 1.0.2 hangs closing the next one
    job.ViewObject.Document.setEdit(job.ViewObject, 0)  # its Setup tab lists the registered ops' defaults
    job.ViewObject.Proxy.taskPanel.reject()  # Cancel


def run():
    try:
        main()
        print("GUI-CHECK-OK", file=sys.__stdout__, flush=True)
        code = 0
    except BaseException:
        traceback.print_exc(file=sys.__stdout__)
        sys.__stdout__.flush()
        code = 1
    os._exit(code)


QtCore.QTimer.singleShot(0, run)
