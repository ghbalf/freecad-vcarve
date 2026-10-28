# SPDX-License-Identifier: LGPL-2.1-or-later
# Authors: alf and Claude (Anthropic)
"""Offscreen GUI check, run as: freecad tests/gui/check_gui.py (see tests/test_gui.py).
Prints GUI-CHECK-OK and exits 0 on success; prints the traceback and exits 1 otherwise."""
import os
import sys
import tempfile
import time
import types
import traceback
from unittest import mock

import FreeCAD as App
import FreeCADGui as Gui
import numpy as np
import Part
import Path
from PySide import QtCore, QtGui

# The addon link made by tests/test_gui.py; gives the test helpers without relying on __file__.
sys.path.insert(0, os.path.join(os.environ["FREECAD_USER_HOME"], "Mod", "freecad-vcarve", "tests", "fc"))
NAMES = ["CAM_VCarveFlat", "CAM_VCarveClearance", "CAM_VCarvePair", "CAM_VCarvePlug", "CAM_VCarveInlay",
         "CAM_VCarveFit", "CAM_VCarvePhoto"]


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


def press_esc():
    QtGui.QApplication.sendEvent(Gui.getMainWindow(), QtGui.QKeyEvent(QtCore.QEvent.KeyPress, QtCore.Qt.Key_Escape,
                                                                      QtCore.Qt.NoModifier))


def spin(progress):
    """Steps for up to 5 s; the time until Cancelled."""
    t0 = time.monotonic()
    try:
        with progress.task("GUI check"):
            while time.monotonic() - t0 < 5:
                progress.step()
                time.sleep(0.01)
    except progress.Cancelled:
        return time.monotonic() - t0
    raise AssertionError("Esc did not cancel")


def check_progress(doc):
    """Events flow and Esc cancels, on its own and inside a recompute (where FreeCAD's sequencer ignores ours),
    there with no prompt of FreeCAD's and for the recompute's later objects too."""
    from vcarve_flat import progress
    fired, asked = [], []

    def answer():  # FreeCAD's "abort the rest of the recompute?" must not show
        box = QtGui.QApplication.activeModalWidget()
        if isinstance(box, QtGui.QMessageBox):
            asked.append(box.text())
            box.button(QtGui.QMessageBox.No).click()
    closer = QtCore.QTimer()
    closer.timeout.connect(answer)
    closer.start(50)
    QtCore.QTimer.singleShot(0, lambda: fired.append(1))
    QtCore.QTimer.singleShot(300, press_esc)
    assert spin(progress) < 2 and fired and not asked, (fired, asked)

    order = []  # the first object recomputed gets the Esc

    class Slow:
        def __init__(self, obj):
            obj.Proxy, self.took = self, None

        def execute(self, obj):
            if not order:
                QtCore.QTimer.singleShot(300, press_esc)
            order.append(obj)
            self.took = spin(progress)

    slow = [doc.addObject("App::FeaturePython", f"Slow{i}") for i in range(3)]
    for obj in slow:
        Slow(obj)
    doc.recompute()
    closer.stop()
    took = [obj.Proxy.took for obj in order]
    assert not asked, asked
    assert len(took) == 3 and took[0] < 2 and max(took[1:]) < 0.1, took
    t0 = time.monotonic()
    while progress.cancelled() and time.monotonic() - t0 < 2:  # held until the event loop runs
        QtGui.QApplication.processEvents()
        time.sleep(0.01)
    assert not progress.cancelled()
    for obj in slow:
        doc.removeObject(obj.Name)
    # Steps stay cheap however slow FreeCAD's indicator and event processing are (1.1 offscreen: 0.35 s a beat)
    QtGui.QApplication.processEvents()
    with progress.task("GUI check"):
        t0, slept = time.monotonic(), 0.0
        while time.monotonic() - t0 < 2:
            progress.step()
            t = time.monotonic()
            time.sleep(0.002)
            slept += time.monotonic() - t
    assert slept > 1, slept  # of the 2 s; 0.12 s when every step beat the indicator
    # FreeCAD 26's Part booleans stop the running sequencer, whose bar then never showed
    bars = Gui.getMainWindow().statusBar().findChildren(QtGui.QProgressBar)
    assert bars, "no progress bar in the status bar"
    with progress.task("GUI check"):
        Part.makeBox(5, 5, 5).cut(Part.makeCylinder(1, 9))
        t0, shown = time.monotonic(), False
        while time.monotonic() - t0 < 4 and not shown:
            progress.step()
            time.sleep(0.01)
            shown = any(b.isVisible() for b in bars)
    assert shown, "no progress bar after a Part boolean"


