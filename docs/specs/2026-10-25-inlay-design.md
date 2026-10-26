# FreeCAD V-Carve addon: V-carve inlay (v2 design)

## Intent

A V-carve inlay puts one wood into another with seams that close perfectly.
It needs two carved parts:

- The **pocket** in the board: a V-carve with a flat floor. This is exactly v1
  (V-Carve Flat plus V-Carve Clearance).
- The **plug** in a second piece of wood: the same design, mirrored and
  carved as its negative. The letters stand up as a raised shape whose sloped
  sides match the pocket walls.

The plug is glued in upside down. Because both parts are cut with the same
V-bit angle, the plug's walls press against the pocket walls. Its top never
reaches the pocket floor; the space left is the glue gap. Later the plug board
is sawn off and the surface planed flat.

The user is a first-time inlayer. They have only seen it in videos so far. The
first real project is a **cutting board with some text in a single contrasting
wood**. Later come boxes, crosses, signs, and SVG designs (imported into
sketches) with several woods. The addon may be published, so beginners must
get safe defaults while experienced users still reach every setting.

Machine and tools (the user's): a Sorotec CL 0605; V-bits of 90°, 60° and 30°;
end mills of 1 to 12 mm; a 1" surfacing bit. Other tool data is not available
yet, so nothing in the design may rely on it.

## Goals

1. One command, **"V-Carve Inlay"**, turns a design sketch into a complete
   inlay. It creates **two new Jobs in the same document** and leaves the
   selected Job as it is (user decision, 2026-10-26):
   - **Pocket Job** (the board): a V-Carve Flat op with Flat Depth equal to
     the pocket depth, plus its V-Carve Clearance op. These are v1 ops.
   - **Plug Job** (the inlay wood): a V-carve plug op plus a clearance op. It
     carves the mirrored design as a raised plug.
2. Both Jobs use **the same sketch** and **the same V-bit**. If the design
   changes, both follow it on recompute.
3. **Beginner settings**, asked for when the command runs: V-bit, end mill,
   pocket depth, glue gap, and how the plug wood is cleared (a ring around
   the plug, or the whole plug board). Every other value gets a sensible
   default.
4. **Advanced settings** are ordinary op properties: plug start depth (shown,
   derived), surface gap (the plug's flat depth), plug margin, mirror axis,
   step-down, and all v1 fields.
5. The tool **prevents the common inlay mistakes** it can see (see
   *Checks*), with clear messages that name the sketch or op.
6. **Multiple passes (user decision).** All four ops (pocket and plug, V-bit
   and end mill) cut in depth passes, not in one pass. See *Step-down*.
7. Unit-tested geometry, including a test that **the parts fit** when seated
   (see *Testing*).

## Non-goals (v2)

- Gluing, sawing the plug off, and surfacing. FreeCAD's own Face op can surface
  a board.
- **Several plug woods** (multicolor) in one inlay. It comes later, so the
  design must not block it: the plug op works on a list of sketches, so a
  later version can make one plug Job per wood, each from a subset of the
  sketches.
- SVG import (the user imports SVGs into sketches themselves, later).
- A tool library dialog. Tools come from the tool controllers already in the
  Job, as in v1's Pair command.
- 3D or non-sketch input, as in v1.

## Anti-goals

- Everything from v1 still applies: no F-Engrave code (clean-room), LGPL-2.1+,
  no silent skipping, no cutting outside what the design allows.
- **A plug that cannot seat.** Any setting combination that physically can't
  fit (plug deeper than the V-bit's cone, glue gap ≥ pocket depth, different
  V-bits) must be an error before G-code is produced, not something found out
  at the glue-up.
- **Numbers that mean something different from Vectric without saying so.**
  Programs disagree on what "start depth" and "flat depth" mean, which
  confuses users who copy settings from videos. Our fields are named after
  what they do. Each tooltip states its reference, e.g. "below the plug
  board's top".

## How it works

### Geometry (derived; the builder should re-check it with the fit test)

Notation: the V-bit half angle is θ, so t = tan θ. The tip radius is r_t.
P is the pocket depth, G the glue gap, S the surface gap.

- A V-bit carving a region has walls that, at depth z below the carve
  surface, lie at the region boundary **offset inward by z·t**. This is
  independent of the tip radius, as v1's medial-axis carving already
  guarantees.
- The **pocket** is v1 with `FlatDepth = P`. Its floor is the design offset
  inward by P·t. Narrow strokes are shallower and have a V bottom; P is a
  maximum depth, as in Vectric.
- The **plug** is the mirrored design. On the plug board, at depth s below the
  board's top, the plug outline must be the mirrored design **offset outward
  by (s − (P − G))·t**. That outline matches the pocket wall at pocket depth
  P − G − s, with the plug's top sitting G above the pocket floor.
- The plug can therefore be cut with v1's carving unchanged, by applying it
  to the **complement region**: the plug boundary minus the mirrored letters.
  The complement's holes are the letters, and the letters' own holes (the
  counter of an O) become islands inside the complement. The carving uses:
  - a **virtual carve surface** `Z_v = plug top − (P − G)`, which lies below
    the stock top (the Vectric "start depth");
  - **flat depth S** below `Z_v`.

  The V-bit's cone also cuts the walls above `Z_v`, up to the stock top. Total
  cut depth on the plug board: **P − G + S**. This matches Vectric's "start +
  flat = total".
- **Plug start depth** `P − G` is therefore derived, not an independent
  input. It is shown as a read-only property for users who think in Vectric
  terms.
- Seated, the plug board's cut floor sits S above the board's surface. That
  material is what gets sawn and planed off.
- **Z reference (my call).** "Plug top" is the real top of the plug wood, and
  the user zeroes Z there. The command sets the plug Job's stock to
  `ExtZpos = 0`, so the stock top equals the sketch plane, which v1 already
  uses as Start Depth. The same applies on the pocket side, where a Z error
  only changes S. On the plug side, a Z error e makes the letters e taller,
  so the README says to zero Z on the plug wood carefully.
- **Narrow strokes have no floor gap (accepted, as in Vectric).** Strokes
  narrower than 2·(r_t + P·t) have a V bottom (2·P·t for a pointed bit) in the pocket. The plug ridge's apex
  lands exactly on it when the walls close, whatever G is. G only protects
  the wide, flat-floor areas.
- **The flat tip (corrected after review; ridge pass = user decision).** A
  uniform offset of a V-carved surface by r_t is the same as shifting it by
  r_t/t in depth, so no offset or start-depth change can fix tip effects. What
  a tip of radius r_t does:
  - A narrow pocket groove gets a flat bottom r_t/t above the ideal V, while
    the plug's ridge for that stroke has a sharp apex. The apex lands on the
    flat bottom before the walls close and lifts the whole plug by r_t/t,
    leaving a wall gap of r_t everywhere.
  - At sharp letter corners the two parts differ by about 0.4·r_t (90°
    corner): local mismatches, not a lift.

  The fix is an optional **ridge pass** on the plug (`RidgePass`, on by
  default; it produces no path for a sharp bit). The V-bit follows the medial
  axis of the mirrored letters at plug depth `start − (r − r_t)/t` below the
  plug top (r = medial radius), only where that depth is positive. This cuts
  each ridge flat where it is narrower than the tip, so it matches the pocket
  groove. It runs once, after the plug's last level. At a convex corner with
  bisector half-angle h (t = tan of the V half-angle, start = P − G) it leaves
  a small corner gap: its half-width is r_t/cos h (1.41·r_t at a 90° corner),
  it reaches (r_t + start·t)/sin h from the corner, and its height on the
  bisector is 2·r_t·sin h/t. Those small gaps are accepted and documented.
- **Sharp inner corners.** The floor outline and the V-bit's wall loops are
  inward offsets with mitred corners where the wood's corner is convex
  (the pocket's reflex corners, the plug's letter corners): the round join
  made the cone round that corner down to the floor (radius about r_flat).
  A mitred offset lies inside the round one, so it never gouges. Strokes
  narrower than the floor, cut along the medial axis, stay rounded.
- **The tool above `Z_v`.** v1 clamps the medial depth at 0 (the carve
  surface). On the plug the carve surface is below the stock top, so the
  plug's carve lets the depth go negative, down to the plug top
  (`−start`). Otherwise the cone would gouge the letters by up to r_t
  wherever the complement is narrower than the tip.
- **Rounded tips.** FreeCAD's V-bit only has a flat tip. For a rounded tip,
  the user enters as Tip Diameter the width where the rounding meets the
  cone. The real tip lies inside that flat-tip model's envelope, so every
  error is a gap, never a collision. Zeroing Z on the bottom of the rounding
  makes the floor gap larger by ρ·(1 − sin θ), never smaller. The README says
  this and recommends pointed V-bits for inlays.
- **Plug start depth** is `start = P − G` (there is no tip term).

### Ops and properties

- **Pocket side:** unchanged v1 ops. The command sets Flat Depth to P.
- **Plug op** (new, "V-Carve Plug"). It reuses v1's carving, rest pocket and
  boundary pass. It differs from V-Carve Flat only in:
  - **region building:** mirror the faces, then subtract them from the plug
    boundary;
  - **depth mapping:** `z_top = Z_v`, `depth = S`.

  It links to the pocket op with `PocketOp` and reads from it the sketches
  (`BaseShapes` and `Base`), the pocket depth P, and the V-bit geometry, so
  the two sides can't drift apart. **(My call.)** It carves from the Pocket
  Job's sketch clones. The plug Job's own model clone is used only for its
  stock and display, and moving it does not move the path. Repositioning the
  plug on the blank is a later option. Its own properties:

  | Property | Default (my call) | Meaning |
  |---|---|---|
  | `PocketOp` | set by command | The pocket's V-Carve Flat op |
  | `GlueGap` | 0.2 mm | Gap between plug top and pocket floor when seated |
  | `SurfaceGap` | 1.5 mm | Gap between plug board and board surface when seated (the plug's flat depth below the start depth) |
  | `PlugStartDepth` | read-only | P − G, below the plug board's top |
  | `RidgePass` | on | Flatten the plug's narrow ridges for a tipped V-bit (see *The flat tip*) |
  | `PlugBoundary` | chosen in the dialog | `Margin`: a ring around the plug; `Stock`: the whole stock of the plug Job. **A choice for the user (user decision)**; the dialog preselects Margin (my call) |
  | `MirrorAxis` | X | X: flip left–right; Y: flip front–back. Mirrored about the design's bounding-box center |
  | `PlugMargin` | 10 mm | Margin mode: width of the flat ring cleared around the plug's footprint at the floor (the design offset outward by S·t); the floor starts r_t beyond the plug wall, so the ring is PlugMargin − r_t wide |

  In Margin mode (my call) the outer edge of the ring is a **straight
  end-mill wall, not a V-wall**: the V-bit carves only the letter walls, and
  the end mill clears the ring. A ring (PlugMargin − r_t) narrower than
  the end mill's diameter is an error. The ring is the room for sawing the plug free.

  v1's carving fields (Discretize, Colinear, StepLength, Tolerance,
  RestScallop) are kept as properties of the plug op too.
- **Plug clearance:** v1's V-Carve Clearance op, linked to the plug op with
  `VCarveOp`. It must ask the linked op for its regions and depth mapping
  instead of calling the module-level `region_sets` / `carve_setup`
  (dispatch through the proxy). With Margin, the margin ring is part of the
  floor and gets cleared by the end mill.
- **Mirroring happens inside the op.** The plug Job's model is a normal Job
  clone of the unmirrored sketch, so the inputs stay sketches only and there
  is one source of truth. As a result, the plug Job's model in the 3D view
  shows the unmirrored design under a mirrored path. This is accepted; the
  README says so.

### The command

1. The user selects the design sketch (or a Job's clone of it). The Job of the
   selection (else the only Job, else FreeCAD's Job chooser) is the source
   Job: it needs at least one V-bit and one end-mill tool controller, and it
   is only read, never changed.
2. A small dialog asks for the beginner settings: V-bit and end mill (from
   that Job's tool controllers), pocket depth, glue gap, and the plug
   boundary (Margin: "saw the plug free inside a ring"; Stock: "clear the
   whole plug board, takes longer"). It opens with
   defaults that fit the chosen V-bit (below), and an "Advanced: edit the op
   properties afterwards" hint.
3. The command creates a new Job "<sketch> Pocket" with the sketch as model,
   copies of the two tool controllers, a copy of the source Job's stock
   settings (FreeCAD's stock template), and the v1 pair with Flat Depth P. It
   creates a new Job "<sketch> Plug" with the same sketch as model, its own
   copies of the two tool controllers, and the plug op plus its clearance op
   (clearance first, as in v1). The labels say which wood each Job is for.
4. The plug Job's stock is FreeCAD's model-based stock, with `ExtZneg` set to
   the selected Job's stock thickness, or to 1 mm below the plug's floor
   (P − G + S) if that is deeper (my call: FreeCAD's default 1 mm board made
   the simulator cut through it). The user sets the real plug wood's
   thickness; the README says it must be at least P − G + S plus a safe base.
5. The dialog also has a **Ridge pass** checkbox (on), see *The flat tip*.

**Defaults that fit the bit** (my call): `P = min(3 mm, 0.6 · cone height)`,
`G = 0.2 mm` (the top of Vectric's 0.02–0.2 mm range, the most forgiving),
`S = min(1.5 mm, cone height − (P − G))`. For a 90° 10 mm bit this gives
P = 2.97 mm, S = 1.5 mm and a total plug depth of 4.27 mm against a 4.95 mm
cone.

### Checks

The checks are errors (no path) unless marked as warnings.

- `0 < G < P`.
- **The plug fits the cone:** `P − G + S ≤ cone height`. Otherwise the shank
  would cut vertical plug walls that can't seat. The message says how much to
  reduce P or S.
- **Same V-bit:** the plug op's tool must equal the pocket op's in diameter,
  angle and tip diameter. The two Jobs have separate tool controllers, so this
  is checked on every recompute, not only at creation.
- **Pocket depth capped** by the cone: v1's existing warning.
- **Warning:** the plug Job's stock is thinner than `P − G + S`, or (in Stock
  mode) does not cover the mirrored design.
- The linked pocket op has a Flat Depth (> 0); without one, P is undefined.
- `G > 0` stays the rule. The flat tip is handled by the ridge pass, not by G.

### Testing

- Pure-math (`geom.py`): plug depth mapping, defaults that fit the bit, and
  the checks.
- freecadcmd integration (`tests/fc/`):
  - plug op on the RECT/RING/AOB-like fixtures: mirrored about the bbox
    center, complement with letter holes and counters, depths, and both
    boundary modes;
  - the command creates two Jobs with the right links and tool controllers;
  - changing the sketch or the pocket depth updates the plug;
  - a different V-bit in the plug Job is an error.
- **Fit test:** take cross-sections (several Y lines through letters, narrow
  strokes and counters). From the paths and the tool shape, build the cut
  profile of the pocket and of the flipped, seated plug. Assert that they
  don't overlap anywhere apart from the documented tip effect, that the walls
  are within a tolerance (e.g. 0.02 mm) where wide, and that the floor gap
  equals G. This is the test that catches sign and mirror mistakes.
- Offscreen GUI test: the command and its dialog.

## Constraints

As for v1: FreeCAD 1.0.2, 1.1.4 and 26.3rc2, the `PathOp.ObjectOp` hooks,
sketches only, an addon layout with no patching of CAM files, LGPL-2.1+ SPDX
headers, and the full suite run via `FREECAD_APPRUNS` before every commit.

### Step-down (user decision: multiple passes)

- The four ops get FreeCAD's standard `StepDown` (`FeatureStepDown`), with
  the setup sheet's default, which is the tool diameter (one pass in
  practice). **The Inlay command sets `StepDown = 1.5 mm` on its four ops
  (user decision).** `StepDown = 0` means one pass, which is what v1
  documents restored from before this change get, so their paths don't
  change.
- **Principle:** pass k at depth `d_k = min(k·StepDown, final depth)` cuts
  exactly what the final cut removes above `d_k`. Every pass is a subset of
  the final cut, and the last pass gives the same result as one pass.
- **Pocket side:** pass k is v1 with flat depth `d_k`. The V-bit cuts the
  medial axis clamped at `d_k`, the boundary loop at `r_flat(d_k)`, and the
  rest pocket of that level. The end mill clears that level's floor, the
  region offset inward by `r_flat(d_k)`, not only the final floor. That is
  why the V-bit's rest area per level stays small.
- **Plug side:** levels are counted from the plug wood's real top, down to
  `P − G + S`. Levels above `Z_v` have a
  "negative" depth relative to `Z_v`. The cross-section there is the
  complement grown outward by the remaining slope. This doesn't fit v1's
  `FlatDepth ≥ 0` directly; the builder has to work out the mapping, keeping
  the principle above. (Resolved in the plan: level k has depth
  `d_k = s_k − (P − G)` relative to `Z_v`, negative above it. The medial
  carve is clamped at `d_k`, and the floor is the complement offset inward by
  `r_t + d_k·t` (outward when that is negative), clipped to the plug
  boundary. That is exactly the level's cross-section.)
- The end-mill passes run before the V-bit passes, as in v1. Whether passes
  run level by level across the two tools is not needed; each op does all of
  its own levels.
- Tests: for each op, the multi-pass result's deepest cut equals the
  one-pass result, and no pass cuts outside the final cut. The fit test also
  runs with step-down on.

## Left to the builder

- How the plug op shares code with V-Carve Flat (subclass or shared helpers).
  The clearance op must not need to know which kind of op it is linked to.
- The dialog layout. The exact way tool controllers are copied into the plug
  Job.
- Safe and clearance heights for the plug op: they must follow the plug
  stock's top, not `Z_v`. Verify FreeCAD's height expressions don't use the
  op's Start Depth.
- Whether the read-only `PlugStartDepth` is a property or only shown in the
  task panel.
