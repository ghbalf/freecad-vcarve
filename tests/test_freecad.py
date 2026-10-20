# SPDX-License-Identifier: LGPL-2.1-or-later
"""Runs tests/fc under headless freecadcmd for each AppRun in FREECAD_APPRUNS."""
import os
import subprocess
from pathlib import Path

import pytest

RUN = Path(__file__).parent / "fc" / "run.py"
APPRUNS = [p for p in os.environ.get("FREECAD_APPRUNS", "").split(os.pathsep) if p]


@pytest.mark.parametrize(
    "apprun", APPRUNS or [None],
    ids=[Path(p).parent.parent.name for p in APPRUNS] or ["unset"])
def test_freecad_suite(apprun):
    if apprun is None:
        pytest.skip("FREECAD_APPRUNS not set")
    res = subprocess.run([apprun, "freecadcmd", str(RUN)], capture_output=True,
                         text=True, timeout=600)
    out = res.stdout + res.stderr
    assert res.returncode == 0 and "FC-TESTS-OK" in res.stdout, out[-6000:]