def check_tree(doc, jobs):
    """Each Job shows its Operations, Model, Tools, Stock and SetupSheet nested below it, not beside it."""
    QtGui.QApplication.processEvents()
    tree = next(t for t in Gui.getMainWindow().findChildren(QtGui.QTreeWidget) if t.topLevelItemCount())
    root = next(tree.topLevelItem(i) for i in range(tree.topLevelItemCount())
                if tree.topLevelItem(i).text(0) == doc.Label)
    top = [root.child(i).text(0) for i in range(root.childCount())]
    loose = [o.Label for j in jobs for o in j.OutList if o.Label in top]
    assert not loose, f"Job children at the document's top level: {loose}"


def check_fit(doc, plug):
    """Check Inlay Fit: one Fit object per inlay, its squares red (collisions) and blue (voids)."""
    from vcarve_flat import fit, fit_object
    from vcarve_flat.gui import commands

    def fits():
        return fit_object.find(doc)
    Gui.Selection.clearSelection()
    with mock.patch.object(Path.Log, "error") as error:
        Gui.runCommand("CAM_VCarveFit")
        assert "Select the plug" in str(error.call_args), error.call_args
        Gui.Selection.addSelection(plug)
        for _ in range(2):
            Gui.runCommand("CAM_VCarveFit")
            QtGui.QApplication.processEvents()
            assert len(fits()) == 1, [o.Label for o in fits()]
        assert error.call_count == 1, error.call_args_list
    obj = fits()[0]
    assert isinstance(obj.ViewObject.Proxy, commands.FitViewProvider), obj.ViewObject.Proxy
    assert os.path.isfile(obj.ViewObject.Proxy.getIcon())
    assert not {"Invalid", "Touched"} & set(obj.State), obj.State
    Gui.Selection.clearSelection()

    pts = np.array([(x, y) for x in range(4) for y in range(3)], float)  # both colours, however the inlay fits
    hits = pts[:, 0] < 1
    result = fit.FitResult(pts, 1.0, np.zeros(len(pts)), np.zeros(len(pts)), hits, ~hits, -0.1, 0.3, fit.chain(plug))
    made = fit_object.create(doc, plug, result)
    commands._show_fit(made)
    colours = [tuple(round(c, 2) for c in m.DiffuseColor[:3]) for m in made.ViewObject.ShapeAppearance]
    n = len(made.Shape.SubShapes[0].Faces)
    assert n and len(made.Shape.Faces) > n, [len(s.Faces) for s in made.Shape.SubShapes]
    assert colours == [(1, 0, 0)] * n + [(0, 0.3, 1)] * (len(made.Shape.Faces) - n), colours
    opaque = [(m.Transparency, m.DiffuseColor[3]) for m in made.ViewObject.ShapeAppearance]
    assert made.ViewObject.Transparency == 0 and all(a == 1 for _, a in opaque), (made.ViewObject.Transparency, opaque)
    doc.removeObject(made.Name)
    none = np.zeros(len(pts), bool)  # a fitting inlay: no faces, no colours
    made = fit_object.create(doc, plug, fit.FitResult(pts, 1.0, none * 0., none * 0., none, none, 0., 0., result.ops))
    commands._show_fit(made)
    QtGui.QApplication.processEvents()
    assert not made.Shape.Faces and isinstance(made.ViewObject.Proxy, commands.FitViewProvider)
    doc.removeObject(made.Name)


