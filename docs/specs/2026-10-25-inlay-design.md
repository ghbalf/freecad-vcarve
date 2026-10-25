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
   inlay. It creates **two Jobs in the same document**:
   - **Pocket Job** (the board): a V-Carve Flat op with Flat Depth equal to
     the pocket depth, plus its V-Carve Clearance op. These are v1 ops.
   - **Plug Job** (the inlay wood): a V-carve plug op plus a clearance op. It
     carves the mirrored design as a raised plug.
2. Both Jobs use **the same sketch** and **the same V-bit**. If the design
   changes, both follow it on recompute.
3. **Beginner settings**, asked for when the command runs: V-bit, end mill,
   pocket depth, glue gap. Every other value gets a sensible default.
4. **Advanced settings** are ordinary op properties: plug start depth (shown,
   derived), surface gap (the plug's flat depth), plug boundary or margin,
   mirror axis, and all v1 fields.
5. The tool **prevents the common inlay mistakes** it can see (see
   *Checks*), with clear messages that name the sketch or op.
6. Unit-tested geometry, including a test that **the parts fit** when seated
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
  narrower than 2·P·t have a V bottom in the pocket. The plug ridge's apex
  lands exactly on it when the walls close, whatever G is. G only protects
  the wide, flat-floor areas.
- **Tip compensation (my call, on by default).** A flat tip makes narrow
  pocket grooves r_t/t shallower than a sharp V. The plug is rigid, so if one
  ridge stopped early, the whole plug would stop there and leave a gap of
  r_t on every wall. That is 0.05 mm for a 0.1 mm tip, and 0.5 mm for a 1 mm
  tip. The plug op therefore shrinks the letters by r_t: it offsets the
  complement outward by r_t before carving. The plug then seats r_t/t deeper,
  the narrow ridges reach the groove floor exactly when the walls close, and
  the start depth becomes `P − G + r_t/t` so the floor gap stays G. The fit
  test covers this.

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
  | `PlugStartDepth` | read-only | P − G + r_t/t, below the plug board's top |
  | `PlugBoundary` | see open question 2 | `Margin`: a ring around the plug; `Stock`: the whole stock of the plug Job |
  | `PlugMargin` | 10 mm | Margin mode: width of the flat ring cleared around the plug's footprint at the floor (the design offset outward by S·t) |

  In Margin mode (my call) the outer edge of the ring is a **straight
  end-mill wall, not a V-wall**: the V-bit carves only the letter walls, and
  the end mill clears the ring. A margin narrower than the end mill's
  diameter is an error. The ring is the room for sawing the plug free.
  | `MirrorAxis` | X | X: flip left–right; Y: flip front–back. Mirrored about the design's bounding-box center |

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

1. The user selects the design sketch in a Job that has at least one V-bit and
   one end-mill tool controller (as for v1's Pair). That Job becomes the
   Pocket Job.
2. A small dialog asks for the beginner settings: V-bit and end mill (from
   that Job's tool controllers), pocket depth, glue gap. It opens with
   defaults that fit the chosen V-bit (below), and an "Advanced: edit the op
   properties afterwards" hint.
3. The command creates, in the Pocket Job, the v1 pair with Flat Depth P. It
   creates a new Job "<sketch> Plug" with the same sketch as model, copies of
   the two tool controllers, and the plug op plus its clearance op (clearance
   first, as in v1). Both Jobs get labels that say which wood they are for.
4. The plug Job's stock defaults to FreeCAD's model-based stock. The user sets
   the plug wood's real thickness; the README says it must be at least
   P − G + S plus a safe base.

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
- `G > 0` stays the rule with tip compensation; the flat tip is handled by
  the compensation, not by G.

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

## Open questions for the user (to settle before planning)

1. **Step-down.** v1 cuts in one pass. The plug is cut P − G + S deep (about
   4.3 mm with the defaults), with the V-bit about 8.5 mm wide at the top and
   the end mill at full depth. v1 has no multi-pass code, so step-down would
   be a work package of its own, covering the V-bit carve and the clearance
   op. Is it in v2, or is one pass OK for a first version?
2. **Plug boundary default:** Margin (a ring is cleared, and the plug is sawn
   free inside it before gluing) or Stock (the whole plug board is cleared,
   so there is nothing to saw free, but it takes longer)?

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
