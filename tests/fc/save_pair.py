# SPDX-License-Identifier: LGPL-2.1-or-later
"""freecadcmd: save a Job with a V-carve pair to $VCARVE_DOC (step 1 of the reopen test)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import FreeCAD as App  # noqa: E402
import helpers  # noqa: E402
from vcarve_flat import op_clearance  # noqa: E402

doc = App.newDocument("Reopen")
sk = helpers.make_sketch(doc, "Letters", [[(0, 0), (30, 0), (30, 20), (0, 20)]])
job, _ = helpers.make_job(doc, [sk])
op_clearance.create_pair(job)
doc.recompute()
doc.saveAs(os.environ["VCARVE_DOC"])
print("SAVED")