def check_photo(doc, job):
    """V-Carve Photo: the panel lists the image plane, the fields follow the pattern, OK carves."""
    from helpers import make_plane
    from vcarve_flat.gui import panels
    from vcarve_flat.op_photo import ObjectVCarvePhoto
    plane = make_plane(doc, os.path.join(tempfile.mkdtemp(), "photo.png"), 20, 10, np.zeros((4, 8, 3), np.uint8))
    plane.Placement.Base = App.Vector(20, 10, 0)  # over the Job's 40 x 20 sketch
    doc.recompute()
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(job.Model.Group[0])
    Gui.runCommand("CAM_VCarvePhoto")
    QtGui.QApplication.processEvents()
    op = job.Operations.Group[-1]
    assert isinstance(op.Proxy, ObjectVCarvePhoto), op.Label
    check_icons([op])
    panel = op.ViewObject.Proxy.panel
    page = next(p for p in panel.featurePages if isinstance(p, panels.PhotoOpPage))
    form = page.form
    combo = form.ImagePlane
    assert plane.Label in [combo.itemText(i) for i in range(combo.count())], combo.count()
    combo.setCurrentIndex(combo.findData(plane.Name))
    grid = form.layout()
    rows = [grid.getItemPosition(grid.indexOf(getattr(form, p)))[0] for p in ("MaxDepth", "MinDepth", "LineSpacing")]
    assert rows == sorted(rows), rows  # the depths come before the spacing that follows them

    def hidden():
        fields = ("Angle", "HatchAngle", "LineSpacing", "VectorsBox", "BandAverage")
        return {p for p in fields if getattr(form, p).isHidden()}
    assert hidden() == {"HatchAngle", "VectorsBox"}, hidden()
    form.Pattern.setCurrentText("Hatch")
    assert hidden() == {"VectorsBox"}, hidden()
    form.Pattern.setCurrentText("Custom")
    assert hidden() == {"Angle", "HatchAngle", "LineSpacing", "BandAverage"}, hidden()
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(doc.getObject("Letters"))
    form.addVectors.click()
    assert list(op.Vectors) == [doc.getObject("Letters")], [o.Label for o in op.Vectors]
    form.Vectors.item(0).setSelected(True)
    form.removeVectors.click()
    assert not op.Vectors and not form.Vectors.count(), [o.Label for o in op.Vectors]
    Gui.Selection.clearSelection()
    form.Pattern.setCurrentText("Lines")
    form.BandAverage.setChecked(True)
    for p in panel.featurePages:
        p.setDirty()
    panel.accept()
    QtGui.QApplication.processEvents()
    assert op.ImagePlane == plane and op.Pattern == "Lines" and op.BandAverage, (op.ImagePlane, op.Pattern)
    assert "LineSpacing" in dict(op.ExpressionEngine), op.ExpressionEngine
    assert any(c.Name in ("G1", "G01") for c in op.Path.Commands), "no cut after OK"
    assert not Gui.Control.activeDialog(), "the photo panel stayed open"


