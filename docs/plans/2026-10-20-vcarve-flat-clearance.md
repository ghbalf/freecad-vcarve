# V-Carve Flat Depth + Clearance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A FreeCAD CAM addon with two operations. "V-Carve (flat depth)" V-carves 2D sketches down to a flat depth, and "V-Carve Clearance" clears the flat floor with an end mill. One command creates both.

**Architecture:**
- A pure-numpy geometry core (`vcarve_flat/geom.py`) holds all depth and ordering math and is tested with plain pytest.
- FreeCAD-dependent modules handle the rest:
  - sketch → loops → faces (`sketches.py`);
  - Voronoi medial axis → 3D carve polylines (`medial.py`);
  - offset and pocket helpers on `Path.Area` (`clearing.py`);
  - polylines → `Path.Command`s (`toolpath.py`).
- Two `Path.Op.Base.ObjectOp` subclasses build on these modules, plus a GUI layer hooked into the CAM workbench through a workbench manipulator.

**Tech Stack:** FreeCAD 1.0.2 / 1.1.4 / 26.3rc2 (bundled Python 3.11–3.13, numpy), Part, Path (Voronoi, Area), PySide; pytest on system Python for the pure core; `freecadcmd` + `unittest` for integration.

**Spec:** `docs/specs/2026-10-19-vcarve-flat-clearance-design.md`

## Global Constraints

- **Supported versions: FreeCAD 1.0.2, 1.1.4 and 26.3rc2** (bundled Python 3.11, 3.11 and 3.13). Each version is extracted under `<scratchpad>/fc-<version>/squashfs-root/AppRun`; the `<scratchpad>` path is given to each implementer. The integration suite must pass on all three. `package.xml` uses `<freecadmin>1.0.0</freecadmin>`.
- **Toolbits differ by version.** 1.1+ uses the asset manager (`CAMTests.PathTestUtils.PathTestWithAssets`), and tools have `ShapeType` ("VBit", "Endmill"). 1.0.2 uses `Path.Tool.Bit.Factory.CreateFrom(path, name)`, and tools have no `ShapeType`, only `BitShape` (a path ending in `v-bit.fcstd` / `endmill.fcstd`). Tests use the bits `60degree_Vbit` and `5mm_Endmill`, which exist in all three versions. Tests read tool dimensions from the TC rather than hard-coding them, because the stock V-bit tip is 1.0 mm in 1.0.2 and 0.1 mm in 1.1+.

- Every source file starts with `# SPDX-License-Identifier: LGPL-2.1-or-later`. `LICENSE` is the LGPL-2.1 text (copy `/usr/share/common-licenses/LGPL-2.1`).
- **No code, structure or naming from F-Engrave.** Do not open its source. Reusing FreeCAD CAM code (LGPL) is allowed: `Path.Op.Vcarve._collectVoronoiWires` and the color constants `PRIMARY, SECONDARY, COLINEAR, EXTERIOR1, EXTERIOR2, TWIN, BORDERLINE` can be imported.
- Input is sketches only: `Sketcher::SketchObject`, or the Job's `Clone2D` of one (`clone.Objects[0].TypeId == "Sketcher::SketchObject"`).
- Only listed bases are carved. There is no fallback to "all Job models"; an empty list cuts nothing and logs a message.
- Selecting an edge picks the whole closed loop that contains it. Holes count only if they are selected too.
- `FlatDepth` is a distance below Start Depth; 0 = off. Final Depth is not user-editable (`FeatureNoFinalDepth`).
- `FlatDepth` deeper than the cone height `(R - tip_r)/tan(half_angle)` is capped to the cone height, with a warning.
- One failing sketch does not stop the others. It gets an error log that names the sketch.
- Defaults: clearance `StepOver` 40 %, `PocketPattern` "Offset", `Allowance` 0, `RestScallop` 0.05 mm.
- The one-click command uses the first VBit TC and the first Endmill TC (`compat.tool_shape(tool) == "VBit"` / `"Endmill"`). If either is missing, it refuses and names the missing tool. The clearance op is placed **before** the V-carve op.
- Package name `vcarve_flat`. No module may be named `Path`, `CAM` or `Vcarve`.
- Units: FreeCAD stores mm internally. Read `Quantity.Value`.

## Review Focus

1. **FlatDepth = 0 on a region wider than the V-bit.** The area would be only partly cut, so the op must log a warning that suggests setting Flat Depth. (Task 5)
2. **Sketch not parallel to the XY plane** (e.g. on an XZ attachment). Error naming the sketch; nothing is cut from it. (Task 3)
3. **Edge selection made stale by a sketch edit** (`Edge12` no longer exists). Error naming the sketch and the edge, no exception escaping the op. (Task 3)
4. **Overlapping or self-intersecting loops**, as in ShapeString text with touching letters. If face building fails or gives zero faces, the error names the sketch and the other sketches are still cut. (Tasks 3, 5)
5. **Features too narrow for the flat radius or the end mill** (thin serifs, small text). The empty offset (`CADKernelError: offset result has no wires`) must be treated as "no floor", not as a crash. (Task 4, Task 6)

