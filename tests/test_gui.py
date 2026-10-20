# SPDX-License-Identifier: LGPL-2.1-or-later
"""Runs tests/gui/check_gui.py in an offscreen FreeCAD GUI for each AppRun in FREECAD_APPRUNS.
FreeCAD gets a throwaway user home with the repo linked as an addon; the real config is untouched."""
import os
import subprocess
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
CHECK = REPO / "tests" / "gui" / "check_gui.py"
APPRUNS = [p for p in os.environ.get("FREECAD_APPRUNS", "").split(os.pathsep) if p]


@pytest.mark.parametrize(
    "apprun", APPRUNS or [None],
    ids=[Path(p).parent.parent.name for p in APPRUNS] or ["unset"])
def test_gui(apprun):
    if apprun is None:
        pytest.skip("FREECAD_APPRUNS not set")
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp) / "home"
        (home / "Mod").mkdir(parents=True)
        (home / "Mod" / "freecad-vcarve").symlink_to(REPO)
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen", FREECAD_QT_QPA_PLATFORM="offscreen", HOME=str(tmp), FREECAD_USER_HOME=str(home),
                   FREECAD_USER_DATA=str(home), FREECAD_USER_TEMP=str(Path(tmp) / "temp"),
                   XDG_CONFIG_HOME=str(Path(tmp) / "xdg"), XDG_DATA_HOME=str(Path(tmp) / "xdg"))
        res = subprocess.run([apprun, "freecad", str(CHECK)], capture_output=True, text=True,
                             timeout=300, env=env, cwd=tmp)
    out = res.stdout + res.stderr
    assert "GUI-CHECK-OK" in res.stdout, out[-6000:]
