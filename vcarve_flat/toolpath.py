# SPDX-License-Identifier: LGPL-2.1-or-later
"""XYZ polylines -> Path.Command list (retract, rapid, plunge, cut)."""
import Path


def paths_to_commands(paths, safe_z, clearance_z, hfeed, vfeed) -> list:
    cmds = []
    for i, p in enumerate(paths):
        x, y, z = (float(v) for v in p[0])
        cmds += [Path.Command("G0", {"Z": clearance_z if i == 0 else safe_z}),
                 Path.Command("G0", {"X": x, "Y": y}),
                 Path.Command("G1", {"Z": z, "F": vfeed})]
        cmds += [Path.Command("G1", {"X": float(a), "Y": float(b), "Z": float(c), "F": hfeed})
                 for a, b, c in p[1:]]
    if cmds:
        cmds.append(Path.Command("G0", {"Z": clearance_z}))
    return cmds