---

### Task 1: Scaffold + depth math

**Files:**
- Create: `LICENSE`, `package.xml`, `README.md` (one paragraph for now), `pytest.ini`, `vcarve_flat/__init__.py`, `vcarve_flat/geom.py`, `vcarve_flat/compat.py`
- Test: `tests/test_geom.py`, `tests/test_compat.py`

**Interfaces:**
- Produces, in `vcarve_flat/compat.py` (no FreeCAD import):
  - `tool_shape(tool) -> str`: returns `tool.ShapeType` if present and non-empty.
    - Otherwise, map the basename of `tool.BitShape` (with any `.fcstd` removed) as `{"v-bit": "VBit", "endmill": "Endmill", "ballend": "Ballend"}`, falling back to the basename itself.
    - Return `""` if the tool has neither attribute.
  - Tests (`tests/test_compat.py`, using `types.SimpleNamespace` fakes):
    - `ShapeType="VBit"` → "VBit".
    - `BitShape="/x/Tools/Shape/v-bit.fcstd"` → "VBit".
    - `BitShape="endmill.fcstd"` → "Endmill".
    - An empty namespace → "".
- Produces, in `vcarve_flat/geom.py` (numpy only, no FreeCAD):
  - `@dataclass(frozen=True) class VBit: diameter: float; angle_deg: float; tip_diameter: float`, with properties:
    - `radius`
    - `tip_radius`
    - `half_angle` (radians)
    - `cone_height = (radius - tip_radius) / tan(half_angle)`
  - `limit_depth(vbit: VBit, flat_depth: float) -> tuple[float, bool]`: returns `(depth_limit, capped)`.
    - `flat_depth <= 0` → `(cone_height, False)`.
    - `flat_depth > cone_height` → `(cone_height, True)`.
    - Otherwise → `(flat_depth, False)`.
  - `flat_radius(vbit: VBit, depth: float) -> float = tip_radius + depth * tan(half_angle)`.
  - `depth_for_radius(vbit: VBit, r: np.ndarray, depth_limit: float) -> np.ndarray = clip((r - tip_radius) / tan(half_angle), 0, depth_limit)`.
  - `distances_to_segments(points: np.ndarray (N,2), segments: np.ndarray (M,2,2)) -> np.ndarray (N,)`: minimum Euclidean distance from each point to any segment. Vectorize over `M`; loop over `N` in chunks of 2048.
  - `rest_stepover(vbit: VBit, scallop: float) -> float = tip_diameter + 2 * scallop * tan(half_angle)`.

- [ ] **Step 1: Write the scaffold.**
  - `package.xml`: FreeCAD package format 1, name "V-Carve Flat", license `LGPL-2.1-or-later`, `<freecadmin>1.1.0</freecadmin>`.
    - The content is one `<workbench>` item with `<name>V-Carve Flat</name>` and `<subdirectory>./</subdirectory>`, with no `<classname>`. It is the Addon Manager's container for a Mod that has an `InitGui.py`. The addon defines no workbench of its own; it extends CAM.
  - `pytest.ini`: `testpaths = tests`, `python_files = test_*.py`.
- [ ] **Step 2: Write the failing tests** in `tests/test_geom.py`:

```python
V60 = VBit(10.0, 60.0, 0.0)
V90 = VBit(10.0, 90.0, 0.2)

def test_cone_height():
    assert V90.cone_height == pytest.approx(4.9)          # (5-0.1)/tan45
    assert V60.cone_height == pytest.approx(5/math.tan(math.radians(30)))

def test_limit_depth():
    assert limit_depth(V90, 0) == (pytest.approx(4.9), False)
    assert limit_depth(V90, 2.0) == (2.0, False)
    assert limit_depth(V90, 7.0) == (pytest.approx(4.9), True)

def test_flat_radius():
    assert flat_radius(V90, 2.0) == pytest.approx(2.1)

def test_depth_for_radius_clamps():
    r = np.array([0.0, 0.05, 1.1, 50.0])
    assert depth_for_radius(V90, r, 2.0) == pytest.approx([0, 0, 1.0, 2.0])

def test_distances_to_segments():
    seg = np.array([[[0, 0], [10, 0]], [[10, 0], [10, 10]]], float)
    pts = np.array([[5, 3], [12, 5], [-3, -4]], float)
    assert distances_to_segments(pts, seg) == pytest.approx([3, 2, 5])

def test_rest_stepover_sharp_tip():
    assert rest_stepover(VBit(10, 90, 0), 0.05) == pytest.approx(0.1)
```

- [ ] **Step 3: Run** `python3 -m pytest tests/test_geom.py -v`. Expected: FAIL (ImportError).
- [ ] **Step 4: Implement** `geom.py` as specified.
- [ ] **Step 5: Run** `python3 -m pytest tests/test_geom.py -v`. Expected: 6 passed.
- [ ] **Step 6: Commit** `feat: addon scaffold and v-bit depth math`.

