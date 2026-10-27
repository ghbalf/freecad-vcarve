# Photo V-Carve Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A "V-Carve Photo" CAM op that carves a FreeCAD Image Plane as V-grooves whose depth follows the photo's darkness, along lines, hatch or custom vectors.

**Architecture:** Pure-numpy tone and geometry in `vcarve_flat/photo.py`, testable with plain pytest. A thin FreeCAD layer, `vcarve_flat/image_plane.py`, reads the image plane's pixels and maps world XY to image coordinates. The op `vcarve_flat/op_photo.py` follows `op_vcarve.py`: properties, `opExecute` under `progress.op_task`, and `toolpath.paths_to_commands`. The GUI gets a task page, a command and an icon.

**Tech Stack:** Python, numpy, FreeCAD CAM (`Path.Op.Base`), PySide `QImage`.

**Spec:** `docs/specs/2026-10-27-photo-vcarve-design.md`

## Global Constraints

- Header on every new .py: `# SPDX-License-Identifier: LGPL-2.1-or-later` and `# Authors: alf and Claude (Anthropic)`.
- Clean-room: no code or behaviour taken from Vectric or F-Engrave.
- Must run headless in `freecadcmd`. No GUI dialogs from op code; messages go to `Path.Log` (error, warning, notice), each starting with `obj.Label`.
- It must work on all four builds in `FREECAD_APPRUNS`: 1.0.2, 1.1.1, 1.1.4 and 26.3rc2.
- The full suite runs before each commit that touches code: `pytest -q` with `FREECAD_APPRUNS` set (about 15 min). Use `pytest -q tests/test_photo.py` for fast loops.
- Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Tone (spec 3, 4, 7):
  - grey = 0.299 R + 0.587 G + 0.114 B on the encoded values, scaled to 0..1;
  - contrast g' = clip(0.5 + (g − 0.5) · Contrast/100, 0, 1);
  - linear light L = sRGB-to-linear(g');
  - ρ = 1 − L, or ρ = L with Invert;
  - transparent pixels count as white: composite onto white by alpha before the grey.
- Depth (spec 7, 8):
  - Lines and Custom use d = ρ · D. Hatch uses d = (1 − √(1 − ρ)) · D for each set.
  - D = MaxDepth, clamped with `geom.limit_depth`.
  - Cut where d ≥ MinDepth; lift elsewhere.
- Defaults (spec 6, 8, 9):
  - `SampleStep` 0.25 mm, `MinDepth` 0.05 mm, `MaxDepth` 2 mm (no upper bound on the property);
  - `Contrast` 100, `Invert` false, `Angle` 45°, `HatchAngle` = `Angle` + 90° at creation;
  - `LineSpacing`: the tool controller's groove width at `MaxDepth` (tip + 2 · D · tan(half angle)) × 1.05, rounded up to 0.1 mm. That is 2.6 mm for the 60° 0.1 mm-tip bit, and 2.5 mm without a V-bit.

## Rulings made while planning

- **Custom vectors use a new `Vectors` property** (`App::PropertyLinkListGlobal`) listing sketches or any objects with edges. Imported SVG paths aren't sketches, and CAM's base-geometry page and the Job-clone mechanism only handle sketches.
  - Why: the user wants Inkscape paths without converting them.
  - Cost if wrong: one property rename.
- **`ImagePlane` is an `App::PropertyLinkGlobal`.** The image plane lives outside the Job and its model, and a scoped link from an op inside the Job would trigger FreeCAD's out-of-scope link warning.
- **Line order is serpentine:** lines in offset order, every second one reversed. The lift segments of a line keep their order. `geom.order_paths` is O(n²) in Python, too slow for thousands of segments.
- **Image orientation:** the image is centred on the plane's local origin, `XSize` along local X and `YSize` along local Y, with the image's top row at local +Y. If the plane's local Z points down (world z < 0), local x is negated, so the photo reads as seen from above. A plane not parallel to XY (|normal z| < 1 − 1e-6) is an error.
- **Clipping:** lines are clipped to the intersection of the image rectangle's world bounding box and the stock's XY bounding box. A warning is given if the image rectangle extends beyond the stock. Custom vectors are only sampled, never clipped: where they leave the image, ρ = 0 and nothing is cut.
- **The cut starts at `StartDepth`** (the base class sets it to the stock top), so z = `StartDepth` − d.

## Review Focus

1. **The photo appears upside down or mirrored in the simulator.** Expect the lion to look as it does on the image plane, seen from above. The headless tests only pin the convention above, so Task 5 adds a GUI check comparing against the image plane, and the final review asks the user for a look in the simulator.
2. **A real photo is large** (4000 × 4000 px, 400 mm, spacing 2.5 mm, step 0.25 mm). The op must stay responsive with Cancel and finish within about 30 s. Task 4 adds a timing test with a 2000 × 2000 synthetic image.
3. **A document that is saved and reopened**, where `ImageFile` points into FreeCAD's transient directory. The op must still recompute. Task 4 tests save, close, reopen and recompute.
4. **An all-white image, or `MinDepth` ≥ `MaxDepth`.** This gives an empty path and a notice, not an error or a traceback. Task 4 tests it.
5. **The user moves or resizes the image plane, or changes its file.** The op must be touched and recompute (link dependency). Task 4 tests that moving the plane changes the path.

---

### Task 1: Tone and raster sampling (`photo.py`, pure numpy)

**Files:**
- Create: `vcarve_flat/photo.py`
- Test: `tests/test_photo.py`

**Interfaces:**
- Produces:
  - `darkness(rgba: np.ndarray[H,W,3|4] uint8, contrast: float, invert: bool) -> np.ndarray[H,W] float` with values in 0..1, applying the tone constraints in order.
  - `class Raster(rho: np.ndarray[H,W], width: float, height: float)` with `sample(uv: np.ndarray[N,2]) -> np.ndarray[N]`.
    - `uv` is in mm, centred on the image, with v up and row 0 at v = +height/2.
    - Sampling is bilinear between pixel centres. Outside the image it returns 0.

- [ ] **Step 1: Write the failing tests** in `tests/test_photo.py`:
  - `test_darkness_black_white_grey`: black → 1, white → 0, encoded grey 128 → about 1 − 0.2158 (sRGB 128 is about 0.2158 linear), within 1e-3.
  - `test_darkness_weights`: pure green is darker than pure red, which is darker than pure blue. Concretely, ρ(green) < ρ(red) < ρ(blue).
  - `test_darkness_alpha_is_white`: an RGBA pixel with alpha 0 → 0.
  - `test_darkness_invert`: with `invert=True`, black → 0 and white → 1.
  - `test_darkness_contrast`: `contrast=200` maps encoded 64 to 0 encoded, so ρ = 1; `contrast=100` leaves it unchanged.
  - `test_raster_orientation`: a 2 × 2 image whose top-left pixel is black and the rest white, 10 × 10 mm. Sampling (−2.5, 2.5) gives 1, (2.5, −2.5) gives 0, and (20, 0) gives 0.
  - `test_raster_bilinear`: on a 1 × 2 image (left pixel black, right white), sampling the centre (0, 0) gives 0.5.
- [ ] **Step 2:** `pytest -q tests/test_photo.py`. Expect it to FAIL (ImportError).
- [ ] **Step 3:** Implement `darkness` and `Raster` in `vcarve_flat/photo.py`. Clamp sample positions at the edge pixels so that the area between the outermost pixel centres and the image edge isn't faded.
- [ ] **Step 4:** `pytest -q tests/test_photo.py`. Expect PASS.
- [ ] **Step 5:** Commit: `feat: photo tone mapping and raster sampling`.

### Task 2: Lines, depth along a line, and cut runs (`photo.py`)

**Files:**
- Modify: `vcarve_flat/photo.py`
- Test: `tests/test_photo.py`

**Interfaces:**
- Consumes: `Raster.sample` from Task 1.
- Produces:
  - `line_set(rect: tuple[float, float, float, float], angle: float, spacing: float) -> list[np.ndarray[2,2]]`
    - `rect` is (xmin, ymin, xmax, ymax). The lines run at `angle` degrees from +X, at offsets k · spacing from the rect centre (k may be negative).
    - Each line is clipped to the rect. The list is in offset order, and every second line is reversed (serpentine). Lines that miss the rect are dropped.
  - `resample(poly: np.ndarray[N,2], step: float) -> np.ndarray[M,2]`: a point every ≤ step along the polyline, keeping the original vertices and both ends.
  - `hatch_share(rho: np.ndarray) -> np.ndarray`: computes 1 − √(1 − ρ).
  - `cut_runs(xy: np.ndarray[N,2], depth: np.ndarray[N], min_depth: float, z_top: float, tol: float) -> list[np.ndarray[M,3]]`
    - Splits the line into maximal runs of consecutive samples with depth ≥ min_depth.
    - z = z_top − depth.
    - Each run is simplified with `geom.simplify(run, tol)`, and single-point runs are kept.

- [ ] **Step 1: Write the failing tests:**
  - `test_line_set_horizontal`: rect (0, 0, 10, 10), angle 0, spacing 2.5. Expect 4 lines at y = 1.25, 3.75, 6.25, 8.75, each spanning x 0..10. The second and fourth lines run from x = 10 to x = 0.
  - `test_line_set_angles`: at angle 90, every line has constant x. At angle 45, every point lies inside the rect within 1e-9, and all line directions are ±(1, 1)/√2. At angle −90, the result has the same lines as at 90.
  - `test_resample`: a 1 mm polyline with step 0.25 gives 5 points. An L-shaped polyline keeps its corner vertex.
  - `test_hatch_share`: ρ 0 → 0, 1 → 1, 0.75 → 0.5.
  - `test_cut_runs_lift_over_white`: depth [1, 1, 0, 0, 1] with min_depth 0.05 gives 2 runs, of 2 points and 1 point, with z = z_top − 1.
  - **`test_eye_fixture`**, using a `Raster`:
    - The image is 30 × 30 mm at 300 × 300 px: a black disk of radius 10 mm, with a white dot of radius 1.5 mm at its centre.
    - Sample a horizontal line through the centre with step 0.25 mm and max depth 2.
    - Expect exactly 2 runs. Both reach z_top − 2 within 1e-6. The gap between them (in x) is at least 2.5 mm and at most 3.5 mm.
- [ ] **Step 2:** `pytest -q tests/test_photo.py`. Expect FAIL.
- [ ] **Step 3:** Implement the four functions. `line_set` clips each infinite line to the rect (slab clipping).
- [ ] **Step 4:** `pytest -q tests/test_photo.py`. Expect PASS.
- [ ] **Step 5:** Commit: `feat: photo line sets and cut runs`.

### Task 3: Reading the Image Plane (`image_plane.py`)

**Files:**
- Create: `vcarve_flat/image_plane.py`
- Test: `tests/fc/test_image_plane.py`

**Interfaces:**
- Consumes: `photo.Raster` from Task 1.
- Produces:
  - `class ImageError(Exception)`; its message starts with the plane's label.
  - `read_rgba(path: str) -> np.ndarray[H,W,4] uint8`
    - Uses `QtGui.QImage(path).convertToFormat(QImage.Format_RGBA8888)` and copies the bits row by row via `bytesPerLine` (PySide2 and PySide6 differ; use `constBits()`).
    - Raises `ImageError` for an empty or unreadable file.
  - `plane_frame(plane) -> tuple[Callable[[np.ndarray[N,2]], np.ndarray[N,2]], tuple[float, float, float, float]]`
    - Returns (world XY → plane uv, the world XY bounding box of the image rectangle), following the orientation ruling.
    - Raises `ImageError` when the plane isn't parallel to XY.

- [ ] **Step 1: Write the failing tests** in `tests/fc/test_image_plane.py` (a unittest class, like the other `tests/fc` files). Each test writes a PNG to a temp dir with QImage and adds an `Image::ImagePlane` with `ImageFile`, `XSize` and `YSize`.
  - `test_read_rgba`: a 3 × 2 image with a red pixel at (x=2, y=0) gives shape (2, 3, 4), and `[0, 2]` is (255, 0, 0, 255).
  - `test_frame_identity`: a 20 × 10 plane at the origin. uv of world (5, 2) is (5, 2), and the bbox is (−10, −5, 10, 5).
  - `test_frame_placed`: the plane moved to (100, 50, 7) and rotated 90° about Z. World (100, 55) maps to uv (5, 0) within 1e-9.
  - `test_frame_face_down`: rotated 180° about X. World (5, 2) is local (5, −2), and u is negated because local z points down, so it maps to uv (−5, −2). That is the image turned 180° in the plane, not mirrored.
  - `test_frame_tilted`: rotated 30° about X raises `ImageError`.
  - `test_missing_file`: an empty `ImageFile` raises `ImageError`.
- [ ] **Step 2:** `freecadcmd tests/fc/run.py` on 1.1.4 (`$B/fc-1.1.4/squashfs-root/AppRun freecadcmd tests/fc/run.py`). Expect the new tests to FAIL.
- [ ] **Step 3:** Implement. Use `plane.Placement.inverse().multVec` for world → local.
- [ ] **Step 4:** Run the fc suite on 1.0.2 and 26.3rc2 too: the QImage bits API differs.
- [ ] **Step 5:** Commit: `feat: read FreeCAD image planes for photo carving`.

### Task 4: The V-Carve Photo op (`op_photo.py`)

**Files:**
- Create: `vcarve_flat/op_photo.py`
- Test: `tests/fc/test_op_photo.py`; add a fixture image helper to `tests/fc/helpers.py`

**Interfaces:**
- Consumes: Tasks 1–3, `geom.limit_depth`, `op_vcarve.tool_vbit`, `op_vcarve.is_tool_controller`, `compat.tool_shape`, `progress.op_task` / `progress.step`, and `toolpath.paths_to_commands`.
- Produces:
  - `Create(name, obj=None, parentJob=None)`, registered with `PathSetupSheet.RegisterOperation("VCarvePhoto", Create, SetupProperties)`.
  - Properties in group `"V-Carve Photo"`:
    - `ImagePlane` (LinkGlobal)
    - `Pattern` (Enumeration: `Lines`, `Hatch`, `Custom`)
    - `Angle` and `HatchAngle` (Angle)
    - `LineSpacing`, `MaxDepth`, `MinDepth` and `SampleStep` (Length)
    - `Contrast` (Percent)
    - `Invert` (Bool)
    - `Vectors` (LinkListGlobal)
    - `Tolerance` (Length, 0.01 mm)
  - Op features: Tool, Heights, Depths, NoFinalDepth and Coolant. No base geometry, no StepDown.
  - `isToolSupported` accepts V-bits only.
  - `opSetDefaultValues` sets `LineSpacing` from the tool controller (Global Constraints) and `HatchAngle` = `Angle` + 90.

- [ ] **Step 1: Write the failing tests** in `tests/fc/test_op_photo.py`:
  - **Setup:**
    - `make_job` on a 60 × 40 × 10 box as the model.
    - A helper `make_plane(doc, path, w, h, pixels)` writes a PNG and adds the image plane.
    - The op is created with the 60° V-bit tool controller.
  - **`test_lines_depth_follows_darkness`:**
    - The image is half black (left) and half white, and the plane is 40 × 20 mm.
    - Pattern Lines, angle 0, spacing 2.5.
    - Every G1 move with x < −1 has z = top − 2 within 1e-6. No G1 move has x > 1.
    - The path has 8 cut runs (one per line).
  - **`test_hatch_reaches_full_depth`:** all black, Hatch. The minimum z = top − 2, and moves follow both directions (0° and 90°).
  - **`test_custom_vectors`:**
    - A sketch with one line from (−15, 0) to (15, 0) over the half-black image. Pattern Custom.
    - The cuts follow y = 0 only, and the depth is 2 where x < 0.
    - A `Part::Feature` with a `Part.makeLine` shape works the same way (as SVG import produces).
  - **`test_eye`:** the eye fixture from Task 2 as an image plane, with a line through its centre. The path lifts over the white dot: there is a G0 between the two cut runs.
  - **`test_warnings`:**
    - `LineSpacing` 1 with a 60° bit at 2 mm gives the merge warning.
    - `MaxDepth` 50 gives the clamp warning, and the deepest z = top − cone height.
    - A plane larger than the stock gives the clipping warning, and every move stays inside the stock's XY bbox.
    - Mock `Path.Log.warning`, as `tests/fc/test_fit.py` does.
  - **`test_errors`:**
    - No image plane gives an error and an empty path.
    - A tilted plane gives an error with the plane label.
    - An end mill tool controller gives the V-bit error.
  - **`test_white_image_notice`:** an all-white image gives an empty path, no error, and a notice.
  - **`test_reopen`:** save, close, reopen, recompute. The path equals the one before.
  - **`test_plane_move_touches_op`:** moving the plane by 5 mm in x and recomputing shifts the first cut's x by 5.
  - **`test_large_image_time`:**
    - A 2000 × 2000 px gradient on a 400 × 400 mm plane, with a 400 × 400 stock.
    - Spacing 2.5, step 0.25, on Lines.
    - The recompute finishes in under 30 s.
- [ ] **Step 2:** Run the fc suite on 1.1.4. Expect FAIL.
- [ ] **Step 3:** Implement `ObjectVCarvePhoto(PathOp.ObjectOp)`:
  - `opExecute` runs under `progress.op_task`, with `progress.step()` once per line.
  - For each line: resample, sample ρ through `plane_frame`, compute the depth (hatch share for Hatch), then `cut_runs`.
  - Hatch emits the `Angle` set first, then the `HatchAngle` set.
  - Custom: discretize each edge of every `Vectors` object, using `Part.sortEdges` on `Shape.Edges` and `discretize(Deflection=...)`.
  - Pass the cut runs in order to `paths_to_commands` with the tool controller's feeds.
- [ ] **Step 4:** Run the fc suite on all four builds. Expect PASS.
- [ ] **Step 5:** Commit: `feat: V-Carve Photo operation`.

### Task 5: GUI: task page, command, icon

**Files:**
- Modify:
  - `vcarve_flat/gui/panels.py`: add `PhotoOpPage(_Page)`
  - `vcarve_flat/gui/commands.py`: in `register()`, add the resource `VCarvePhoto` and `CAM_VCarvePhoto=_OpCommand(photo)`; add `_ICON` and `_NO_TC` entries
  - `InitGui.py`: add a `_COMMANDS` entry for `CAM_VCarvePhoto` with "V-Carve Photo" / "V-carve a FreeCAD image plane as grooves whose depth follows its darkness"
  - `tests/gui/check_gui.py`
- Create: `vcarve_flat/resources/icons/vcarve_photo.svg` (in the style of the other icons, original artwork)

**Interfaces:** consumes `op_photo.Create` and the properties from Task 4.

- [ ] **Step 1:** Extend `check_gui.py`:
  - Create a V-Carve Photo op through the command with an image plane in the document.
  - Open its task panel.
  - Assert the panel's ImagePlane combo lists the plane.
  - Assert that switching Pattern to Custom hides LineSpacing and the angle fields.
  - Accept, and assert the op has a non-empty path.
  - Check that the icon shows in the tree (`check_icons`).
- [ ] **Step 2:** Run `pytest -q tests/test_gui.py` with `FREECAD_APPRUNS` set to 1.1.4 only. Expect FAIL.
- [ ] **Step 3:** Implement the page:
  - an ImagePlane combo listing the document's `Image::ImagePlane` objects by label;
  - a Pattern combo;
  - quantity fields for the lengths and angles;
  - a Contrast spin box and an Invert check box;
  - a Vectors list with "Add selected" and "Remove" buttons.
  - Visibility: LineSpacing and the angles are hidden for Custom, HatchAngle only shows for Hatch, and Vectors only shows for Custom.
- [ ] **Step 4:** `pytest -q tests/test_gui.py` on all four builds. Expect PASS.
- [ ] **Step 5:** Commit: `feat: V-Carve Photo command and task panel`.

### Task 6: Docs and release notes

**Files:** `README.md` (a new "## Photo V-carve" section before "## Check inlay fit", and the Known limitations bullet "Input is 2D sketches only" becomes "Input is 2D sketches or a FreeCAD image plane"), and `CHANGELOG.md` (`[Unreleased]` → `Added`).

- [ ] **Step 1:** The README section covers:
  - importing the photo (File → Import → image plane, then size and place it over the stock);
  - preparing it in GIMP (contrast, a white background as the mask, colour → grey control);
  - the patterns, properties and defaults;
  - the tone rule (black = MaxDepth, grooves merge when spacing < groove width);
  - the eye tip (dark pupil plus a white catchlight, a 30° bit or custom vectors for detail);
  - custom vectors from Inkscape (File → Import the SVG; the paths work directly).
- [ ] **Step 2:** Run the full suite (`pytest -q` with all four `FREECAD_APPRUNS`). Expect all to pass.
- [ ] **Step 3:** Commit: `docs: photo V-carve`.
