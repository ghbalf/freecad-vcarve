# SPDX-License-Identifier: LGPL-2.1-or-later
# Authors: alf and Claude (Anthropic)
"""Runs tests/fc under headless freecadcmd for each AppRun in FREECAD_APPRUNS (isolated user home)."""
import subprocess
from pathlib import Path

import pytest

from conftest import appruns

FC = Path(__file__).parent / "fc"
RUN = FC / "run.py"


@pytest.mark.parametrize(**appruns())
def test_freecad_suite(apprun, fc_env, tmp_path):
    if apprun is None:
        pytest.skip("FREECAD_APPRUNS not set")
    res = subprocess.run([apprun, "freecadcmd", str(RUN)], capture_output=True,
                         text=True, timeout=600, env=fc_env, cwd=tmp_path)
    out = res.stdout + res.stderr
    assert res.returncode == 0 and "FC-TESTS-OK" in res.stdout, out[-6000:]


@pytest.mark.parametrize(**appruns())
def test_reopen_in_fresh_process(apprun, fc_env, tmp_path):
    """Restore must not depend on the addon being imported already (26.3 blocks unknown modules)."""
    if apprun is None:
        pytest.skip("FREECAD_APPRUNS not set")
    env = dict(fc_env, VCARVE_DOC=str(tmp_path / "pair.FCStd"))
    outs = [subprocess.run([apprun, "freecadcmd", str(FC / script)], capture_output=True, text=True,
                           timeout=300, env=env, cwd=tmp_path).stdout for script in ("save_pair.py", "reopen_pair.py")]
    assert "SAVED" in outs[0], outs[0][-3000:]
    assert ("PROXIES ['ObjectVCarveClearance', 'ObjectVCarveClearance', 'ObjectVCarveClearance', "
            "'ObjectVCarveFlat', 'ObjectVCarveFlat', 'ObjectVCarvePlug']") in outs[1], outs[1][-3000:]
    assert "PLUG-OK" in outs[1], outs[1][-3000:]
