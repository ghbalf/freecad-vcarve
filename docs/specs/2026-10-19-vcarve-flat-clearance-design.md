# FreeCAD V-Carve addon: flat depth and clearance (v1 design)

## Intent

FreeCAD's CAM workbench has a basic `CAM_Vcarve` operation. It carves the medial
axis of a face with a V-bit, but it has no notion of a *flat depth*: either the
whole design is cut as deep as the V-bit cone allows, or the depth is truncated
by Final Depth, which leaves wide areas half-cut with ridges and no clean
bottom.

Commercial tools such as Vectric VCarve Pro, Carbide Create and Estlcam, as
well as the open-source F-Engrave, solve this the same way:

- The V-bit carves the sloped walls down to a **flat depth**.
- A second, flat-bottomed **clearance tool** (end mill) removes the flat floor
  of the wide areas.

This addon brings that workflow to FreeCAD CAM, in a form that can later be
proposed for inclusion in FreeCAD itself. Inlay carving (pocket plus mirrored
plug) is the next step and builds directly on this one, so v1 has to keep it
easy to add.

## Goals

1. A CAM operation **"V-Carve (flat depth)"** that, from 2D sketches,
   generates V-bit toolpaths with an optional flat depth.
2. A CAM operation **"V-Carve Clearance"** that, for a given V-carve
   operation, clears the flat floor with a flat end mill.
3. A single toolbar/menu command that creates both operations together, so
   the common case is one click. The clearance op is linked to its V-carve op.
4. Correct results for typical engraving input: text converted to sketches,
   letters with holes (O, A, B), several separate letters, nested islands,
   arcs and B-splines.
5. Unit-tested geometry. Integration tests run headless with `freecadcmd`.

## Non-goals (v1)

- Inlay (female pocket, male plug, glue gap, auto-mirror). This is planned
  for v2 and the design below must not block it.
- Prism carving, ball-nose carving, step-down/roughing passes, image or bitmap
  input, and a built-in font engine. Text comes from Draft ShapeString turned
  into a sketch, or from a hand-drawn sketch.
- 3D input. Solids, faces of solids and meshes are not accepted. **Input is
  sketches only** (`Sketcher::SketchObject`), one or more per operation.
- Its own G-code writer. Output is a normal CAM `Path`; post-processing,
  simulation and export stay with the CAM workbench.

## Anti-goals (would be a failure even if it "works")

- **Copied code from F-Engrave** (GPL-3). It is inspiration only; no code,
  structure or naming is ported. The geometry is built on FreeCAD's own
  primitives.
- Licensing that prevents an upstream merge. Every file is
  **LGPL-2.1-or-later** and carries an SPDX header, matching FreeCAD.
- Letters that are silently skipped or partly cut. If a region can't be
  processed, the op logs a clear error that names the sketch, instead of
  emitting a partial path quietly.
- Cutting outside the outline. No toolpath point may lie outside the input
  region, apart from the tool's own swept volume.

## Constraints

- Target: FreeCAD 1.1.x (tested against 1.1.1 AppImage), Python 3.11 bundled.
- Must integrate with the existing CAM framework: `Path.Op.Base.ObjectOp`,
  tool controllers (V-bit with `CuttingEdgeAngle`, `Diameter`,
  `TipDiameter`; end mill with `Diameter`), heights/depths pages, setup sheet,
  post-processors.
- Ships as an addon (classic `Mod/<name>/InitGui.py` layout with
  `package.xml`). It hooks its commands into the CAM workbench's
  "New Operations" toolbar and CAM menu through a workbench manipulator, not
  by patching CAM files.
- Pure-math helpers live in a FreeCAD-free module so they can be tested with
  plain `pytest`.

## How it works (decided)

### Input → region faces

- The op's base list accepts sketches only, from the Job model (CAM clones
  base objects into the Job; we use those clones). The selection gate rejects
  anything else.
- **Only the listed sketches are used (user decision).** Whatever is
  selected when the op is created fills its base list, and the user can add
  or remove entries in the task panel. There is **no fallback** to "all
  sketches in the Job" (the built-in Vcarve has one). An empty list cuts
  nothing and logs a clear message.
- **Partial sketches by edge selection (user decision).** A base entry is
  either a whole sketch or a sketch with selected sub-elements
  (`Base = [(sketch, ["Edge3", ...])]`, the standard CAM mechanism).
  Selecting any edge picks the **whole closed loop** containing it, so one
  click per outline is enough. Holes count only if one of their edges is
  selected too: picking only the outer loop of an "O" carves a solid disc.
  A selected edge that lies on no closed loop is reported as an error
  naming the sketch. The chosen loops then go through the same face-building
  step as a whole sketch.
- Each sketch's closed wires are combined into faces with
  `Part::FaceMakerBullseye`, so letters with holes and islands in holes work.
  Open wires are reported as an error naming the sketch.
- Several sketches are processed independently, one face set per sketch.
- The carve surface Z is the op's **Start Depth** (default: the top of the
  model bounding box, as the built-in Vcarve does).

### V-bit path

- **Medial axis** from `Path.Voronoi` on the discretized boundary,
  following the approach of the existing `CAM_Vcarve` op (Voronoi of
  segments, drop exterior, secondary and twin edges, chain the rest into
  wires). Each Voronoi edge gives the maximum inscribed circle (MIC) radius
  at its ends, and depth follows the V-bit geometry:
  `depth = (r - tip_radius) / tan(half_angle)`, clamped at 0.
