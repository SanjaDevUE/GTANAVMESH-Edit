# GTANAVMESH Edit - Import, Source Binding, and Native Compilation

This document describes the safe workflow for creating or editing GTA V YNV
navmeshes with GTANAVMESH Edit. The Blender addon writes CodeWalker-compatible
`.ynv.xml`; native `.ynv` compilation is deliberately a separate, opt-in
step.

Version: **v0.12.2**
Copyright © 2026 devsanja

> Unofficial community tool. GTANAVMESH Edit is not affiliated with, endorsed
> by, or associated with Rockstar Games or Take-Two Interactive.

## Requirements and external tools

Blender 2.80+ is required. Sollumz is optional and must be installed
separately if its importer or property panels are needed. CodeWalker is
optional but recommended for inspecting exports. Building `ynv_compiler` from
source additionally requires the .NET 8 SDK and a compatible local
`CodeWalker.Core` project.

The release ZIP contains GTANAVMESH Edit only. It does not package Sollumz,
CodeWalker, CodeWalker.Core, GTA V files or other third-party assets.

GTANAVMESH Edit directly imports **`.ynv.xml`**, not native binary `.ynv`
files. The optional compiler writes a binary only after validated XML export;
it is not a binary importer or a replacement for source XML review.

## Choose the source deliberately

An imported source XML is more than a template. It carries the cell identity
(`AreaID`), content flags, polygon metadata, portal references, points and
edge information which geometry alone cannot recover reliably.

Use one source XML per navmesh mesh. The recommended order is:

1. Import the original `.ynv.xml` with **Import YNV XML**
   (`cw_navmesh.import_xml`). The imported file is attached as the source
   immediately.
2. For an already existing mesh, select it and use **Load Source**
   (`cw_navmesh.load_source_xml`) to choose the exact original file.
3. Check the `Source XML` field, `AreaID`, polygon count and portal count
   before making edits.

`Fix Sources` is an opt-in recovery aid, not a substitute for step 2. Enable
**Auto Find Source** only when needed and optionally set **Source Search
Folder**. Discovery is restricted to the blend/export folder and that chosen
folder; an unnamed cell must have the same polygon count, near-identical bounds
and exactly one candidate. It never replaces an already stored manual source.
Confirm its choice in the `Source XML` field. Keep the original XML outside
the export folder and never use an unrelated cell merely because its name
looks similar.

An explicit `AreaID` **0** is a real, valid cell identifier and is preserved
as such. The valid range is 0–16382; `16383` is the reserved open-edge
sentinel, not an editable cell identity. Do not replace an imported zero with
another AreaID merely because a zero-valued field looks unset.

If no trustworthy source exists, leave the source field empty. Set a unique
`AreaID` manually (including `0` only when that is deliberately the target
cell), build/rebuild connectivity deliberately, and treat every
portal, point and edge link as data that needs review.

## Edit navmesh metadata from the sidebar

The **GTANAVMESH Edit** tab presents the GTA navmesh values in both structured
and raw forms. Its compact default view starts with **Quick Face Edit** and
**Navmesh**; less common fields remain reachable in named collapsed foldouts.
Select a face and use **Load Active** before changing polygon-level metadata.

- **ContentFlags:** open **Navmesh Setup**, then use the `Polygons`, `Portals`, `Vehicle`, `Unknown8` and
  `Unknown16` toggles for the known values. The raw comma-separated
  `ContentFlags` value remains the source of truth for unfamiliar tokens.
- **Polygon fields:** in **Advanced Face Data**, `Flags1`, `Flags2`, `Flags3`, `Flags4`, `UnkX` and
  `UnkY` accept 0–255; `Flags5 (B16)` accepts 0 or 1. They stay synchronized
  with the raw `Flags` field and named bit controls.
