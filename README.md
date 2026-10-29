# V-Carve Flat

A FreeCAD CAM addon that V-carves 2D sketches to a **flat depth** and adds an **end-mill clearance
operation** for the floor. Think of the Vectric-style "flat depth + clearance" workflow: the V-bit
cuts the sharp edges and the narrow strokes, the end mill removes the wide flat areas quickly.

Supported FreeCAD versions: 1.0.2, 1.1.4 and 26.3rc2 (minimum 1.0.0).

**New here?** The [user guide](docs/guide/Home.md) covers installation and walks through carving a sign,
an inlay and a photo, with screenshots.

## Install

Symlink the repository into your FreeCAD user Mod directory. Find that directory by running
`App.getUserAppDataDir()` in the FreeCAD Python console; it differs by version, for example
`~/.local/share/FreeCAD/` or `~/.local/share/FreeCAD/v1-1/`.

```sh
ln -s /path/to/freecad-vcarve "<UserAppData>/Mod/freecad-vcarve"
```

Restart FreeCAD. Addon Manager: a custom repository URL will be added here once the repository is
public (`<placeholder, no public repository yet>`).

## Usage

The commands appear in the CAM workbench, in the "New Operations" toolbar just before the Engrave
dropdown, and in the CAM menu after Vcarve:

- **V-Carve Flat**: the V-bit operation.
- **V-Carve Clearance**: the end-mill operation that clears the flat floor.
- **V-Carve Pair**: creates both, linked, in one step.
- **V-Carve Inlay**: sets up a pocket and a matching plug, see below.
- **Check Inlay Fit**: simulates the seated plug and marks where it collides or leaves a gap, see below.
- **V-Carve Photo**: carves an image plane as grooves whose depth follows its darkness, see below.

Workflow:

1. Draft ShapeString (or any 2D drawing) and convert it to a Sketch.
2. Create a CAM Job with the sketch as its model. Add a V-bit tool controller and an end mill
   tool controller.
3. Select the sketch (or some of its edges) and run **V-Carve Pair**.

Selection: selecting a whole sketch carves all of it. Selecting edges carves only the loops they
belong to: an edge picks its whole closed loop, and holes count only if their edges are selected.

**Flat depth.** `FlatDepth` is the depth of the flat floor below Start Depth. With `FlatDepth = 0`
the V-bit carves as deep as its cone allows and no floor is made. A flat depth deeper than the
V-bit cone allows is capped and a warning is logged. Areas wider than the bit at that depth are
reported too; set a flat depth to clear them.

**Sharp corners.** The V-bit's wall pass around a flat floor runs into each inner corner of the
floor outline instead of circling it, so the cone leaves the wood's corner sharp down to the floor
(the plug's letter corners too). The floor's own corners keep only the V-bit's tip radius. Such a
corner leaves a sharp ridge in the pocket, so the plug op cuts the matching valley: a straight pass
down the bisector of each of the design's inner corners.

**Clearance.** The clearance op's `VCarveOp` property links it to the V-carve op (Pair does this
for you); it cuts the floor with the end mill, using `PocketPattern`, `StepOver` and `Allowance`.
Where the end mill cannot reach part of the floor (corners, narrow areas), the V-bit clears that
rest area. With no clearance op the V-bit clears the whole floor, which is slow, and a warning says so.
The V-carve op follows its clearance op: after you change the end mill, `Allowance` or `Active`,
re-point `VCarveOp`, or delete or reorder clearance ops, the next recompute updates the V-bit rest area
too (in the same recompute).

**Rest machining.** The active clearance ops of a V-carve op form a chain, in the Job's order. The first
clears the floor; each following op with `RestOnly` on and a smaller end mill clears only what the ops
before it left (corners, narrow areas); the V-bit cleans up the rest. A `RestOnly` op with no clearance op
before it clears the whole floor, and a warning says so.

## Properties

V-Carve operation (group "V-Carve"):

| Property | Default | Meaning |
|---|---|---|
| `BaseShapes` | empty | Whole sketches to carve (edge selections go to the standard `Base`) |
| `FlatDepth` | 0 mm | Depth of the flat floor below Start Depth (0 = as deep as the V-bit cone allows) |
| `Discretize` | 0.01 | Deflection used to discretize curves |
| `Colinear` | 10 | Angle (degrees) below which medial-axis segments count as colinear |
| `StepLength` | 0.5 mm | Sampling distance along the medial axis |
| `Tolerance` | 0.01 mm | Simplification tolerance of the toolpath |
| `RestScallop` | 0.05 mm | Allowed scallop height where the V-bit clears floor the end mill cannot reach |

Clearance operation (group "V-Carve"):

