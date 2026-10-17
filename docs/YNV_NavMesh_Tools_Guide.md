# GTANAVMESH Edit - User Guide

Version: **v0.12.2**
Copyright © 2026 devsanja

## 1. Purpose

GTANAVMESH Edit is a Blender addon for importing, editing and exporting GTA
V YNV navmesh XML files in a CodeWalker-compatible format. It can import XML
directly or work with a navmesh imported through Sollumz.

The direct input format is `.ynv.xml`, not a native binary `.ynv`. A native
`.ynv` can be produced only by the separately configured local compiler after
XML validation; GTANAVMESH Edit does not decode/import native `.ynv` files.

The addon is designed to stay a pure Blender addon. CodeWalker and Sollumz
reference behavior was used for compatibility decisions, but the addon does
not require CodeWalker at runtime.

> Unofficial community tool. GTANAVMESH Edit is not affiliated with, endorsed
> by, or associated with Rockstar Games or Take-Two Interactive.

### Requirements and external tools

Blender 2.80+ is required. Sollumz is optional and must be installed
separately if its importer or property panels are needed. CodeWalker is
optional but recommended for inspection and the target workflow. Building the
optional `ynv_compiler` requires the .NET 8 SDK and a compatible local
`CodeWalker.Core` project.

The release ZIP contains only GTANAVMESH Edit; it does not package Sollumz,
CodeWalker, CodeWalker.Core, GTA V files or other third-party assets.

Main goals:

- Import CodeWalker `.ynv.xml` navmesh files directly, and retain compatibility
  with Sollumz-imported navmeshes.
- Preserve important original metadata such as `AreaID`, `ContentFlags`, points, portals, polygon flags, edge flags and edge links.
- Allow face-level flag editing inside Blender.
- Export one selected navmesh or all loaded navmeshes back to `.ynv.xml`.
- Support geometry-based edge rebuilds for edited navmeshes.
- Load the source cells around a bound navmesh without broad file-system
  guessing.
- Create a starter cell or generate a reviewable starter navmesh from selected
  collision/regular mesh geometry.
- Optionally compile a validated XML export to native RSC7 `.ynv` with a
  user-configured local compiler.

## 2. Important Concepts

### Navmesh Cell

A YNV file usually represents one navmesh cell. The file name often looks like `navmesh[123][99].ynv.xml`.

Each cell has its own:

- `AreaID`
- `ContentFlags`
- bounding box (`BBMin`, `BBMax`, `BBSize`)
- polygons
- points
- portals
- edge links to internal polygons and external neighbor cells

### AreaID

`AreaID` is the numeric cell identifier used inside edge links. It must stay correct when replacing an existing game navmesh.

If the `AreaID` is wrong, edge links can point to the wrong cell or become invalid.

The valid range is **0–16382**. `AreaID` **0 is valid** and must not be
treated as an empty/missing value; `16383` is reserved as the open-edge
sentinel. An imported source with AreaID 0 is therefore authoritative just
like any other imported cell.

### Source XML

The Source XML is the original `.ynv.xml` file that belongs to the imported navmesh.

It is important because it allows the addon to preserve data that is difficult to reconstruct perfectly from Blender geometry alone:

- original edge links
- edge flags
- polygon flags
- portal references
- points
- bounds
- `AreaID`
- `ContentFlags`

Face metadata is stored by stable Blender face ID rather than by a transient
polygon position. Reordering faces keeps matching metadata aligned; deleting a
face removes it from the output instead of restoring it from the source XML.

Manual source selection is the safe default. Select the navmesh, use the Load
Source button, and choose the exact original XML. `Fix Sources` is only an
opt-in recovery aid for a moved `.blend`: enable **Auto Find Source** and
optionally set a narrow **Source Search Folder**. An unnamed automatic match
requires equal polygon count, near-identical bounds and exactly one candidate.
It cannot prove that similarly named cells are interchangeable. Always confirm
the selected path, `AreaID`, polygon count and portal count before you edit or
export.

### Polygon Flags

Each polygon has CodeWalker-style packed flag bytes. The add-on exposes the
raw values, individual numeric fields, and all **33 known bits** as grouped
checkboxes. The groups mirror the data layout rather than pretending that all
community names are fully understood:

