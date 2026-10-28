# SPDX-License-Identifier: LGPL-2.1-or-later
# Authors: alf and Claude (Anthropic)
"""Runs tests/gui/check_gui.py in an offscreen FreeCAD GUI for each AppRun in FREECAD_APPRUNS.
FreeCAD gets a throwaway user home with the repo linked as an addon; the real config is untouched."""
import subprocess
from pathlib import Path

import pytest

from conftest import appruns

CHECK = Path(__file__).parent / "gui" / "check_gui.py"
# No notification area: FreeCAD 1.0 deadlocks offscreen when it shows a popup, as Qt warns "This plugin does
# not support raise()" and FreeCAD posts that warning back to the area while holding the area's lock.
USER_CFG = """<?xml version="1.0" encoding="UTF-8" standalone="no" ?>
<FCParameters><FCParamGroup Name="Root"><FCParamGroup Name="BaseApp"><FCParamGroup Name="Preferences">
<FCParamGroup Name="NotificationArea"><FCBool Name="NotificationAreaEnabled" Value="0"/></FCParamGroup>
</FCParamGroup></FCParamGroup></FCParamGroup></FCParameters>
"""


def pyside2_crash(out):
    """FreeCAD 1.0's PySide2 5.15 hands out stale wrappers of deleted widgets and so crashes now and then in
    FreeCAD's own code, such as CAM's op panels (about one GUI check in sixty), which earns that check a rerun."""
    return "Program received signal" in out and "libpyside2" in out


@pytest.mark.parametrize(**appruns())
def test_gui(apprun, fc_env, tmp_path):
    if apprun is None:
        pytest.skip("FREECAD_APPRUNS not set")
    cfg = tmp_path / "user.cfg"
    cfg.write_text(USER_CFG)
    def run():
        return subprocess.run([apprun, "freecad", "-u", str(cfg), str(CHECK)], capture_output=True, text=True,
                              timeout=300, env=fc_env, cwd=tmp_path)
    res = run()
    if pyside2_crash(res.stdout + res.stderr):
        res = run()
    out = res.stdout + res.stderr
    assert "GUI-CHECK-OK" in res.stdout, out[-6000:]
    assert "Job.ERROR" not in out, out[-6000:]  # the Job panel logs, not raises, e.g. a bad op default


def test_pyside2_crash():
    stack = "Program received signal SIGSEGV, Segmentation fault.\n#4 0x7b in PySide::SignalManager from libpyside2.so.5.15"
    assert pyside2_crash(stack)
    assert not pyside2_crash(stack.replace("libpyside2", "libFreeCADApp"))  # a crash outside PySide2: no second chance
    assert not pyside2_crash("AssertionError: from libpyside2")  # a failed check, not a crash
