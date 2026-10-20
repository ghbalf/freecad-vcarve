# V-Carve Flat

A FreeCAD CAM addon that V-carves 2D sketches to a **flat depth** and adds an **end-mill clearance
operation** for the floor. Think of the Vectric-style "flat depth + clearance" workflow: the V-bit
cuts the sharp edges and the narrow strokes, the end mill removes the wide flat areas quickly.

Supported FreeCAD versions: 1.0.2, 1.1.4 and 26.3rc2 (minimum 1.0.0).

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

**Clearance.** The clearance op's `VCarveOp` property links it to the V-carve op (Pair does this
for you); it cuts the floor with the end mill, using `PocketPattern`, `StepOver` and `Allowance`.
Where the end mill cannot reach part of the floor (corners, narrow areas), the V-bit clears that
rest area. With no clearance op the V-bit clears the whole floor, which is slow, and a warning says so.

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

## Known limitations

- V-bit rest clearing leaves scallops up to `RestScallop`.
- The ZigZag pocket pattern can overshoot the floor edge by about 0.012 mm (a libarea artefact).
  Offset, the default, is unaffected.
- Overlapping or touching outlines in one sketch (for example ShapeString letters that touch)
  are rejected with an error naming the sketch. Separate them, or put them in separate sketches.
- A self-intersecting single loop (a figure-8) is not detected.
- Inlay is not supported yet (planned for v2).
- Input is 2D sketches only.

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

## License

LGPL-2.1-or-later, see `LICENSE`. This is a clean-room implementation, inspired by F-Engrave and
commercial V-carving tools; no code was copied from them.