| Native field | Bits | Visible controls |
| --- | --- | --- |
| `Flags1` | B00–B07 | `AvoidUnk`, `Footpath`, `Underground`, `Unused`, `SteepSlope`, `Water` |
| `Flags2` | B08–B15 | four underground-unknown bits, `PathNode`, `Interior`, `InteractionUnk` and `Unused` |
| `Flags5` | B16 | the optional single `Unused` B16 bit |
| `Flags3` | B17–B24 | `FlatGround`, `Road`, `CellEdge`, `TrainTrack`, `ShallowWater`, `FootpathUnk1`, `FootpathUnk2`, `FootpathMall` |
| `Flags4` | B25–B32 | `SlopeSouth`, `SlopeSouthEast`, `SlopeEast`, `SlopeNorthEast`, `SlopeNorth`, `SlopeNorthWest`, `SlopeWest`, `SlopeSouthWest` |

`Flags5` is not a general eighth byte: it stores B16 only and is restricted to
0 or 1. `Unknown` and `Unused` are still real exported bits, but their names
are intentionally conservative. Do not turn them into assumed gameplay
presets without comparing the source cell in CodeWalker.

The compact **Quick Face Edit** section is the first editing area in the
sidebar. It includes `Load Active`, **Show Flag Colors**, a live active-face
colour swatch, eight common surface flags and a multi-face paint switch.
**All 33 GTA V Flag Bits** holds every named bit, while **Advanced Face Data**
holds raw values, refresh, copy/paste and matching tools. **Edges & Portals**,
**Navmesh Setup**, **Neighbour & Batch Tools** and **Compile** are also
available as closed foldouts so the normal sidebar stays short. **Show Flag Colors**
uses the same additive color calculation as CodeWalker and switches
the current 3D View to Material Preview. Refresh Colors reassigns display
materials after raw/bulk edits without touching YNV metadata. **Load Source**
and **Use Selected** also refresh the materials automatically for existing
meshes. The preview has alpha 0.75 and is diagnostic: some known bits have no
color contribution, and a color is not proof of intended gameplay behavior.

Opening the sidebar is safe even when an imported or Sollumz navmesh has not
yet received stable GTANAVMESH Edit metadata. The UI draw path is read-only;
metadata initialization is deferred until Blender allows an explicit write.

The visible per-bit contributions are B00/B01 red +0.01, B02 green +0.25,
B03 green +0.02, B06 red +0.25, B07 blue +0.25, B14 blue +0.10, B17 green
+0.10, B18 blue +0.03, B20 green +0.75, B21 blue +0.75, B22 red +0.20,
B23 blue +0.20 and B24 green =0.20. Every other known bit is still editable
and exported, but deliberately has no visible CodeWalker material tint.

### Edge Links

Each polygon edge has a link row such as:

`4038:5, 4038:5`

This points to polygon `5` in area `4038`.

An open edge is written as:

`16383:16383, 16383:16383`

Open edges are allowed on true borders, but too many open edges usually means connectivity was lost.

### Boundary Edges

A boundary edge is an edge used by only one face in the current mesh.

If another loaded navmesh has a matching boundary edge at the same world position, the addon can create a cross-cell edge link.

## 3. Installation

1. In Blender, open `Edit > Preferences > Add-ons`.
2. Use `Install...`.
3. Select `GTANAVMESH-Edit-v0.12.2.zip`.
4. Enable `GTANAVMESH Edit`.
5. Open the 3D View sidebar and use the `GTANAVMESH Edit` tab.

After updating the addon zip, reload or reinstall the addon so Blender uses the newest code.

## 4. Panel Fields

### AreaID

The navmesh cell ID written into the exported XML.

Use the original Source XML whenever possible so this value stays correct.

### ContentFlags (Navmesh Setup)

The XML `ContentFlags` value is still shown as text, for example:

`Polygons, Portals`

or:

`Polygons, Portals, Unknown8`

For direct editing, the panel also provides five toggles:

- `Polygons`
- `Portals`
- `Vehicle`
- `Unknown8`
- `Unknown16`

