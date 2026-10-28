# SPDX-License-Identifier: LGPL-2.1-or-later
# Authors: alf and Claude (Anthropic)
"""Builds the guide's examples in a real FreeCAD window and saves its screenshots to docs/guide/images.

    python3 docs/guide/make_screenshots.py /path/to/squashfs-root/AppRun

FreeCAD gets a throwaway user home with this repo linked as its only addon, so the shots show default
preferences and your own FreeCAD configuration is untouched. Windows open on your desktop for a few minutes.
The relief images are rendered from the toolpaths with the addon's own cut simulation (vcarve_flat.fit)."""
import os
import sys
import tempfile
import traceback
from pathlib import Path

# No notification popups over the 3D view.
USER_CFG = """<?xml version="1.0" encoding="UTF-8" standalone="no" ?>
<FCParameters><FCParamGroup Name="Root"><FCParamGroup Name="BaseApp"><FCParamGroup Name="Preferences">
<FCParamGroup Name="NotificationArea"><FCBool Name="NotificationAreaEnabled" Value="0"/></FCParamGroup>
</FCParamGroup></FCParamGroup></FCParamGroup></FCParameters>
"""


def launch(apprun):
    import subprocess
    here = Path(__file__).resolve().parent
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp, "home")
        (home / "Mod").mkdir(parents=True)
        (home / "Mod" / "freecad-vcarve").symlink_to(here.parent.parent)
        cfg = Path(tmp, "user.cfg")
        cfg.write_text(USER_CFG)
        env = dict(os.environ, HOME=tmp, FREECAD_USER_HOME=str(home), FREECAD_USER_DATA=str(home),
                   FREECAD_USER_TEMP=str(Path(tmp, "temp")), XDG_CONFIG_HOME=str(Path(tmp, "xdg")),
                   XDG_DATA_HOME=str(Path(tmp, "xdg")), XDG_CACHE_HOME=str(Path(tmp, "xdg")),
                   LANG="en_US.UTF-8", LC_ALL="en_US.UTF-8", VCARVE_SHOTS=str(here / "images"),
                   VCARVE_SHOTS_LOG=str(Path(tmp, "shots.log")))
        (here / "images").mkdir(exist_ok=True)
        res = subprocess.run([apprun, "freecad", "-u", str(cfg), __file__], env=env, cwd=tmp, timeout=900,
                             capture_output=True, text=True)
        log = Path(tmp, "shots.log")
        result = log.read_text() if log.exists() else f"FreeCAD exited with {res.returncode}:\n{res.stderr[-3000:]}"
        print(result)
        sys.exit(0 if result == "SHOTS-OK\n" else 1)


try:
    import FreeCAD as App
except ImportError:
    if __name__ == "__main__":
        launch(sys.argv[1])
    raise SystemExit

import FreeCADGui as Gui
import numpy as np
import Part
from pivy import coin
from PySide import QtCore, QtGui

OUT = os.environ["VCARVE_SHOTS"]
REPO = os.path.join(os.environ["FREECAD_USER_HOME"], "Mod", "freecad-vcarve")
sys.path.insert(0, os.path.join(REPO, "tests", "fc"))
WOOD = np.array([236, 214, 172])  # maple


def settle(ms=500):
    loop = QtCore.QEventLoop()
    QtCore.QTimer.singleShot(ms, loop.quit)
    loop.exec_()


def window(name, panel=False):
    """Grab the main window, the model fitted into the 3D view (left of the task panel with panel)."""
    Gui.SendMsgToActiveView("ViewFit")
    if panel:
        v = Gui.ActiveDocument.ActiveView
        cam = v.getCameraNode()
        w, h = v.getSize()
        cam.height.setValue(cam.height.getValue() * 1.3)
        right = cam.orientation.getValue().multVec(coin.SbVec3f(1, 0, 0))
        d = 0.14 * cam.height.getValue() * w / h
        p = cam.position.getValue()
        cam.position.setValue(*(p[i] + right[i] * d for i in range(3)))
    settle()
    Gui.getMainWindow().grab().save(os.path.join(OUT, name + ".png"))


def view3d(name, view="Isometric", w=1200, h=800):
    v = Gui.ActiveDocument.ActiveView
    getattr(v, "view" + view)()
    v.fitAll()
    settle()
    v.saveImage(os.path.join(OUT, name + ".png"), w, h, "Current")


def tool(doc, job, bit, label, **dims):
    import Path.Tool.Controller as Controller
    from helpers import _tool
    tc = Controller.Create(label, tool=_tool(doc, bit))
    for k, v in dims.items():
        setattr(tc.Tool, k, v)
    tc.Label = label
    job.Proxy.addToolController(tc)
    return tc


def new_job(doc, models):
    import Path.Main.Gui.Job as JobGui
    job = JobGui.Create(models, None, False)
    for tc in list(job.Tools.Group):  # the default end mill
        bit = tc.Tool
        doc.removeObject(tc.Name)
        doc.removeObject(bit.Name)
    tool(doc, job, "60degree_Vbit", "60° V-bit", TipDiameter=0.1)
    tool(doc, job, "5mm_Endmill", "3.175 mm end mill", Diameter=3.175)
    doc.recompute()
    return job