- **Named bits:** **Quick Face Edit** exposes the eight common surface flags.
  **All 33 GTA V Flag Bits** exposes all 33 known GTA V bits in native storage
  groups: `Flags1` B00–B07, `Flags2` B08–B15, optional `Flags5` B16,
  `Flags3` B17–B24 and `Flags4` B25–B32. This includes `Footpath`, `Road`,
  `CellEdge`, `FlatGround`, `Water`, `TrainTrack`, `ShallowWater`, `Interior`,
  `PathNode` and the eight slope directions. Do not infer a gameplay meaning
  for controls labelled `Unknown` or `Unused`.
- **Bulk bit painting:** enable **Paint named changes to selected faces** before
  clicking a checkbox to change only that bit across selected faces. The tool
  preserves each face's other bits and `UnkX`/`UnkY`. Named bit changes save
  immediately; use **Apply Raw Face Data** for raw fields.
- **Flag colors:** **Quick Face Edit** shows a live active-face colour swatch.
  **Show Flag Colors** switches the current 3D View to Material Preview and
  **Refresh Colors** in **Advanced Face Data** reapplies display
  materials. **Load Source** and **Use Selected** refresh those materials
  automatically. The additive colors and 0.75 alpha follow CodeWalker's
  calculation; they are a diagnostic display rather than a semantic flag
  validator.
- **EdgesFlags:** open **Edges & Portals**, select the zero-based edge row, then edit `Poly1 Unk2`,
  `Poly1 Unk3`, `Poly2 Unk2` and `Poly2 Unk3`. `Unk2` is 0–3 and `Unk3` is
  0–2047. One `EdgesFlags` row is required per polygon vertex.

Use **Apply Raw Face Data** after editing a raw multi-line value, then run **Validate**. An
unknown source value is not an error by itself; preserve it unless a reviewed
change is needed for the target navmesh.

## Import an existing cell

1. In Blender, choose **File > Import > YNV NavMesh XML (.ynv.xml)**, or use
   the **Import YNV XML** panel button.
2. Select the original `.ynv.xml`. The importer creates the navmesh mesh and
   its point/portal hierarchy and attaches that file as `Source XML`.
3. Select the mesh and press **Validate** before changing it. This verifies
   the export model; it does not prove in-game navigation behavior. Leave
   **Strict Validation** disabled for an unmodified Rockstar source with
   legacy warnings; enable it for newly authored geometry and final review.
4. When changing a boundary, switch to Object Mode and use **Load Neighbours**
   after the source XML is bound. It safely loads only expected surrounding
   source files from that source folder. Use **Export All** for a multi-cell
   change so reciprocal cross-cell edges can be checked.

Sollumz-imported navmeshes are supported too. When both addons are enabled,
GTANAVMESH Edit reads the Sollumz navmesh properties as well as its own
stored metadata. If the source was not attached during the Sollumz import,
attach it manually with **Load Source**.

## Create a new cell

1. Decide which world/navmesh cell the mesh belongs to and assign a unique,
   valid `AreaID` first. AreaID 0 is valid if it is the intended cell; do not
   copy an existing ID for a production replacement.
2. Press **New Navmesh** (`cw_navmesh.create_navmesh`) to make the starter
   triangle, then model only walkable faces.
3. Set polygon flags and material semantics, add points/portals only when
   their target polygons are known, and run **Rebuild Edges**.
4. Load every edited neighbour, rebuild reciprocal boundary links, run
   **Validate**, then use **Export All**.

New geometry has no authoritative source topology. The exporter always writes
the live Blender face list—deleted source polygons are never retained—but it
cannot infer gameplay intent such as portal placement, edge flags or an
unloaded neighbour's polygon identity. Inspect these in CodeWalker and test in
the target game/mod setup.

## Generate from selected collision or mesh geometry

Use **Generate Navmesh From Selected Mesh** when a regular mesh or collision
surface is a better starting point than the single-triangle **New Navmesh**
cell. Select a non-navmesh mesh and set the intended `AreaID`/`ContentFlags`
in the panel first. In Object Mode the generator considers all source faces;
in Edit Mode it considers selected faces only.

