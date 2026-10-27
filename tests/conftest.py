# SPDX-License-Identifier: LGPL-2.1-or-later
# Authors: alf and Claude (Anthropic)
"""Shared fixtures for the tests that run FreeCAD AppImages."""
import os
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
APPRUNS = [p for p in os.environ.get("FREECAD_APPRUNS", "").split(os.pathsep) if p]


def appruns():
    """parametrize() arguments over FREECAD_APPRUNS; a single None when it is unset."""
    return dict(argnames="apprun", argvalues=APPRUNS or [None],
                ids=[Path(p).parent.parent.name for p in APPRUNS] or ["unset"])


@pytest.fixture
def fc_env(tmp_path):
    """Environment for a FreeCAD subprocess with a throwaway HOME and user home, so the user's real
    FreeCAD config and data are never read or written. The repo is linked as an addon."""
    home = tmp_path / "home"
    (home / "Mod").mkdir(parents=True)
    (home / "Mod" / "freecad-vcarve").symlink_to(REPO)
    return dict(os.environ, HOME=str(tmp_path), FREECAD_USER_HOME=str(home), FREECAD_USER_DATA=str(home),
                FREECAD_USER_TEMP=str(tmp_path / "temp"), XDG_CONFIG_HOME=str(tmp_path / "xdg"),
                XDG_DATA_HOME=str(tmp_path / "xdg"), XDG_CACHE_HOME=str(tmp_path / "xdg"),
                QT_QPA_PLATFORM="offscreen", FREECAD_QT_QPA_PLATFORM="offscreen")