def expand(*objs):
    for obj in objs:
        Gui.ActiveDocument.toggleTreeItem(obj, 2)


def relief(name, ops, top, bounds, grid=0.12, mirror=False):
    """A shaded picture of the board after ops, from the simulated cut heights."""
    from helpers import write_png
    from vcarve_flat.fit import cut_height, op_paths
    x0, y0, x1, y1 = bounds
    X, Y = np.meshgrid(np.arange(x0, x1, grid), np.arange(y1, y0, -grid))  # row 0 on top
    z = cut_height(op_paths(*ops, top=top), np.column_stack([X.ravel(), Y.ravel()])).reshape(X.shape)
    dzdy, dzdx = np.gradient(z, grid)
    n = np.dstack([-dzdx, dzdy, np.ones_like(z)])  # rows run down, so +y is -row
    n /= np.linalg.norm(n, axis=2, keepdims=True)
    light = np.array([-1.0, 1.0, 1.4]) / np.linalg.norm([-1.0, 1.0, 1.4])
    shade = 0.3 + 0.7 * np.clip(n @ light, 0, 1) / light[2]
    shade *= 1 - 0.25 * np.clip(-z / max(-z.min(), 1e-9), 0, 1)  # deeper is darker
    pixels = np.clip(WOOD * shade[..., None], 0, 255)
    write_png(os.path.join(OUT, name + ".png"), pixels[:, ::-1] if mirror else pixels)


def text_example():
    import Draft
    doc = App.newDocument("Sign")
    font = os.path.join(App.getHomePath(), "fonts", "Ubuntu-B.ttf")
    text = Draft.make_shapestring("Maple", font, 25)
    doc.recompute()
    sk = Draft.make_sketch(text, autoconstraints=False)
    sk.Label = "Maple"
    doc.removeObject(text.Name)
    doc.recompute()
    window("text-1-sketch")
    job = new_job(doc, [sk])
    expand(job)
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(job.Model.Group[0])
    Gui.runCommand("CAM_VCarvePair")
    settle()
    vcarve = job.Operations.Group[-1]
    panel = vcarve.ViewObject.Proxy.panel
    page = next(p for p in panel.featurePages if hasattr(p.form, "FlatDepth"))
    page.form.FlatDepth.setProperty("rawValue", 1.0)
    Gui.Selection.clearSelection()
    window("text-2-panel", panel=True)
    for p in panel.featurePages:
        p.setDirty()
    panel.accept()
    doc.recompute()
    expand(job.Operations)
    window("text-3-ops")
    sk.ViewObject.Visibility = False
    view3d("text-4-paths", "Top")
    bb = sk.Shape.BoundBox
    relief("text-5-relief", list(job.Operations.Group), vcarve.StartDepth.Value,
           (bb.XMin - 3, bb.YMin - 3, bb.XMax + 3, bb.YMax + 3))
    close(doc)


def close(doc):
    App.closeDocument(doc.Name)
    settle()


def heart(doc):
    from helpers import make_sketch
    sk = make_sketch(doc, "Heart", [])
    V = App.Vector
    a = np.arcsin(4 / 15)  # the arcs end 4 mm up, joined by a V notch: a cusp would not fit as an inlay
    x = 15 - 15 * np.cos(a)
    sk.addGeometry(Part.ArcOfCircle(Part.Circle(V(-15, 0, 0), V(0, 0, 1), 15), a, np.pi))
    sk.addGeometry(Part.LineSegment(V(-30, 0, 0), V(0, -38, 0)))
    sk.addGeometry(Part.LineSegment(V(0, -38, 0), V(30, 0, 0)))
    sk.addGeometry(Part.ArcOfCircle(Part.Circle(V(15, 0, 0), V(0, 0, 1), 15), 0, np.pi - a))
    sk.addGeometry(Part.LineSegment(V(x, 4, 0), V(0, -1, 0)))
    sk.addGeometry(Part.LineSegment(V(0, -1, 0), V(-x, 4, 0)))
    doc.recompute()
    return sk


