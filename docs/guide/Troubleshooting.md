# Troubleshooting

The ops report their problems in the **Report view** (View → Panels → Report view); keep it open while
you work. To have FreeCAD open it by itself, tick *Show report view on error* (and *on warning*) in
Edit → Preferences → General → Report view. An op with an error gets a red mark in the tree and an empty
toolpath.

## Commands and selection

**The V-Carve commands are greyed out.** They need a CAM Job in the active document. Create one first
(CAM → Job).

**"Add a V-bit tool controller to the job"** (or an end mill). The Job needs a tool controller whose
tool has the V-bit (or end mill) shape. Add one in the Job's Tools tab.

**"&lt;op&gt;: &lt;name&gt; is not a tool controller, pick its tool controller &lt;TC&gt;"**. In the
property editor the Tool Controller link was set to a ToolBit (the tool itself) instead of its tool
controller. Pick the entry named in the message.

**"&lt;op&gt;: the tool controller must use a V-bit"**. V-Carve Flat, Plug and Photo cut with a V-bit,
the clearance op with an end mill.

**"Not a sketch of the Job &lt;job&gt;, skipped: …"**. Only sketches that are part of the Job's model
are carved. Select the sketch (or its clone) inside the Job, or add the sketch to the Job's model.

**"&lt;sketch&gt;: outlines overlap or touch"**. A sketch's closed outlines must be disjoint: an outline
may lie inside another (a letter's counter) but not cross or touch it. ShapeString letters of tight or
script fonts often touch; increase the tracking, choose another font, or put the touching letters in
separate sketches.

## Depths and clearing

**"areas wider than the V-bit; set Flat Depth to clear them"**. With `FlatDepth` 0 the V-bit carves as
deep as its cone allows, and areas wider than the cone stay uncut in the middle. Set a flat depth and
add a clearance op ([V-Carve Pair](V-Carve-Flat.md) does both).

**"Flat Depth … is deeper than the V-bit …"** (or Max Depth for photos). The depth is capped at the
V-bit's cone height. Use a longer cone (larger diameter) or a shallower depth.

**"no V-Carve Clearance op, so the V-bit is clearing the whole floor"**. It works, but slowly. Add a
clearance op with an end mill, linked through its `VCarveOp` property, or use V-Carve Pair.

**"no floor reachable by the end mill"**. The end mill is wider than every part of the floor; the V-bit
clears it instead. A smaller end mill helps.

**Thin slivers of floor left in sharp corners.** With a wide V-bit tip (about 1 mm, like FreeCAD 1.0's
stock 60° bit), a non-zero `Allowance` or star-like shapes, the V-bit's rest pass can leave 0.07–0.3 mm
in sharp corners. Use a bit with a small tip.

## MillFace before a photo or V-carve does nothing

CAM's MillFace needs a face picked under *Base Geometry*; without one it makes no path, silently. A Job
whose model is only a sketch has no face to pick, so add a solid for the board (for example a Part Cube
with its top at the faced height) to the Job and pick its top face. Then set the following op's
`StartDepth` to the faced surface; V-Carve Photo warns when a MillFace before it faces deeper than its
`StartDepth`.

## Inlays

**The fit check shows red marks.** See [Inlays: reading the fit check](Inlays.md#2-check-the-fit). A collision
of about a millimetre at a cusp (two curves meeting along one tangent, as at the top of a heart drawn from two
half circles) comes from the design: see [Inlays: no cusps](Inlays.md#example-a-heart).

**"the plug Job's stock … is thinner than …"** or **"the stock margin beyond the plug is narrower than
the end mill"**. Set the plug Job's stock to the real plug board; see
[Inlays: stock and Z zero](Inlays.md#stock-and-z-zero).

**Check Inlay Fit says "recompute it first" or refuses arcs.** Recompute the document. The check
simulates straight (G1) moves only, which is what the addon's ops produce.

## Messages that are not the addon's

- **`ccurve not closed`** in the report view comes from FreeCAD's area code closing letter outlines
  itself. Harmless.
- **`'NoneType' object has no attribute 'setOrigin'`** tracebacks from CAM's `Job.py` appear when a tool
  or tool controller editor is opened while the Job's task panel is open. A FreeCAD bug; harmless, gone
  after a restart.

## Slow ops and cancelling

Large designs, small `StepLength` or `SampleStep` values and fine photos take a while. The status bar
shows a progress bar; press **Esc** to cancel (there is no confirmation). In a recompute, Esc cancels the
running op and every later V-carve op of that recompute. A cancelled op keeps an empty path and an error
mark; recompute it to try again. A cancelled Check Inlay Fit or V-Carve Inlay changes nothing and says
"… cancelled" in the report view.

## Known limitations

- V-bit rest clearing leaves scallops up to `RestScallop`.
- The ZigZag pocket pattern can overshoot the floor edge by about 0.01 mm at inner corners (a libarea
  artefact); Offset, the default, does not.
- In strokes narrower than the flat floor the V-bit follows the centre line, so their inner corners keep
  the cone's rounding.
- A clearance `StepOver` near 100 % leaves uncut ridges between passes, as with CAM Pocket.
- A self-intersecting single outline (a figure 8) is not detected.
- Input is 2D sketches or a FreeCAD image plane, not 3D models.

## Reporting a problem

Open an [issue](https://github.com/ghbalf/freecad-vcarve/issues) with your FreeCAD version
(Help → About FreeCAD → Copy to clipboard), the report view's messages and, if you can, the `.FCStd`
file.
