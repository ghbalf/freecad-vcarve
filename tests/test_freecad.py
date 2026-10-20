# SPDX-License-Identifier: LGPL-2.1-or-later
"""Runs tests/fc under headless freecadcmd for each AppRun in FREECAD_APPRUNS (isolated user home)."""
import subprocess
from pathlib import Path

import pytest

from conftest import appruns

RUN = Path(__file__).parent / "fc" / "run.py"


@pytest.mark.parametrize(**appruns())
def test_freecad_suite(apprun, fc_env, tmp_path):
    if apprun is None:
        pytest.skip("FREECAD_APPRUNS not set")
    res = subprocess.run([apprun, "freecadcmd", str(RUN)], capture_output=True,
                         text=True, timeout=600, env=fc_env, cwd=tmp_path)
    out = res.stdout + res.stderr
    assert res.returncode == 0 and "FC-TESTS-OK" in res.stdout, out[-6000:]
