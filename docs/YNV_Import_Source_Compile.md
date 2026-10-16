# GTANAVMESH Edit - Import, Source Binding, and Native Compilation

This document describes the safe workflow for creating or editing GTA V YNV
navmeshes with GTANAVMESH Edit. The Blender addon writes CodeWalker-compatible
`.ynv.xml`; native `.ynv` compilation is deliberately a separate, opt-in
step.

Version: **v0.11.0**
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

If no trustworthy source exists, leave the source field empty. Set a unique
`AreaID` manually, build/rebuild connectivity deliberately, and treat every
portal, point and edge link as data that needs review.

## Import an existing cell

1. In Blender, choose **File > Import > YNV NavMesh XML (.ynv.xml)**, or use
   the **Import YNV XML** panel button.
2. Select the original `.ynv.xml`. The importer creates the navmesh mesh and
   its point/portal hierarchy and attaches that file as `Source XML`.
3. Select the mesh and press **Validate** before changing it. This verifies
   the export model; it does not prove in-game navigation behavior. Leave
   **Strict Validation** disabled for an unmodified Rockstar source with
   legacy warnings; enable it for newly authored geometry and final review.
4. Keep neighbouring cells loaded when changing a boundary. Use **Export All**
   for a multi-cell change so reciprocal cross-cell edges can be checked.

Sollumz-imported navmeshes are supported too. When both addons are enabled,
GTANAVMESH Edit reads the Sollumz navmesh properties as well as its own
stored metadata. If the source was not attached during the Sollumz import,
attach it manually with **Load Source**.

## Create a new cell

1. Decide which world/navmesh cell the mesh belongs to and assign a unique,
   valid `AreaID` first. Do not copy an existing area ID for a production
   replacement.
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
