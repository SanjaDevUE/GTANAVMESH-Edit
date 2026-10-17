# GTANAVMESH Edit v0.12.0

Release date: 2026-10-18
Copyright © 2026 devsanja

> Unofficial community tool. GTANAVMESH Edit is not affiliated with, endorsed
> by, or associated with Rockstar Games or Take-Two Interactive.

## Release asset

Install **`GTANAVMESH-Edit-v0.12.0.zip`** through Blender's
**Edit > Preferences > Add-ons > Install...** command, then enable
**GTANAVMESH Edit**. Do not unpack the ZIP before installing it.

## What is new

### Full GTA flag editor and CodeWalker colors

- The Polygon Editor now presents all **33 known GTA V polygon bits** in five
  storage groups: `Flags1` (B00–B07), `Flags2` (B08–B15), optional `Flags5`
  (B16), `Flags3` (B17–B24), and `Flags4` (B25–B32).
- Raw flag bytes, structured numeric fields, and named checkboxes stay in
  sync. Labels that are still uncertain in community tooling remain marked
  `Unknown` or `Unused`; the add-on does not invent gameplay meaning for them.
- **Show Flag Colors** switches the current 3D View to Material Preview;
  **Refresh Colors** reapplies the materials without changing geometry or YNV
  metadata. Their colors use CodeWalker's additive flag calculation and its
  0.75 alpha, rather than a simplified category palette. A bit with no visible
  color contribution is not lost or disabled.
- Enable **Change named bit on selected faces** to paint one checkbox value
  across selected faces while preserving every face's other bits and raw
  `UnkX`/`UnkY` fields. **Apply Flags to Selected** remains the explicit tool
  for copying the complete raw flag set. **Select Matching** finds faces whose
  complete raw flag values match the active face.

### Safer points, portals, and AreaID handling

- **Add Point** and **Add Portal** now require a selected imported or newly
  created navmesh. They cannot leave an orphan marker in the scene.
- A new portal uses the active face as `PolyFrom` and another selected face as
  `PolyTo`; the add-on writes its polygon portal-reference rows immediately.
  With only one valid face, it creates an explicit same-face starting link for
  the user to review instead of silently defaulting to polygon zero.
- An explicit **AreaID `0`** is retained as a genuine CodeWalker cell ID in
  source binding, export, cross-cell processing and neighbour loading. Only
  `16383` is the reserved edge sentinel; the valid AreaID range is 0–16382.

### Load neighbouring source cells

**Load Neighbours** imports nearby existing source XML files from the folder
of the selected cell's bound source XML. It uses CodeWalker's grid conversion:
`AreaID = y * 100 + x` and source names such as
`navmesh[x*3][y*3].ynv.xml`. By default it considers all eight surrounding
cells; the operator can be invoked with diagonals disabled when only the four
cardinal neighbours are desired.

The loader deliberately does not search unrelated folders or guess from a
similar file name. It skips cells already loaded in the scene, absent files,
unreadable files, and candidates whose embedded `AreaID` does not match the
expected grid cell. After loading, use **Rebuild Edges** and **Export All** to
review and write reciprocal shared-border links.

### Generate a navmesh from a selected mesh

**Generate Navmesh From Selected Mesh** builds a new, separate navmesh from
the active regular or collision mesh. In Object Mode it considers every face;
in Edit Mode it considers only selected faces. It triangulates source faces,
uses world-space positions, corrects downward winding, skips degenerate and
too-steep triangles, optionally removes exact duplicate triangles, builds
local links, and provides starting presets for Flat Ground, Footpath, Road or
empty/custom flags.

This is a controlled geometry-conversion helper, not a full automatic GTA
pathfinding generator. It cannot infer portals, obstacle clearance,
non-manifold intent, cell ownership, edge behavior, or final gameplay flags.
Validate every result, resolve open/non-manifold edges, inspect the XML in
CodeWalker, and test in the intended game/mod setup.

## Compatibility and boundaries

- Blender 2.80 or newer is required. The add-on supports Blender 3.x and 4.x.
- Sollumz and CodeWalker remain optional, separately installed tools. When
  Sollumz is present, GTANAVMESH Edit can read and write its standard navmesh,
  point and portal properties.
- The primary format is CodeWalker-compatible **`.ynv.xml`**. GTANAVMESH Edit
  does **not** import native binary `.ynv` files. Native output is optional and
  is produced only by the separately built local `ynv_compiler` after XML
  validation.
- The release ZIP contains GTANAVMESH Edit only; it does not include Sollumz,
  CodeWalker, CodeWalker.Core, GTA V files, or other third-party assets. See
  [third-party notices](THIRD_PARTY_NOTICES.md).

## Release verification scope

Before publishing an asset, verify the exact release ZIP with
`tools/package_blender_addon.py --check`, install it in a clean Blender
profile, and confirm the sidebar tab is available. The v0.12.0 verification
scope includes:

- Python syntax checks and Blender background registration.
- XML import/re-export, source-face deletion, edge/portal/point preservation,
  and optional compiler XML-to-RSC7 `--check` round trip.
- Full 33-bit group coverage, raw-field synchronization, bit painting,
  matching-face selection, and CodeWalker color refresh.
- AreaID `0` preservation, safe point/portal creation and portal-reference
  rows.
- Neighbour filename/AreaID validation and selected-mesh generation with
  slope/duplicate filtering.

These checks establish structural compatibility and binary readability where
the optional compiler is used. They do not prove in-game navigation behavior.

## Upgrade notes

- Reinstall or reload the v0.12.0 ZIP so Blender does not retain an older
  module in memory.
- Open the 3D Viewport sidebar with `N`, choose **GTANAVMESH Edit**, select a
  navmesh mesh, and use **Load Active** before editing polygon metadata.
- Bind the exact original XML with **Load Source** before using **Load
  Neighbours**. The loader needs that real source folder; it intentionally
  refuses broad automatic discovery.
- For generated or topology-edited meshes, rebuild edges, validate, use
  **Export All** for linked cells, and inspect all generated references before
  game testing.

For detailed workflows, read [README.md](README.md),
[the user guide](docs/YNV_NavMesh_Tools_Guide.md), and
[the import/compilation guide](docs/YNV_Import_Source_Compile.md).