Toggling a known value updates the comma-separated XML value. Other tokens
from an imported source remain in the text field, so a new control does not
discard an unfamiliar source flag. Use the raw field only when you need to
preserve or deliberately author a value outside the named controls.

### Face flags: Quick Face Edit and foldouts

After selecting a face, use **Load Active** in **Quick Face Edit**. It shows
the common surface flags. Open **Advanced Face Data** to inspect/edit the raw
`Flags` line and matching individual values:

- `Flags1`, `Flags2`, `Flags3`, `Flags4`, `UnkX` and `UnkY`: byte values
  (0–255).
- `Flags5 (B16)`: the single supported B16 value (0 or 1).

Numeric fields, the raw `Flags` line and the bit controls stay synchronized.
Open **All 33 GTA V Flag Bits** for the full named set. The full set is grouped as `Flags1 — general (B00–B07)`,
`Flags2 — behaviour (B08–B15)`, `Flags5 — optional B16`,
`Flags3 — surface category (B17–B24)` and
`Flags4 — slope direction (B25–B32)`. It includes `Footpath`, `Road`,
`CellEdge`, `FlatGround`, `Water`, `TrainTrack`, `ShallowWater`, `Interior`,
`PathNode`, `SteepSlope` and all eight slope-direction flags. Other controls
are labelled as `Unknown` or `Unused` where their gameplay meaning is not
established; they are still editable raw YNV data, not recommended defaults.

Enable **Paint named changes to selected faces** before clicking a named flag to
paint only that flag bit over the current selected faces. Unlike a full flag
copy, this retains every selected face's other bits, `UnkX` and `UnkY` values.
When the option is off, a checkbox affects only the active polygon. Named flag
changes save immediately; use **Apply Raw Face Data** after raw edits.

### Structured Edge Flags (Edges & Portals)

Every polygon vertex has one `EdgesFlags` row. Choose the zero-based **Edge**
index to expose that row as four bounded values:

- `Poly1 Unk2` and `Poly2 Unk2` (0–3)
- `Poly1 Unk3` and `Poly2 Unk3` (0–2047)

The values are written back to the selected row in CodeWalker form:

`Poly1 Unk2:Poly1 Unk3, Poly2 Unk2:Poly2 Unk3`

The raw multi-line `EdgesFlags` value remains available. Keep exactly one
edge link and one edge-flags row for each vertex of the polygon.

### Source XML

Path to the original `.ynv.xml` file used to preserve metadata.

### Auto Build Edges

For a mesh without prior metadata, the addon can build local same-cell links
during export. This is mainly a fallback for newly created simple navmeshes;
use an explicit
**Rebuild Edges** after a topology change.

For existing imported cells, Source XML preservation is preferred.

### Strict Validation

Compatibility validation always rejects unsafe packed-field, bounds, edge and
portal data. With **Strict Validation** disabled, known legacy Rockstar issues
such as a zero-area corner or one-way local link are reported as warnings.
Enable it to turn those warnings into errors when authoring new geometry.

## 5. Button Reference

### Import YNV XML

Opens an original `.ynv.xml` and creates the navmesh mesh, point hierarchy and
portal hierarchy. The selected XML becomes the Source XML immediately.

You can also reach it from `File > Import > YNV NavMesh XML (.ynv.xml)`.

### New Navmesh

Creates a small starter triangle using the panel's `AreaID` and `ContentFlags`.

Use it only for a genuinely new cell. Set a unique, valid `AreaID`, create
walkable geometry, assign flags and rebuild edges before export. A new mesh
does not have authoritative source topology, portal intent or neighbour links.

### Generate Navmesh From Selected Mesh

Creates a new navmesh from the active **non-navmesh** mesh; the original mesh
is never modified. A confirmation dialog provides:

- **Max walkable slope** (0–89.9 degrees from world up; default 45 degrees).
- A starting flag preset: Flat Ground, Footpath, Road or Empty/custom.
- **Remove exact duplicate faces**.