### Task 2: Path simplification and ordering (pure)

**Files:**
- Modify: `vcarve_flat/geom.py`
- Test: `tests/test_geom.py`

**Interfaces:**
- Produces:
  - `simplify(points: np.ndarray (N,3), tol: float) -> np.ndarray (K,3)`: Douglas–Peucker on 3D distance. It keeps the first and last points. A closed polyline (first point equals last) stays closed.
  - `order_paths(paths: list[np.ndarray], start: tuple[float,float]=(0,0)) -> list[np.ndarray]`: greedy nearest-neighbor on XY.
    - An open path may be reversed if its end is nearer.
    - A closed path is rotated so that it starts at its point nearest to the current position.
    - Every input path appears exactly once.

- [ ] **Step 1: Write the failing tests:**
  - `test_simplify_collinear`: 11 collinear points → 2 points.
  - `test_simplify_keeps_corner`: an L shape → 3 points.
  - `test_simplify_respects_z`: a straight XY line whose z dips by 1.0 in the middle, with tol 0.1 → keeps the dip point.
  - `test_order_paths_reverses`: path A from (0,0) to (10,0), path B from (20,0) to (11,0) → result `[A, B reversed]`, with B starting at (11,0).
  - `test_order_closed_rotates`: closed square starting at (10,10); after an open path ending at (0,0), it starts at (0,0).
- [ ] **Step 2: Run** `python3 -m pytest tests/test_geom.py -v`. Expected: new tests FAIL.
- [ ] **Step 3: Implement** both functions. Use an iterative stack for Douglas–Peucker, not recursion, because text outlines give paths with 10⁴+ points.
- [ ] **Step 4: Run** the same command. Expected: all pass.
- [ ] **Step 5: Commit** `feat: polyline simplification and path ordering`.

### Task 3: FreeCAD test harness + sketch → faces

**Files:**
- Create: `vcarve_flat/sketches.py`, `tests/fc/run.py`, `tests/fc/helpers.py`, `tests/fc/test_sketches.py`, `tests/test_freecad.py`
- Test: `tests/fc/test_sketches.py`

**Interfaces:**
- Produces, in `vcarve_flat/sketches.py`:
  - `class SketchError(Exception)`: the message always starts with the sketch label.
  - `is_sketch_base(obj) -> bool`: true for a `Sketcher::SketchObject`, or for an object whose `Objects[0]` is one (the Job clone).
  - `loops_for_base(obj, subs: Sequence[str] | None) -> list[Part.Wire]`.
    - With `subs` empty or None: return every closed wire of `obj.Shape`, and raise `SketchError` if the shape has any open wire.
    - With `subs`: for each `EdgeN`, return the closed wire containing an edge that `isSame` the element, deduplicated.
      - An unknown name raises `SketchError("<label>: Edge12 no longer exists")`.
      - An edge on no closed wire raises `SketchError("<label>: Edge3 is not part of a closed outline")`.
      - `Vertex*` subs are ignored.
  - `faces_from_loops(label: str, loops: list[Part.Wire]) -> list[Part.Face]`.
    - Uses `Part.makeFace(loops, "Part::FaceMakerBullseye").Faces`.
    - Raises `SketchError` if face building raises or returns no faces.
    - Raises `SketchError("<label>: sketch is not parallel to the XY plane")` if any face normal deviates more than 1e-6 from ±Z.
- Produces, in `tests/fc/helpers.py`:
  - `make_sketch(doc, name, loops: list[list[tuple]], circles: list[tuple[x,y,r]] = ()) -> SketchObject`: a polygon loop for each list of points.
  - `make_job(doc, sketches, bits=("60degree_Vbit", "5mm_Endmill")) -> (job, dict[str, ToolController])`.
    - Creates the tool with the first approach that works:
      - 1.1+: `PathTestWithAssets().setUp()` assets, then `assets.get("toolbit://<bit>").attach_to_doc(doc=doc)`;
      - 1.0.2: `Path.Tool.Bit.Factory.CreateFrom(<Mod/CAM>/Tools/Bit/<bit>.fctb, <bit>)`.
    - Then `Path.Tool.Controller.Create(name, tool=tb)` and `job.Proxy.addToolController(tc)`.
    - Keys are the bit names.
- Produces `tests/fc/run.py`, the integration entry point:
  - Puts the repo root and `os.path.dirname(os.path.dirname(Path.__file__))` (Mod/CAM) on `sys.path`.
  - Discovers `tests/fc/test_*.py` with `unittest`.
  - `sys.exit(1)` on failure.
  - Prints `FC-TESTS-OK` on success.
