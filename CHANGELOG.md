# Changelog

All notable changes to V-Carve Flat. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## [0.4.1] - 2026-10-28

### Fixed
- FreeCAD 1.1.4 and 26.3 no longer crash when carving some bold font letters with holes (OCC 7.8's
  whole-face offset segfaulted on their B-spline outlines).
- A cusp, where two curves meet along one tangent (the top of a heart drawn from two half circles), no
  longer fails the V-carve ("Cannot normalize null vector") or the plug ("float division by zero").

### Added
- User guide in `docs/guide`: installation, walk-throughs of a sign, an inlay and a photo with
  screenshots, and troubleshooting.

## [0.4.0] - 2026-10-28

### Added
- **V-Carve Photo** operation: carves a FreeCAD image plane as V-grooves whose depth follows its
  darkness, along parallel lines, two crossed line sets (Hatch) or custom vectors such as imported
  Inkscape paths, with contrast and invert controls. Black reaches `MaxDepth`; transparent pixels stay
  uncut, also with `Invert`. The image is carved as the top view shows it.
- `LineSpacing` defaults to the V-bit's groove width at `MaxDepth` plus 5 %, as an expression, so it
  follows `MaxDepth` live in the task panel and is filled in anew when a V-bit is picked.
- `BandAverage` (off by default): Lines and Hatch average the image across each line's band instead of
  reading it under the line; `SampleStep` also averages finer image pixels.
- Warnings when grooves at `MaxDepth` merge, when the image reaches outside the stock, and when a MillFace
  before the photo op faces below its `StartDepth`.

### Changed
- The plug's flat-tip limit at sharp, narrow inner corners (such as a counter's mirrored tip) is
  documented: up to 0.023 mm over about 0.004 mm² with a 0.1 mm tip, none with a pointed bit.

## [0.3.0] - 2026-10-27

### Added
- **Check Inlay Fit** command: simulates the seated plug from both Jobs' toolpaths and creates a Fit
  object with red collision and blue void marks; it marks itself outdated when the ops change.
- Rest machining: a `RestOnly` clearance op clears what the earlier clearance ops left, so a chain of
  smaller end mills can precede the V-bit's rest pass.
- V-Carve Inlay dialog: an optional rest end mill, added to both Jobs as a `RestOnly` clearance op.
- Progress indicator with Cancel (Esc, no confirmation; in a recompute it also cancels the later ops) for
  the ops, V-Carve Inlay and the fit check.

### Changed
- Several clearance ops per V-carve op are supported (the V-bit rest area follows the whole chain),
  replacing the single-op restriction.
- Deleting or reordering a clearance op updates the chain in the same recompute.

### Fixed
- Where a sharp (mitred) corner of a counter reaches through the floor's edge opposite it, the V-bit now
  runs up the two grooves this leaves; the cone alone rounded them and the wall above them, and the plug
  collided there (by up to 0.4 mm with a 60° bit, 0.03 mm in a 90° "A").
- FreeCAD 26: the progress bar of Check Inlay Fit and V-Carve Inlay showed nothing; its Part booleans stop
  the running progress indicator, which is now restarted.

## [0.2.0] - 2026-10-26

### Added
- **V-Carve Inlay** command: from a sketch it builds a pocket Job and a mirrored plug Job, leaving the
  selected Job as it is. Its dialog asks for the V-bit, end mill, pocket depth, glue gap, plug boundary
  (Margin ring or whole Stock) and the ridge pass.
- **V-Carve Plug** operation: carves the complement of the mirrored design from a virtual surface, with
  a ridge pass that flattens narrow plug ridges for a tipped V-bit.
- Step-down levels for the V-carve, plug and clearance ops.
- Sharp inner corners: the V-bit's wall pass runs into each inner corner of a flat floor instead of
  circling it, in pockets and plugs.
- Warnings for gaps narrower than the V-bit tip and for stock too thin or too narrow for the plug.

### Fixed
- The seated plug fits the pocket at sharp inner corners (a valley pass down each corner's bisector)
  and in counters wider than the plug margin (they were left uncut).
- The plug Job's stock is deep enough for the plug.
- The inlay Jobs are named `Job*`, so the CAM simulators list them; the plug op is named `VCarvePlug`.
- Exact offsets of faces with holes and full circles; medial paths stay on their Voronoi edges.
- The V-bit rest area falls back to Path.Area when OCC's cut keeps the floor.
- Naming the right tool controller when a tool bit is linked instead.

## [0.1.0] - 2026-10-20

### Added
- **V-Carve Flat** operation: V-carves sketches along the medial axis down to a flat depth, with a
  V-bit rest pass for floor areas the end mill cannot reach.
- **V-Carve Clearance** operation: clears the flat floor with an end mill (ZigZag or Offset pattern,
  step over, allowance), and a command that creates both ops as a pair.
- GUI commands, task panels and CAM toolbar integration; tested on FreeCAD 1.0.2, 1.1.x and 26.3.

[0.4.1]: https://github.com/ghbalf/freecad-vcarve/releases/tag/v0.4.1
[0.4.0]: https://github.com/ghbalf/freecad-vcarve/releases/tag/v0.4.0
[0.3.0]: https://github.com/ghbalf/freecad-vcarve/releases/tag/v0.3.0
[0.2.0]: https://github.com/ghbalf/freecad-vcarve/releases/tag/v0.2.0