Object Mode processes all source faces. In Edit Mode it processes only the
selected source faces. The generator triangulates them, converts vertices to
world space, reverses downward face winding, and skips degenerate, too-steep,
and optionally exact duplicate triangles. It creates local same-cell links and
selects the resulting mesh.

This conversion is not a collision raycast/voxel generator and does not infer
clearance, portals, custom edge behavior, correct cell boundaries or final
gameplay flags. Review all open/non-manifold edges, add intentional markers,
then validate and test the exported XML.

### Use Selected

Marks the selected mesh as a YNV navmesh and loads its metadata into the panel.

Use this if a mesh should be treated as the active navmesh.

### Apply

Writes the panel metadata to the selected navmesh:

- `AreaID`
- `ContentFlags`
- `Source XML`

### Load Source

Loads an original CodeWalker `.ynv.xml` as source metadata.

For live faces that exactly match the source, the addon attaches:

- polygon flags
- edge links
- edge flags
- polygon portal references

### Load Neighbours

Loads existing surrounding `.ynv.xml` cells from the folder containing the
selected navmesh's explicit **Source XML**. It needs that real bound source
path and must be run in Object Mode; it does not use broad automatic file
searches.

The lookup follows CodeWalker's cell grid:

```text
AreaID = y * 100 + x
navmesh[x * 3][y * 3].ynv.xml
```

It considers all eight surrounding cells by default (the operator's advanced
option can limit it to north/south/east/west). It skips files that are absent,
unreadable, already loaded, or whose embedded AreaID disagrees with the
expected cell. It restores the original selected mesh afterward. Run
**Rebuild Edges** after loading when a shared boundary has changed, and use
**Export All** for the edited group.

### Fix Sources

Attempts to find missing Source XML paths for loaded navmeshes.

This is useful when a Blender file was moved or reopened and the addon needs to
reconnect a navmesh to its original XML. The addon stores the absolute source
path, the path relative to the `.blend` when possible, and the source file
name.

It is deliberately best effort. It does not overwrite a manually chosen
source and leaves ambiguous candidates unresolved. Inspect the resulting
`Source XML`, `AreaID`, polygon count and portal count yourself.

### Validate

Checks the current export model for CodeWalker-compatible structure.

Use this before final export. Toggle **Strict Validation** when newly authored
geometry must also be free of legacy compatibility warnings. It is not a native
RSC7 compilation check and it does not prove in-game pathfinding behavior.

### Export XML

Exports the selected navmesh to one `.ynv.xml` file.

The exporter preserves Source XML data when possible.

### Export All

Exports all loaded navmeshes to a folder.

This is the recommended export when several neighboring cells are loaded. It preserves:

- `AreaID`
- `ContentFlags`
- bounds
- points
- portals
- flags
- edge links

It also updates matching cross-cell boundary links without destroying existing internal links.

### Compile YNV

Runs the optional `cw_navmesh.compile_ynv` operator. It invokes a local
`ynv_compiler.exe` chosen by the user and writes a native `.ynv` only after the
XML has passed the configured validation mode and the resulting bytes have
passed an in-memory RSC7 round trip.

Keep the source XML and output binary separate. The addon does not download a
compiler, and compilation is not a replacement for Validate or a game test.
After compiling, run `ynv_compiler --check <output.ynv>` to verify the RSC7
file can be read by the CodeWalker.Core-based reader used by the local
compiler.

### Build Edges

Builds local edge links inside the same navmesh only.

Use this for simple same-cell geometry, but be careful on imported cells because it does not rebuild external neighbor links.

### Rebuild Edges

Rebuilds edge links from geometry.

It can create:

- internal links between faces in the same mesh
- cross-cell links to matching loaded neighbor cells
- preserved external links to cells that are not loaded

Use this after adding or changing faces, for example when adding a bridge or custom walkway.

### Add Point

Adds a YNV point at the 3D cursor under the current navmesh root. It is
available only when an imported or newly created GTANAVMESH Edit navmesh is
selected, preventing orphan points from being exported under the wrong cell.

### Add Portal

Adds a YNV portal at the 3D cursor under the current navmesh root. It is
available only for a selected navmesh that has at least one polygon.