- Produces `tests/test_freecad.py`:
  - Is parametrized over the `os.pathsep`-separated paths in `FREECAD_APPRUNS`, with the test id taken from `<version dir>`.
  - Runs `[appimage_run, "freecadcmd", tests/fc/run.py]` via `subprocess`, with a 600 s timeout.
  - Asserts return code 0 and `FC-TESTS-OK` in stdout, and prints the tail of the output on failure.
  - `pytest.skip` when `FREECAD_APPRUNS` is unset.
  - In this plan, "the integration command" means `FREECAD_APPRUNS=<sc>/fc-1.0.2/squashfs-root/AppRun:<sc>/fc-1.1.4/squashfs-root/AppRun:<sc>/fc-26.3rc2/squashfs-root/AppRun python3 -m pytest tests/test_freecad.py -v`. It passes only if all three versions pass.

- [ ] **Step 1: Write the failing tests** in `tests/fc/test_sketches.py` (unittest, a new document per test). Fixture: an outer 40×20 rectangle with a circle hole r=4 at (10,10) and a separate 5×5 square at (50,0).
  - `test_whole_sketch`: 3 loops → `faces_from_loops` → 2 faces. The rectangle face has 1 inner wire, and its area ≈ 800 − π·16.
  - `test_edge_picks_loop`: subs `["Edge1"]` (a rectangle edge) → 1 loop → 1 face with no hole, area 800.
  - `test_edge_picks_loop_and_hole`: subs of one rectangle edge plus the circle edge → 1 face with a hole.
  - `test_same_loop_twice`: two edges of the rectangle → 1 loop.
  - `test_stale_edge` (Review Focus 3): `["Edge99"]` → `SketchError` whose message contains the label and `Edge99`.
  - `test_open_wire`: a sketch with an extra loose line → `SketchError` when `subs` is empty.
  - `test_not_xy` (Review Focus 2): the sketch `Placement` rotated 90° about X → `SketchError` containing "parallel".
  - `test_clone_is_sketch_base`: `make_job` with the sketch → `is_sketch_base(job.Model.Group[0])` is true. A `Part::Feature` box → false.
  - Use the Job clone in all tests, to prove that edge names map 1:1 onto the clone.
- [ ] **Step 2: Run** the integration command (defined under Interfaces above). Expected: FAIL (ImportError on `vcarve_flat.sketches`) on all three versions.
- [ ] **Step 3: Implement** `sketches.py`, `helpers.py`, `run.py` and `test_freecad.py`.
- [ ] **Step 4: Run** the same command. Expected: PASS.
- [ ] **Step 5: Commit** `feat: sketch loop selection and face building`.

### Task 4: Medial axis, carve polylines, clearing helpers

**Files:**
- Create: `vcarve_flat/medial.py`, `vcarve_flat/clearing.py`
- Test: `tests/fc/test_medial.py`

**Interfaces:**
- Consumes: `geom.VBit`, `depth_for_radius`, `distances_to_segments`, `flat_radius`, `simplify`.
- Produces, in `medial.py`:
  - `boundary_segments(face, deflection: float) -> np.ndarray (M,2,2)`: each wire `discretize(QuasiDeflection=deflection)`. If the last point is within `Precision.confusion()` of the first, drop it, then close the polygon.
  - `medial_polylines(face, segments, colinear_deg: float, step: float) -> list[np.ndarray (N,2)]`.
    - Builds a `Path.Voronoi.Diagram` from the segments.
    - Colors edges like `Path.Op.Vcarve.ObjectVcarve.buildMedialWires`: primary/borderline/secondary, then colinear, exterior (both passes, with the face-domain test), then twins.
    - Chains the wires with the imported `_collectVoronoiWires`.
    - Turns each wire into points by `edge.toShape().discretize(Distance=step)` per edge, concatenated, with duplicate joints removed.
  - `carve_polylines(face, vbit, z_top, depth_limit, *, deflection, colinear_deg, step, tol, boundary_pass: bool) -> list[np.ndarray (N,3)]`.
    - Medial points get `z = z_top - depth_for_radius(vbit, distances_to_segments(pts, segments), depth_limit)`.
    - With `boundary_pass`, append the wires of `clearing.offset_faces([face], -flat_radius(vbit, depth_limit))`. Discretize them with `deflection`, close them, and set them at `z_top - depth_limit`.
    - Apply `simplify(…, tol)` to everything.
- Produces, in `clearing.py`:
  - `offset_faces(faces, distance: float) -> list[Part.Face]`: `makeOffset2D(distance, join=0)` per face. Return `[]` on `Part.OCCError` / "offset result has no wires". Return `faces` unchanged for distance 0.
  - `swept_faces(floor, tool_radius, allowance) -> list[Part.Face]`: `offset_faces(offset_faces(floor, -(tool_radius + allowance)), +tool_radius)`.
  - `subtract(a: list[Face], b: list[Face]) -> list[Face]`: the `.Faces` of `Part.makeCompound(a).cut(Part.makeCompound(b))`. Return `a` when `b` is empty. Return `[]` when `a` is empty.
  - `pocket_polylines(faces, tool_radius, stepover, pattern: str ("Offset" | "ZigZag"), extra_offset, z, deflection) -> list[np.ndarray (N,3)]`.
    - Uses `Path.Area()`: `add` each face, then `setParams(PocketMode=2 for Offset / 1 for ZigZag, ToolRadius=…, PocketStepover=stepover, PocketExtraOffset=…)`, then `makePocket()`.
    - Discretizes each output wire with `deflection` and sets it at `z`.
    - Returns `[]` for empty input.

