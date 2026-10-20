# SPDX-License-Identifier: LGPL-2.1-or-later
"""freecadcmd, fresh process with nothing imported: reopen $VCARVE_DOC and print the op proxies."""
import os

import FreeCAD as App

doc = App.openDocument(os.environ["VCARVE_DOC"])
print("PROXIES", sorted(type(o.Proxy).__name__ for o in doc.Objects if o.Name.startswith("VCarve")))
