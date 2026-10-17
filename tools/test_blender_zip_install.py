"""Install the release ZIP in an isolated Blender profile and smoke-test it.

Run with Blender 3.5+ and fresh ``BLENDER_USER_*`` directories, for example::

    blender --background --factory-startup --python-exit-code 1 \
        --python tools/test_blender_zip_install.py -- dist/GTANAVMESH-Edit-v0.12.2.zip

The script deliberately removes the repository from ``sys.path`` before
enabling the add-on. That prevents a local checkout from making an installed
ZIP appear healthy by accident.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import bpy


EXPECTED_VERSION = (0, 12, 2)
MODULE_NAME = "ynv_blender_addon"
ROOT = Path(__file__).resolve().parents[1]


class FakeLayout:
    """Small UILayout substitute sufficient for the panel draw regression."""

    def __init__(self):
        self.enabled = True

    def _child(self):
        return type(self)()

    def box(self):
        return self._child()

    def row(self, **_kwargs):
        return self._child()

    def column(self, **_kwargs):
        return self._child()

    def label(self, **_kwargs):
        return None

    def prop(self, _data, _property_name, **_kwargs):
        return None

    def operator(self, _operator_id, **_kwargs):
        return self._child()

    def separator(self):
        return None


def _expect_argument() -> Path:
    try:
        separator = sys.argv.index("--")
        argument = sys.argv[separator + 1]
    except (ValueError, IndexError) as exc:
        raise RuntimeError("Pass the release ZIP after '--'.") from exc
    archive = Path(argument).resolve()
    if not archive.is_file():
        raise RuntimeError(f"Release ZIP does not exist: {archive}")
    return archive


def _remove_checkout_from_import_path(isolation_root: Path) -> None:
    """Ensure the following import can only resolve the installed ZIP payload."""

    os.chdir(isolation_root)
    root_text = str(ROOT.resolve()).casefold()
    sys.path[:] = [
        entry
        for entry in sys.path
        if entry
        and str(Path(entry).resolve()).casefold() != root_text
    ]
    sys.modules.pop(MODULE_NAME, None)


def _assert_under(path: Path, root: Path, label: str) -> None:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise AssertionError(f"{label} is not under the isolated add-on folder: {path}") from exc


def _draw_installed_panel(addon) -> None:
    mesh = bpy.data.meshes.new("ZIP install panel mesh")
    mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
    navmesh = bpy.data.objects.new("ZIP install panel navmesh", mesh)
    bpy.context.scene.collection.objects.link(navmesh)
    navmesh[addon.YNV_MESH_TAG] = True
    bpy.context.view_layer.objects.active = navmesh
    navmesh.select_set(True)

    assert addon.YNV_NEXT_FACE_ID not in navmesh
    original_settings_sync = addon._schedule_settings_sync
    original_editor_load = addon._schedule_polygon_editor_load
    addon._schedule_settings_sync = lambda *_args, **_kwargs: None
    addon._schedule_polygon_editor_load = lambda *_args, **_kwargs: None
    try:
        panel = type("PanelProxy", (), {"layout": FakeLayout()})()
        addon.CWNAVMESH_PT_panel.draw(panel, bpy.context)
    finally:
        addon._schedule_settings_sync = original_settings_sync
        addon._schedule_polygon_editor_load = original_editor_load

    assert addon.YNV_NEXT_FACE_ID not in navmesh
    assert mesh.attributes.get(addon.YNV_FACE_ID_ATTR) is None
    assert mesh.attributes.get(addon.YNV_SOURCE_POLYGON_ATTR) is None


def main() -> None:
    archive = _expect_argument()
    scripts_root_text = os.environ.get("BLENDER_USER_SCRIPTS")
    if not scripts_root_text:
        raise RuntimeError("BLENDER_USER_SCRIPTS must point at an isolated test directory.")
    scripts_root = Path(scripts_root_text).resolve()
    scripts_root.mkdir(parents=True, exist_ok=True)
    isolation_root = scripts_root.parent

    _remove_checkout_from_import_path(isolation_root)
    result = bpy.ops.preferences.addon_install(filepath=str(archive), overwrite=True, target="DEFAULT")
    if "FINISHED" not in result:
        raise RuntimeError(f"Blender could not install the release ZIP: {result}")

    installed_package = scripts_root / "addons" / MODULE_NAME
    installed_init = installed_package / "__init__.py"
    if not installed_init.is_file():
        raise AssertionError(f"Blender did not install the expected module: {installed_init}")

    result = bpy.ops.preferences.addon_enable(module=MODULE_NAME)
    if "FINISHED" not in result:
        raise RuntimeError(f"Blender could not enable the installed add-on: {result}")

    addon = __import__(MODULE_NAME)
    _assert_under(Path(addon.__file__), installed_package, "Loaded add-on module")
    assert tuple(addon.bl_info["version"]) == EXPECTED_VERSION
    assert bpy.context.preferences.addons.get(MODULE_NAME) is not None
    assert hasattr(bpy.types.Scene, "cw_navmesh_settings")
    assert hasattr(addon, "CWNAVMESH_PT_panel")
    _draw_installed_panel(addon)
    print("ZIP INSTALL + PANEL SMOKE PASS")


if __name__ == "__main__":
    main()
