# FreeCAD V-Carve addon: fit check, rest clearing, responsive GUI (v3 design)

Three features, decided with the user on 2026-10-26, after the 0.2.0 release:

- **A. Check Inlay Fit:** a command that shows where a seated plug would hit the pocket, before
  anything is cut.
- **B. Rest clearing:** a chain of end mills (large, then smaller "rest" ones), so the V-bit no
  longer clears large floor areas.
- **C. Responsive GUI:** a progress indicator with Cancel for the long computations, so FreeCAD
  stays responsive.

They share code paths (B changes what A must simulate; C wraps A and the inlay command), so one
branch, one plan.

## Why

- **A.** Both inlay bugs fixed in 0.2.0 (the uncut O centre and the rounded plug corners) were
  found by the user in the CAM simulator screenshots, after the Jobs looked fine. They were only
  measured with the seated-fit simulation in `tests/fc/fit.py`. A ruined plug costs wood and
  hours; the user wants to know before cutting or before post-processing.
- **B.** On real cuts (the "AOB" test document) the V-bit's rest clearing takes the longest of
  all passes. A V-bit with a 0.1 mm tip clears area very slowly. A small end mill should clear
  almost all of what the main end mill cannot reach; the V-bit only the corners nothing else
  reaches.
- **C.** V-Carve Inlay recomputes all ops on the GUI thread. That takes long enough that Ubuntu
  shows "FreeCAD is not responding" and offers to close it. The fit check takes minutes and would
  do the same.

## Goals

### A. Check Inlay Fit

1. A command **"Check Inlay Fit"** in the CAM menu/toolbar next to V-Carve Inlay. Used after
   V-Carve Inlay, before cutting or post-processing.
2. It simulates the plug seated in the pocket from the **toolpaths of both Jobs** (what the
   machine will cut), not from the sketch: the V-carve op and **every active clearance op**
   (including rest ops) of the pocket Job, and the plug op and every active clearance op of the
   plug Job. Ops with errors or empty paths are reported, not silently ignored.