- [ ] **Step 1: Write the failing tests:**
  - `test_rectangle_depth`: a 40×20 rectangle face, `VBit(10, 90, 0)`, `z_top = 0`, `depth_limit = 5.0` (cone height of a sharp 10 mm 90° bit), no boundary pass.
    - min z ≈ −5.0 (the inscribed radius 10 is capped by the cone; tolerance 0.05).
    - Max z of polyline endpoints at the corners ≈ 0.
  - `test_containment` (anti-goal): for a letter-like L face plus the ring face from Task 3, `distances_to_segments(xy, segments) >= depth * tan(half) - 1e-3` at every polyline point. This means the cone never crosses the outline. Also, `face.isInside(Vector(x, y, face_z), 1e-6, True)` holds for every point.
  - `test_flat_clamp_and_boundary`: 40×20 rectangle, `VBit(10, 90, 0)`, depth_limit 2.
    - No point is below z = −2.
    - A boundary loop at z = −2 has bounding box (2, 2)–(38, 18) ± 0.01.
  - `test_offset_empty` (Review Focus 5): `offset_faces([5×5 square], -3) == []`.
  - `test_rest_area`: floor = 30×10 rectangle plus a 2 mm wide, 10 mm long neck; end mill radius 1.5.
    - `subtract(floor, swept_faces(floor, 1.5, 0))` is not empty.
    - It contains a point in the middle of the neck.
  - `test_pocket_polylines`: 20×20 square, tool radius 1.5, stepover 1.2 → every point lies within (1.5, 18.5) on X and Y, and every z equals the `z` passed in.
- [ ] **Step 2: Run** the integration command from Task 3. Expected: the new tests FAIL.
- [ ] **Step 3: Implement** `medial.py` and `clearing.py`.
- [ ] **Step 4: Run** the integration command. Expected: PASS.
- [ ] **Step 5: Commit** `feat: medial-axis carve polylines and clearing helpers`.

### Task 5: V-Carve (flat depth) operation

**Files:**
- Create: `vcarve_flat/toolpath.py`, `vcarve_flat/op_vcarve.py`
- Test: `tests/fc/test_op_vcarve.py`

**Interfaces:**
- Consumes: Tasks 1–4.
- Produces, in `toolpath.py`:
  - `paths_to_commands(paths, safe_z, clearance_z, hfeed, vfeed) -> list[Path.Command]`. For each path: `G0` to `clearance_z` if this is the first path (otherwise to `safe_z`), `G0 XY`, `G1 Z` at `vfeed`, then `G1 XYZ` at `hfeed`, and finally `G0` to `clearance_z`.
- Produces, in `op_vcarve.py`:
  - `class ObjectVCarveFlat(Path.Op.Base.ObjectOp)`:
    - `opFeatures = FeatureTool | FeatureHeights | FeatureDepths | FeatureNoFinalDepth | FeatureBaseEdges | FeatureCoolant`.
    - Properties, in group "V-Carve":
      - `BaseShapes` (LinkList, hidden in the editor; holds whole sketches)
      - `FlatDepth` (Length, 0)
      - `Discretize` (Float, 0.01)
      - `Colinear` (Float, 10.0)
      - `StepLength` (Length, 0.5)
      - `Tolerance` (Length, 0.01)
      - `RestScallop` (Length, 0.05)
  - `CarveSetup` (dataclass): `vbit: VBit, z_top: float, depth: float, r_flat: float, capped: bool`, from `carve_setup(obj) -> CarveSetup`. `depth` = `limit_depth(...)[0]`; `r_flat = flat_radius(vbit, depth)` if `FlatDepth > 0`, else 0.
  - `region_sets(obj) -> list[tuple[str, list[Part.Face] | SketchError]]`: one entry per `BaseShapes` sketch, plus one per sketch in `Base` (subs grouped by base object). Each entry is a sketch label with either its faces or the error.
  - `find_clearance_op(obj) -> obj | None`: the first op in the parent Job's `Operations.Group` whose `Proxy` is an `ObjectVCarveClearance` and whose `VCarveOp is obj`. Duck-type on the `VCarveOp` attribute, to avoid importing `op_clearance` (Task 6).
  - `opExecute`:
    - Empty bases → `Path.Log.warning("<op label>: no sketches selected, nothing to cut")`.
    - For each region set, an error → `Path.Log.error(str(err))`, and processing continues.
    - Faces → `carve_polylines(... boundary_pass=FlatDepth > 0)`.
    - With `FlatDepth > 0`: add the rest pocket first:
      - `floor = offset_faces(faces, -r_flat)`.
      - With a clearance op: `rest = subtract(floor, swept_faces(floor, cop.ToolController.Tool.Diameter.Value/2, cop.Allowance.Value))`. Without one: `rest = floor`.
      - `pocket_polylines(rest, vbit.tip_radius, rest_stepover(vbit, RestScallop), "Offset", 0, z_top - depth, Discretize)`.
    - Order: rest pocket, then medial, then boundary loops. Use `order_paths` within each group, chained from the previous end point.
    - `self.commandlist.extend(paths_to_commands(...))`, using the op's `SafeHeight`, `ClearanceHeight`, and the TC's `HorizFeed` / `VertFeed`.
    - `capped` → `Path.Log.warning` naming the requested and used depth.
    - **Review Focus 1:** with `FlatDepth == 0` and any `distances_to_segments` value > `vbit.radius`, log a warning: "<label>: areas wider than the V-bit; set Flat Depth to clear them".
  - `opSetDefaultValues(obj, job)`: `OpStartDepth` = model bounding box `ZMax`.
  - `opUpdateDepths(obj)`: `OpFinalDepth = OpStartDepth - carve_setup(obj).depth` (display only).
  - `opRejectAddBase(obj, base, sub)`: `not is_sketch_base(base)`.
  - `isToolSupported`: `compat.tool_shape(tool) == "VBit"`.
  - `Create(name, obj=None, parentJob=None)` follows `Path.Op.Vcarve.Create`.
  - `SetupProperties() -> list[str]`.

