# SPDX-License-Identifier: LGPL-2.1-or-later
"""Runs tests/gui/check_gui.py in an offscreen FreeCAD GUI for each AppRun in FREECAD_APPRUNS.
FreeCAD gets a throwaway user home with the repo linked as an addon; the real config is untouched."""
import subprocess
from pathlib import Path

import pytest

from conftest import appruns

CHECK = Path(__file__).parent / "gui" / "check_gui.py"


@pytest.mark.parametrize(**appruns())
def test_gui(apprun, fc_env, tmp_path):
    if apprun is None:
        pytest.skip("FREECAD_APPRUNS not set")
    res = subprocess.run([apprun, "freecad", str(CHECK)], capture_output=True, text=True,
                         timeout=300, env=fc_env, cwd=tmp_path)
    out = res.stdout + res.stderr
    assert "GUI-CHECK-OK" in res.stdout, out[-6000:]