The active face becomes `PolyFrom`. When another face is selected, it becomes
`PolyTo`; both affected polygon portal-reference rows are created immediately.
With one available face, the portal starts as a same-face reference for
deliberate editing; it is never silently assigned to polygon zero. Select the
portal afterward to edit its Type, Angle, `PolyFrom`, `PolyTo` and center in
the panel.

## 6. Face Editing

**Quick Face Edit** works on the active face. Advanced controls remain
available in foldouts without crowding the standard workflow.

### Load Active

Loads the active face metadata into the editor:

- flags
- edges
- edge flags
- portal refs
- individual `Flags1`–`Flags5`, `UnkX` and `UnkY` controls
- named polygon bit controls
- the selected `EdgesFlags` row and its packed components

### Apply Raw Face Data

Writes the raw `Flags`, `Edges`, `EdgesFlags` and portal-row values from
**Advanced Face Data** / **Edges & Portals** back to the active face. Named
flag checkboxes write their changes immediately.

### Apply Flags to Selected

Copies the complete currently shown raw flag set to selected faces (or to the
active face when nothing is selected). This intentionally replaces all flag
bytes on those faces. For a one-bit paint operation that preserves their other
data, enable **Paint named changes to selected faces** and click the desired
named checkbox instead.

### Select Matching

Selects every polygon whose complete raw CodeWalker flag bytes match the
active face. This is useful for finding an existing material/flag class before
making a targeted change; it does not compare visible color alone.

### Show Flag Colors and Refresh Colors

**Show Flag Colors** refreshes the active navmesh's display materials and
switches the current 3D View to Material Preview. **Refresh Colors** only
refreshes those materials. Both use the packed flag data and do not rewrite
geometry, edge rows, portals, or source XML metadata. Quick labels and
named-control tooltips identify visible color contributions before using
Material Preview.

### Copy Flags

Copies the active face flags.

### Paste Flags

Pastes copied flags to all selected faces. If no faces are selected, the flags are pasted to the active face.

## 7. Typical Workflows

### Import and Re-export Without Changes

1. Import the original `.ynv.xml`.
2. Confirm that the exact original file appears in `Source XML`.
3. Use `Validate`.
4. Use `Export XML` or `Export All`.

Expected result: bounds, points, flags and edge links should match the original.

### Editing Flags

1. Select a face.
2. Click `Load Active`.
3. Change a common surface bit in **Quick Face Edit**, open **All 33 GTA V Flag Bits**
   for another named bit, or open **Advanced Face Data** for `Flags1`–`Flags4`,
   `UnkX`, `UnkY` or `Flags5 (B16)`. The five grouped
   sections together cover B00–B32. Use the raw `Flags` value only for an
   exact existing value.
4. To paint just one named bit over several faces, select those faces, enable
   **Paint named changes to selected faces**, then toggle the checkbox. Their
   remaining bit values and raw unknown bytes stay intact. To copy all bytes,
   use **Apply Flags to Selected** in **Advanced Face Data** instead.
5. Use **Show Flag Colors** to inspect the CodeWalker material calculation;
   use **Select Matching** to find equivalent full raw flag sets.
6. To edit edge metadata, open **Edges & Portals**, select an **Edge** and change the two `Unk2` and
   two `Unk3` values for that row.
7. Click **Apply Raw Face Data** after any raw field change.
8. Use `Validate`.
9. Export.

### Adding a Custom Bridge or Walkway

1. Place or model the bridge/collision surface in Blender.
2. Create navmesh faces on the walkable surface.
3. Join those faces into the correct navmesh mesh, or create a new navmesh cell if needed.
4. Set suitable flags, for example road, footpath or flat ground depending on the use case.
5. Make sure connection edges line up cleanly with the existing navmesh.
6. Run `Rebuild Edges`.
7. Use `Export All` if neighbor cells are involved.
8. Validate and compare the exported XML.

Important: if the polygon count changes, the exporter still writes only the
current Blender faces. It cannot blindly copy original edge links to new or
deleted faces, so `Rebuild Edges` must create valid connectivity from geometry.

### Compile a Native Replacement