3. Selection: the user selects the plug op, the plug Job, the pocket op or the pocket Job (any of
   them identifies the inlay: the plug op's `PocketOp` links the two). Without a usable selection
   it says what to select (report view, as the other commands do with `_warn`).
4. Result: a document object in the tree, labelled `<sketch label> Fit`, placed in the pocket Job's
   group or next to it (builder's choice where it shows best). It marks **the pocket board** in
   the 3D view:
   - **red** where the plug would hit the pocket (gap below `-tolerance`),
   - **a second colour (blue)** where the plug leaves a void wider than the glue gap
     (gap above `GlueGap + tolerance`) on the pocket walls,
   - nothing elsewhere.
   It can be hidden, its transparency changed, and it is saved with the document.
5. It ignores the plug's waste: points of the mirrored plug outside the plug boundary (beyond the
   saw ring in Margin mode, outside the stock in Stock mode) are not checked. **Inside** the
   boundary everything is checked, including the ring between the pocket edge and the saw ring:
   there the plug's cleared floor must stay above the board surface (by `SurfaceGap`); an uncut
   island in that ring would rest on the board and stop the plug seating, so it is marked red on
   the board surface around the pocket. (Claude's call, following the anti-goal "when in doubt,
   mark".)
6. One summary line in the report view: worst collision (mm, negative), number of collision
   spots, worst void, or "fits" when there is neither. No popup (user rule: no GUI dialogs from op
   code; use FreeCAD's "Show report view on error" preference).
7. It does **not** recompute on its own (a run takes minutes). It stores a signature of the
   paths it checked (for example a hash of each checked op's path commands). When a later
   recompute finds the paths changed, it does not re-run the simulation; it puts itself in an
   error state with the message "outdated: run Check Inlay Fit" (FreeCAD's error mark in the
   tree) and its marks stay as they were. Claude's call: FreeCAD's touched mark cannot be kept
   through a recompute without touching the object inside its own execute, which is unreliable
   across builds. Running the command again **replaces** the existing Fit object of that inlay:
   only one per inlay.
8. It runs under C's progress indicator and can be cancelled; cancelling leaves the previous Fit
   object (if any) unchanged.

### B. Rest clearing

1. **VCarveClearance gets a boolean property `RestOnly`** (default False, group like the other
   op properties, with a tooltip). With it on, the op clears only the part of the floor that the
   clearance ops **before it in the Job's operation list**, linked to the **same** V-carve (or
   plug) op and active, could not reach. Order in the Job = cutting order, so a chain
   6 mm → 3 mm (rest) → 1 mm (rest) works with any number of ops.
2. The V-bit's rest pass (V-Carve Flat and V-Carve Plug) clears only what **all** active linked
   clearance ops together could not reach. Today it uses only the first one and warns about the
   others; that warning goes.
3. A rest op must reach into the leftovers **from the area already cleared**: the leftover
   corners are often narrower than the rest end mill, but it can still reach them from the
   cleared side. So its cut region is the leftover area grown by the rest tool's reach and kept
   inside the floor, not the leftover area alone (pocketing only the leftover slivers would cut
   nothing). The rest op's paths should stay mostly within the leftovers plus a margin; it must
   not re-clear the whole floor.
4. A `RestOnly` op with no earlier active clearance op on the same V-carve op clears the whole
   floor and logs a warning (decision: Claude's call, the user agreed).
5. A `RestOnly` op whose end mill is not smaller than every earlier one in its chain logs a
   warning (it would cut little or nothing) but still runs.
6. **Recompute on change:** deleting, deactivating, reordering a clearance op, or changing its
   tool, `Allowance` or `RestOnly`, makes the later clearance ops of the same chain and the linked
   V-carve/plug op recompute. This also removes today's README limitation "after deleting a
   clearance op, recompute its V-carve op by hand". The existing `RestClearance` property (a
   single (radius, allowance) vector the V-carve op stores to notice end mill changes) must be
   replaced or extended to cover the whole chain; old documents must still open (the op's
   `opOnDocumentRestored` already migrates properties).
7. **Pair command unchanged:** V-Carve pair still creates one clearance op. Users add rest ops
   with the existing V-Carve Clearance command and tick `RestOnly`. The clearance task panel
   gets the `RestOnly` checkbox.
8. **V-Carve Inlay dialog:** a new optional **"Rest end mill"** combo listing the Job's end mill
   tool controllers plus "None" (the default). When set, both the pocket Job and the plug Job get
   a second clearance op with that end mill (a copied tool controller, as the inlay already copies
   the V-bit and end mill), `RestOnly` on, placed after the first clearance op and before the
   V-carve/plug op, with the same step-down. The dialog blocks a rest end mill that is not smaller
   than the end mill (same mechanism that blocks too-deep pockets).
9. The plug op's other uses of the end mill (Stock-mode bound grown by its radius; the "stock
   margin narrower than the end mill" warning) keep using the first (non-rest) clearance op's
   end mill.

### C. Responsive GUI

1. Long computations show FreeCAD's progress indicator (the status-bar progress bar FreeCAD uses
   for its own long jobs) and keep the GUI event loop running, so the desktop does not show "not
   responding". Pressing Cancel (FreeCAD's progress bar is cancelled with Esc / its button)
   stops the computation.
2. Covered: the **V-Carve Inlay command**, the **Check Inlay Fit command**, and **recomputes of
   the addon's ops** (V-Carve Flat, V-Carve Plug, V-Carve Clearance), which are long on large
   designs.
3. Cancel semantics:
   - V-Carve Inlay: the whole creation is undone (the command's transaction is aborted), nothing
     is left in the document.
   - Check Inlay Fit: no new Fit object; an existing one is unchanged.
   - An op recompute: the op logs "cancelled" and keeps an empty path / error state, so it shows
     as failed and can be recomputed again. No half-computed path is kept.
4. The user does not need to keep working in FreeCAD meanwhile (user decision): no background
   threads. FreeCAD's document and OCC geometry are not safe to use off the GUI thread.

## Non-goals

- Working in FreeCAD while a computation runs.
- Changing the V-Carve pair command or adding a dialog to it.
- Automatic re-checking of the fit on every change.
- Fixing a bad fit automatically: the check only shows it.
- Checking plain (non-inlay) V-carves.

## Anti-goals

- The check reporting "fits" for a plug that collides inside the pocket. False alarms in the
  waste are annoying; missed collisions inside the pocket ruin the wood. When in doubt, mark.
- A rest op that re-clears the whole floor (no time saved) or cuts into the pocket walls.
- Cancel leaving a broken half-state (a Job without its ops, a path cut off mid-way).
- Popups from op code.

## Constraints

- LGPL-2.1-or-later SPDX header on every new file; clean-room (no F-Engrave code).
- Must work on all four test builds: FreeCAD 1.0.2, 1.1.1, 1.1.4 and 26.3rc2. Any FreeCAD API
  used (progress indicator, view provider colouring) must exist on all four.
- Headless (`freecadcmd`) must keep working: the ops and the fit computation run without a GUI;
  the progress indicator degrades to nothing there.
- Regression test first for every fix; the full 4-build suite (currently 41 tests, about 8 min)
  passes before committing.
- The fit simulation in `tests/fc/fit.py` (`cut_height`, `_lowest`, `g1_segments`,
  `tool_profile`, `seated`) is the starting point. It moves into the addon package; the tests then
  import it from there. It refuses arcs (G2/G3): the addon's ops emit only G0/G1 today; keep it
  that way or extend the simulation.
- The simulation is exact between path samples but slow (the AOB check took about 3 minutes at a
  0.25 mm grid in a script). Speed it up where cheap; it must stay accurate enough to see a
  0.05 mm collision.

## Decided by the user

- A: run after V-Carve Inlay, before cutting/posting; collisions shown in the 3D view, on the
  pocket board, red; voids too, in another colour; result is a tree object that goes outdated and
  is replaced by re-running.
- B: a `RestOnly` flag on VCarveClearance, chain by Job order, nothing added to the pair command;
  an optional rest end mill in the V-Carve Inlay dialog; both plain V-carves and inlays.
- C: progress indicator with Cancel is enough; no background work.

## Test data

The user's AOB document (the 0.2.0 test document: text "AOB", 3.175 mm end mill, 90° V-bit
10 mm with a 0.1 mm tip) has copies in the session scratchpad
(`/tmp/claude-1000/-home-alf-Projects-programming-misc-freecad-vcarve/c437d1b8-6fba-4dbb-8677-d0595316cbdd/scratchpad/aob/vcarve-test-AOB-1.FCStd`
and `after_inlay.FCStd` there). It is used for measurements and tuning by script, and the user
checks the result in the GUI. It is **not** committed and not part of the 4-build suite (it is
the user's document, and an AOB fit run would add minutes per build). The suite uses small
synthetic designs, as `tests/fc/test_fit.py` does today. (Claude's call.)

## Left to the builder

- The fit grid resolution, the tolerance (start from the tests' 0.02 mm) and the void threshold
  beyond `GlueGap + tolerance`, as long as the 0.2.0 AOB document shows no false collisions
  inside the pocket and the known tipped-bit corner voids are visible but not alarming.
- How the marks are drawn (coloured points, a coloured mesh or faces on the pocket floor/walls),
  as long as red and blue are clearly visible on the pocket and can be hidden.
- How the Fit object is built (a `Part::FeaturePython`, `Mesh::FeaturePython` or similar) and how
  it notices the Jobs changed (links to the ops so FreeCAD's dependency graph touches it is the
  obvious way, as long as recomputing it does not re-run the simulation).
- How the rest op's region is computed (point B.3), and how the chain is stored for change
  detection (point B.6).
- Progress step granularity: a single uninterruptible OCC / Path.Area / Voronoi call may block;
  steps should be short enough (a few seconds at most on the AOB document) that the desktop's
  not-responding timeout is not reached.
- Where the fit computation lives (a new module such as `vcarve_flat/fit.py` is the obvious
  place) and the command's icon.

## Done when

- The full 4-build suite passes, with new tests for: rest-only clearing (chain of three, wrong
  order, no earlier op, delete/deactivate triggers recompute), the V-bit's rest area shrinking
  with a rest op, the inlay with a rest end mill, the fit check on a fitting and on a
  deliberately colliding inlay (e.g. the 0.2.0 bugs reintroduced via a too-large `PlugMargin`
  hole or a mock), cancel for each covered computation, and an old document (saved by 0.2.0)
  opening.
- On the user's AOB document, with a 3.175 mm end mill and a 1 mm rest end mill, the V-bit's
  rest pass is much shorter (path length reported in the PR), and Check Inlay Fit shows no red
  inside the pocket.
- README: the new command, `RestOnly`, the inlay dialog's rest end mill; the limitation about
  recomputing after deleting a clearance op is removed. CHANGELOG "Unreleased" section.
