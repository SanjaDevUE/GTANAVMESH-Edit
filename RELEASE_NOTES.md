# GTANAVMESH Edit v0.12.2

Release date: 2026-10-18
Copyright © 2026 devsanja

> Unofficial community tool. GTANAVMESH Edit is not affiliated with, endorsed
> by, or associated with Rockstar Games or Take-Two Interactive.

## Release asset

Install **`GTANAVMESH-Edit-v0.12.2.zip`** through Blender's
**Edit > Preferences > Add-ons > Install...** command, then enable
**GTANAVMESH Edit**. Do not unpack the ZIP before installing it.

If v0.12.1 is already installed, disable it, install this ZIP, enable the
add-on again and reopen Blender. This ensures Blender reloads the updated
Python module rather than retaining the previous one in memory.

## Fixed: safe sidebar drawing in Blender 3.5

v0.12.1 could show the following Blender exception when a navmesh had not yet
received stable GTANAVMESH Edit metadata:

`Writing to ID classes in this context is not allowed`

The previous draw path attempted to migrate/write polygon metadata while
Blender was rendering the sidebar. Blender correctly rejects writes from a
`Panel.draw()` callback.

v0.12.2 makes the entire draw path read-only. Metadata initialization still happens via
**Use Selected**, **Load Active**, imports and deferred editor initialization,
where Blender permits the write.

## Compact panel, full editing surface

The normal view now shows only two short blocks:

- **Quick Face Edit** — `Load Active`, **Show Flag Colors**, a live active-face
  swatch, eight common surface flags and **Paint named changes to selected
  faces**.
- **Navmesh** — AreaID, source load, validation, edge rebuild and XML export.

Everything else is present but starts closed, so the sidebar stays useful on a
normal Blender screen: **All 33 GTA V Flag Bits**, **Advanced Face Data**,
**Edges & Portals**, **Navmesh Setup**, **Neighbour & Batch Tools** and
**Compile**. Named flags save immediately. Raw flag/edge/portal values are
reviewed in the advanced foldouts and use **Apply Raw Face Data** when needed.

### Exact CodeWalker colour behavior

Quick labels and named-control tooltips document every bit that has a visible
contribution in CodeWalker's additive material calculation: B00/B01, B02,
B03, B06, B07, B14, B17, B18, B20, B21, B22, B23 and B24.

Other valid known flags intentionally have no material colour contribution in
CodeWalker; they are still fully editable and exported. The display has 0.75
alpha and **Show Flag Colors** switches the current 3D View to Material
Preview.

### Colours refresh automatically

**Load Source** and **Use Selected** now assign CodeWalker material colours
automatically. This fixes existing or Sollumz-imported meshes whose source
flags were correct but whose material slots had not yet been refreshed.

Direct XML import also reuses material slots for identical flag combinations,
instead of adding a duplicate material slot for each polygon.

## Earlier v0.12.0 features retained

- Direct CodeWalker-compatible `.ynv.xml` import/export and optional native
  compiler workflow.
- ContentFlags editing, all 33 named polygon bits, raw byte fields and packed
  `EdgesFlags` editing.
- Safe points/portals, AreaID `0` support, source metadata preservation,
  neighbour-cell loading and cross-cell edge rebuilding.
- Generation of a reviewable starter navmesh from selected mesh geometry.

## Verification

The v0.12.2 source was tested in Blender 3.5.1 using a newly tagged navmesh
with no pre-existing stable metadata. The real panel draw path completed in
both Object Mode and Edit Mode without creating face attributes or object
metadata. An explicit **Use Selected** operation then initialized metadata
successfully, as intended.

The v0.12.2 ZIP is syntax-checked, archive-checked and installed/enabled in
an isolated Blender 3.5 profile.

A real 2,824-polygon YNV XML was imported, one Road polygon was changed to
Water + ShallowWater, a second Road polygon was deleted, edges were rebuilt,
and the result exported. CodeWalker-Core validated the XML, compiled it to an
RSC7 `.ynv`, and read it again as Area ID 4039 with 2,823 polygons, 0 portals
and 811 points. The original source file was not modified.

These checks establish Blender and CodeWalker-Core structural compatibility and
material-preview behavior. The CodeWalker desktop app itself requires a valid
GTA V installation folder on this PC before it can open a resource; its
pre-filled folder did not contain `GTA5.exe`, so no setting was saved. Neither
kind of check proves in-game navigation behavior; test the exported navmesh in
the intended game/mod setup.