1. Export a validated `.ynv.xml` to a new output folder.
2. In the addon, choose the local compiler executable and use **Compile YNV**,
   or run `ynv_compiler <input.ynv.xml> <output.ynv>` in PowerShell.
3. Run `ynv_compiler --check <output.ynv>`.
4. Keep both outputs, inspect the XML in CodeWalker, and test the exact
   replacement/mod-loading setup in game.

### Collision-to-Navmesh Workflow

1. Set the intended `AreaID` (including a deliberate `0` when appropriate)
   and `ContentFlags` before generating.
2. Select the collision or ordinary mesh; enter Edit Mode and select only the
   wanted source faces when conversion should not use the entire object.
3. Run **Generate Navmesh From Selected Mesh**. Choose a conservative maximum
   walkable slope and a starting flag preset.
4. Inspect the created separate navmesh: solve any non-manifold/open edges,
   apply source-appropriate flags, add points/portals deliberately, and do not
   assume the source collision encoded gameplay pathing intent.
5. Bind/load neighboring source cells if this navmesh joins other cells, run
   **Rebuild Edges**, validate, export and test.

Avoid tiny gaps, overlapping duplicate faces and disconnected vertices at
connection points. The generator is a starting geometry conversion, not a
guarantee that every accepted triangle is usable in-game.

### Edit a Cell Boundary With Neighbours

1. Import or bind the exact original cell with **Load Source**.
2. In Object Mode, select the navmesh and use **Load Neighbours**. Review the
   report for absent, unreadable or AreaID-mismatched candidates instead of
   treating missing files as loaded cells.
3. Edit the boundary geometry and run **Rebuild Edges** after all relevant
   cells are present.
4. Use **Export All**. Inspect reciprocal boundary rows in the XML and test
   traversal on both sides of the cell border.

## 8. Export All Safety Rules

`Export All` is designed to avoid the old problem where cells, bounds or edge data were lost.

Current behavior:

- Each navmesh exports with its own Source XML when available.
- Points and portals are taken only from the matching navmesh root.
- If no clear root exists, Source XML points and portals are used.
- Existing internal edge links are preserved.
- Face metadata is reindexed through stable face IDs; links to deleted faces
  become open boundaries instead of reviving source geometry.
- Cross-cell boundary links are updated only where geometry matches loaded
  neighbour cells, with reciprocal links on both loaded cells.

## 9. Troubleshooting

### Bounds are too large

Cause: points or portals from multiple navmeshes may have been included.

Fix: use the updated addon, keep each imported navmesh under its own root, and use Source XML paths.

### Too many `16383:16383` open edges

Cause: edge links were lost or geometry does not connect.

Fix:

- Reload the exact Source XML if the mesh was never bound to it.
- After topology changes, run `Rebuild Edges`.
- Check for gaps or misaligned boundary edges.

### NPCs do not cross a custom bridge

Possible causes:

- bridge navmesh faces are not connected to the existing navmesh
- flags are wrong
- edge links are open
- the bridge is in the wrong cell
- connection edges do not match neighbor geometry

Use `Rebuild Edges`, then inspect exported edge links.

### Duplicate AreaID warning

Two loaded navmeshes have the same `AreaID`.

This is usually wrong unless you intentionally duplicated a cell for testing.

### Polygon count differs from Source XML

The addon preserves matching face metadata but does not blindly reuse a
source-only polygon row.

Use `Rebuild Edges` and validate the result.

## 10. Recommended Checks Before Game Testing

Before putting an exported XML into a game workflow:

1. Run `Validate`.
2. Use `Export All` for multi-cell edits.
3. Compare important fields against the original:
   - `AreaID`
   - `ContentFlags`
   - `BBMin`
   - `BBMax`
   - point count
   - portal count
   - edge open/internal/external counts
4. Inspect custom areas for open edges.
5. Keep backups of original XML files.

## 11. Notes

This addon exports CodeWalker-compatible XML and can optionally call a
user-configured local compiler for native `.ynv` output.

For edited geometry, correct navmesh behavior in game still depends on valid YNV compilation and on how the target game setup loads the replacement navmesh.

See `YNV_Import_Source_Compile.md` for the companion workflow.