| Property | Default | Meaning |
|---|---|---|
| `VCarveOp` | none | The V-Carve operation whose floor is cleared |
| `PocketPattern` | Offset | Clearing pattern: Offset or ZigZag |
| `StepOver` | 40 % | Stepover as a percentage of the tool diameter |
| `Allowance` | 0 mm | Distance kept from the floor boundary |
| `RestOnly` | off | Clear only what the earlier clearance ops of the same V-carve op left; warns when its end mill is not smaller than theirs |

## V-carve inlay

**V-Carve Inlay** makes a pocket in one board and a matching plug in another. Select one sketch (or its
clone in a Job) and run the command. The tool controllers come from the sketch's Job (or the only Job),
which needs a V-bit and an end mill; that Job itself is not changed. The dialog asks for:

- **V-bit** and **End mill**: the tool controllers to use.
- **Rest end mill** (optional, *None* by default): a smaller end mill that clears what the end mill left,
  as a `RestOnly` clearance op after the first one in both Jobs. It must be smaller than the end mill.
- **Pocket depth** P and **Glue gap** G: the defaults fit the chosen V-bit.
- **Plug boundary**: *Margin* (saw the plug free inside a ring) or *Stock* (clear the whole plug board,
  which takes longer).
- **Ridge pass**: on by default, see below.

The command creates two new Jobs, each with its own copies of the two tool controllers:

- **The pocket Job** "`<sketch> Pocket`" has your Job's stock settings and the usual V-Carve Pair with
  `FlatDepth` = P.
- **The plug Job** "`<sketch> Plug`" has a V-Carve Plug op and its clearance op. The plug op carves the mirrored design as a raised plug.

The plug is carved at depth P − G + S below the plug board's top (S is `SurfaceGap`; `PlugStartDepth`
shows P − G). Seated, the plug's cut floor sits S above the pocket board's surface. Saw and plane
that material off. The plug op must use the same V-bit as the pocket op, and P − G + S must not exceed
the V-bit's cone height.

**Z and stock.** Zero Z on the real top of the plug wood, carefully: an error of e makes the letters
e taller. The plug Job's stock starts as thick as your Job's stock, or 1 mm deeper than
the plug's floor (P − G + S) if that board is too thin; set it to the real plug wood afterwards. The plug
op warns when the stock is thinner than P − G + S. In *Stock* mode the end mill clears the floor out to the stock edge, so the stock must extend past the plug's outline (the mirrored design grown by the V-bit's flat radius) by at least the end mill diameter. FreeCAD's default 1 mm stock margins are narrower, so the end mill cannot cut the strip: the clearance op logs "no floor reachable by the end mill" (a warning) and the plug op warns that the stock margin is narrower than the end mill, with the advice to set the plug Job's stock to the real board size. The V-bit rest pass then clears the strip and, as its path is not clipped to the stock, runs out to the stock edge and a little past it, through air.

**Model view.** The plug Job's model shows the unmirrored design; the op mirrors it (about `MirrorAxis`)
when it makes the path.

Plug operation (group "V-Carve Plug"):

