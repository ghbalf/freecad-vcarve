# SPDX-License-Identifier: LGPL-2.1-or-later
"""V-Carve Flat GUI hook: lightweight commands plus a CAM toolbar/menu manipulator.
The CAM machinery (vcarve_flat.gui.commands) is imported only when a command runs.
FreeCAD execs this file with separate globals and locals: methods must not use its top-level names."""
import FreeCAD
import FreeCADGui

QT_TRANSLATE_NOOP = FreeCAD.Qt.QT_TRANSLATE_NOOP
_COMMANDS = [
    ("CAM_VCarveFlat", "vcarve_flat.svg", QT_TRANSLATE_NOOP("CAM_VCarveFlat", "V-Carve Flat"),
     QT_TRANSLATE_NOOP("CAM_VCarveFlat", "V-carve sketches with a flat floor")),
    ("CAM_VCarveClearance", "vcarve_clearance.svg", QT_TRANSLATE_NOOP("CAM_VCarveClearance", "V-Carve Clearance"),
     QT_TRANSLATE_NOOP("CAM_VCarveClearance", "Clear the flat floor of a V-carve operation with an end mill")),
    ("CAM_VCarvePair", "vcarve_pair.svg", QT_TRANSLATE_NOOP("CAM_VCarvePair", "V-Carve Pair"),
     QT_TRANSLATE_NOOP("CAM_VCarvePair", "Create a clearance op and a V-carve op for the selected sketches")),
    ("CAM_VCarvePlug", "vcarve_plug.svg", QT_TRANSLATE_NOOP("CAM_VCarvePlug", "V-Carve Plug"),
     QT_TRANSLATE_NOOP("CAM_VCarvePlug", "Carve the mirrored plug of a V-carve pocket")),
    ("CAM_VCarveInlay", "vcarve_inlay.svg", QT_TRANSLATE_NOOP("CAM_VCarveInlay", "V-Carve Inlay"),
     QT_TRANSLATE_NOOP("CAM_VCarveInlay", "Set up a V-carve inlay: a new Job for the pocket and a new Job for the plug")),
    ("CAM_VCarveFit", "vcarve_fit.svg", QT_TRANSLATE_NOOP("CAM_VCarveFit", "Check Inlay Fit"),
     QT_TRANSLATE_NOOP("CAM_VCarveFit", "Show where the seated plug would hit the pocket (red) or leave a void (blue)")),
]


class _VCarveCommand:
    def __init__(self, name, icon, menu, tip):
        import os
        import vcarve_flat

        self.name = name
        icon = os.path.join(os.path.dirname(vcarve_flat.__file__), "resources", "icons", icon)
        self.resources = {"Pixmap": icon, "MenuText": menu, "ToolTip": tip}

    def GetResources(self):
        return self.resources

    def IsActive(self):
        import FreeCAD

        doc = FreeCAD.ActiveDocument
        return doc is not None and any(
            o.TypeId == "Path::FeaturePython" and o.Name.startswith("Job") for o in doc.Objects)

    def Activated(self):
        from vcarve_flat.gui.commands import register

        register()[self.name].Activated()


class _CamManipulator:
    """Puts the commands next to CAM's Vcarve in the "New Operations" toolbar and the CAM menu."""

    def __init__(self, names):
        self.names = names

    def modifyToolBars(self):
        # toolItem inserts before the anchor; Vcarve itself sits inside the CAM_EngraveTools group
        return [{"insert": name, "toolItem": "CAM_EngraveTools"} for name in self.names]

    def modifyMenuBar(self):
        names = ["CAM_Vcarve"] + self.names
        return [{"insert": cmd, "menuItem": prev, "after": ""} for prev, cmd in zip(names, names[1:])]


for _cmd in _COMMANDS:
    FreeCADGui.addCommand(_cmd[0], _VCarveCommand(*_cmd))
FreeCADGui.addWorkbenchManipulator(_CamManipulator([c[0] for c in _COMMANDS]))
