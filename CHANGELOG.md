# Changelog

All notable changes to GTANAVMESH Edit are documented in this file.

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
