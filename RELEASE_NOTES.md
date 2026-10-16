# GTANAVMESH Edit v0.11.0

Release date: 2026-10-16
Copyright © 2026 devsanja

> Unofficial community tool. GTANAVMESH Edit is not affiliated with, endorsed
> by, or associated with Rockstar Games or Take-Two Interactive.

## Release asset

Install **`GTANAVMESH-Edit-v0.11.0.zip`** from the release page through
Blender's **Edit > Preferences > Add-ons > Install...** command, then enable
**GTANAVMESH Edit**.

## What is new

v0.11.0 makes the add-on suitable for a safer existing-cell editing workflow:

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

- Blender 2.80 or newer is required; v0.11.0 was checked in Blender 4.1.
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
validator limit checks, .NET release compilation and native RSC7 `--check`
readback.

This verification covers export structure and binary readability. Review each
changed cell in CodeWalker and test it in the intended game/mod setup before
distributing a replacement.

## Upgrade notes

- Reinstall or reload the new ZIP in Blender after upgrading.
- Rebind the exact original `.ynv.xml` with **Load Source** if an older blend
  lacks an attached source path.
- For geometry changes, load all affected neighbours, use **Rebuild Edges**,
  then use **Export All** and inspect the resulting boundary links.
- Keep the original XML and generated XML outside each other's output paths.

For the full workflow, read [README.md](README.md) and
[the import/compilation guide](docs/YNV_Import_Source_Compile.md).
