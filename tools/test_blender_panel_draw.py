"""Regression smoke test for drawing the GTANAVMESH Edit sidebar.

Run with Blender 3.5 or newer in factory startup mode, for example:

    blender --background --factory-startup --python tools/test_blender_panel_draw.py

The test deliberately draws the panel for a tagged mesh which has no stable
YNV metadata yet.  Blender panel draw callbacks are read-only: metadata
migration must wait for an operator or a deferred timer.
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
    module = importlib.util.module_from_spec(spec)
    sys.modules[MODULE_NAME] = module
    spec.loader.exec_module(module)
    module.register()
    return module


class FakeLayout:
    """Record the Blender UILayout calls made by the panel draw path."""

    def __init__(self, record=None):
        self.record = record if record is not None else {"props": [], "operators": [], "icons": []}
        self.enabled = True

    def child(self):
        return type(self)(self.record)

    def box(self):
        return self.child()

    def row(self, **_kwargs):
        return self.child()

    def column(self, **_kwargs):
        return self.child()

    def label(self, **kwargs):
        if "icon" in kwargs:
            self.record["icons"].append(kwargs["icon"])
        return None

    def prop(self, _data, property_name, **kwargs):
        self.record["props"].append(property_name)
        if "icon" in kwargs:
            self.record["icons"].append(kwargs["icon"])
        return None

    def operator(self, operator_id, **kwargs):
        self.record["operators"].append(operator_id)
        if "icon" in kwargs:
            self.record["icons"].append(kwargs["icon"])
        return self.child()

    def separator(self):
        return None


def _metadata_snapshot(addon, navmesh_object):
    mesh = navmesh_object.data

    def attribute_values(attribute_name):
        attribute = mesh.attributes.get(attribute_name)
        if attribute is None:
            return None
        return tuple(getattr(item, "value", repr(item)) for item in attribute.data)

    return {
        "object_properties": tuple(sorted((key, repr(navmesh_object[key])) for key in navmesh_object.keys())),
        "face_ids": attribute_values(addon.YNV_FACE_ID_ATTR),
        "source_indices": attribute_values(addon.YNV_SOURCE_POLYGON_ATTR),
    }


def draw_panel(addon, capture_deferred=False):
    """Draw without running migrations and return the recorded UI surface."""
    layout = FakeLayout()
    panel = type("PanelProxy", (), {"layout": layout})()
    original_settings_sync = addon._schedule_settings_sync
    original_editor_load = addon._schedule_polygon_editor_load
    deferred_loads = []
    addon._schedule_settings_sync = lambda *_args, **_kwargs: None
    if capture_deferred:
        addon._schedule_polygon_editor_load = lambda scene, obj, index: deferred_loads.append((scene.name, obj.name, index))
    else:
        addon._schedule_polygon_editor_load = lambda *_args, **_kwargs: None
    try:
        addon.CWNAVMESH_PT_panel.draw(panel, bpy.context)
    finally:
        addon._schedule_settings_sync = original_settings_sync
        addon._schedule_polygon_editor_load = original_editor_load
    return layout.record, deferred_loads


def assert_no_metadata_was_created(addon, navmesh_object):
    mesh = navmesh_object.data
    assert addon.YNV_NEXT_FACE_ID not in navmesh_object
    assert addon.YNV_POLYGON_METADATA_V2 not in navmesh_object
    assert mesh.attributes.get(addon.YNV_FACE_ID_ATTR) is None
    assert mesh.attributes.get(addon.YNV_SOURCE_POLYGON_ATTR) is None


def assert_subset(values, expected, label):
    missing = sorted(set(expected) - set(values))
    assert not missing, f"{label} missing: {missing}"


def assert_supported_icons(record):
    icon_parameter = bpy.types.UILayout.bl_rna.functions["label"].parameters["icon"]
    supported = {item.identifier for item in icon_parameter.enum_items}
    invalid = sorted(set(record["icons"]) - supported)
    assert not invalid, f"Unsupported Blender UI icon(s): {invalid}"


def main():
    addon = load_addon()
    mesh = bpy.data.meshes.new("Panel Draw Regression Mesh")
    mesh.from_pydata(
        [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)],
        [],
        [(0, 1, 2), (0, 2, 3)],
    )
    navmesh_object = bpy.data.objects.new("Panel Draw Regression Object", mesh)
    bpy.context.scene.collection.objects.link(navmesh_object)
    navmesh_object[addon.YNV_MESH_TAG] = True
    bpy.context.view_layer.objects.active = navmesh_object
    navmesh_object.select_set(True)

    # The old v0.12.1 panel wrote stable IDs at this point and raised the
    # exact "Writing to ID classes in this context is not allowed" exception.
    assert_no_metadata_was_created(addon, navmesh_object)
    before_draw = _metadata_snapshot(addon, navmesh_object)
    quick_record, _ = draw_panel(addon)
    assert_no_metadata_was_created(addon, navmesh_object)
    assert _metadata_snapshot(addon, navmesh_object) == before_draw
    assert_subset(
        quick_record["props"],
        {
            "polygon_index",
            "active_flag_color",
            "apply_flag_bit_to_selected",
            "flag_b02_footpath",
            "flag_b06_steep_slope",
            "flag_b07_water",
            "flag_b14_interior",
            "flag_b17_flat_ground",
            "flag_b18_road",
            "flag_b20_train_track",
            "flag_b21_shallow_water",
            "area_id",
        },
        "quick controls",
    )
    assert_subset(
        quick_record["operators"],
        {
            "cw_navmesh.pick_polygon",
            "cw_navmesh.show_flag_colors",
            "cw_navmesh.load_source_xml",
            "cw_navmesh.validate",
            "cw_navmesh.rebuild_edges_from_geometry",
            "export_scene.ynv_xml",
        },
        "quick actions",
    )
    assert "polygon_edges" not in quick_record["props"]
    assert_supported_icons(quick_record)

    bpy.ops.object.mode_set(mode="EDIT")
    edit_record, _ = draw_panel(addon)
    assert_no_metadata_was_created(addon, navmesh_object)
    assert _metadata_snapshot(addon, navmesh_object) == before_draw
    assert_supported_icons(edit_record)
    bpy.ops.object.mode_set(mode="OBJECT")

    # A timer scheduled from draw is deferred: it must not migrate while the
    # draw is active, but migration is legal after draw returns.
    settings = bpy.context.scene.cw_navmesh_settings
    settings.polygon_index = 1
    before_deferred_draw = _metadata_snapshot(addon, navmesh_object)
    _record, deferred_loads = draw_panel(addon, capture_deferred=True)
    assert deferred_loads == [(bpy.context.scene.name, navmesh_object.name, 0)]
    assert _metadata_snapshot(addon, navmesh_object) == before_deferred_draw
    addon._deferred_load_polygon_editor(*deferred_loads[0])
    assert addon.YNV_NEXT_FACE_ID in navmesh_object
    assert addon.YNV_POLYGON_METADATA_V2 in navmesh_object
    assert mesh.attributes.get(addon.YNV_FACE_ID_ATTR) is not None
    assert mesh.attributes.get(addon.YNV_SOURCE_POLYGON_ATTR) is not None

    # Every compact foldout remains reachable without making it part of the
    # normal editing view.
    settings.ui_show_all_flag_bits = True
    all_flags_record, _ = draw_panel(addon)
    assert_subset(all_flags_record["props"], [entry[0] for entry in addon.POLYGON_FLAG_BITS], "all flag bits")
    settings.ui_show_advanced_face_data = True
    advanced_face_record, _ = draw_panel(addon)
    assert_subset(
        advanced_face_record["props"],
        {"polygon_flags", "polygon_flags_1", "polygon_flags_2", "polygon_flags_3", "polygon_flags_4", "polygon_unk_x", "polygon_unk_y", "polygon_flags_5"},
        "advanced face data",
    )
    settings.ui_show_edges_portals = True
    edges_record, _ = draw_panel(addon)
    assert_subset(
        edges_record["props"],
        {"polygon_edges", "polygon_edges_flags", "polygon_portals", "edge_flag_index", "edge_poly1_unk2", "edge_poly1_unk3", "edge_poly2_unk2", "edge_poly2_unk3"},
        "edge and portal controls",
    )
    settings.ui_show_navmesh_setup = True
    settings.ui_show_neighbour_tools = True
    settings.ui_show_compiler = True
    expanded_record, _ = draw_panel(addon)
    assert_subset(
        expanded_record["operators"],
        {
            "cw_navmesh.use_selected",
            "cw_navmesh.generate_from_selected_mesh",
            "cw_navmesh.import_xml",
            "cw_navmesh.create_navmesh",
            "cw_navmesh.load_neighbour_cells",
            "cw_navmesh.fix_sources",
            "cw_navmesh.build_edges",
            "cw_navmesh.export_all_ynv_xml",
            "cw_navmesh.add_point",
            "cw_navmesh.add_portal",
            "cw_navmesh.compile_ynv",
        },
        "advanced actions",
    )
    assert_supported_icons(expanded_record)

    before_normalized_draw = _metadata_snapshot(addon, navmesh_object)
    draw_panel(addon)
    assert _metadata_snapshot(addon, navmesh_object) == before_normalized_draw
    print("PANEL DRAW REGRESSION SMOKE PASS")


if __name__ == "__main__":
    main()