- [ ] **Step 1: Write the failing tests** with `make_job`, 60° V-bit TC, a rectangle sketch 40×20 and a ring sketch. Start Depth comes from the default, z = 0.
  - `test_execute_full_cone`: whole rectangle in `BaseShapes`, `FlatDepth` 0 → `op.Path.BoundBox.ZMin ≈ -cone_height` (tolerance 0.05). There are `G1` commands, and every XY lies inside the rectangle.
  - `test_execute_flat`: `FlatDepth` 1.0 → `ZMin ≈ -1.0`. Some `G1` points are at z = −1 on the boundary offset.
  - `test_depth_capped`: `FlatDepth` 100 → `ZMin ≈ -cone_height`, and the warning was logged. Capture the warning by patching `Path.Log.warning` with a recorder.
  - `test_only_listed`: the Job has two sketches, but only the ring is listed → every path XY lies inside the ring's bounding box.
  - `test_empty_bases`: nothing is listed → `op.Path` has no `G1` commands, and the warning is logged.
  - `test_partial_failure` (Review Focus 4): a good rectangle plus a sketch with an open wire → paths exist for the rectangle, and an error is logged that contains the bad sketch's label.
  - `test_overlapping_loops` (Review Focus 4): a sketch with two overlapping rectangles. Either an error naming the sketch is logged, or the faces cover the union. In both cases there is no exception, and the op state is not `Invalid`.
  - `test_wide_area_warning` (Review Focus 1): a 60×60 square, a 10 mm bit, `FlatDepth` 0 → warning logged.
  - `test_edge_base`: `op.Proxy.addBase(op, clone, "Edge1")` on the rectangle → the path is equivalent to the whole-sketch path (same `ZMin`, and a bounding box within 0.01).
- [ ] **Step 2: Run** the integration command. Expected: FAIL.
- [ ] **Step 3: Implement** `toolpath.py` and `op_vcarve.py`.
- [ ] **Step 4: Run** the integration command. Expected: PASS.
- [ ] **Step 5: Commit** `feat: V-Carve flat depth operation`.

### Task 6: V-Carve Clearance operation + rest-clearing link

**Files:**
- Create: `vcarve_flat/op_clearance.py`
- Modify: `vcarve_flat/op_vcarve.py` (only if `find_clearance_op` needs adjusting)
- Test: `tests/fc/test_op_clearance.py`

**Interfaces:**
- Consumes: `op_vcarve.carve_setup`, `region_sets`; `clearing.*`; `toolpath.paths_to_commands`.
- Produces:
  - `class ObjectVCarveClearance(Path.Op.Base.ObjectOp)`:
    - `opFeatures = FeatureTool | FeatureHeights | FeatureDepths | FeatureNoFinalDepth | FeatureCoolant`.
    - Properties:
      - `VCarveOp` (Link)
      - `StepOver` (Percent, 40)
      - `PocketPattern` (Enumeration `["Offset", "ZigZag"]`, "Offset")
      - `Allowance` (Length, 0)
  - `opExecute`:
    - Without a link → error.
    - Take `setup = carve_setup(link)`. If `link.FlatDepth == 0`, or every floor is empty → `Path.Log.info` and an empty path.
    - Otherwise, for each face set: `pocket_polylines(offset_faces(faces, -setup.r_flat), R, StepOver/100 * 2R, PocketPattern, Allowance, setup.z_top - setup.depth, link.Discretize)`.
    - Region-set errors are skipped; the V-carve op already logs them.
  - `opSetDefaultValues` / `opUpdateDepths`: copy `OpStartDepth` from the link, and `OpFinalDepth = start - depth`.
  - `onChanged(obj, prop)`: for `ToolController`, `Allowance` or `VCarveOp`, call `obj.VCarveOp.touch()` when linked. This makes the V-carve op's rest area follow changes to the end mill.
  - `isToolSupported`: `compat.tool_shape(tool) == "Endmill"`.
  - `Create(name, obj=None, parentJob=None)`.
  - `SetupProperties()`.
  - `create_pair(job) -> tuple[clearance_op, vcarve_op]`:
    - Picks the first VBit and the first Endmill TC from `job.Tools.Group`. If either is missing, raises `ValueError("Add a V-bit tool controller to the job")` or the matching end-mill message.
    - Creates the clearance op, then the V-carve op (so the clearance op comes first in the Job), and links them.
    - Does not add bases (the GUI does that).

