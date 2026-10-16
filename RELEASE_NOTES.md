# GTANAVMESH Edit v0.11.1

Release date: 2026-10-16
Copyright © 2026 devsanja

> Unofficial community tool. GTANAVMESH Edit is not affiliated with, endorsed
> by, or associated with Rockstar Games or Take-Two Interactive.

## Release asset

Install **`GTANAVMESH-Edit-v0.11.1.zip`** from the release page through
Blender's **Edit > Preferences > Add-ons > Install...** command, then enable
**GTANAVMESH Edit**.

## What is new

v0.11.1 makes GTA navmesh metadata directly editable from the visible
**GTANAVMESH Edit** sidebar while retaining the safer existing-cell workflow:

- `ContentFlags` now has individual **Polygons**, **Portals**, **Vehicle**,
  **Unknown8** and **Unknown16** controls. These synchronize with the raw
  comma-separated value and preserve unrecognised tokens from a source cell.
- The active-polygon editor exposes numeric `Flags1`, `Flags2`, `Flags3`,
  `Flags4`, `UnkX`, `UnkY` and `Flags5 (B16)` fields. The first six fields are
  byte values; `Flags5 (B16)` is constrained to 0 or 1.
- Named bit controls let you edit familiar flags such as **Footpath**,
  **Road**, **CellEdge**, **FlatGround**, **Water**, **TrainTrack**,
  **ShallowWater**, **Interior** and the slope-direction bits without
  calculating packed values by hand. Unknown-labelled controls remain raw
  data: preserve them unless the intended target requires a change.
- The selected-edge editor exposes the packed `EdgesFlags` values as
  `Poly1 Unk2`, `Poly1 Unk3`, `Poly2 Unk2` and `Poly2 Unk3`. The `Unk2`
  fields accept 0–3 and the `Unk3` fields accept 0–2047; the corresponding
  XML row is kept in `a:b, c:d` form.
- Explicit `AreaID` and `ContentFlags` edits now win over a bound source XML
  during export, including AreaID `0` and intentionally empty ContentFlags.
- `Flags5 (B16)` is validated as its native 0-or-1 value, preventing a value
  from being silently truncated by the native compiler.
- The release ZIP now includes the explicit add-on package directory entry
  required for reliable Blender upgrades.

- Imported metadata is attached to stable face identities rather than only to
  Blender's changing polygon indexes.
- Deleting a face exports one fewer live polygon. The exporter never inserts
  the deleted source polygon simply to preserve old metadata.
- Existing bounds, edge flags, portal references, points and matching polygon
  properties are retained where they remain applicable.
- Loaded neighbouring cells can receive reciprocal border-edge links through
  **Rebuild Edges** and **Export All**.
- Source-file recovery is deliberately narrow and opt-in, preventing an
  automatic guess from replacing a user-selected source cell.
- The validator supports a compatibility mode for legacy source XML and a
  strict mode for authored/final-review geometry.
- The optional local compiler creates a native RSC7 `.ynv` only after input
  validation and verifies its own output before replacement.

## Compatibility and prerequisites

- Blender 2.80 or newer is required; v0.11.1 was checked in Blender 3.5 and
  Blender 4.1.
- Sollumz is optional and is installed separately. When available, its
  navmesh properties are read and written directly.
- CodeWalker is optional and is obtained separately; it is recommended for
  inspecting exported XML and the final target workflow.
- Build the optional Windows compiler with the .NET 8 SDK and a compatible
  local CodeWalker.Core project if a native `.ynv` output is needed.

The release asset contains GTANAVMESH Edit only. It does not package Sollumz,
CodeWalker, CodeWalker.Core, GTA V files or other third-party assets. See
[third-party notices](THIRD_PARTY_NOTICES.md).

## Verification performed

The release candidate passed add-on syntax checks, Blender background
registration, direct import/re-export of a 2,534-polygon source cell,
face-deletion export (2,533 polygons), reciprocal cross-cell edge-link checks,
cell/polygon/edge editor synchronization, validator limit checks, .NET release
compilation and native RSC7 `--check` readback.

This verification covers export structure and binary readability. Review each
changed cell in CodeWalker and test it in the intended game/mod setup before
distributing a replacement.

## Upgrade notes

- Reinstall or reload the new ZIP in Blender after upgrading.
- Open the 3D Viewport sidebar with `N` and choose **GTANAVMESH Edit**. Select
  a navmesh mesh, then use **Load Active** before editing a polygon; the
  structured fields mirror the raw values instead of replacing them.
- Rebind the exact original `.ynv.xml` with **Load Source** if an older blend
  lacks an attached source path.
- For geometry changes, load all affected neighbours, use **Rebuild Edges**,
  then use **Export All** and inspect the resulting boundary links.
- Keep the original XML and generated XML outside each other's output paths.

For the full workflow, read [README.md](README.md) and
[the import/compilation guide](docs/YNV_Import_Source_Compile.md).
