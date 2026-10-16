# Third-Party Notices

Copyright © 2026 devsanja

GTANAVMESH Edit is an unofficial community tool. It is not affiliated with,
endorsed by, or associated with Rockstar Games or Take-Two Interactive.

The names GTA V, Rockstar Games, Take-Two Interactive, Sollumz and CodeWalker
are used only to describe file compatibility and optional interoperability.

## Release-asset contents

The release asset `GTANAVMESH-Edit-v0.11.0.zip` packages GTANAVMESH Edit only.
It does not package:

- GTA V game files, archives, models, textures or other game assets;
- Sollumz, its source tree or its assets;
- CodeWalker or CodeWalker.Core, their source trees, binaries or assets.

## Optional external components

- **Sollumz** is optional. GTANAVMESH Edit can read and write its supported
  navmesh property groups when it is installed independently in Blender.
- **CodeWalker** is optional. It is useful for XML inspection and the final
  target workflow.
- **CodeWalker.Core** is required only when building the optional
  `ynv_compiler` from source. Provide a compatible local project through the
  `CodeWalkerCoreProject` MSBuild property when it is not at the compiler
  project's default sibling path.

Obtain optional components separately from their respective upstream projects.
