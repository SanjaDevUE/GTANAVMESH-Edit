"""Edit a real YNV XML copy in Blender and verify the exported result.

Run in Blender factory startup mode with two arguments after ``--``:

    blender --background --factory-startup --python tools/test_real_nav_end_to_end.py -- \
        C:\\path\\to\\navmesh[117][120].ynv.xml C:\\safe\\output\\directory

The source file is read-only.  The test intentionally performs a representative
edit on an output copy: one real road polygon becomes shallow water, a second
road polygon is deleted, edge links are rebuilt, and the result is exported.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import bpy


ROOT = Path(__file__).resolve().parents[1]
ADDON_ROOT = ROOT / "ynv_blender_addon"
MODULE_NAME = "ynv_blender_addon"


def load_addon():
    spec = importlib.util.spec_from_file_location(
        MODULE_NAME,
        ADDON_ROOT / "__init__.py",
        submodule_search_locations=[str(ADDON_ROOT)],
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load the GTANAVMESH Edit source package.")
    addon = importlib.util.module_from_spec(spec)
    sys.modules[MODULE_NAME] = addon
    spec.loader.exec_module(addon)
    addon.register()
    return addon


def arguments_after_double_dash():
    try:
        return sys.argv[sys.argv.index("--") + 1 :]
    except ValueError:
        return []


def polygon_key(polygon):
    return tuple(sorted((round(vertex.x, 4), round(vertex.y, 4), round(vertex.z, 4)) for vertex in polygon.vertices))


def main():
    arguments = arguments_after_double_dash()
    if len(arguments) != 2:
        raise RuntimeError("Expected source YNV XML path and output directory after --.")
    source_path = Path(arguments[0]).resolve()
    output_directory = Path(arguments[1]).resolve()
    if not source_path.is_file():
        raise RuntimeError(f"Source XML not found: {source_path}")
    output_directory.mkdir(parents=True, exist_ok=True)
    output_path = output_directory / f"{source_path.stem}.edited.ynv.xml"
    if output_path.resolve() == source_path:
        raise RuntimeError("Refusing to overwrite the source XML.")

    addon = load_addon()
    source = addon.read_navmesh_xml(source_path)
    source_count = len(source.polygons)
    road_indices = [index for index, polygon in enumerate(source.polygons) if addon._flag_enabled(polygon.flags, 18)]
    if len(road_indices) < 2:
        raise RuntimeError("The selected source needs at least two road polygons for this end-to-end test.")
    edited_source_index, deleted_source_index = road_indices[:2]
    deleted_source_key = polygon_key(source.polygons[deleted_source_index])

    mesh_obj = addon.import_navmesh_xml(str(source_path))
    polygon_flags, _edges, _edge_flags, _portals = addon._read_polygon_metadata(mesh_obj)
    edited_flags = list(polygon_flags[edited_source_index])
    for bit, enabled in ((18, False), (17, False), (7, True), (21, True)):
        edited_flags = addon._set_flag_enabled(edited_flags, bit, enabled)
    original_edited_flag_count = sum(1 for polygon in source.polygons if list(polygon.flags) == edited_flags)
    addon._set_polygon_flags(mesh_obj, [edited_source_index], edited_flags)
    assert addon._flag_enabled(edited_flags, 7)
    assert addon._flag_enabled(edited_flags, 21)
    assert not addon._flag_enabled(edited_flags, 17)
    assert not addon._flag_enabled(edited_flags, 18)

    bpy.context.view_layer.objects.active = mesh_obj
    bpy.ops.object.mode_set(mode="EDIT")
    import bmesh

    edit_mesh = bmesh.from_edit_mesh(mesh_obj.data)
    edit_mesh.faces.ensure_lookup_table()
    bmesh.ops.delete(edit_mesh, geom=[edit_mesh.faces[deleted_source_index]], context="FACES")
    bmesh.update_edit_mesh(mesh_obj.data, loop_triangles=False, destructive=True)
    bpy.ops.object.mode_set(mode="OBJECT")
    assert len(mesh_obj.data.polygons) == source_count - 1

    post_delete_flags, _edges, _edge_flags, _portals = addon._read_polygon_metadata(mesh_obj)
    _face_ids, post_delete_source_indices = addon._current_face_identity(mesh_obj)
    assert edited_source_index in post_delete_source_indices
    edited_live_index = post_delete_source_indices.index(edited_source_index)
    assert post_delete_flags[edited_live_index] == edited_flags

    edge_result = addon._rebuild_edge_links_from_geometry(mesh_obj, source.area_id)
    addon._refresh_flag_materials(mesh_obj)
    export_warnings = addon.export_navmesh_xml(mesh_obj, str(output_path))

    exported = addon.read_navmesh_xml(output_path)
    assert len(exported.polygons) == source_count - 1
    assert exported.area_id == source.area_id
    assert polygon_key(source.polygons[deleted_source_index]) not in {polygon_key(polygon) for polygon in exported.polygons}
    # The export can reorder faces after a topology edit.  Verify the changed
    # raw flag tuple by count, then its individual named bits, rather than
    # assuming a face-index or vertex-order convention in the XML serializer.
    exported_edited = [polygon for polygon in exported.polygons if list(polygon.flags) == edited_flags]
    assert len(exported_edited) == original_edited_flag_count + 1
    assert all(addon._flag_enabled(polygon.flags, 7) for polygon in exported_edited)
    assert all(addon._flag_enabled(polygon.flags, 21) for polygon in exported_edited)
    assert all(not addon._flag_enabled(polygon.flags, 17) for polygon in exported_edited)
    assert all(not addon._flag_enabled(polygon.flags, 18) for polygon in exported_edited)
    validation_warnings = addon.validate_navmesh_for_codewalker(exported)

    print("REAL NAV END-TO-END PASS")
    print(f"Source: {source_path}")
    print(f"Output: {output_path}")
    print(f"AreaID: {exported.area_id}")
    print(f"Polygons: {source_count} -> {len(exported.polygons)}")
    print(f"Edited source polygon: {edited_source_index} (Road -> Water + ShallowWater)")
    print(f"Deleted source polygon: {deleted_source_index}")
    print(f"Edge rebuild: {edge_result}")
    print(f"Export warnings: {len(export_warnings)}")
    print(f"Validation warnings: {len(validation_warnings)}")


if __name__ == "__main__":
    main()
