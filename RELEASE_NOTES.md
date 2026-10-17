# GTANAVMESH Edit v0.12.1

Release date: 2026-10-18
Copyright © 2026 devsanja

> Unofficial community tool. GTANAVMESH Edit is not affiliated with, endorsed
> by, or associated with Rockstar Games or Take-Two Interactive.

## Release asset

Install **`GTANAVMESH-Edit-v0.12.1.zip`** through Blender's
**Edit > Preferences > Add-ons > Install...** command, then enable
**GTANAVMESH Edit**. Do not unpack the ZIP before installing it.

## What this patch fixes

### Flag editor is immediately visible

The full **Polygon Flags & Colors** editor now appears at the top of the
GTANAVMESH Edit sidebar, before cell setup, import, export and compiler
controls. This fixes the former long-panel layout where the flag editor,
**Show Flag Colors**, **Refresh Colors** and all 33 bit controls were below
the first visible screen area.

The top editor contains:

- `Load Active` and `Apply` for the active polygon.
- **Show Flag Colors** and **Refresh Colors**.
- A live active-face CodeWalker colour swatch.
- All 33 editable native GTA bits, raw flag bytes and `Flags5 (B16)`.
- Bit painting, full-flag copy/paste and matching-face selection.
- Edge and portal data for the same active polygon.

### Exact CodeWalker colour key

The panel now documents every bit that has a visible contribution in
CodeWalker's additive material calculation: B00/B01, B02, B03, B06, B07,
B14, B17, B18, B20, B21, B22, B23 and B24. Hovering a named checkbox also
shows its exact colour contribution.

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

## Existing v0.12.0 features retained

- Direct CodeWalker-compatible `.ynv.xml` import/export and optional native
  compiler workflow.
- ContentFlags editing, all 33 named polygon bits, raw byte fields and packed
  `EdgesFlags` editing.
- Safe points/portals, AreaID `0` support, source metadata preservation,
  neighbour-cell loading and cross-cell edge rebuilding.
- Generation of a reviewable starter navmesh from selected mesh geometry.

## Verification

The v0.12.1 ZIP was syntax-checked, archive-checked and installed/enabled in
an isolated Blender 3.5 profile. The colour workflow was also checked for
direct imports, `Load Source` metadata binding, material-slot deduplication,
the active-face swatch and CodeWalker colour values.

These checks establish structural compatibility and material-preview behavior.
They do not prove in-game navigation behavior; inspect exports in CodeWalker
and test them in the intended game/mod setup.