def inlay_example():
    import PathScripts.PathUtils as PathUtils
    from vcarve_flat.gui import inlay_dialog
    doc = App.newDocument("Inlay")
    sk = heart(doc)
    job = new_job(doc, [sk])
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(job.Model.Group[0])

    def snap():
        dialog = QtGui.QApplication.activeModalWidget()
        if not isinstance(dialog, inlay_dialog.InlayDialog):
            return QtCore.QTimer.singleShot(200, snap)
        dialog.grab().save(os.path.join(OUT, "inlay-1-dialog.png"))
        dialog.accept()
    QtCore.QTimer.singleShot(800, snap)
    Gui.runCommand("CAM_VCarveInlay")
    doc.recompute()
    pocket_job, plug_job = [j for j in PathUtils.GetJobs() if j.Document == doc and j != job]
    Gui.ActiveDocument.toggleTreeItem(job, 1)
    job.ViewObject.Visibility = False
    expand(pocket_job, plug_job, pocket_job.Operations, plug_job.Operations)
    for j in (pocket_job, plug_job):
        for o in (j.Model, j.Tools):
            Gui.ActiveDocument.toggleTreeItem(o, 1)
    Gui.Selection.clearSelection()
    window("inlay-2-jobs")
    plug = next(o for o in plug_job.Operations.Group if hasattr(o, "PocketOp"))
    Gui.Selection.addSelection(plug)
    Gui.runCommand("CAM_VCarveFit")
    doc.recompute()
    Gui.Selection.clearSelection()
    report = Gui.getMainWindow().findChild(QtGui.QDockWidget, "Report view")
    report.show()
    for j in (job, pocket_job, plug_job):
        j.ViewObject.Visibility = False
    window("inlay-3-fit")
    report.hide()
    bb = sk.Shape.BoundBox
    pocket = list(pocket_job.Operations.Group)
    relief("inlay-4-pocket", pocket, pocket[-1].StartDepth.Value,
           (bb.XMin - 5, bb.YMin - 5, bb.XMax + 5, bb.YMax + 5))
    m = plug.PlugMargin.Value + 3
    relief("inlay-5-plug", list(plug_job.Operations.Group), plug.StartDepth.Value,
           (bb.XMin - m, bb.YMin - m, bb.XMax + m, bb.YMax + m))
    close(doc)


def photo_image(path, n=360):
    """A lit sphere and its shadow on white: every grey from highlight to black."""
    from helpers import write_png
    y, x = (np.mgrid[0:n, 0:n] + 0.5) / n * 2 - 1
    img = np.ones((n, n))
    shadow = ((x - 0.25) / 0.75) ** 2 + ((y - 0.62) / 0.22) ** 2
    img = np.where(shadow < 1, 0.75 + 0.25 * shadow, img)
    cx, cy, r = -0.08, -0.12, 0.62
    d2 = ((x - cx) ** 2 + (y - cy) ** 2) / r ** 2
    nz = np.sqrt(np.clip(1 - d2, 0, 1))
    lit = np.clip(((x - cx) / r * -0.5 + (y - cy) / r * -0.6 + nz * 0.62), 0, 1)
    img = np.where(d2 < 1, 0.04 + 0.96 * lit ** 0.6, img)
    write_png(path, np.repeat((img * 255)[..., None], 3, axis=2))


def photo_example():
    doc = App.newDocument("Photo")
    board = doc.addObject("Part::Box", "Board")
    board.Length = board.Width = 100
    board.Height = 12
    path = os.path.join(OUT, "photo-0-image.png")
    photo_image(path)
    plane = doc.addObject("Image::ImagePlane", "Sphere")
    plane.ImageFile = path
    plane.XSize = plane.YSize = 90
    plane.Placement.Base = App.Vector(50, 50, 12.05)
    doc.recompute()
    job = new_job(doc, [board])
    job.Model.Group[0].ViewObject.Visibility = False
    expand(job)
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(plane)
    Gui.runCommand("CAM_VCarvePhoto")
    settle()
    op = job.Operations.Group[-1]
    Gui.Selection.clearSelection()
    window("photo-1-panel", panel=True)
    panel = op.ViewObject.Proxy.panel
    for p in panel.featurePages:
        p.setDirty()
    panel.accept()
    doc.recompute()
    plane.ViewObject.Visibility = False
    view3d("photo-2-paths", "Top")
    relief("photo-3-relief", [op], op.StartDepth.Value, (5, 5, 95, 95), grid=0.15)
    op.Pattern = "Hatch"
    doc.recompute()
    relief("photo-4-hatch", [op], op.StartDepth.Value, (5, 5, 95, 95), grid=0.15)


def run():
    try:
        mw = Gui.getMainWindow()
        mw.showNormal()
        mw.resize(1440, 900)
        Gui.activateWorkbench("CAMWorkbench")
        settle(1000)
        for sp in mw.findChildren(QtGui.QSplitter):  # the model tree over the property view
            if sp.orientation() == QtCore.Qt.Vertical and sp.findChild(QtGui.QTreeWidget):
                sp.setSizes([560, 140])
        bar = next(b for b in mw.findChildren(QtGui.QToolBar) if b.objectName() == "New Operations")
        ours = [bar.widgetForAction(a).geometry() for a in bar.actions()
                if str(a.objectName()).startswith("CAM_VCarve") and bar.widgetForAction(a)]
        rect = ours[0]
        for r in ours[1:]:
            rect = rect.united(r)
        bar.grab(rect.adjusted(-4, -4, 4, 4)).save(os.path.join(OUT, "install-toolbar.png"))
        for example in (text_example, inlay_example, photo_example):
            example()
        result = "SHOTS-OK\n"
    except BaseException:
        result = traceback.format_exc()
    with open(os.environ["VCARVE_SHOTS_LOG"], "a") as f:
        f.write(result)
    for d in list(App.listDocuments()):  # else FreeCAD asks to save them
        App.closeDocument(d)
    os._exit(0)


QtCore.QTimer.singleShot(0, run)
