# Changelog

All notable changes to GTANAVMESH Edit are documented in this file.

## [0.11.1] - 2026-10-16

### Added

- Visible `ContentFlags` controls for `Polygons`, `Portals`, `Vehicle`,
  `Unknown8` and `Unknown16`, synchronized with the raw XML-style value.
- Structured active-polygon fields for `Flags1`–`Flags4`, `UnkX`, `UnkY` and
  `Flags5 (B16)`, plus named editable GTA navmesh bit controls.
- A selected-edge `EdgesFlags` editor for the packed `Poly1 Unk2`,
  `Poly1 Unk3`, `Poly2 Unk2` and `Poly2 Unk3` components.

### Changed

- The sidebar now presents cell, polygon and edge metadata as directly
  editable structured controls while retaining the raw values for exact
  review and advanced use.

### Fixed

- Explicit `AreaID` and `ContentFlags` edits now take precedence over a bound
  source XML during export, including AreaID `0` and intentionally empty
  content flags.
- `Flags5` is constrained to its native single B16 bit instead of silently
  truncating higher values during compilation.
- The deterministic release packager writes and verifies an explicit
  `ynv_blender_addon/` ZIP directory entry so Blender reliably discovers and
  replaces the add-on package during installation.

## [0.11.0] - 2026-10-16

### Added

- Direct `.ynv.xml` import through Blender's File menu and the GTANAVMESH Edit
  panel.
- Safe source lookup controls: explicit source-search folder and opt-in auto
  discovery that does not replace a manually selected source.
- Stable face IDs, source-face mapping and portal reference mapping for
  resilient face reordering and deletion.
- Cross-cell edge reconciliation that writes reciprocal links for loaded
  neighbour cells.
- CodeWalker-oriented validation for packed fields, bounds, edge rows,
  portal references and the 32 adjacent-AreaID limit.
- Optional `ynv_compiler` native RSC7 compilation with post-build `--check`.

### Changed

- Rebranded the Blender add-on as **GTANAVMESH Edit**.
- Existing source bounds, `EdgesFlags`, portals and matching polygon metadata
  remain authoritative when live Blender geometry has not invalidated them.
- Export uses only current Blender faces; removed source faces are no longer
  restored by metadata recovery.
- Strict validation is opt-in so unmodified source XML files with known legacy
  warnings can still be examined and exported.

### Verified

- Blender 4.1 registration, direct import/export, face deletion, cross-cell
  links, compiler release build and RSC7 binary readback.

Copyright © 2026 devsanja