- [ ] **Step 1: Write the failing tests:**
  - `test_clears_floor`: 40×20 rectangle, `FlatDepth` 1, 60° V-bit, 5 mm end mill (radius `R` read from the TC).
    - The clearance path's `ZMin ≈ -1`.
    - Every XY lies inside the rectangle offset inward by `r_flat + R − 0.01`.
  - `test_no_flat_depth`: `FlatDepth` 0 → no `G1` commands, and the op state is not `Invalid`.
  - `test_too_narrow` (Review Focus 5): a 1.5 mm wide strip → empty clearance path, no exception.
  - `test_rest_shrinks_with_clearance`: a floor with a neck narrower than the end mill.
    - The rest-pocket point count in the V-carve op is lower with a clearance op than without one.
    - Rest-pocket points (z = −D, outside the boundary loop set) lie in the neck region. Isolate them by recomputing with and without the clearance op.
  - `test_create_pair_order`: the Job's `Operations.Group` order is `[clearance, vcarve]`, `clearance.VCarveOp is vcarve`, and the TC shape types are correct.
  - `test_create_pair_missing_vbit`: a Job with only an end mill → `ValueError` mentioning "V-bit".
  - `test_toolchange_retouches`: changing the clearance op's TC to a different end mill puts the V-carve op in `Touched` state.
- [ ] **Step 2: Run** the integration command. Expected: FAIL.
- [ ] **Step 3: Implement** `op_clearance.py`.
- [ ] **Step 4: Run** the integration command. Expected: PASS.
- [ ] **Step 5: Commit** `feat: V-Carve clearance operation and op pair creation`.

### Task 7: GUI integration

**Files:**
- Create:
  - `InitGui.py`
  - `vcarve_flat/gui/__init__.py`
  - `vcarve_flat/gui/selection.py`
  - `vcarve_flat/gui/panels.py`
  - `vcarve_flat/gui/commands.py`
  - `vcarve_flat/resources/icons/vcarve_flat.svg`, `vcarve_clearance.svg`, `vcarve_pair.svg`
- Test: `tests/fc/test_gui_import.py` (headless smoke test) plus the manual checklist below

**Interfaces:**
- Consumes: `op_vcarve.Create`, `SetupProperties`; `op_clearance.Create`, `SetupProperties`, `create_pair`; `sketches.is_sketch_base`.
- Produces:
  - `selection.SketchGate`: `allow(doc, obj, sub)` is true when `is_sketch_base(obj)` holds and `sub` is empty or starts with `"Edge"`. `select()` installs the gate.
  - `panels.VCarveOpPage(PathOpGui.TaskPanelPage)`: a programmatic form with:
    - `toolController`, `editToolController` (QGridLayout) and `coolantController`;
    - QuantitySpinBoxes for `FlatDepth`, `RestScallop`, `StepLength`, `Tolerance`;
    - double spin boxes for `Discretize` and `Colinear`.
    - `taskPanelBaseGeometryPage` returns `Path.Op.Gui.Vcarve.TaskPanelBaseGeometryPage`, which is reused because it handles both `BaseShapes` and edge subs.
  - `panels.ClearanceOpPage`: TC and coolant widgets, a `VCarveOp` combo box listing the Job's `ObjectVCarveFlat` ops, `StepOver`, `PocketPattern`, `Allowance`.
  - `commands.ViewProvider(PathOpGui.ViewProvider)`: overrides `getIcon` to return the addon's SVG path, and `getSelectionFactory` to return `selection.select`.
  - `commands.register()`:
    - Calls `PathOpGui.SetupOperation` for `"VCarveFlat"` / `"CAM_VCarveFlat"` and `"VCarveClearance"` / `"CAM_VCarveClearance"`, passing the ViewProvider through.
    - If `SetupOperation` doesn't accept a ViewProvider class, subclass `CommandPathOp` and call `PathOpGui.Create` with the custom view provider. Check `Path/Op/Gui/Base.py` before writing this.
    - Registers `CAM_VCarvePair` too.
  - `CAM_VCarvePair.Activated`:
    1. Find the Job: from the selection's parent Job, or the only Job in the document.
    2. Call `create_pair`. On `ValueError`, show a `QMessageBox` warning with its text.
    3. Add the selected sketches and edges to the V-carve op: whole objects go to `BaseShapes`, edges go through `addBase`.
    4. Attach view providers and open the V-carve op's task panel.
  - `InitGui.py`: keep it light. Define the command classes with cheap `GetResources` / `IsActive` (any `Path::FeaturePython` named `Job*` exists), and import `vcarve_flat.gui.commands` lazily in `Activated`. Add a workbench manipulator that inserts the three commands after `"CAM_Vcarve"` in the "New Operations" toolbar and in the `&CAM` menu engrave group.