- **Flat depth `D`** (property `FlatDepth`; 0 = off, the cone limits the
  depth as today). The flat radius is
  `r_flat = tip_radius + D * tan(half_angle)`, capped at the tool radius.
  Where the MIC radius is larger than `r_flat`, the tool is clamped at depth
  `D`.
- **Flat-boundary pass.** When `D > 0`, the V-bit also follows the inward
  offset of the region by `r_flat` (`Part.Face.makeOffset2D(-r_flat)`) at
  depth `D`. This is the crisp edge where the sloped wall meets the flat
  floor, and it is what makes the floor edge clean, as in Vectric. The
  medial-axis branches meet this contour exactly where `r = r_flat`.
- The medial-axis parts inside the flat area (clamped to `D`) are kept,
  because they clean the corners the clearance tool can't reach.
- Ordering: wires are sorted greedily by nearest start/end to cut down rapid
  moves, as the built-in op does. Moves: retract to Safe Height, rapid, plunge
  at the tool controller's vertical feed, cut at horizontal feed.

### Clearance path

- A separate op with its own (flat) tool controller and a link property
  `VCarveOp` to the V-carve op. It reads the faces, Start Depth, flat depth
  and V-bit geometry from that op, so the two always agree.
- Area to clear: region offset inward by `r_flat`, i.e. the flat floor. It
  is pocketed at depth `D` with **`Path.Area`** (the same engine as
  `CAM_Pocket`). The tool must stay inside the floor, so its center path is
  offset by its radius (`Path.Area` handles this through `ToolRadius`).
- Properties: `StepOver` (% of tool diameter, default 40), `PocketPattern`
  (Offset or ZigZag, default Offset), `Allowance` (default 0, extra distance
  from the floor edge).
- **Rest clearing by the V-bit (user decision).** Some floor is wider than
  the V-bit tip but narrower than the end mill. The end mill can't reach it,
  so the V-bit op pockets it at depth `D`. That rest area is the floor minus
  what the end mill sweeps: its center region offset outward by its radius.
  It is computed with `Path.Area` using the V-bit tip radius as the tool
  radius. Because many V-bits have a sharp point (tip diameter 0), the
  stepover comes from an allowed scallop height `h` (property
  `RestScallop`, default 0.05 mm):
  `stepover = tip_diameter + 2 * h * tan(half_angle)`. The V-bit op therefore
  knows about the clearance op that links to it (it finds it in the Job, or
  through a back-link). Without a clearance op, the V-bit clears the whole
  floor. This is slow, but the floor ends up correct.
- With `FlatDepth = 0` on the linked op, or if the floor is empty (the
  design is too narrow to have a flat area), the op produces an empty path
  with an info message, not an error.

### Packaging

```
freecad-vcarve/
  package.xml, LICENSE (LGPL-2.1), README.md
  InitGui.py                      # registers commands + workbench manipulator
  vcarve_flat/
    geom.py                       # FreeCAD-free math (depth, r_flat, ordering)
    sketches.py                   # sketch → faces, discretization
    medial.py                     # Path.Voronoi medial-axis extraction
    op_vcarve.py, op_clearance.py # App-side operations
    gui/                          # commands, task panels, view providers
    resources/icons/*.svg
  tests/                          # pytest (pure) + freecadcmd integration
```

Module and package names must not collide with FreeCAD's (`Path`, `CAM`,
`Vcarve`).

## Planned v2 (must stay easy)

Inlay with Vectric-style parameters: one sketch gives a pocket op (= v1 with
flat depth) and a plug op (auto-mirrored, start depth above the surface, flat
depth, glue gap, clearance of the area around the plug inside a boundary).
This is why region building, depth mapping and clearance are separate
functions: the plug just inverts the region (boundary minus letters), mirrors
it and shifts the depth mapping.

## Left to the builder

- Discretization tolerance defaults, the colinear filter angle, and exact
  property names beyond those listed.
- Task-panel layout (built programmatically or from `.ui` files).
- How Voronoi wires are chained and sorted. The built-in op's approach is
  LGPL and may be reused or imported where that fits.
- Icon artwork.

## Decisions made after builder review (my calls; check while reading)

1. **Depth reference.** `FlatDepth` is a *distance below Start Depth*, not
   an absolute Z, so the same value works on any stock. The op does not
   expose Final Depth: it uses `FeatureNoFinalDepth` or hides the property.
   Depth is limited only by `FlatDepth` and the V-bit cone. (Final Depth as a
   second clamp was the confusing part of the built-in op.)
2. **Flat depth deeper than the cone.** If `FlatDepth` is deeper than the
   V-bit's cone height `(radius - tip_radius) / tan(half_angle)`, the op logs
   a warning and uses the cone height instead. We never cut vertical walls
   with the shank, and never cut outside the outline.
3. **Partial failure.** Each sketch is processed on its own. If one fails
   (open wire, Voronoi failure, empty face), the op still emits the paths for
   the good sketches and logs an **error** naming the failed sketch. It never
   fails silently.
4. **One-click command.** The command picks the first V-bit tool
   controller and the first end-mill tool controller in the Job. If either is
   missing, it refuses with a message that says which tool to add (no
   controller is created automatically). The **clearance op is placed before
   the V-carve op**, as Vectric orders them, so the V-bit's final boundary
   pass cuts against an already-cleared floor.

## Known limitations (accepted for v1)

- Rest clearing with the V-bit leaves scallops up to `RestScallop` high on
  the floor areas the end mill can't reach. This is a deliberate trade-off
  between finish and run time.