| Property | Default | Meaning |
|---|---|---|
| `PocketOp` | set by the command | The pocket's V-Carve Flat op (sketches, P and V-bit come from it) |
| `GlueGap` | 0.2 mm | Gap between plug top and pocket floor when seated |
| `SurfaceGap` | set by the command: min(1.5 mm, cone height − (P − G)) | Gap between plug board and board surface when seated (the plug's flat depth S) |
| `RidgePass` | on | Flatten the plug's narrow ridges for a tipped V-bit |
| `PlugMargin` | 10 mm | Margin mode: width of the flat ring cleared around the plug (counters are cleared whole, however wide); its width beyond the V-bit tip radius must be at least the end mill diameter |
| `PlugBoundary` | Margin | Margin: a ring around the plug; Stock: the whole stock of the plug Job |
| `MirrorAxis` | X | X flips left-right, Y flips front-back, about the design's bounding-box centre |
| `PlugStartDepth` | read-only | P − G |

**Narrow strokes.** Strokes narrower than 2·(r_t + P·tan(half angle)), with r_t the tip radius, have a V bottom in the pocket and no
floor gap. The plug's ridge lands on it whatever G is. G protects only the wide, flat areas.

**Tip and ridge pass.** A V-bit with a flat tip (radius r_t) cuts a narrow pocket groove with a flat
bottom, but the plug's ridge for that stroke has a sharp apex. The apex would land on the flat bottom
and lift the plug. The ridge pass (`RidgePass`) cuts each plug ridge flat where it is narrower than
the tip. It runs once, after the plug's last level, and makes no path for a pointed bit. It leaves a
small gap at convex corners. With t = tan(half angle), start = P − G and a corner whose bisector makes
the half-angle h with the sides: the gap is r_t/cos h wide on each side (1.41·r_t at a 90 degree
corner), reaches (r_t + start·t)/sin h from the corner, and is 2·r_t·sin h/t high on the bisector.
These gaps are accepted. The plug op warns when the design has gaps narrower than the tip.

The flat tip's centre cannot get closer than r_t/sin(a/2) to a sharp inner corner of the plug's cut area
(angle a), such as the mirrored tip of a counter. The corner's valley pass therefore goes on along the bisector
at the plug's floor to that point, so the tip cuts the corner too. Its cone widens the cut there by less than
r_t, which leaves a sliver of void that the glue fills.

**Rounded tips.** FreeCAD's V-bit only has a flat tip. For a rounded tip, enter as Tip Diameter the
width where the rounding meets the cone. The real tip lies inside that model, so errors are gaps,
never collisions. Zeroing Z on the bottom of the rounding makes the floor gap larger, never smaller.
Pointed V-bits are best for inlays.

**Step-down.** The command sets a 1.5 mm step-down. The clearance op follows the levels of its V-carve
op (pocket or plug). On the pocket op, `FlatDepth` 0 means no flat floor at all: the clearance op cuts nothing, and the V-bit stops adding step-down levels once a level no longer cuts deeper. The plug op always has a flat floor (it hides `FlatDepth`), and it errors if its pocket op has `FlatDepth` 0.

## Photo V-carve

**V-Carve Photo** carves a picture as parallel V-grooves: dark areas get deep, wide grooves, light areas
shallow ones or none. It suits light, close-grained hardwood such as maple.

1. **Import the photo.** File → Import, choose the image and "Image plane". Set the plane's size
   (`XSize`, `YSize`) and place it over the stock, flat in XY. It is carved as the top view shows it,
   so a plane facing down gives a mirrored carving. Only the part
   over the stock is carved; the op warns when the image reaches outside it.
2. **Prepare it beforehand** in GIMP or similar. Colour images are converted to grey
   (0.299 R + 0.587 G + 0.114 B), but converting yourself gives control over which colours turn dark.
   Raise the contrast there, and paint whatever should stay uncut (the background) pure white;
   transparent pixels stay uncut, even with `Invert`.
3. Create a CAM Job with a V-bit tool controller, select the image plane and run **V-Carve Photo**
   (with a single image plane in the document it is picked anyway; otherwise pick it in the task panel).
4. **Facing the board first?** CAM's MillFace needs a face picked under Base Geometry and does nothing
   without one, so a sketch-only Job needs a solid for the board (e.g. a Part Cube with its top at the
   faced height) whose top face you pick. Then set the photo's `StartDepth` to the faced surface: it
   defaults to the stock top. The op warns when a MillFace before it faces below its `StartDepth`.

Each groove is cut at depth = darkness × `MaxDepth`, where darkness is 0 for white and 1 for black on a
linear (not sRGB) light scale, so black always reaches `MaxDepth`. The bit lifts out where the depth is
under `MinDepth`. A groove is tip + 2·depth·tan(half angle) wide. When that is wider than `LineSpacing`
at `MaxDepth`, neighbouring grooves merge into a flat dark area and the op warns. The default spacing
is an expression: the groove width at `MaxDepth` plus 5 %, filled in from the op's V-bit, so it
follows `MaxDepth`. Picking a V-bit (also a different one) fills it in anew, replacing a spacing you
typed; clear the expression (f(x) button) after that to set your own.

Patterns (group "V-Carve Photo"):

- **Lines**: parallel lines at `Angle`.
- **Hatch**: two crossed line sets, at `Angle` and `HatchAngle`. Each set cuts 1 − √(1 − darkness) of
  the depth: two crossed sets cover 1 − (1 − c)² of the surface, so together they match the darkness,
  and both reach `MaxDepth` at black.
- **Custom**: the edges of the `Vectors` objects instead of straight lines, for example paths drawn in
  Inkscape: save them as SVG, File → Import the SVG into the document, and add the imported objects
  with "Add selected" in the task panel. Sketches work too. The image plane still sets the depth.

| Property | Default | Meaning |
|---|---|---|
| `ImagePlane` | picked in the panel | The image plane to carve |
| `Pattern` | Lines | Lines, Hatch or Custom |
| `Vectors` | none | Objects whose edges are carved (Custom) |
| `Angle` | 45° | Direction of the lines, from the X axis |
| `HatchAngle` | 135° | Direction of the second line set (Hatch) |
| `LineSpacing` | groove width at `MaxDepth` × 1.05, as an expression | Distance between lines; follows `MaxDepth` until you clear the expression (f(x) button) |
| `MaxDepth` | 2 mm | Depth of black below Start Depth; capped at the V-bit's cone height |
| `MinDepth` | 0.05 mm | Shallower than this, the bit lifts out |
| `SampleStep` | 0.25 mm | Distance between depth samples along a line; finer pixels are averaged to it |
| `Contrast` | 100 % | Contrast around mid-grey; above 100 % strengthens it |
| `Invert` | off | Swap dark and light |
| `BandAverage` | off | Lines and Hatch: each groove follows the image averaged over its whole band (`LineSpacing` wide) instead of the strip under the line. Truer tone and thin details between lines show, but a highlight smaller than the spacing fades |
| `Tolerance` | 0.01 mm | Simplification tolerance of the toolpath |

**Eyes.** A portrait lives or dies by its eyes. Make the pupil fully black and leave a small pure-white
catchlight in it, at least a groove width across, so the bit lifts out there. For fine detail use a
narrower bit (30°) or closer `LineSpacing`, or trace the eye's outlines in Inkscape and carve them in a
second op with the Custom pattern.

## Check inlay fit

**Check Inlay Fit** simulates the plug seated in the pocket (flipped, as you would glue it) from the G1
moves of both Jobs' ops, clearance ops included. Select the plug or pocket op or Job of an inlay and run
the command. It creates a "`<sketch> Fit`" object with marks just above the pocket: **red** where the plug
collides with the board (the seated gap is below −0.02 mm, so it would not seat) and **blue** where a void is
left (inside the pocket, a gap wider than the glue gap by more than 0.1 mm). The summary (worst collision,
worst void, the number of colliding grid points) goes to the report view. A new check replaces the previous Fit object,
as one undo step.

The check refuses ops that are touched or invalid or a pocket or plug op without a toolpath ("recompute it
first"), and an inactive pocket or plug op. A clearance op with nothing to cut, such as a rest end mill that fits
nowhere, is skipped with a notice. The Fit
object never simulates again by itself: when the ops' toolpaths change it only marks itself
"outdated: run Check Inlay Fit". The grid is 0.25 mm, so features smaller than that can be missed.

## Progress and cancel

Ops, V-Carve Inlay and Check Inlay Fit show a progress indicator in the GUI. Press **Esc** to cancel; there
is no confirmation. In a recompute, Esc cancels the running op and every later V-Carve
or clearance op of that recompute. A
cancelled op keeps an empty path and an error mark (recompute it to try again), a cancelled V-Carve Inlay
leaves nothing behind, and a cancelled check keeps the old Fit object. Headless (`freecadcmd`) there is no
indicator and no cancel.

## Known limitations

- V-bit rest clearing leaves scallops up to `RestScallop`.
- The ZigZag pocket pattern can overshoot the floor edge by about 0.01 mm (up to 0.02 mm with
  small tools) at inner corners (a libarea artefact). Offset, the default, is unaffected.
- With a wide V-bit tip (about 1 mm, e.g. the FreeCAD 1.0.x stock 60° bit), a non-zero
  `Allowance`, or star-like shapes, the V-bit rest pass can leave thin slivers of floor uncut in
  sharp corners (measured 0.07–0.3 mm).
- In strokes narrower than the flat floor the V-bit follows the centre line, so their inner corners
  keep the cone's rounding.
- A clearance `StepOver` near 100 % leaves uncut ridges between passes, as with CAM Pocket.
- Overlapping or touching outlines in one sketch (for example ShapeString letters that touch)
  are rejected with an error naming the sketch. Separate them, or put them in separate sketches.
- A self-intersecting single loop (a figure-8) is not detected.
- Input is 2D sketches or a FreeCAD image plane.
- Check Inlay Fit simulates G1 moves only: it refuses ops with arc moves (G2/G3).

## Tests

```sh
python3 -m pytest                      # pure suite, no FreeCAD needed
```

The FreeCAD suites (`tests/test_freecad.py` headless, `tests/test_gui.py` an offscreen GUI check)
need one or more FreeCAD AppRun executables, given in `FREECAD_APPRUNS` separated by `os.pathsep`
(`:` on Linux). Without it they are skipped.

```sh
FREECAD_APPRUNS=/opt/fc-1.0.2/squashfs-root/AppRun:/opt/fc-1.1.4/squashfs-root/AppRun python3 -m pytest -v
```

To get an AppRun, extract a FreeCAD AppImage: `./FreeCAD_x.AppImage --appimage-extract` creates
`squashfs-root/AppRun`. The FreeCAD tests run with a throwaway HOME and user directories, so your
own FreeCAD configuration is never read or modified.

## Authors

alf and Claude (Anthropic), who designed, wrote and tested this addon together.

## License

LGPL-2.1-or-later, see `LICENSE`. This is a clean-room implementation, inspired by F-Engrave and
commercial V-carving tools; no code was copied from them.
