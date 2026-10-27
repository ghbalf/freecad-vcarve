# SPDX-License-Identifier: LGPL-2.1-or-later
# Authors: alf and Claude (Anthropic)
"""freecadcmd: save a Job with a V-carve pair and an inlay to $VCARVE_DOC (step 1 of the reopen test)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import FreeCAD as App  # noqa: E402
import helpers  # noqa: E402
from vcarve_flat import inlay, op_clearance  # noqa: E402

doc = App.newDocument("Reopen")
sk = helpers.make_sketch(doc, "Letters", [[(0, 0), (30, 0), (30, 20), (0, 20)]])
job, tcs = helpers.make_job(doc, [sk])
op_clearance.create_pair(job)
inlay.create_inlay(job, sk, tcs["60degree_Vbit"], tcs["5mm_Endmill"], pocket_depth=3.0, glue_gap=0.2)
doc.recompute()
doc.saveAs(os.environ["VCARVE_DOC"])
print("SAVED")
