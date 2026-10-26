# SPDX-License-Identifier: LGPL-2.1-or-later
"""Medial axis of a face (Path.Voronoi) -> V-carve polylines with flat-depth clamping."""
import math

import FreeCAD as App
import numpy as np
import Path
from Path.Op.Vcarve import (BORDERLINE, COLINEAR, EXTERIOR1, EXTERIOR2, PRIMARY, SECONDARY, TWIN,
                            _collectVoronoiWires)

from .clearing import offset_faces
from .geom import (depth_for_radius, distances_to_segments, drop_collinear, drop_floor_runs, flat_radius,
                   insert_crossings, narrow_points, simplify)


def _closed_loop(wire, deflection) -> np.ndarray:
    pts = np.array([(p.x, p.y) for p in wire.discretize(QuasiDeflection=deflection)])
    if len(pts) > 1 and np.linalg.norm(pts[-1] - pts[0]) < App.Base.Precision.confusion():
        pts = pts[:-1]
    pts = drop_collinear(pts, App.Base.Precision.confusion())
    return np.vstack([pts, pts[:1]])


def boundary_segments(face, deflection: float) -> np.ndarray:
    segs = [np.stack([loop[:-1], loop[1:]], axis=1) for loop in
            (_closed_loop(w, deflection) for w in face.Wires)]
    return np.concatenate(segs) if segs else np.empty((0, 2, 2))


def _chord(a, b, step) -> list:
    n = max(2, math.ceil(math.dist(a, b) / step) + 1)
    return list(zip(np.linspace(a[0], b[0], n), np.linspace(a[1], b[1], n)))


def medial_polylines(face, segments, colinear_deg: float, step: float) -> list:
    vd = Path.Voronoi.Diagram()
    for a, b in segments:
        vd.addSegment(App.Vector(*a, 0), App.Vector(*b, 0))
    vd.construct()
    for e in vd.Edges:
        if e.isPrimary():
            e.Color = BORDERLINE if e.isBorderline() else PRIMARY
        else:
            e.Color = SECONDARY
    # Order of FreeCAD >= 1.1 (colinear before exterior); 1.0 colors colinear last.
    vd.colorColinear(COLINEAR, colinear_deg)
    z = face.BoundBox.ZMin

    def exterior(v):
        return not face.isPartOfDomain(*face.Surface.parameter(App.Vector(v.toPoint(z))))

    vd.colorExterior(EXTERIOR1)
    vd.colorExterior(EXTERIOR2, exterior)
    vd.colorTwins(TWIN)
    out = []
    for wire in _collectVoronoiWires(vd):
        pts = []
        for edge in wire:
            shape = edge.toShape()
            if shape is None:
                continue
            edge_pts = [(p.x, p.y) for p in shape.discretize(Distance=step)]
            ends = [(p.x, p.y) for p in (v.toPoint(z) for v in edge.Vertices)]
            if len(ends) == 2 and min(max(math.dist(edge_pts[0], a), math.dist(edge_pts[-1], b))
                                      for a, b in (ends, ends[::-1])) > max(step, math.dist(*ends)):
                # FreeCAD 26.3 discretizes some short parabolic edges far from their ends (43 mm); the
                # ends of a sound one miss its vertices by up to 0.05 mm
                edge_pts = _chord(*ends, step)
            for p in edge_pts:
                if not pts or np.hypot(p[0] - pts[-1][0], p[1] - pts[-1][1]) > 1e-9:
                    pts.append(p)
        if len(pts) > 1:
            out.append(np.array(pts))
    return out


def _depths(vbit, xy, segments, lo, hi) -> tuple:
    """Clipped V depths along xy, with the points where the clip starts inserted."""
    def radius(p):
        return distances_to_segments(p, segments)
    levels = [vbit.tip_radius + d * math.tan(vbit.half_angle) for d in (lo, hi)]
    xy, r = insert_crossings(xy, radius(xy), radius, levels)
    return xy, depth_for_radius(vbit, r, hi, lo)


def carve_polylines(face, vbit, z_top, depth_limit, *, deflection, colinear_deg, step, tol,
                    drop_floor=False, min_depth=0.0) -> list:
    """V-bit paths along the medial axis; drop_floor leaves out their runs on the flat floor
    (cleared by the end mill and the rest pocket)."""
    segments = boundary_segments(face, deflection)
    if not len(segments):
        return []
    paths = []
    for xy in medial_polylines(face, segments, colinear_deg, step):
        xy, depth = _depths(vbit, xy, segments, min_depth, depth_limit)
        path = np.column_stack([xy, z_top - depth])
        paths += drop_floor_runs(path, z_top - depth_limit) if drop_floor else [path]
    return [simplify(p, tol) for p in paths]


def ridge_polylines(face, vbit, z_base, height, *, deflection, colinear_deg, step, tol) -> list:
    """Medial axis at z = z_base + clip((r - r_t)/t, 0, height), without its runs on the plug top
    z_base + height. A pointed bit leaves no ridge."""
    if vbit.tip_radius == 0:
        return []
    segments = boundary_segments(face, deflection)
    if not len(segments):
        return []
    paths = []
    for xy in medial_polylines(face, segments, colinear_deg, step):
        xy, up = _depths(vbit, xy, segments, 0.0, height)
        path = np.column_stack([xy, -(z_base + up)])  # z negated: drop_floor_runs drops runs at/below a floor
        paths += [p * [1, 1, -1] for p in drop_floor_runs(path, -(z_base + height))]
    return [simplify(p, tol) for p in paths]


def has_narrow_gap(face, radius, *, deflection, colinear_deg, step) -> bool:
    """Whether face is narrower than 2*radius somewhere other than in its corners."""
    segments = boundary_segments(face, deflection)
    return any(narrow_points(xy, segments, radius).any()
               for xy in medial_polylines(face, segments, colinear_deg, step))


def flat_boundary_loops(face, vbit, z_top, depth_limit, *, deflection, tol) -> list:
    """Closed loops where the V-bit wall meets the flat floor (face offset inward by r_flat)."""
    return face_loops(offset_faces([face], -flat_radius(vbit, depth_limit)), z_top - depth_limit,
                      deflection=deflection, tol=tol)


def face_loops(faces, z, *, deflection, tol) -> list:
    """Every wire of faces as a closed, simplified polyline at height z."""
    out = []
    for w in (w for f in faces for w in f.Wires):
        loop = _closed_loop(w, deflection)
        out.append(simplify(np.column_stack([loop, np.full(len(loop), z)]), tol))
    return out