def main():
    home = os.path.realpath(os.environ["FREECAD_USER_HOME"])
    data = os.path.realpath(App.getUserAppDataDir())
    assert data.startswith(home), f"FREECAD_USER_HOME not honored: user data dir is {data}"
    # A warning shown as a notification popup deadlocks FreeCAD 1.0 offscreen (see tests/test_gui.py).
    Gui.getMainWindow().activateWindow()
    App.Console.PrintWarning("GUI check: notification probe\n")
    loop = QtCore.QEventLoop()  # past the notification area's 250 ms delay
    QtCore.QTimer.singleShot(1000, loop.quit)
    loop.exec_()

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
    step_down = [p.form.stepDown for p in clr.ViewObject.Proxy.panel.featurePages if hasattr(p.form, "stepDown")]
    assert step_down and all(w.isHidden() for w in step_down), "clearance panel shows Step Down"
    clr.ViewObject.Proxy.panel.reject()
    QtGui.QApplication.processEvents()
    for link in (None, stray):  # a link the combo does not list must survive OK
        clr.VCarveOp = link
        accept_clearance()
        assert clr.VCarveOp == link, f"VCarveOp {link and link.Name} rewritten to {clr.VCarveOp.Name}"
    clr.VCarveOp = vc
    accept_clearance()
    assert clr.VCarveOp == vc
    for rest in (True, False):  # the checkbox shows RestOnly, and OK writes the toggled box back
        clr.RestOnly = rest
        clr.ViewObject.Document.setEdit(clr.ViewObject, 0)
        panel = clr.ViewObject.Proxy.panel
        box = next(p.form.RestOnly for p in panel.featurePages if hasattr(p.form, "RestOnly"))
        assert box.isChecked() == rest, f"RestOnly {rest} shown as {box.isChecked()}; obj {clr.RestOnly}"
        box.setChecked(not rest)
        for page in panel.featurePages:
            page.setDirty()
        panel.accept()
        QtGui.QApplication.processEvents()
        assert clr.RestOnly == (not rest), f"RestOnly not written back: {clr.RestOnly}"

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

    from vcarve_flat.compat import tool_shape
    from vcarve_flat.geom import inlay_defaults
    from vcarve_flat.gui import inlay_dialog, panels
    from vcarve_flat.op_vcarve import tool_vbit
    Gui.Selection.clearSelection()
    warnings[:] = []
    Gui.runCommand("CAM_VCarveInlay")
    assert len(warnings) == 1 and len(PathUtils.GetJobs()) == 1, warnings

    job0 = PathUtils.GetJobs()[0]
    vtc = next(t for t in job0.Tools.Group if tool_shape(t.Tool) == "VBit")
    etc = next(t for t in job0.Tools.Group if tool_shape(t.Tool) == "Endmill")
    narrow = Controller.Create("Narrow", tool=_tool(doc, "60degree_Vbit"))
    narrow.Tool.Diameter = 4
    dialog = inlay_dialog.InlayDialog(job0, [vtc, narrow], [etc])
    ok = dialog.buttons.button(QtGui.QDialogButtonBox.Ok)
    assert dialog.parent() == Gui.getMainWindow(), "dialog has no parent window"
    p, g, _ = inlay_defaults(tool_vbit(vtc))
    assert ok.isEnabled() and not dialog.error.text(), dialog.error.text()
    assert abs(dialog.pocket.value() - p) < 0.01 and abs(dialog.glue.value() - g) < 0.01
    dialog.pocket.setValue(tool_vbit(vtc).cone_height + dialog.glue.value() + 0.1)  # P - G passes the cone height
    assert not ok.isEnabled() and dialog.error.text(), "too deep a pocket is accepted"
    dialog.vbit.setCurrentIndex(1)
    p2, g2, _ = inlay_defaults(tool_vbit(narrow))
    assert abs(p2 - p) > 0.1, "the test V-bits do not differ"
    assert abs(dialog.pocket.value() - p2) < 0.01 and abs(dialog.glue.value() - g2) < 0.01, "V-bit change keeps P and G"
    assert ok.isEnabled() and not dialog.error.text()

    assert dialog.rest.itemText(0) == "None" and dialog.rest.count() == 2 and dialog.values()["rest_etc"] is None
    dialog.rest.setCurrentIndex(1)  # the end mill itself
    assert not ok.isEnabled() and "smaller" in dialog.error.text(), "an equal rest end mill is accepted"
    dialog.rest.setCurrentIndex(0)
    assert ok.isEnabled() and not dialog.error.text()

    check_progress(doc)
    names = [o.Name for o in doc.Objects]
    esc = QtCore.QTimer()
    esc.timeout.connect(press_esc)
    with mock.patch.object(inlay_dialog.InlayDialog, "exec_", lambda self: QtGui.QDialog.Accepted):
        Gui.Selection.addSelection(doc.getObject("Letters"))
        esc.start(50)
        Gui.runCommand("CAM_VCarveInlay")
        esc.stop()
        QtGui.QApplication.processEvents()
    assert [o.Name for o in doc.Objects] == names and len(warnings) == 1, \
        f"cancelled Inlay left {set(o.Name for o in doc.Objects) - set(names)}; {warnings}"
    Gui.Selection.clearSelection()

    ops0, tools0 = list(job0.Operations.Group), list(job0.Tools.Group)
    seen = []
    with mock.patch.object(inlay_dialog.InlayDialog, "exec_",
                           lambda self: seen.append(self.values()) or QtGui.QDialog.Accepted):
        Gui.Selection.addSelection(doc.getObject("Letters"))
        Gui.runCommand("CAM_VCarveInlay")
        QtGui.QApplication.processEvents()
    assert len(warnings) == 1 and len(seen) == 1, warnings
    assert set(seen[0]) == {"vtc", "etc", "pocket_depth", "glue_gap", "boundary", "ridge", "rest_etc"}, seen
    jobs = PathUtils.GetJobs()
    assert len(jobs) == 3, [j.Label for j in jobs]
    assert (list(job0.Operations.Group), list(job0.Tools.Group)) == (ops0, tools0), "Inlay changed the selected Job"
    qjob, pjob = (next(j for j in jobs if j.Label == f"Letters {s}") for s in ("Pocket", "Plug"))
    check_tree(doc, jobs)
    for j in jobs:
        for op in j.Operations.Group:
            want = "Endmill" if hasattr(op, "VCarveOp") else "VBit"
            assert tool_shape(op.ToolController.Tool) == want, f"{j.Label}/{op.Label}: {op.ToolController.Label}"
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(pjob.Model.Group[0])  # the plug Job's clone picks the plug Job
    assert commands._find_job() == pjob, commands._find_job().Label
    pclr, plug = pjob.Operations.Group
    new_ops = [*qjob.Operations.Group, pclr, plug]
    assert all(abs(op.StepDown.Value - 1.5) < 1e-9 for op in new_ops), [op.StepDown for op in new_ops]
    check_icons([pclr, plug])
    assert plug.PocketOp is not None
    page = types.SimpleNamespace(job=pjob)
    assert plug in panels.ClearanceOpPage._vcarve_ops(page), "clearance combo omits the plug op"

    check_fit(doc, plug)
    pocket = plug.PocketOp
    plug.Active = False  # its recompute is slow and not under test
    plug.ViewObject.Document.setEdit(plug.ViewObject, 0)
    assert any(isinstance(p, panels.PlugOpPage) for p in plug.ViewObject.Proxy.panel.featurePages)
    for p in plug.ViewObject.Proxy.panel.featurePages:
        p.setDirty()
    plug.ViewObject.Proxy.panel.accept()
    QtGui.QApplication.processEvents()
    assert plug.PocketOp == pocket, "OK lost PocketOp"

    check_photo(doc, PathUtils.GetJobs()[0])

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
