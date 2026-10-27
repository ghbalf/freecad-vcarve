# FreeCAD V-Carve addon: photo V-carve (v4 design)

Decided with the user on 2026-10-27, after the 0.3.0 release. Choices marked **(Claude's call)** were
not discussed with the user; everything else is theirs.

## Why

The user wants to carve a photo of a lion's head into a 400 × 400 mm panel of light hardwood
(probably maple), to hang beside their front door. It is a showpiece: the look matters more than
machining time. They have seen the result in a video of a commercial V-carve program: parallel
V-grooves whose width (and so darkness) follows the photo. That program's implementation is not
a reference. This design works only from the general, well-known technique: depth follows
darkness, and a V-bit's groove width follows its depth.

## Goals

1. **A new CAM operation "V-Carve Photo"** in the CAM menu and toolbar next to the other V-Carve
   commands. It belongs to a Job, uses a V-bit tool controller, and shows in FreeCAD's CAM
   simulator like any op.
2. **Input: a FreeCAD Image Plane.** The user imports the photo with FreeCAD's own image import
   (`Image::ImagePlane`, which has `ImageFile`, `XSize`, `YSize` and `Placement`). The op links to
   that object and does not read files the user picks itself. The image plane's size and placement
   set where the photo lies over the stock. The plane must be parallel to the XY plane (an error
   otherwise). **(Claude's call:** the photo is projected straight down onto the stock top whatever the
   plane's Z, and a plane facing −Z is carved as the top view shows it — mirrored, as on screen; ruled at review.) This loosens the project's "sketches only" rule to "sketches or a FreeCAD image
   plane".
3. **Colour photos** are converted to grey inside the op with the usual luminance weights
   (0.299 R + 0.587 G + 0.114 B). **(Claude's call:** the grey is converted from the image's sRGB
   encoding to linear light, because the grooves darken the surface by the share they cover, so
   covered area must follow physical light, not the encoded pixel value. Transparent pixels count as
   white.) Finer control (the channel mixer, curves) belongs in GIMP before
   the import.
4. **Image adjustments in the op: only `Contrast` and `Invert`.** Contrast stretches around mid-grey
   (100 % = unchanged); Invert swaps dark and light. Anything more is done in GIMP. **(Claude's
   call:** exact contrast formula; a contrast that clips to black and white is acceptable.)
5. **Three patterns** (`Pattern` property):
   - **Lines:** parallel straight lines at `Angle`, from −90° to +90° (0° = along X), `LineSpacing`
     apart, covering the image rectangle.
   - **Hatch:** two crossed sets of lines, at `Angle` and at `HatchAngle`. **(Claude's call:**
     `HatchAngle` is its own absolute property, defaulting to `Angle` + 90° when created.)
   - **Custom vectors:** the lines come from `Base` objects instead: sketches, or the path objects
     FreeCAD's SVG import creates (any object whose shape has edges), so paths drawn in Inkscape
     work without first converting them to a sketch. The depth along each path follows the photo
     underneath.
6. **The depth along every line follows the photo's darkness**, sampled at short steps
   (`SampleStep`, default 0.25 mm **(Claude's call)**). The cut is a single pass of 3D G1 moves with
   a smoothly varying Z, measured from the stock top.
7. **Tone mapping: black always reaches the full `MaxDepth`** (the user's choice). Where the groove at
   `MaxDepth` is wider than `LineSpacing`, neighbouring grooves cut into each other in the darkest
   areas and the surface there becomes all groove: the deepest black, at the cost of the line pattern.
   **(Claude's call:** depth d = ρ · `MaxDepth`, with darkness ρ from 0 = white to 1 = black after
   contrast and invert; in Hatch each set carries c = 1 − √(1 − ρ), because two crossed sets cover
   1 − (1 − c)² of the surface, so both reach `MaxDepth` at black. Custom vectors use d = ρ · `MaxDepth`
   and ignore `LineSpacing`, which the task panel hides for them.)
8. **White stays uncut maple.** Where the depth falls below `MinDepth` (default 0.05 mm
   **(Claude's call)**), the bit lifts out and stays out until the line is dark again, so it never
   scratches the light areas.
9. **Defaults for the user's bits:** V-bits of 60°, 45° or 30° with a 0.1 mm tip. `MaxDepth`
   defaults to 2 mm, with **no upper limit** (the user's words: "do not constrain it"). **(Claude's
   call:** a depth beyond the V-bit's cutting edge would cut with the shank, so it is clamped to the
   cone with a warning, as the V-Carve Flat op already does with `geom.limit_depth`.)
   `LineSpacing` defaults to slightly more than the default bit's groove width at `MaxDepth`
   **(Claude's call)**.
10. **Warnings, not errors** (report view, as the other ops do; no popups):
    - Lines and Hatch: the groove at `MaxDepth` is wider than `LineSpacing`, so neighbouring grooves
      merge in the darkest areas (60° at 2 mm needs spacing above about 2.4 mm to keep them apart).
      This is allowed, the warning only says so;
    - `MaxDepth` was clamped to the V-bit's cone;
    - the image rectangle lies partly outside the stock (the carve is clipped to the stock's top
      face).
11. **Progress and Cancel** like the other ops (`progress.op_task`). A 400 × 400 mm photo at 2.5 mm
    spacing is about 160 lines × 1600 samples; it must not freeze the GUI.
12. **Tested on all four FreeCAD builds** (1.0.2, 1.1.1, 1.1.4, 26.3rc2), headless and GUI.
    Verified 2026-10-27: on 1.0.2 and 26.3rc2 `Image::ImagePlane` exists with these properties, and
    `PySide.QtGui.QImage` reads pixels in `freecadcmd`.

## Success: the eyes must not look flat

This is the user's wince test. A lion's eyes are small (in a 400 mm head about 30 mm, about 12 lines
at 2.5 mm spacing) and live from contrast: a dark pupil next to a white catchlight. So:

- the darkest pixels reach the full `MaxDepth`;
- a white spot stays uncut (point 8), even a small one a few millimetres across;
- the depth can change within one or two `SampleStep`s along a line. Sampling must not average
  away a small highlight, and simplifying the path must keep its corners.

Test fixture **(Claude's call)**: a synthetic image with a black disk and a small white dot inside
it. Along a line through both, the path reaches `MaxDepth` on the disk and lifts out over the dot.

## Non-goals

- 3D relief or height-map carving (depth as surface shape rather than groove width).
- Dithering, stippling or dot patterns.
- Reading image files directly, or any format FreeCAD's image import does not read.
- Converting SVG fills or gradients into brightness (export a PNG from Inkscape instead).
- Automatic tracing of the photo into vectors.
- Step-down levels: one pass at the computed depth **(Claude's call;** revisit if deep cuts in
  maple chip).
- A boundary sketch to mask part of the photo: mask in GIMP (make it white).

## Anti-goals

- Flat-looking eyes: lost contrast in small, high-contrast features (see Success).
- Scratches or shallow cuts in areas that should be white.
- Grooves that merge into a dark mush without warning.
- Any code or behaviour taken from Vectric or F-Engrave (clean-room, as for the whole project).

## Constraints

- LGPL-2.1-or-later, clean-room, headers `# Authors: alf and Claude (Anthropic)`.
- Must run headless (`freecadcmd`) for the test suite; no GUI dialogs from op code.
- Sampling and pattern geometry should be plain numpy, testable without FreeCAD **(Claude's call)**.
- Follow the existing op structure (`op_vcarve.py`, `toolpath.paths_to_commands`, the task panels
  under `vcarve_flat/gui`).

## Left to the builder

- Module names and how the task panel lays out its fields (an image-plane picker listing the
  document's image planes; the pattern as a combo box).
- Line order: serpentine (alternating direction) to save rapids is expected; lift height between
  dark segments (the op's safe height, or a lower one if FreeCAD's op heights allow).
- Path simplification: dropping nearly collinear samples within a small Z tolerance, as long as
  the eye fixture passes.
- Bilinear or nearest-pixel sampling, and what to do where the image is smaller than one
  `SampleStep` per pixel.