The dialog offers a maximum walkable slope, Flat Ground/Footpath/Road/empty
starting flags, and exact duplicate removal. The new navmesh is separate from
the source mesh. Source faces are triangulated in world space, downward
winding is corrected, degenerate and too-steep triangles are skipped, and
local edge links are built.

The result still needs authoring review. The generator does not decode collision
materials into gameplay flags, raycast obstacle clearance, decide portal
locations, infer cross-cell ownership, or resolve non-manifold geometry.
Review accepted faces and open edges, add markers deliberately, load relevant
neighbours, rebuild links, validate and test before using the export.

## Load neighbouring source cells

**Load Neighbours** requires an existing explicit Source XML on the selected
navmesh and runs only in Object Mode. It uses the source file's folder and
CodeWalker's grid convention:

```text
AreaID = y * 100 + x
navmesh[x * 3][y * 3].ynv.xml
```

By default it considers the eight surrounding cells (including diagonals).
It skips already loaded cells, files that are absent/unreadable, and a file
whose embedded `AreaID` differs from the expected cell. This prevents a
same-named but wrong source file from silently producing invalid edge targets.
It is not a directory-wide discovery feature. After a boundary edit, use
**Rebuild Edges** with all relevant cells loaded and export them together with
**Export All**.

## Points and portals

**Add Point** and **Add Portal** require a selected GTANAVMESH Edit navmesh
root. New points are parented under its local point hierarchy, and no orphan
marker is created if there is no valid navmesh selection.

For a new portal, the active face is `PolyFrom`; another selected face becomes
`PolyTo` when available. The creator writes the portal-reference rows on the
affected polygons immediately. A single valid face creates an explicit
self-reference that must be reviewed, rather than silently choosing polygon
zero. Select the resulting portal in Blender to edit its type, angle, face
references and position.

## XML export and optional native `.ynv` compilation

The safe output chain is:

```text
Blender scene -> Validate -> exported .ynv.xml -> Compile YNV -> .ynv -> --check
```

`Compile YNV` (`cw_navmesh.compile_ynv`) is optional. It invokes a configured
local `ynv_compiler` executable only after the XML passes the same validation
mode selected in the panel. It does not replace the source XML, does not fetch
tools from the network, and writes the native output only after an in-memory
RSC7 round-trip check. Keep the XML beside the binary for debugging and
revision control.

Build from a source checkout only after `CodeWalker.Core` is available. If it
is not at the default sibling path configured by `ynv_compiler.csproj`, point
the build to it explicitly:

```powershell
dotnet build .\ynv_compiler\ynv_compiler.csproj -c Release `
  /p:CodeWalkerCoreProject=C:\src\CodeWalker\CodeWalker.Core\CodeWalker.Core.csproj
```

After a successful `dotnet build -c Release`, the current Windows executable
is located at:

```text
ynv_compiler\bin\Release\net8.0\ynv_compiler.exe
```

The same operation can be run outside Blender from PowerShell:

```powershell
& .\ynv_compiler\bin\Release\net8.0\ynv_compiler.exe `
  .\export\navmesh[123][99].ynv.xml `
  .\export\navmesh[123][99].ynv

& .\ynv_compiler\bin\Release\net8.0\ynv_compiler.exe `
  --check .\export\navmesh[123][99].ynv
```

Successful `--check` output confirms that the produced file has an RSC7
header and can be read by the CodeWalker.Core-based reader used by the local
compiler. It is a binary
integrity check, not proof that all links are semantically correct or that the
game will load a particular replacement.

## Before game testing

1. Preserve the original XML and native YNV outside the output directory.
2. Verify that source identity, `AreaID`, content flags, bounds, portal count
   and point count are expected.
3. Review changed polygons and every newly opened or cross-cell edge.
4. Run Blender **Validate**, compile only the XML that passed validation, then
   run `ynv_compiler --check` on the resulting binary.
5. Test the exact replacement/mod-loading setup in game, including traversal
   across edited cell boundaries.

Neither auto source recovery, XML validation nor RSC7 compilation replaces
that final behavior test.