- [ ] **Step 1: Write the failing smoke test** `test_gui_import`: under `freecadcmd`, `import vcarve_flat.gui.selection` succeeds. Guard `FreeCADGui` usage so the gate class can be imported. `SketchGate().allow(doc, clone, "Edge1")` is true; `(doc, clone, "Vertex1")` is false; a Part box is false.
- [ ] **Step 2: Run** the integration command. Expected: FAIL.
- [ ] **Step 3: Implement** the GUI files and icons. Icons are simple 64×64 SVGs: a V groove, a flat-bottom groove, and both side by side.
- [ ] **Step 4: Run** the integration command. Expected: PASS.
- [ ] **Step 4b: Offscreen GUI check.** This step does not modify the user's real FreeCAD config.
  - Write `tests/gui/check_gui.py` and `tests/test_gui.py`. The test is parametrized over `FREECAD_APPRUNS` like `test_freecad.py`. For each AppRun it:
    - creates a temp dir `home`, symlinks the repo to `home/Mod/freecad-vcarve`;
    - runs `QT_QPA_PLATFORM=offscreen FREECAD_USER_HOME=<home> <AppRun> freecad tests/gui/check_gui.py` with a 300 s timeout;
    - expects `GUI-CHECK-OK` in stdout.
  - `check_gui.py`:
    - activates `CAMWorkbench`;
    - asserts that `CAM_VCarveFlat`, `CAM_VCarveClearance` and `CAM_VCarvePair` are in `FreeCADGui.listCommands()`, and that all three are in the "New Operations" toolbar (`FreeCADGui.getMainWindow().findChildren(QtGui.QToolBar)` → action `objectName`/`data` or the command's MenuText);
    - builds a Job with a sketch, selects the sketch, and runs `FreeCADGui.runCommand("CAM_VCarvePair")`;
    - asserts two ops, clearance first, with view providers whose `getIcon()` paths exist;
    - closes the task dialog (`FreeCADGui.Control.closeDialog()`);
    - prints `GUI-CHECK-OK`;
    - calls `os._exit(0)`, or `os._exit(1)` on any exception after printing the traceback.
  - If `FREECAD_USER_HOME` is not honored by a version (check `App.getUserAppDataDir()` inside the script), report it instead of falling back to the real home.
- [ ] **Step 5: Manual check (by the user).** Symlink the repo into the user Mod dir (confirm the path with `App.getUserAppDataDir()`), launch each of the three GUI AppImages (`~/bin/FreeCAD_1.0.2-conda-Linux-x86_64-py311.AppImage`, `~/bin/FreeCAD_1.1.4-Linux-x86_64-py311.AppImage`, `~/bin/FreeCAD_26.3rc2-Linux-x86_64.AppImage`), and check:
  1. The three commands appear next to Vcarve in the CAM toolbar and menu.
  2. With a Job and a ShapeString-derived sketch, select the sketch and run *V-Carve pair*: two ops appear, clearance first.
  3. Edit the V-carve op, add the edge of one letter in the base page, set Flat Depth to 1 mm → recompute; the path is shown.
  4. CAM simulator: floor flat, walls sloped, no cuts outside the letters.
  5. Save, close and reopen the document; the ops still open their panels and show their icons.
- [ ] **Step 6: Commit** `feat: GUI commands, panels and CAM toolbar integration`.

### Task 8: Docs and full-suite verification

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Write the README:**
  - what the addon does, with a Vectric-style workflow and an explanation of flat depth vs. clearance;
  - how to install it (symlink or Addon Manager custom repository);
  - the properties table;
  - the known limitation about scallops;
  - the license line;
  - how to run tests (`python3 -m pytest`, with `FREECAD_APPRUN` set).
- [ ] **Step 2: Run the full suite:** `FREECAD_APPRUNS=<all three AppRuns> python3 -m pytest -v`. Expected: all pure tests pass, `test_freecad.py` passes, and nothing is skipped.
- [ ] **Step 3: Check the headers:** `grep -L "SPDX-License-Identifier: LGPL-2.1-or-later" $(git ls-files '*.py')` prints nothing.
- [ ] **Step 4: Commit** `docs: README with workflow and testing`.
