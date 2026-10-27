# Changelog

All notable changes to V-Carve Flat. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

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

[0.3.0]: https://github.com/ghbalf/freecad-vcarve/releases/tag/v0.3.0
[0.2.0]: https://github.com/ghbalf/freecad-vcarve/releases/tag/v0.2.0
