# Copyright (c) 2026 devsanja

bl_info = {
    "name": "GTANAVMESH Edit",
    "author": "devsanja",
    "version": (0, 11, 0),
    "blender": (2, 80, 0),
    "location": "File > Import/Export; View3D > Sidebar > GTANAVMESH Edit",
    "description": "GTANAVMESH Edit imports, edits and exports GTA V YNV navmesh XML with CodeWalker validation.",
    "category": "Import-Export",
}

import json
import math
import re
import subprocess
from pathlib import Path

import bpy
from bpy.app.handlers import persistent
from bpy_extras.io_utils import ExportHelper, ImportHelper

from .ynv_format import (
    NavMesh,
    NavMeshValidationError,
    Point,
    Polygon,
    Portal,
    Vec3,
    read_navmesh_xml,
    validate_navmesh_for_codewalker,
    write_navmesh_xml,
)


YNV_COLLECTION_TAG = "ynv_collection"
YNV_MESH_TAG = "ynv_mesh"
YNV_POINT_TAG = "ynv_point"
YNV_PORTAL_TAG = "ynv_portal"
DEFAULT_EDGE = "16383:16383, 16383:16383"
EDGE_REF_PATTERN = re.compile(r"(\d+)\s*:\s*(\d+)")
EDGE_MATCH_PRECISION = 3
SOLLUMZ_NAVMESH_POLY_MESH = "sollumz_navmesh_mesh"
SOLLUMZ_NAVMESH_PORTAL = "sollumz_navmesh_portal"
SOLLUMZ_NAVMESH_POINT = "sollumz_navmesh_point"
DEFAULT_CONTENT_FLAGS = "Polygons, Portals"
DEFAULT_EDGE_FLAGS = "0:0, 0:0"
# Polygon metadata used to live only in four arrays indexed by Blender's
# transient polygon index.  That corrupts an export as soon as faces are
# reordered.  Keep the legacy arrays for backwards-compatible .blend files,
# but make a stable face id (a FACE attribute when Blender provides one) the
# authoritative key from v2 onwards.
YNV_FACE_ID_ATTR = "ynv_face_id"
YNV_SOURCE_POLYGON_ATTR = "ynv_source_polygon_index"
YNV_POLYGON_METADATA_V2 = "ynv_polygon_metadata_v2_json"
YNV_NEXT_FACE_ID = "ynv_next_face_id"
YNV_METADATA_VERSION = "ynv_polygon_metadata_version"
YNV_REFERENCE_FACE_IDS = "ynv_edge_reference_face_ids_json"
YNV_PORTAL_REFERENCE_FACE_IDS = "ynv_portal_reference_face_ids_json"
NO_SOURCE_POLYGON = -1
_PENDING_POLYGON_EDITOR_LOADS = set()
_PENDING_SETTINGS_SYNCS = set()
_SYNCING_FLAG_CHECKBOXES = False
_SOLLUMZ_IMPORT_PATCHED = False
_SOLLUMZ_OPERATOR_PATCHED = False
POLYGON_FLAG_BITS = (
    ("flag_b00_avoid_unk", "B00 AvoidUnk", 0),
    ("flag_b01_avoid_unk", "B01 AvoidUnk", 1),
    ("flag_b02_footpath", "B02 Footpath", 2),
    ("flag_b03_underground", "B03 Underground", 3),
    ("flag_b04_unused", "B04 Unused", 4),
    ("flag_b05_unused", "B05 Unused", 5),
    ("flag_b06_steep_slope", "B06 SteepSlope", 6),
    ("flag_b07_water", "B07 Water", 7),
    ("flag_b08_underground_unk0", "B08 UndergroundUnk0", 8),
    ("flag_b09_underground_unk1", "B09 UndergroundUnk1", 9),
    ("flag_b10_underground_unk2", "B10 UndergroundUnk2", 10),
    ("flag_b11_underground", "B11 Underground", 11),
    ("flag_b12_unused", "B12 Unused", 12),
    ("flag_b13_path_node", "B13 PathNode", 13),
    ("flag_b14_interior", "B14 Interior", 14),
    ("flag_b15_interaction", "B15 InteractionUnk", 15),
    ("flag_b16_unused", "B16 Unused", 16),
    ("flag_b17_flat_ground", "B17 FlatGround", 17),
    ("flag_b18_road", "B18 Road", 18),
    ("flag_b19_cell_edge", "B19 CellEdge", 19),
    ("flag_b20_train_track", "B20 TrainTrack", 20),
    ("flag_b21_shallow_water", "B21 ShallowWater", 21),
    ("flag_b22_footpath_unk1", "B22 FootpathUnk1", 22),
    ("flag_b23_footpath_unk2", "B23 FootpathUnk2", 23),
    ("flag_b24_footpath_mall", "B24 FootpathMall", 24),
    ("flag_b25_slope_south", "B25 SlopeSouth", 25),
    ("flag_b26_slope_south_east", "B26 SlopeSouthEast", 26),
    ("flag_b27_slope_east", "B27 SlopeEast", 27),
    ("flag_b28_slope_north_east", "B28 SlopeNorthEast", 28),
    ("flag_b29_slope_north", "B29 SlopeNorth", 29),
    ("flag_b30_slope_north_west", "B30 SlopeNorthWest", 30),
    ("flag_b31_slope_west", "B31 SlopeWest", 31),
    ("flag_b32_slope_south_west", "B32 SlopeSouthWest", 32),
)


def _safe_json_loads(value, fallback):
    if not value:
        return fallback
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return fallback


def _get_int_prop(obj, key, default=0):
    if not obj:
        return default
    try:
        return int(obj.get(key, default))
    except (TypeError, ValueError):
        return default


def _navmesh_root_for_props(mesh_obj):
    if not mesh_obj:
        return None
    if mesh_obj.parent:
        return mesh_obj.parent
    return mesh_obj


def _get_sollumz_navmesh_area_id(mesh_obj, default=0):
    root = _navmesh_root_for_props(mesh_obj)
    props = getattr(root, "sz_navmesh", None)
    if not props:
        return default
    try:
        return int(props.area_id)
    except (TypeError, ValueError):
        return default


def _get_sollumz_navmesh_content_flags(mesh_obj, default=""):
    root = _navmesh_root_for_props(mesh_obj)
    props = getattr(root, "sz_navmesh", None)
    if not props:
        return default
    value = str(getattr(props, "content_flags", "") or "").strip()
    return value or default


def _get_rna_property(props, name, default=None):
    """Return an optional Sollumz RNA property without assuming Sollumz is installed."""
    if props is None:
        return default
    try:
        value = getattr(props, name)
    except (AttributeError, TypeError, ValueError):
        return default
    return default if value is None else value


def _set_rna_property(props, name, value):
    """Best-effort write for optional Sollumz RNA property groups."""
    if props is None:
        return False
    try:
        setattr(props, name, value)
    except (AttributeError, TypeError, ValueError):
        return False
    return True


def _custom_property_value(obj, key):
    try:
        if key in obj:
            return obj.get(key)
    except (AttributeError, TypeError):
        pass
    return None


def _object_uses_legacy_ynv_properties(obj):
    """Old add-on objects stored portal data only as ID properties.

    Keep those values authoritative for one migration pass; native Sollumz objects
    never have this marker and therefore use their RNA property groups directly.
    """
    try:
        return bool(obj.get(YNV_PORTAL_TAG) or obj.get(YNV_POINT_TAG)) and not bool(
            obj.get("ynv_sollumz_properties_v1", False)
        )
    except (AttributeError, TypeError):
        return False


def _read_portal_property(obj, rna_name, custom_name, default):
    props = getattr(obj, "sz_nav_portal", None)
    custom_value = _custom_property_value(obj, custom_name)
    rna_value = _get_rna_property(props, rna_name)
    if _object_uses_legacy_ynv_properties(obj) and custom_value is not None:
        return custom_value
    if rna_value is not None:
        return rna_value
    if custom_value is not None:
        return custom_value
    return default


def _read_point_type(obj, default):
    props = getattr(obj, "sz_nav_point", None)
    custom_value = _custom_property_value(obj, "ynv_type")
    rna_value = _get_rna_property(props, "point_type")
    if _object_uses_legacy_ynv_properties(obj) and custom_value is not None:
        return custom_value
    if rna_value is not None:
        return rna_value
    if custom_value is not None:
        return custom_value
    return default


def _as_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _as_float(value, default):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return float(default)
    return value if math.isfinite(value) else float(default)


def _world_z_angle(obj, default=0.0):
    try:
        return float(obj.matrix_world.to_euler()[2])
    except (AttributeError, TypeError, ValueError):
        return _as_float(default, 0.0)


def _write_sollumz_portal_properties(obj, portal):
    """Mirror CW metadata into Sollumz's standard portal property group."""
    obj["ynv_type"] = int(portal.type)
    obj["ynv_angle"] = float(portal.angle)
    obj["ynv_poly_from"] = int(portal.poly_from)
    obj["ynv_poly_to"] = int(portal.poly_to)
    props = getattr(obj, "sz_nav_portal", None)
    _set_rna_property(props, "portal_type", int(portal.type))
    _set_rna_property(props, "angle", float(portal.angle))
    _set_rna_property(props, "poly_from", int(portal.poly_from))
    _set_rna_property(props, "poly_to", int(portal.poly_to))
    obj["ynv_sollumz_properties_v1"] = True


def _write_sollumz_point_properties(obj, point):
    """Mirror CW metadata into Sollumz's standard point property group."""
    obj["ynv_type"] = int(point.type)
    obj["ynv_angle"] = float(point.angle)
    props = getattr(obj, "sz_nav_point", None)
    _set_rna_property(props, "point_type", int(point.type))
    obj["ynv_sollumz_properties_v1"] = True


def _vec_from_id_property(value):
    try:
        if len(value) != 3:
            return None
        vector = Vec3(float(value[0]), float(value[1]), float(value[2]))
    except (TypeError, ValueError, IndexError):
        return None
    if not all(math.isfinite(component) for component in (vector.x, vector.y, vector.z)):
        return None
    return vector


def _store_bounds_on_owner(owner, bb_min, bb_max, bb_size, source=False):
    if not owner:
        return
    prefix = "ynv_source_" if source else "ynv_"
    owner[prefix + "bb_min"] = _json_vec(bb_min)
    owner[prefix + "bb_max"] = _json_vec(bb_max)
    owner[prefix + "bb_size"] = _json_vec(bb_size)


def _store_navmesh_bounds(mesh_obj, bb_min, bb_max, bb_size, source=False):
    owners = [mesh_obj]
    if mesh_obj and mesh_obj.parent:
        owners.append(mesh_obj.parent)
    for owner in owners:
        _store_bounds_on_owner(owner, bb_min, bb_max, bb_size, source=source)

    root = _navmesh_root_for_props(mesh_obj)
    props = getattr(root, "sz_navmesh", None)
    _set_rna_property(props, "bb_min", _vec_to_tuple(bb_min))
    _set_rna_property(props, "bb_max", _vec_to_tuple(bb_max))


def _store_source_navmesh_snapshot(mesh_obj, navmesh):
    """Retain exact source-only data that Blender/Sollumz does not model itself."""
    _store_navmesh_bounds(mesh_obj, navmesh.bb_min, navmesh.bb_max, navmesh.bb_size, source=True)
    owners = [mesh_obj]
    if mesh_obj and mesh_obj.parent:
        owners.append(mesh_obj.parent)
    edge_flags = json.dumps([polygon.edges_flags for polygon in navmesh.polygons], separators=(",", ":"))
    portal_links = json.dumps([getattr(polygon, "portals", []) for polygon in navmesh.polygons], separators=(",", ":"))
    for owner in owners:
        owner["ynv_source_polygon_edges_flags_json"] = edge_flags
        owner["ynv_source_polygon_portals_json"] = portal_links


def _bounds_from_owner(owner, prefix):
    if not owner:
        return None
    bb_min = _vec_from_id_property(_custom_property_value(owner, prefix + "bb_min"))
    bb_max = _vec_from_id_property(_custom_property_value(owner, prefix + "bb_max"))
    bb_size = _vec_from_id_property(_custom_property_value(owner, prefix + "bb_size"))
    if not bb_min or not bb_max or not bb_size:
        return None
    if any(minimum > maximum for minimum, maximum in zip(_vec_to_tuple(bb_min), _vec_to_tuple(bb_max))):
        return None
    if any(value < 0 for value in _vec_to_tuple(bb_size)):
        return None
    return bb_min, bb_max, bb_size


def _bounds_from_sollumz(mesh_obj):
    root = _navmesh_root_for_props(mesh_obj)
    props = getattr(root, "sz_navmesh", None)
    bb_min = _vec_from_id_property(_get_rna_property(props, "bb_min"))
    bb_max = _vec_from_id_property(_get_rna_property(props, "bb_max"))
    if not bb_min or not bb_max:
        return None
    if any(minimum > maximum for minimum, maximum in zip(_vec_to_tuple(bb_min), _vec_to_tuple(bb_max))):
        return None
    bb_size = Vec3(bb_max.x - bb_min.x, bb_max.y - bb_min.y, bb_max.z - bb_min.z)
    return bb_min, bb_max, bb_size


def _bounds_enclose(candidate, actual, epsilon=1.0e-4):
    candidate_min, candidate_max, _candidate_size = candidate
    actual_min, actual_max, _actual_size = actual
    return all(
        lower - epsilon <= value_min and value_max <= upper + epsilon
        for lower, upper, value_min, value_max in zip(
            _vec_to_tuple(candidate_min),
            _vec_to_tuple(candidate_max),
            _vec_to_tuple(actual_min),
            _vec_to_tuple(actual_max),
        )
    )


def _select_export_bounds(mesh_obj, source_navmesh, polygons, portals, points):
    """Keep source bounds byte-for-byte stable unless edited data escapes them."""
    calculated = _calculate_bounds(polygons, portals, points)
    has_data = bool(polygons or portals or points)
    candidates = []
    if source_navmesh:
        candidates.append(("source XML", (source_navmesh.bb_min, source_navmesh.bb_max, source_navmesh.bb_size)))
    for owner in (mesh_obj, mesh_obj.parent if mesh_obj else None):
        source_bounds = _bounds_from_owner(owner, "ynv_source_")
        if source_bounds:
            candidates.append(("stored source", source_bounds))
        current_bounds = _bounds_from_owner(owner, "ynv_")
        if current_bounds:
            candidates.append(("stored", current_bounds))
    sollumz_bounds = _bounds_from_sollumz(mesh_obj)
    if sollumz_bounds:
        candidates.append(("Sollumz", sollumz_bounds))

    for label, candidate in candidates:
        if not has_data or _bounds_enclose(candidate, calculated):
            return candidate[0], candidate[1], candidate[2], label
    return calculated[0], calculated[1], calculated[2], None


def _scene_settings(context):
    scene = context.scene if hasattr(context, "scene") else context
    return scene.cw_navmesh_settings


def _sync_settings_from_mesh(context, mesh_obj):
    settings = _scene_settings(context)
    source_navmesh = None
    source_path = str(mesh_obj.get("ynv_source_xml", "")).strip()
    resolved_source = _resolve_source_value(source_path) if source_path else None
    if resolved_source and resolved_source.exists():
        try:
            source_navmesh = read_navmesh_xml(resolved_source)
            source_path = str(resolved_source)
        except Exception:
            source_navmesh = None

    area_id = _get_int_prop(mesh_obj, "ynv_area_id", 0)
    if not area_id and mesh_obj.parent:
        area_id = _get_int_prop(mesh_obj.parent, "ynv_area_id", 0)
    if not area_id:
        area_id = _get_sollumz_navmesh_area_id(mesh_obj, 0)
    if not area_id and source_navmesh:
        area_id = source_navmesh.area_id

    settings.area_id = area_id
    content_flags = str(mesh_obj.get("ynv_content_flags", "")).strip()
    if not content_flags and mesh_obj.parent:
        content_flags = str(mesh_obj.parent.get("ynv_content_flags", "")).strip()
    if not content_flags:
        content_flags = _get_sollumz_navmesh_content_flags(mesh_obj, "")
    if not content_flags and source_navmesh:
        content_flags = source_navmesh.content_flags
    settings.content_flags = content_flags or DEFAULT_CONTENT_FLAGS
    settings.source_xml_path = source_path
    mesh_obj["ynv_area_id"] = area_id
    mesh_obj["ynv_content_flags"] = settings.content_flags
    if mesh_obj.parent:
        mesh_obj.parent["ynv_area_id"] = area_id
        mesh_obj.parent["ynv_content_flags"] = settings.content_flags


def _apply_settings_to_mesh(context, mesh_obj):
    settings = _scene_settings(context)
    area_id = int(settings.area_id)
    content_flags = settings.content_flags.strip() or DEFAULT_CONTENT_FLAGS
    mesh_obj["ynv_area_id"] = area_id
    mesh_obj["ynv_content_flags"] = content_flags
    if settings.source_xml_path.strip():
        _store_source_xml_path(mesh_obj, settings.source_xml_path.strip())
    if mesh_obj.parent:
        mesh_obj.parent["ynv_area_id"] = area_id
        mesh_obj.parent["ynv_content_flags"] = content_flags
        if settings.source_xml_path.strip():
            _store_source_xml_path(mesh_obj.parent, settings.source_xml_path.strip())


def _store_source_xml_path(owner, source_path):
    path_text = str(source_path).strip()
    owner["ynv_source_xml"] = path_text
    if path_text:
        owner["ynv_source_xml_name"] = Path(path_text).name
        try:
            if bpy.data.filepath:
                blend_dir = Path(bpy.data.filepath).resolve().parent
                owner["ynv_source_xml_rel"] = str(Path(path_text).resolve().relative_to(blend_dir))
        except (OSError, ValueError):
            owner["ynv_source_xml_rel"] = Path(path_text).name


def _set_source_xml_path(mesh_obj, source_path):
    _store_source_xml_path(mesh_obj, source_path)
    if mesh_obj.parent:
        _store_source_xml_path(mesh_obj.parent, source_path)


def _store_sollumz_import_source(root_obj, filepath):
    if not root_obj:
        return
    mesh_obj = root_obj if _is_navmesh_mesh(root_obj) else _find_navmesh_mesh_from_root(root_obj)
    owners = [root_obj]
    if mesh_obj and mesh_obj not in owners:
        owners.append(mesh_obj)

    source_navmesh = None
    try:
        source_navmesh = read_navmesh_xml(filepath)
    except Exception:
        source_navmesh = None

    area_id = source_navmesh.area_id if source_navmesh else _get_sollumz_navmesh_area_id(mesh_obj or root_obj, 0)
    content_flags = (
        source_navmesh.content_flags
        if source_navmesh and source_navmesh.content_flags
        else _get_sollumz_navmesh_content_flags(mesh_obj or root_obj, DEFAULT_CONTENT_FLAGS)
    )
    for owner in owners:
        _store_source_xml_path(owner, filepath)
        if area_id:
            owner["ynv_area_id"] = area_id
        if content_flags:
            owner["ynv_content_flags"] = content_flags

    if mesh_obj:
        if source_navmesh:
            _apply_source_navmesh_to_mesh(mesh_obj, filepath, source_navmesh)
        mesh_obj["ynv_auto_source_checked"] = False


def _strip_blender_number_suffix(name):
    return re.sub(r"\.\d{3}$", "", name or "")


def _ynv_import_root_name(filepath):
    name = Path(filepath).name
    for suffix in (".ynv.xml", ".xml", ".ynv"):
        if name.lower().endswith(suffix):
            return name[: -len(suffix)]
    return Path(name).stem


def _is_sollumz_navmesh_root(obj):
    return (
        obj
        and obj.type == "EMPTY"
        and (
            _get_sollum_type(obj) == "sollumz_navmesh"
            or hasattr(obj, "sz_navmesh")
        )
        and _find_navmesh_mesh_from_root(obj)
    )


def _attach_imported_source_paths(import_paths, before_object_names):
    if not import_paths:
        return

    new_roots = [
        obj for obj in bpy.data.objects
        if obj.name not in before_object_names and _is_sollumz_navmesh_root(obj)
    ]
    remaining_roots = list(new_roots)

    for import_path in import_paths:
        expected_name = _ynv_import_root_name(import_path)
        matched_root = None
        for root in remaining_roots:
            if _strip_blender_number_suffix(root.name) == expected_name:
                matched_root = root
                break
        if matched_root is None and len(import_paths) == 1 and len(remaining_roots) == 1:
            matched_root = remaining_roots[0]
        if not matched_root:
            continue
        _store_sollumz_import_source(matched_root, str(import_path))
        remaining_roots.remove(matched_root)


def _ynv_paths_from_sollumz_operator(operator):
    directory = str(getattr(operator, "directory", "") or "").strip()
    if not directory:
        return []
    try:
        directory = bpy.path.abspath(directory)
    except Exception:
        pass

    paths = []
    for file_item in getattr(operator, "files", []) or []:
        filename = str(getattr(file_item, "name", "") or "").strip()
        if filename.lower().endswith(".ynv.xml"):
            paths.append(Path(directory) / filename)
    return paths


def _patch_sollumz_import_operators(importlib_module):
    global _SOLLUMZ_OPERATOR_PATCHED
    if _SOLLUMZ_OPERATOR_PATCHED:
        return True

    module = None
    for module_name in ("Sollumz.sollumz_operators", "Sollumz_Navmesh.sollumz_operators"):
        try:
            module = importlib_module.import_module(module_name)
            break
        except Exception:
            continue
    if not module:
        return False

    patched_any = False
    for class_name in ("SOLLUMZ_OT_import_assets", "SOLLUMZ_OT_import_assets_legacy"):
        cls = getattr(module, class_name, None)
        if not cls or not hasattr(cls, "execute_timed"):
            continue
        original_execute_timed = cls.execute_timed
        if getattr(original_execute_timed, "_ynv_tools_wrapped", False):
            patched_any = True
            continue

        def wrapped_execute_timed(self, context, _original=original_execute_timed):
            import_paths = _ynv_paths_from_sollumz_operator(self)
            before_object_names = {obj.name for obj in bpy.data.objects}
            result = _original(self, context)
            if import_paths:
                try:
                    _attach_imported_source_paths(import_paths, before_object_names)
                except Exception:
                    pass
            return result

        wrapped_execute_timed._ynv_tools_wrapped = True
        wrapped_execute_timed._ynv_tools_original = original_execute_timed
        cls.execute_timed = wrapped_execute_timed
        patched_any = True

    if patched_any:
        _SOLLUMZ_OPERATOR_PATCHED = True
    return patched_any


def _patch_sollumz_importer():
    global _SOLLUMZ_IMPORT_PATCHED
    if _SOLLUMZ_IMPORT_PATCHED and _SOLLUMZ_OPERATOR_PATCHED:
        return True

    import importlib

    _patch_sollumz_import_operators(importlib)

    if _SOLLUMZ_IMPORT_PATCHED:
        return True

    module = None
    for module_name in ("Sollumz.ynv.ynvimport", "Sollumz_Navmesh.ynv.ynvimport"):
        try:
            module = importlib.import_module(module_name)
            break
        except Exception:
            continue
    if not module or not hasattr(module, "import_ynv"):
        return False

    original_import_ynv = module.import_ynv
    if getattr(original_import_ynv, "_ynv_tools_wrapped", False):
        _SOLLUMZ_IMPORT_PATCHED = True
        return True

    def wrapped_import_ynv(filepath):
        root_obj = original_import_ynv(filepath)
        try:
            _store_sollumz_import_source(root_obj, filepath)
        except Exception:
            pass
        return root_obj

    wrapped_import_ynv._ynv_tools_wrapped = True
    wrapped_import_ynv._ynv_tools_original = original_import_ynv
    module.import_ynv = wrapped_import_ynv

    for operators_module_name in ("Sollumz.sollumz_operators", "Sollumz_Navmesh.sollumz_operators"):
        try:
            operators_module = importlib.import_module(operators_module_name)
        except Exception:
            continue
        if getattr(operators_module, "import_ynv", None) == original_import_ynv:
            operators_module.import_ynv = wrapped_import_ynv

    _SOLLUMZ_IMPORT_PATCHED = True
    return True


def _retry_sollumz_import_patch():
    if _patch_sollumz_importer() and _SOLLUMZ_OPERATOR_PATCHED:
        return None
    return 1.0


def _unpatch_sollumz_importer():
    """Restore Sollumz methods on addon unload instead of leaving closures live."""
    global _SOLLUMZ_IMPORT_PATCHED, _SOLLUMZ_OPERATOR_PATCHED
    try:
        import importlib
    except ImportError:
        return

    for module_name in ("Sollumz.sollumz_operators", "Sollumz_Navmesh.sollumz_operators"):
        try:
            module = importlib.import_module(module_name)
        except Exception:
            continue
        for class_name in ("SOLLUMZ_OT_import_assets", "SOLLUMZ_OT_import_assets_legacy"):
            cls = getattr(module, class_name, None)
            current = getattr(cls, "execute_timed", None) if cls else None
            original = getattr(current, "_ynv_tools_original", None)
            if original is not None:
                cls.execute_timed = original

    for module_name in ("Sollumz.ynv.ynvimport", "Sollumz_Navmesh.ynv.ynvimport"):
        try:
            module = importlib.import_module(module_name)
        except Exception:
            continue
        current = getattr(module, "import_ynv", None)
        original = getattr(current, "_ynv_tools_original", None)
        if original is None:
            continue
        module.import_ynv = original
        for operator_module_name in ("Sollumz.sollumz_operators", "Sollumz_Navmesh.sollumz_operators"):
            try:
                operator_module = importlib.import_module(operator_module_name)
            except Exception:
                continue
            if getattr(operator_module, "import_ynv", None) is current:
                operator_module.import_ynv = original

    _SOLLUMZ_IMPORT_PATCHED = False
    _SOLLUMZ_OPERATOR_PATCHED = False


def _legacy_polygon_metadata(mesh_obj):
    """Read the pre-v2 index-based metadata without treating it as stable."""
    return (
        _safe_json_loads(mesh_obj.get("ynv_polygon_flags_json", "[]"), []),
        _safe_json_loads(mesh_obj.get("ynv_polygon_edges_json", "[]"), []),
        _safe_json_loads(mesh_obj.get("ynv_polygon_edges_flags_json", "[]"), []),
        _safe_json_loads(mesh_obj.get("ynv_polygon_portals_json", "[]"), []),
    )


def _face_int_attribute(mesh, name, create=False):
    """Return a FACE int attribute on Blender 2.80 through current Blender.

    Blender 2.93 introduced ``mesh.attributes``.  Older versions expose the
    same data through ``polygon_layers_int``.  Returning whether the layer was
    created lets us distinguish a freshly zero-filled layer from a real id 0.
    """
    attrs = getattr(mesh, "attributes", None)
    if attrs is not None:
        try:
            attribute = attrs.get(name)
            created = False
            if attribute is None and create:
                attribute = attrs.new(name, "INT", "FACE")
                created = True
            if attribute is not None and getattr(attribute, "domain", "FACE") == "FACE":
                return attribute, created
        except (AttributeError, RuntimeError, TypeError):
            pass

    layers = getattr(mesh, "polygon_layers_int", None)
    if layers is not None:
        try:
            attribute = layers.get(name)
            created = False
            if attribute is None and create:
                attribute = layers.new(name=name)
                created = True
            if attribute is not None:
                return attribute, created
        except (AttributeError, RuntimeError, TypeError):
            pass
    return None, False


def _read_face_attribute_values(mesh_obj, name):
    attribute, _created = _face_int_attribute(mesh_obj.data, name, create=False)
    if attribute is None or len(getattr(attribute, "data", [])) != len(mesh_obj.data.polygons):
        return None
    try:
        return [int(item.value) for item in attribute.data]
    except (AttributeError, TypeError, ValueError):
        return None


def _write_face_attribute_values(mesh_obj, name, values):
    attribute, _created = _face_int_attribute(mesh_obj.data, name, create=True)
    if attribute is None or len(getattr(attribute, "data", [])) != len(values):
        return False
    try:
        for index, value in enumerate(values):
            attribute.data[index].value = int(value)
    except (AttributeError, TypeError, ValueError, RuntimeError):
        return False
    return True


def _face_geometry_key(mesh_obj, face, precision=5):
    """A winding-independent key used only as a fallback on older Blender."""
    coords = []
    for vertex_index in face.vertices:
        point = mesh_obj.matrix_world @ mesh_obj.data.vertices[vertex_index].co
        coords.append(
            f"{round(float(point.x), precision):.{precision}f},"
            f"{round(float(point.y), precision):.{precision}f},"
            f"{round(float(point.z), precision):.{precision}f}"
        )
    if not coords:
        return ""
    candidates = []
    for ordered in (coords, list(reversed(coords))):
        for offset in range(len(ordered)):
            candidates.append(";".join(ordered[offset:] + ordered[:offset]))
    return min(candidates)


def _metadata_records(mesh_obj):
    records = _safe_json_loads(mesh_obj.get(YNV_POLYGON_METADATA_V2, "{}"), {})
    if not isinstance(records, dict):
        return {}
    return {str(key): value for key, value in records.items() if isinstance(value, dict)}


def _int_or_default(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalized_row(values, width, default):
    values = list(values) if isinstance(values, (list, tuple)) else []
    return (values + [default] * width)[:width]


def _default_flags_for_face(mesh, face):
    material = mesh.materials[face.material_index] if face.material_index < len(mesh.materials) else None
    return list(_parse_flags_from_material(material) or [0, 0, 0, 0, 0, 0])


def _ensure_face_identity(mesh_obj, records):
    """Get a stable id and optional original polygon id for every current face."""
    mesh = mesh_obj.data
    geometry_keys = [_face_geometry_key(mesh_obj, face) for face in mesh.polygons]
    face_attribute, face_attribute_created = _face_int_attribute(mesh, YNV_FACE_ID_ATTR, create=True)
    source_attribute, source_attribute_created = _face_int_attribute(mesh, YNV_SOURCE_POLYGON_ATTR, create=True)
    raw_face_ids = None if face_attribute_created else _read_face_attribute_values(mesh_obj, YNV_FACE_ID_ATTR)
    raw_source_ids = None if source_attribute_created else _read_face_attribute_values(mesh_obj, YNV_SOURCE_POLYGON_ATTR)

    by_geometry = {}
    for record_id, record in records.items():
        key = str(record.get("geometry_key", ""))
        if key:
            by_geometry.setdefault(key, []).append(_int_or_default(record_id, NO_SOURCE_POLYGON))
    for values in by_geometry.values():
        values.sort()

    next_face_id = max(0, _int_or_default(mesh_obj.get(YNV_NEXT_FACE_ID, 0), 0))
    for record_id in records:
        next_face_id = max(next_face_id, _int_or_default(record_id, -1) + 1)

    face_ids = []
    used_face_ids = set()
    for index, key in enumerate(geometry_keys):
        candidate = raw_face_ids[index] if raw_face_ids and index < len(raw_face_ids) else -1
        if candidate < 0 or candidate in used_face_ids:
            candidate = next(
                (value for value in by_geometry.get(key, []) if value >= 0 and value not in used_face_ids),
                -1,
            )
        if candidate < 0:
            candidate = next_face_id
            next_face_id += 1
        face_ids.append(candidate)
        used_face_ids.add(candidate)

    source_ids = []
    used_source_ids = set()
    for index, face_id in enumerate(face_ids):
        record = records.get(str(face_id), {})
        candidate = raw_source_ids[index] if raw_source_ids and index < len(raw_source_ids) else record.get("source_index", NO_SOURCE_POLYGON)
        candidate = _int_or_default(candidate, NO_SOURCE_POLYGON)
        # A topology operation may duplicate a FACE attribute.  Only one face
        # may claim a source polygon; the duplicate is deliberately new.
        if candidate >= 0 and candidate in used_source_ids:
            candidate = NO_SOURCE_POLYGON
        if candidate >= 0:
            used_source_ids.add(candidate)
        source_ids.append(candidate)

    _write_face_attribute_values(mesh_obj, YNV_FACE_ID_ATTR, face_ids)
    _write_face_attribute_values(mesh_obj, YNV_SOURCE_POLYGON_ATTR, source_ids)
    mesh_obj[YNV_NEXT_FACE_ID] = next_face_id
    return face_ids, source_ids, geometry_keys


def _write_polygon_metadata(mesh_obj, polygon_flags, polygon_edges, polygon_edges_flags, polygon_portals, source_indices=None):
    """Write metadata keyed by stable face id and mirror it to legacy arrays."""
    mesh = mesh_obj.data
    records = _metadata_records(mesh_obj)
    face_ids, stored_source_indices, geometry_keys = _ensure_face_identity(mesh_obj, records)
    if source_indices is None:
        source_indices = stored_source_indices
    source_indices = [
        _int_or_default(source_indices[index], NO_SOURCE_POLYGON) if index < len(source_indices) else NO_SOURCE_POLYGON
        for index in range(len(mesh.polygons))
    ]

    normalized_flags = []
    normalized_edges = []
    normalized_edges_flags = []
    normalized_portals = []
    new_records = {}
    for index, face in enumerate(mesh.polygons):
        width = len(face.vertices)
        flags = polygon_flags[index] if index < len(polygon_flags) else _default_flags_for_face(mesh, face)
        flags = list(flags) if isinstance(flags, (list, tuple)) else _default_flags_for_face(mesh, face)
        edges = _normalized_row(polygon_edges[index] if index < len(polygon_edges) else [], width, DEFAULT_EDGE)
        edges_flags = _normalized_row(
            polygon_edges_flags[index] if index < len(polygon_edges_flags) else [], width, DEFAULT_EDGE_FLAGS
        )
        portals = polygon_portals[index] if index < len(polygon_portals) else []
        portals = list(portals) if isinstance(portals, (list, tuple)) else []
        normalized_flags.append(flags)
        normalized_edges.append(edges)
        normalized_edges_flags.append(edges_flags)
        normalized_portals.append(portals)
        new_records[str(face_ids[index])] = {
            "flags": flags,
            "edges": edges,
            "edges_flags": edges_flags,
            "portals": portals,
            "source_index": source_indices[index],
            "geometry_key": geometry_keys[index],
        }

    mesh_obj[YNV_POLYGON_METADATA_V2] = json.dumps(new_records, separators=(",", ":"))
    mesh_obj[YNV_METADATA_VERSION] = 2
    mesh_obj["ynv_polygon_flags_json"] = json.dumps(normalized_flags, separators=(",", ":"))
    mesh_obj["ynv_polygon_edges_json"] = json.dumps(normalized_edges, separators=(",", ":"))
    mesh_obj["ynv_polygon_edges_flags_json"] = json.dumps(normalized_edges_flags, separators=(",", ":"))
    mesh_obj["ynv_polygon_portals_json"] = json.dumps(normalized_portals, separators=(",", ":"))
    _write_face_attribute_values(mesh_obj, YNV_SOURCE_POLYGON_ATTR, source_indices)
    mesh_obj[YNV_MESH_TAG] = True
    _set_sollum_type(mesh_obj, SOLLUMZ_NAVMESH_POLY_MESH)
    return normalized_flags, normalized_edges, normalized_edges_flags, normalized_portals


def _ensure_polygon_metadata(mesh_obj):
    mesh = mesh_obj.data
    legacy_flags, legacy_edges, legacy_edges_flags, legacy_portals = _legacy_polygon_metadata(mesh_obj)
    records = _metadata_records(mesh_obj)
    face_ids, source_indices, geometry_keys = _ensure_face_identity(mesh_obj, records)
    polygon_flags = []
    polygon_edges = []
    polygon_edges_flags = []
    polygon_portals = []

    for index, face in enumerate(mesh.polygons):
        width = len(face.vertices)
        record = records.get(str(face_ids[index]))
        if record is None:
            flags = legacy_flags[index] if index < len(legacy_flags) else _default_flags_for_face(mesh, face)
            edges = legacy_edges[index] if index < len(legacy_edges) else []
            edges_flags = legacy_edges_flags[index] if index < len(legacy_edges_flags) else []
            portals = legacy_portals[index] if index < len(legacy_portals) else []
        else:
            flags = record.get("flags", _default_flags_for_face(mesh, face))
            edges = record.get("edges", [])
            edges_flags = record.get("edges_flags", [])
            portals = record.get("portals", [])
            # If a face changed arity, its old directed edge/portal topology is
            # not meaningful.  Preserve material flags, but make topology new.
            if len(edges) != width or len(edges_flags) != width:
                edges = []
                edges_flags = []
                portals = []
                source_indices[index] = NO_SOURCE_POLYGON
        polygon_flags.append(list(flags) if isinstance(flags, (list, tuple)) else _default_flags_for_face(mesh, face))
        polygon_edges.append(_normalized_row(edges, width, DEFAULT_EDGE))
        polygon_edges_flags.append(_normalized_row(edges_flags, width, DEFAULT_EDGE_FLAGS))
        polygon_portals.append(list(portals) if isinstance(portals, (list, tuple)) else [])

    return _write_polygon_metadata(
        mesh_obj,
        polygon_flags,
        polygon_edges,
        polygon_edges_flags,
        polygon_portals,
        source_indices=source_indices,
    )


def _current_face_identity(mesh_obj):
    """Return stable face ids and the source polygon id for current face order."""
    return _ensure_face_identity(mesh_obj, _metadata_records(mesh_obj))[:2]


def _stored_reference_face_ids(mesh_obj):
    values = _safe_json_loads(mesh_obj.get(YNV_REFERENCE_FACE_IDS, "[]"), [])
    if not isinstance(values, list):
        return []
    return [_int_or_default(value, NO_SOURCE_POLYGON) for value in values]


def _store_reference_face_ids(mesh_obj, face_ids):
    mesh_obj[YNV_REFERENCE_FACE_IDS] = json.dumps([int(value) for value in face_ids], separators=(",", ":"))


def _remap_local_edge_row(edge_row, area_id, reference_face_ids, current_face_ids):
    """Translate local edge target indices from one face order to another."""
    current_index_by_id = {face_id: index for index, face_id in enumerate(current_face_ids)}
    invalid_local_ref = False

    def replace(match):
        nonlocal invalid_local_ref
        ref_area = _int_or_default(match.group(1), -1)
        ref_index = _int_or_default(match.group(2), -1)
        if ref_area != area_id:
            return match.group(0)
        if ref_index < 0 or ref_index >= len(reference_face_ids):
            invalid_local_ref = True
            return match.group(0)
        face_id = reference_face_ids[ref_index]
        current_index = current_index_by_id.get(face_id)
        if face_id < 0 or current_index is None:
            invalid_local_ref = True
            return match.group(0)
        return f"{area_id}:{current_index}"

    remapped = EDGE_REF_PATTERN.sub(replace, str(edge_row))
    return (DEFAULT_EDGE if invalid_local_ref else remapped), (invalid_local_ref or remapped != edge_row)


def _remap_local_edge_rows(polygon_edges, area_id, reference_face_ids, current_face_ids):
    if not reference_face_ids:
        return [list(rows) for rows in polygon_edges], 0
    remapped_rows = []
    changed = 0
    for rows in polygon_edges:
        remapped = []
        for edge_row in rows:
            value, row_changed = _remap_local_edge_row(edge_row, area_id, reference_face_ids, current_face_ids)
            remapped.append(value)
            changed += int(row_changed)
        remapped_rows.append(remapped)
    return remapped_rows, changed


def _remap_portal_polygon_indices(portals, reference_face_ids, current_face_ids):
    if not reference_face_ids:
        return list(portals), 0
    current_index_by_id = {face_id: index for index, face_id in enumerate(current_face_ids)}
    changed = 0
    remapped = []
    for portal in portals:
        def remap(index):
            nonlocal changed
            index = _int_or_default(index, NO_SOURCE_POLYGON)
            if index < 0 or index >= len(reference_face_ids):
                changed += 1
                return NO_SOURCE_POLYGON
            face_id = reference_face_ids[index]
            current_index = current_index_by_id.get(face_id)
            if face_id < 0 or current_index is None:
                changed += 1
                return NO_SOURCE_POLYGON
            if current_index != index:
                changed += 1
            return current_index

        remapped.append(
            Portal(
                type=portal.type,
                angle=portal.angle,
                poly_from=remap(portal.poly_from),
                poly_to=remap(portal.poly_to),
                position_from=portal.position_from,
                position_to=portal.position_to,
            )
        )
    return remapped, changed


def _read_polygon_metadata(mesh_obj):
    # Reading also migrates an old file once.  This is intentional: all
    # following tools see exactly the same stable mapping rather than a stale
    # polygon-index array.
    return _ensure_polygon_metadata(mesh_obj)


def _apply_source_navmesh_to_mesh(mesh_obj, source_path, navmesh=None):
    navmesh = navmesh or read_navmesh_xml(source_path)
    _set_source_xml_path(mesh_obj, source_path)
    mesh_obj["ynv_area_id"] = navmesh.area_id
    mesh_obj["ynv_content_flags"] = navmesh.content_flags or DEFAULT_CONTENT_FLAGS
    if mesh_obj.parent:
        mesh_obj.parent["ynv_area_id"] = navmesh.area_id
        mesh_obj.parent["ynv_content_flags"] = navmesh.content_flags or DEFAULT_CONTENT_FLAGS
    _store_source_navmesh_snapshot(mesh_obj, navmesh)
    _store_navmesh_bounds(mesh_obj, navmesh.bb_min, navmesh.bb_max, navmesh.bb_size)

    mesh = mesh_obj.data
    source_by_key = {}
    for source_index, polygon in enumerate(navmesh.polygons):
        key = _polygon_centroid_key_from_vertices(polygon.vertices)
        source_by_key.setdefault(key, []).append(source_index)
    used_source_indices = set()
    source_indices = []
    for face in mesh.polygons:
        vertices = [_tuple_to_vec(mesh_obj.matrix_world @ mesh.vertices[vertex_index].co) for vertex_index in face.vertices]
        candidates = [
            source_index
            for source_index in source_by_key.get(_polygon_centroid_key_from_vertices(vertices), [])
            if source_index not in used_source_indices
            and len(navmesh.polygons[source_index].vertices) == len(vertices)
        ]
        source_index = candidates[0] if candidates else NO_SOURCE_POLYGON
        if source_index >= 0:
            used_source_indices.add(source_index)
        source_indices.append(source_index)

    # Source XML edge/portal references address source polygon positions.
    # Store the equivalent stable face id for each source slot before copying
    # rows, then translate those references into the current Blender order.
    face_ids, _old_source_indices = _current_face_identity(mesh_obj)
    source_reference_face_ids = [NO_SOURCE_POLYGON] * len(navmesh.polygons)
    for face_index, source_index in enumerate(source_indices):
        if source_index >= 0:
            source_reference_face_ids[source_index] = face_ids[face_index]

    polygon_flags = []
    polygon_edges = []
    polygon_edges_flags = []
    polygon_portals = []
    for face_index, face in enumerate(mesh.polygons):
        source_index = source_indices[face_index]
        if source_index >= 0:
            source_polygon = navmesh.polygons[source_index]
            polygon_flags.append(list(source_polygon.flags))
            polygon_edges.append(list(source_polygon.edges))
            polygon_edges_flags.append(list(source_polygon.edges_flags))
            polygon_portals.append(list(getattr(source_polygon, "portals", [])))
        else:
            polygon_flags.append(_default_flags_for_face(mesh, face))
            polygon_edges.append([DEFAULT_EDGE] * len(face.vertices))
            polygon_edges_flags.append([DEFAULT_EDGE_FLAGS] * len(face.vertices))
            polygon_portals.append([])
    polygon_edges, _changed_edge_refs = _remap_local_edge_rows(
        polygon_edges,
        navmesh.area_id,
        source_reference_face_ids,
        face_ids,
    )
    _write_polygon_metadata(
        mesh_obj,
        polygon_flags,
        polygon_edges,
        polygon_edges_flags,
        polygon_portals,
        source_indices=source_indices,
    )
    _store_reference_face_ids(mesh_obj, face_ids)

    # Imported portal objects use the same source polygon positions.  Keep
    # their editable Sollumz properties in the current face-index space too.
    source_portals, _source_points = _read_collection_items(mesh_obj, navmesh)
    remapped_portals, _changed_portals = _remap_portal_polygon_indices(
        source_portals,
        source_reference_face_ids,
        face_ids,
    )
    _sync_portal_objects(mesh_obj, remapped_portals)
    return len(mesh.polygons) == len(navmesh.polygons) and all(index >= 0 for index in source_indices)


def _polygon_flags_from_sollumz_attributes(mesh_obj):
    mesh = getattr(mesh_obj, "data", None)
    attrs = getattr(mesh, "attributes", None)
    if not attrs:
        return []

    names = [
        ".navmesh.poly_flag0",
        ".navmesh.poly_flag1",
        ".navmesh.poly_flag2",
        ".navmesh.poly_flag3",
        ".navmesh.poly_centroid_x",
        ".navmesh.poly_centroid_y",
    ]
    if any(name not in attrs for name in names):
        return []

    flags = []
    f4_attr = attrs.get(".navmesh.poly_flag4")
    has_f4_attr = attrs.get(".navmesh.poly_has_f4")
    for index, _face in enumerate(mesh.polygons):
        try:
            row = [int(attrs[name].data[index].value) for name in names]
            if f4_attr and has_f4_attr and int(has_f4_attr.data[index].value):
                row.append(int(f4_attr.data[index].value))
            flags.append(row)
        except Exception:
            return []
    return flags


def _world_vec(obj):
    return _tuple_to_vec(obj.matrix_world.translation)


def _set_sollum_type(obj, sollum_type):
    try:
        obj.sollum_type = sollum_type
    except Exception:
        obj["sollum_type"] = sollum_type


def _get_sollum_type(obj):
    if not obj:
        return ""
    value = getattr(obj, "sollum_type", "")
    if not value:
        value = obj.get("sollum_type", "")
    return str(value)


def _tuple_to_vec(values):
    return Vec3(float(values[0]), float(values[1]), float(values[2]))


def _vec_to_tuple(vec):
    return (vec.x, vec.y, vec.z)


def _json_vec(vec):
    return [vec.x, vec.y, vec.z]


def _vec_add(left, right):
    return Vec3(left.x + right.x, left.y + right.y, left.z + right.z)


def _vec_sub(left, right):
    return Vec3(left.x - right.x, left.y - right.y, left.z - right.z)


def _calculate_bounds(polygons, portals, points):
    coords = []
    for polygon in polygons:
        coords.extend(polygon.vertices)
    for portal in portals:
        coords.extend((portal.position_from, portal.position_to))
    for point in points:
        coords.append(point.position)

    if not coords:
        zero = Vec3(0.0, 0.0, 0.0)
        return zero, zero, zero

    bb_min = Vec3(min(v.x for v in coords), min(v.y for v in coords), min(v.z for v in coords))
    bb_max = Vec3(max(v.x for v in coords), max(v.y for v in coords), max(v.z for v in coords))
    bb_size = Vec3(bb_max.x - bb_min.x, bb_max.y - bb_min.y, bb_max.z - bb_min.z)
    return bb_min, bb_max, bb_size


def _collection_link(collection, obj):
    if not any(existing == obj for existing in collection.objects):
        collection.objects.link(obj)


def _new_empty(name, sollum_type=None):
    obj = bpy.data.objects.new(name, None)
    obj.empty_display_type = "PLAIN_AXES"
    obj.empty_display_size = 0
    if sollum_type:
        _set_sollum_type(obj, sollum_type)
    return obj


def _material_color_for_flags(flags):
    values = [int(value) for value in flags[:7]]
    while len(values) < 7:
        values.append(0)
    red = 0
    green = 0
    blue = 0
    flags0 = values[0]
    if flags0 & 1 > 0:
        red += 0.01
    if flags0 & 2 > 0:
        red += 0.01
    if flags0 & 4 > 0:
        green += 0.25
    if flags0 & 8 > 0:
        green += 0.02
    if flags0 & 64 > 0:
        red += 0.25
    if flags0 & 128 > 0:
        blue += 0.25

    flags1 = values[1] | ((values[6] & 0x01) << 8) | (values[2] << 9)
    if flags1 & 64 > 0:
        blue += 0.1
    if flags1 & 512 > 0:
        green += 0.1
    if flags1 & 1024 > 0:
        blue += 0.03
    if flags1 & 4096 > 0:
        green += 0.75
    if flags1 & 8192 > 0:
        blue += 0.75
    if flags1 & 16384 > 0:
        red += 0.2
    if flags1 & 32768 > 0:
        blue += 0.2
    if flags1 & 65536 > 0:
        green = 0.2

    return (min(red, 1.0), min(green, 1.0), min(blue, 1.0), 0.75)


def _set_material_color(mat, color):
    mat.diffuse_color = color
    mat.metallic = 0.0
    mat.roughness = 0.4
    mat.blend_method = "OPAQUE"
    mat.use_screen_refraction = False
    mat.show_transparent_back = False
    try:
        mat.use_nodes = True
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        if bsdf:
            if "Base Color" in bsdf.inputs:
                bsdf.inputs["Base Color"].default_value = color
            if "Alpha" in bsdf.inputs:
                bsdf.inputs["Alpha"].default_value = color[3]
            if "Metallic" in bsdf.inputs:
                bsdf.inputs["Metallic"].default_value = 0.0
            if "Roughness" in bsdf.inputs:
                bsdf.inputs["Roughness"].default_value = 0.4
    except Exception:
        pass


def _create_material_for_flags(flags):
    name = " ".join(str(value) for value in flags)
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    _set_material_color(mat, _material_color_for_flags(flags))
    return mat


def _create_navmesh_mesh_from_data(navmesh):
    vertices = []
    faces = []
    for polygon in navmesh.polygons:
        start = len(vertices)
        vertices.extend(_vec_to_tuple(vertex) for vertex in polygon.vertices)
        faces.append(list(range(start, start + len(polygon.vertices))))

    mesh = bpy.data.meshes.new("NavMesh Poly Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update(calc_edges=True)
    obj = bpy.data.objects.new("NavMesh Poly Mesh", mesh)
    obj[YNV_MESH_TAG] = True
    obj["ynv_area_id"] = navmesh.area_id
    obj["ynv_content_flags"] = navmesh.content_flags or DEFAULT_CONTENT_FLAGS
    _write_polygon_metadata(
        obj,
        [polygon.flags for polygon in navmesh.polygons],
        [polygon.edges for polygon in navmesh.polygons],
        [polygon.edges_flags for polygon in navmesh.polygons],
        [getattr(polygon, "portals", []) for polygon in navmesh.polygons],
        source_indices=list(range(len(navmesh.polygons))),
    )
    face_ids, _source_indices = _current_face_identity(obj)
    _store_reference_face_ids(obj, face_ids)
    _set_sollum_type(obj, SOLLUMZ_NAVMESH_POLY_MESH)

    for polygon in navmesh.polygons:
        mesh.materials.append(_create_material_for_flags(polygon.flags))
    for index, face in enumerate(mesh.polygons):
        face.material_index = index if index < len(mesh.materials) else 0
    return obj


def _create_marker_mesh(name, size=0.4):
    half = size * 0.5
    vertices = [
        (-half, -half, -half),
        (half, -half, -half),
        (half, half, -half),
        (-half, half, -half),
        (-half, -half, half),
        (half, -half, half),
        (half, half, half),
        (-half, half, half),
    ]
    faces = [(0, 1, 2, 3), (4, 7, 6, 5), (0, 4, 5, 1), (1, 5, 6, 2), (2, 6, 7, 3), (3, 7, 4, 0)]
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(vertices, [], faces)
    mesh.update(calc_edges=True)
    return mesh


def _create_point_object(point, index):
    obj = bpy.data.objects.new(f"NavMesh Point {index}", _create_marker_mesh("GTANAVMESH Edit Point Marker"))
    obj.location = _vec_to_tuple(point.position)
    obj.rotation_euler = (0.0, 0.0, point.angle)
    obj[YNV_POINT_TAG] = True
    _write_sollumz_point_properties(obj, point)
    _set_sollum_type(obj, SOLLUMZ_NAVMESH_POINT)
    return obj


def _create_portal_object(portal, index):
    center = Vec3(
        (portal.position_from.x + portal.position_to.x) * 0.5,
        (portal.position_from.y + portal.position_to.y) * 0.5,
        (portal.position_from.z + portal.position_to.z) * 0.5,
    )
    obj = bpy.data.objects.new(f"NavMesh Portal {index}", _create_marker_mesh("GTANAVMESH Edit Portal Marker", 0.6))
    obj.location = _vec_to_tuple(center)
    obj.rotation_euler = (0.0, 0.0, portal.angle)
    obj[YNV_PORTAL_TAG] = True
    _write_sollumz_portal_properties(obj, portal)
    obj["ynv_position_from"] = _json_vec(portal.position_from)
    obj["ynv_position_to"] = _json_vec(portal.position_to)
    obj["ynv_center"] = _json_vec(center)
    _set_sollum_type(obj, SOLLUMZ_NAVMESH_PORTAL)

    from_obj = bpy.data.objects.new("from", _create_marker_mesh("GTANAVMESH Edit Portal From", 0.3))
    from_obj.location = (
        portal.position_from.x - center.x,
        portal.position_from.y - center.y,
        portal.position_from.z - center.z,
    )
    from_obj.parent = obj

    to_obj = bpy.data.objects.new("to", _create_marker_mesh("GTANAVMESH Edit Portal To", 0.3))
    to_obj.location = (
        portal.position_to.x - center.x,
        portal.position_to.y - center.y,
        portal.position_to.z - center.z,
    )
    to_obj.parent = obj
    return obj, from_obj, to_obj


def import_navmesh_xml(filepath, context=None):
    context = context or bpy.context
    navmesh = read_navmesh_xml(filepath)
    name = Path(filepath).name
    for suffix in (".ynv.xml", ".xml"):
        if name.lower().endswith(suffix):
            name = name[: -len(suffix)]
            break

    root = _new_empty(name, "sollumz_navmesh")
    root[YNV_COLLECTION_TAG] = True
    root["ynv_area_id"] = navmesh.area_id
    root["ynv_content_flags"] = navmesh.content_flags or DEFAULT_CONTENT_FLAGS
    _store_source_xml_path(root, filepath)
    _collection_link(context.collection, root)

    mesh_obj = _create_navmesh_mesh_from_data(navmesh)
    mesh_obj.parent = root
    _store_source_xml_path(mesh_obj, filepath)
    _store_source_navmesh_snapshot(mesh_obj, navmesh)
    _store_navmesh_bounds(mesh_obj, navmesh.bb_min, navmesh.bb_max, navmesh.bb_size)
    _collection_link(context.collection, mesh_obj)

    portals_parent = _new_empty("Portals")
    portals_parent.parent = root
    _collection_link(context.collection, portals_parent)
    for index, portal in enumerate(navmesh.portals):
        portal_obj, from_obj, to_obj = _create_portal_object(portal, index)
        portal_obj.parent = portals_parent
        _collection_link(context.collection, portal_obj)
        _collection_link(context.collection, from_obj)
        _collection_link(context.collection, to_obj)

    points_parent = _new_empty("Points")
    points_parent.parent = root
    _collection_link(context.collection, points_parent)
    for index, point in enumerate(navmesh.points):
        point_obj = _create_point_object(point, index)
        point_obj.parent = points_parent
        _collection_link(context.collection, point_obj)

    # Source positions are identical to the newly created face order.  Record
    # that fact on every portal before an edit can reorder/delete faces.
    _sync_portal_objects(mesh_obj, navmesh.portals)

    for obj in context.scene.objects:
        obj.select_set(False)
    mesh_obj.select_set(True)
    context.view_layer.objects.active = mesh_obj
    _sync_settings_from_mesh(context, mesh_obj)
    return mesh_obj


def _safe_without_suffix(value, suffix):
    if value.endswith(suffix):
        return value[: -len(suffix)]
    return value


def _ynv_xml_path(filepath):
    value = str(filepath)
    lower = value.lower()
    if lower.endswith(".ynv.xml"):
        return value
    if lower.endswith(".ynv"):
        return value + ".xml"
    if lower.endswith(".xml"):
        return value
    return value + ".ynv.xml"


def _normalize_ynv_xml_filepath(filepath):
    return _ynv_xml_path(filepath)


def _sanitize_edge_links(edge_links, area_id, polygon_count):
    sanitized = []
    changed = False
    for edge_link in edge_links:
        invalid_local_ref = False
        for match in EDGE_REF_PATTERN.finditer(edge_link):
            link_area = int(match.group(1))
            polygon_index = int(match.group(2))
            if link_area == area_id and polygon_index >= polygon_count:
                invalid_local_ref = True
                break
        if invalid_local_ref:
            sanitized.append(DEFAULT_EDGE)
            changed = True
        else:
            sanitized.append(edge_link)
    return sanitized, changed


def _first_edge_ref(edge_link):
    match = EDGE_REF_PATTERN.search(edge_link or "")
    if not match:
        return None, None
    return int(match.group(1)), int(match.group(2))


def _edge_row(area_id, polygon_index):
    return f"{area_id}:{polygon_index}, {area_id}:{polygon_index}"


def _parse_flags_from_material(material):
    if not material:
        return None
    parts = material.name.split()
    if len(parts) not in (6, 7):
        return None
    try:
        return [int(part) for part in parts]
    except ValueError:
        return None


def _flags_are_all_zero(polygon_flags):
    return bool(polygon_flags) and all(all(int(value) == 0 for value in flags) for flags in polygon_flags)


def _edges_are_all_open(polygon_edges):
    return bool(polygon_edges) and all(all(edge == DEFAULT_EDGE for edge in edges) for edges in polygon_edges)


def _read_area_id_from_xml(path):
    try:
        navmesh = read_navmesh_xml(path)
    except Exception:
        return 0
    return navmesh.area_id


def _source_search_dirs(export_filepath=None):
    """Return deliberately narrow source lookup locations.

    Older versions scanned Downloads, Documents and OneDrive and then selected
    the nearest-looking YNV.  A wrong source is much worse than no source: it
    can silently transplant AreaID, links and portal metadata.  Manual source
    paths are always resolved, while discovery is restricted to the current
    export/.blend directory and one user-selected folder.
    """
    dirs = []
    if export_filepath:
        try:
            dirs.append(Path(export_filepath).resolve().parent)
        except OSError:
            pass
    if bpy.data.filepath:
        dirs.append(Path(bpy.data.filepath).resolve().parent)
    try:
        settings = getattr(bpy.context.scene, "cw_navmesh_settings", None)
        configured_dir = str(getattr(settings, "source_search_directory", "") or "").strip()
        if configured_dir:
            dirs.append(Path(bpy.path.abspath(configured_dir)))
    except (AttributeError, RuntimeError, TypeError):
        pass
    if not dirs:
        # Unsaved .blend files still need a predictable local-only fallback.
        dirs.append(Path.cwd())
    seen = []
    for directory in dirs:
        try:
            resolved = directory.resolve()
        except OSError:
            continue
        if resolved not in seen:
            seen.append(resolved)
    return seen


def _stored_source_values(mesh_obj):
    values = []
    for owner in (mesh_obj, mesh_obj.parent):
        if not owner:
            continue
        for key in ("ynv_source_xml", "ynv_source_xml_rel", "ynv_source_xml_name"):
            value = str(owner.get(key, "")).strip()
            if value and value not in values:
                values.append(value)
    return values


def _resolve_source_value(value, export_filepath=None):
    path = Path(value).expanduser()
    candidates = []
    if path.is_absolute():
        candidates.append(path)
    else:
        for directory in _source_search_dirs(export_filepath):
            candidates.append(directory / path)
    if path.name != value:
        for directory in _source_search_dirs(export_filepath):
            candidates.append(directory / path.name)
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved.exists():
            return resolved
    return None


def _generic_navmesh_name(name):
    clean = re.sub(r"\.\d+$", "", name or "")
    return clean in {"NavMesh Poly Mesh", "NavMesh", "Polygons", ""}


def _source_used_by_other_mesh(source_path, mesh_obj):
    if not source_path:
        return False
    try:
        target = Path(source_path).resolve()
    except OSError:
        return False
    for obj in bpy.data.objects:
        if obj == mesh_obj or not _is_navmesh_mesh(obj):
            continue
        for owner in (obj, obj.parent):
            if not owner:
                continue
            stored = str(owner.get("ynv_source_xml", "")).strip()
            if not stored:
                continue
            try:
                if Path(stored).resolve() == target:
                    return True
            except OSError:
                continue
    return False


def _mesh_bounds_score(mesh_obj, navmesh):
    if not mesh_obj or not mesh_obj.data.vertices:
        return 0.0
    coords = [mesh_obj.matrix_world @ vertex.co for vertex in mesh_obj.data.vertices]
    mesh_min = Vec3(min(v.x for v in coords), min(v.y for v in coords), min(v.z for v in coords))
    mesh_max = Vec3(max(v.x for v in coords), max(v.y for v in coords), max(v.z for v in coords))
    mesh_center = Vec3(
        (mesh_min.x + mesh_max.x) * 0.5,
        (mesh_min.y + mesh_max.y) * 0.5,
        (mesh_min.z + mesh_max.z) * 0.5,
    )
    source_center = Vec3(
        (navmesh.bb_min.x + navmesh.bb_max.x) * 0.5,
        (navmesh.bb_min.y + navmesh.bb_max.y) * 0.5,
        (navmesh.bb_min.z + navmesh.bb_max.z) * 0.5,
    )
    center_delta = abs(mesh_center.x - source_center.x) + abs(mesh_center.y - source_center.y) + abs(mesh_center.z - source_center.z)
    size_delta = (
        abs((mesh_max.x - mesh_min.x) - navmesh.bb_size.x)
        + abs((mesh_max.y - mesh_min.y) - navmesh.bb_size.y)
        + abs((mesh_max.z - mesh_min.z) - navmesh.bb_size.z)
    )
    return center_delta + (size_delta * 0.25)


def _source_xml_candidates(root_name="", export_filepath=None):
    candidates = []
    names = []
    if root_name and not _generic_navmesh_name(root_name):
        names.extend([root_name + ".ynv.xml", root_name + ".xml"])
    for directory in _source_search_dirs(export_filepath):
        for name in names:
            candidates.append(directory / name)
        try:
            # Glob brackets denote a character class.  Filter names explicitly
            # so literal GTA tile names such as navmesh[123][102].ynv.xml work.
            candidates.extend(
                candidate
                for candidate in directory.glob("*.ynv.xml")
                if re.fullmatch(r"navmesh\[\d+\]\[\d+\]\.ynv\.xml", candidate.name, re.IGNORECASE)
            )
        except OSError:
            continue
    seen = []
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved not in seen and resolved.exists():
            seen.append(resolved)
    return seen


def _direct_source_xml_for_root(root_name, export_filepath=None):
    if not root_name or _generic_navmesh_name(root_name):
        return None
    for directory in _source_search_dirs(export_filepath):
        for suffix in (".ynv.xml", ".xml"):
            candidate = directory / (root_name + suffix)
            try:
                resolved = candidate.resolve()
            except OSError:
                continue
            if resolved.exists():
                return resolved
    return None


def _best_source_xml_for_mesh(mesh_obj, export_filepath=None, exclude_used=True, exclude_paths=None):
    """Return only a high-confidence automatic source candidate.

    A same-name file is authoritative enough to offer.  For unnamed cells we
    require equal polygon counts, near-identical world bounds and exactly one
    candidate; choosing the lowest score out of unrelated game tiles is not a
    safe recovery strategy.
    """
    root_name = mesh_obj.parent.name if mesh_obj.parent else mesh_obj.name
    best_candidates = []
    exclude_paths = exclude_paths or set()
    direct = _direct_source_xml_for_root(root_name, export_filepath)
    if direct and direct not in exclude_paths:
        if not exclude_used or not _source_used_by_other_mesh(direct, mesh_obj):
            try:
                return (0.0, direct, read_navmesh_xml(direct))
            except Exception:
                pass
    for candidate in _source_xml_candidates(root_name, export_filepath):
        try:
            resolved_candidate = candidate.resolve()
        except OSError:
            continue
        if resolved_candidate in exclude_paths:
            continue
        if exclude_used and _source_used_by_other_mesh(candidate, mesh_obj):
            continue
        try:
            navmesh = read_navmesh_xml(resolved_candidate)
        except Exception:
            continue
        if len(mesh_obj.data.polygons) != len(navmesh.polygons):
            continue
        score = _mesh_bounds_score(mesh_obj, navmesh)
        # The tolerance covers XML float rounding but deliberately does not
        # guess after a real geometry move or a neighbouring GTA tile.
        if score <= 0.01:
            best_candidates.append((score, resolved_candidate, navmesh))
    if len(best_candidates) == 1:
        return best_candidates[0]
    return None


def _auto_source_lookup_enabled(scene=None):
    try:
        scene = scene or bpy.context.scene
        return bool(getattr(scene.cw_navmesh_settings, "auto_find_source_xml", False))
    except (AttributeError, RuntimeError):
        return False


def _find_matching_source_xml(mesh_obj, export_filepath):
    for stored_source in _stored_source_values(mesh_obj):
        stored_path = _resolve_source_value(stored_source, export_filepath)
        # A path chosen by the user is an explicit authority, including the
        # rare but valid case of intentionally duplicated source data.
        if stored_path:
            return stored_path

    root_name = mesh_obj.parent.name if mesh_obj.parent else Path(export_filepath).stem
    if not _generic_navmesh_name(root_name):
        direct = _direct_source_xml_for_root(root_name, export_filepath)
        if direct and not _source_used_by_other_mesh(direct, mesh_obj):
            return direct
    if _auto_source_lookup_enabled():
        best = _best_source_xml_for_mesh(mesh_obj, export_filepath, exclude_used=True)
        if best:
            return best[1]
    return None


def _load_source_navmesh_for_export(mesh_obj, export_filepath):
    source_xml = _find_matching_source_xml(mesh_obj, export_filepath)
    if not source_xml:
        return None
    try:
        return read_navmesh_xml(source_xml)
    except Exception:
        return None


def _attach_source_xml_if_missing(mesh_obj, export_filepath):
    for stored_source in _stored_source_values(mesh_obj):
        try:
            path = _resolve_source_value(stored_source, export_filepath)
            if path and path.exists():
                navmesh = read_navmesh_xml(path)
                _apply_source_navmesh_to_mesh(mesh_obj, path, navmesh)
                return path, navmesh
        except Exception:
            continue

    if not _auto_source_lookup_enabled():
        return None, None
    best = _best_source_xml_for_mesh(mesh_obj, export_filepath, exclude_used=True)
    if not best:
        return None, None
    _score, source_path, navmesh = best
    _apply_source_navmesh_to_mesh(mesh_obj, source_path, navmesh)
    return source_path, navmesh


def _auto_attach_source_xml(mesh_obj):
    if not _is_navmesh_mesh(mesh_obj):
        return False
    for stored_source in _stored_source_values(mesh_obj):
        source_xml = _resolve_source_value(stored_source, mesh_obj.name + ".ynv.xml")
        if not source_xml:
            continue
        try:
            navmesh = read_navmesh_xml(source_xml)
            matched = _apply_source_navmesh_to_mesh(mesh_obj, str(source_xml), navmesh)
        except Exception:
            continue
        mesh_obj["ynv_auto_source_checked"] = True
        mesh_obj["ynv_auto_source_matched_polygons"] = matched
        return True

    if not _auto_source_lookup_enabled():
        return False
    probe_name = mesh_obj.parent.name if mesh_obj.parent else mesh_obj.name
    source_xml = _find_matching_source_xml(mesh_obj, probe_name + ".ynv.xml")
    if not source_xml:
        area_id = _get_sollumz_navmesh_area_id(mesh_obj, 0)
        content_flags = _get_sollumz_navmesh_content_flags(mesh_obj, "")
        if area_id:
            mesh_obj["ynv_area_id"] = area_id
            if mesh_obj.parent:
                mesh_obj.parent["ynv_area_id"] = area_id
        if content_flags:
            mesh_obj["ynv_content_flags"] = content_flags
            if mesh_obj.parent:
                mesh_obj.parent["ynv_content_flags"] = content_flags
        return False

    try:
        navmesh = read_navmesh_xml(source_xml)
        matched = _apply_source_navmesh_to_mesh(mesh_obj, str(source_xml), navmesh)
    except Exception:
        return False

    mesh_obj["ynv_auto_source_checked"] = True
    mesh_obj["ynv_auto_source_matched_polygons"] = matched
    return True


def _repair_scene_navmesh_sources(context):
    repaired = 0
    used = set()
    meshes = sorted([obj for obj in context.scene.objects if _is_navmesh_mesh(obj)], key=_object_sort_key)
    for mesh_obj in meshes:
        # The operator is explicit, but still refuses an ambiguous automatic
        # match.  Existing manual paths are handled below instead of replaced.
        if _stored_source_values(mesh_obj):
            continue
        best = _best_source_xml_for_mesh(mesh_obj, mesh_obj.name + ".ynv.xml", exclude_used=False, exclude_paths=used)
        if not best:
            continue
        _, source_xml, navmesh = best
        matched = _apply_source_navmesh_to_mesh(mesh_obj, str(source_xml), navmesh)
        mesh_obj["ynv_auto_source_checked"] = True
        mesh_obj["ynv_auto_source_matched_polygons"] = matched
        try:
            used.add(source_xml.resolve())
        except OSError:
            pass
        repaired += 1
    return repaired


@persistent
def _cw_navmesh_auto_source_handler(scene, depsgraph):
    _patch_sollumz_importer()
    for obj in scene.objects:
        if obj.type != "MESH":
            continue
        if _is_navmesh_mesh(obj):
            should_auto_attach = _auto_source_lookup_enabled(scene) and not obj.get("ynv_auto_source_checked")
            attached = _auto_attach_source_xml(obj) if should_auto_attach else False
            if should_auto_attach:
                obj["ynv_auto_source_checked"] = True
            if attached and hasattr(scene, "cw_navmesh_settings"):
                settings = scene.cw_navmesh_settings
                settings.area_id = _get_int_prop(obj, "ynv_area_id", 0)
                settings.content_flags = str(obj.get("ynv_content_flags", DEFAULT_CONTENT_FLAGS))
                settings.source_xml_path = str(obj.get("ynv_source_xml", ""))
            elif hasattr(scene, "cw_navmesh_settings"):
                settings = scene.cw_navmesh_settings
                area_id = _get_int_prop(obj, "ynv_area_id", _get_sollumz_navmesh_area_id(obj, 0))
                if area_id and not int(settings.area_id):
                    settings.area_id = area_id
                content_flags = str(obj.get("ynv_content_flags", "")) or _get_sollumz_navmesh_content_flags(obj, "")
                if content_flags and not str(settings.content_flags).strip():
                    settings.content_flags = content_flags


def _is_navmesh_mesh(obj):
    return (
        obj
        and obj.type == "MESH"
        and (
            obj.get(YNV_MESH_TAG)
            or _get_sollum_type(obj) == SOLLUMZ_NAVMESH_POLY_MESH
            or obj.name == "NavMesh Poly Mesh"
        )
    )


def _find_navmesh_mesh_from_root(obj):
    if not obj:
        return None
    for child in _children_recursive(obj):
        if _is_navmesh_mesh(child):
            return child
    return None


def _navmesh_root(mesh_obj):
    if mesh_obj and mesh_obj.parent:
        return mesh_obj.parent
    return None


def _child_empty(root_obj, name):
    if root_obj:
        for child in root_obj.children:
            if child.name == name:
                return child
    empty = _new_empty(name)
    if root_obj:
        empty.parent = root_obj
    bpy.context.collection.objects.link(empty)
    return empty


def _selected_navmesh_object(context):
    active = getattr(context, "object", None) or getattr(context, "active_object", None)
    if not active and getattr(context, "view_layer", None):
        active = context.view_layer.objects.active
    if _is_navmesh_mesh(active):
        return active
    active_navmesh = _find_navmesh_mesh_from_root(active)
    if active_navmesh:
        return active_navmesh

    for obj in getattr(context, "selected_objects", []) or []:
        if _is_navmesh_mesh(obj):
            return obj
        selected_navmesh = _find_navmesh_mesh_from_root(obj)
        if selected_navmesh:
            return selected_navmesh

    navmesh_objects = [obj for obj in bpy.data.objects if _is_navmesh_mesh(obj)]
    if len(navmesh_objects) == 1:
        return navmesh_objects[0]

    raise ValueError("Select the imported YNV navmesh mesh before exporting.")


def _children_recursive(obj):
    children = []
    for child in obj.children:
        children.append(child)
        children.extend(_children_recursive(child))
    return children


def _scene_navmesh_meshes(context):
    meshes = []
    seen = set()
    for obj in getattr(context, "scene", bpy.context.scene).objects:
        mesh_obj = obj if _is_navmesh_mesh(obj) else _find_navmesh_mesh_from_root(obj)
        if mesh_obj and mesh_obj.name not in seen:
            meshes.append(mesh_obj)
            seen.add(mesh_obj.name)
    return sorted(meshes, key=_object_sort_key)


def _object_sort_key(obj):
    match = re.search(r"(\d+)$", obj.name)
    if match:
        return (obj.name[: match.start()], int(match.group(1)))
    return (obj.name, -1)


def _active_polygon_index(mesh_obj):
    if not mesh_obj or mesh_obj.type != "MESH":
        return 0
    if mesh_obj.mode == "EDIT":
        try:
            import bmesh

            bm = bmesh.from_edit_mesh(mesh_obj.data)
            bm.faces.ensure_lookup_table()
            active_face = bm.faces.active
            if active_face is not None and active_face.is_valid:
                return active_face.index
            selected = [face.index for face in bm.faces if face.select]
            if selected:
                return selected[0]
        except Exception:
            pass
    active = getattr(mesh_obj.data.polygons, "active", -1)
    if active >= 0:
        return active
    selected = [poly.index for poly in mesh_obj.data.polygons if poly.select]
    if selected:
        return selected[0]
    return 0


def _split_rows(value):
    return [row.strip() for row in (value or "").splitlines() if row.strip()]


def _normalize_flags_text(value):
    parts = [int(part) for part in re.split(r"[\s,]+", value.strip()) if part]
    if len(parts) not in (6, 7):
        raise ValueError("Polygon Flags must contain 6 or 7 integers.")
    return parts


def _flag_bit_location(bit):
    if 0 <= bit <= 15:
        return bit // 8, bit % 8
    if bit == 16:
        return 6, 0
    if 17 <= bit <= 24:
        return 2, bit - 17
    if 25 <= bit <= 32:
        return 3, bit - 25
    raise ValueError(f"Unsupported polygon flag bit {bit}")


def _polygon_flag_bits(flags):
    values = [int(value) for value in flags[:7]]
    while len(values) < 7:
        values.append(0)
    field = 0
    for bit in range(33):
        byte_index, bit_index = _flag_bit_location(bit)
        if values[byte_index] & (1 << bit_index):
            field |= 1 << bit
    return field


def _flag_enabled(flags, bit):
    return bool(_polygon_flag_bits(flags) & (1 << bit))


def _set_flag_enabled(flags, bit, enabled):
    original_len = len(flags)
    values = [int(value) for value in flags[:7]]
    while len(values) < 7:
        values.append(0)
    byte_index, bit_index = _flag_bit_location(bit)
    if enabled:
        values[byte_index] |= 1 << bit_index
    else:
        values[byte_index] &= ~(1 << bit_index)
    if original_len >= 7 or values[6]:
        return values
    return values[:6]


def _set_polygon_flag_text(settings, flags):
    settings.polygon_flags = " ".join(str(value) for value in flags)


def _apply_current_flags_to_active_polygon(context, settings):
    if not context:
        return
    try:
        mesh_obj = _selected_navmesh_object(context)
    except Exception:
        return
    if not mesh_obj or mesh_obj.type != "MESH":
        return
    try:
        flags = _normalize_flags_text(settings.polygon_flags)
    except ValueError:
        return

    polygon_flags, polygon_edges, polygon_edges_flags, polygon_portals = _ensure_polygon_metadata(mesh_obj)
    index = int(settings.polygon_index)
    if index < 0 or index >= len(mesh_obj.data.polygons):
        index = _active_polygon_index(mesh_obj)
    if index < 0 or index >= len(mesh_obj.data.polygons):
        return

    was_edit_mode = mesh_obj.mode == "EDIT"
    if was_edit_mode:
        try:
            bpy.ops.object.mode_set(mode="OBJECT")
        except Exception:
            return

    try:
        material = _create_material_for_flags(flags)
        material_index = next((idx for idx, mat in enumerate(mesh_obj.data.materials) if mat == material), None)
        if material_index is None:
            mesh_obj.data.materials.append(material)
            material_index = len(mesh_obj.data.materials) - 1
        polygon_flags[index] = flags
        mesh_obj.data.polygons[index].material_index = material_index
        _write_polygon_metadata(
            mesh_obj,
            polygon_flags,
            polygon_edges,
            polygon_edges_flags,
            polygon_portals,
        )
        mesh_obj.data.update()
    finally:
        if was_edit_mode:
            try:
                bpy.ops.object.mode_set(mode="EDIT")
            except Exception:
                pass


def _sync_flag_checkboxes_from_flags(settings, flags):
    global _SYNCING_FLAG_CHECKBOXES
    _SYNCING_FLAG_CHECKBOXES = True
    try:
        for attr_name, _label, bit in POLYGON_FLAG_BITS:
            setattr(settings, attr_name, _flag_enabled(flags, bit))
    finally:
        _SYNCING_FLAG_CHECKBOXES = False


def _make_flag_checkbox_update(bit, attr_name):
    def update(self, context):
        if _SYNCING_FLAG_CHECKBOXES:
            return
        try:
            flags = _normalize_flags_text(self.polygon_flags)
        except ValueError:
            flags = [0, 0, 0, 0, 0, 0]
        _set_polygon_flag_text(self, _set_flag_enabled(flags, bit, bool(getattr(self, attr_name))))
        _apply_current_flags_to_active_polygon(context, self)

    return update


def _load_polygon_editor_from_mesh(context, mesh_obj, polygon_index=None, ensure_metadata=True):
    settings = _scene_settings(context)
    was_edit_mode = mesh_obj.mode == "EDIT"
    if was_edit_mode:
        mesh_obj.update_from_editmode()
    if ensure_metadata:
        polygon_flags, polygon_edges, polygon_edges_flags, polygon_portals = _ensure_polygon_metadata(mesh_obj)
    else:
        polygon_flags, polygon_edges, polygon_edges_flags, polygon_portals = _read_polygon_metadata(mesh_obj)
    if polygon_index is None:
        polygon_index = _active_polygon_index(mesh_obj)
    polygon_index = max(0, min(int(polygon_index), max(0, len(mesh_obj.data.polygons) - 1)))
    settings.polygon_index = polygon_index
    if polygon_index < len(polygon_flags):
        _set_polygon_flag_text(settings, polygon_flags[polygon_index])
        _sync_flag_checkboxes_from_flags(settings, polygon_flags[polygon_index])
    if polygon_index < len(polygon_edges):
        settings.polygon_edges = "\n".join(polygon_edges[polygon_index])
    if polygon_index < len(polygon_edges_flags):
        settings.polygon_edges_flags = "\n".join(polygon_edges_flags[polygon_index])
    if polygon_index < len(polygon_portals):
        settings.polygon_portals = " ".join(str(value) for value in polygon_portals[polygon_index])


def _deferred_load_polygon_editor(scene_name, object_name, polygon_index):
    key = (scene_name, object_name)
    try:
        scene = bpy.data.scenes.get(scene_name)
        mesh_obj = bpy.data.objects.get(object_name)
        if scene and mesh_obj:
            _load_polygon_editor_from_mesh(scene, mesh_obj, polygon_index, ensure_metadata=True)
    finally:
        _PENDING_POLYGON_EDITOR_LOADS.discard(key)
    return None


def _deferred_sync_settings(scene_name, object_name):
    key = (scene_name, object_name)
    try:
        scene = bpy.data.scenes.get(scene_name)
        mesh_obj = bpy.data.objects.get(object_name)
        if scene and mesh_obj:
            _sync_settings_from_mesh(scene, mesh_obj)
    finally:
        _PENDING_SETTINGS_SYNCS.discard(key)
    return None


def _schedule_settings_sync(scene, mesh_obj):
    key = (scene.name, mesh_obj.name)
    if key in _PENDING_SETTINGS_SYNCS:
        return
    _PENDING_SETTINGS_SYNCS.add(key)
    bpy.app.timers.register(
        lambda: _deferred_sync_settings(scene.name, mesh_obj.name),
        first_interval=0.01,
    )


def _schedule_polygon_editor_load(scene, mesh_obj, polygon_index):
    key = (scene.name, mesh_obj.name)
    if key in _PENDING_POLYGON_EDITOR_LOADS:
        return
    _PENDING_POLYGON_EDITOR_LOADS.add(key)
    bpy.app.timers.register(
        lambda: _deferred_load_polygon_editor(scene.name, mesh_obj.name, polygon_index),
        first_interval=0.01,
    )


def _apply_polygon_editor_to_mesh(context, mesh_obj):
    settings = _scene_settings(context)
    polygon_flags, polygon_edges, polygon_edges_flags, polygon_portals = _ensure_polygon_metadata(mesh_obj)
    index = int(settings.polygon_index)
    if index < 0 or index >= len(mesh_obj.data.polygons):
        raise ValueError("Polygon index is outside the mesh polygon range.")
    vertex_count = len(mesh_obj.data.polygons[index].vertices)
    flags = _normalize_flags_text(settings.polygon_flags)
    edges = _split_rows(settings.polygon_edges)
    edges_flags = _split_rows(settings.polygon_edges_flags)
    if len(edges) != vertex_count:
        raise ValueError(f"Polygon {index} needs {vertex_count} Edges rows.")
    if len(edges_flags) != vertex_count:
        raise ValueError(f"Polygon {index} needs {vertex_count} EdgesFlags rows.")
    for edge in edges + edges_flags:
        if not re.match(r"^\d+:\d+,\s*\d+:\d+$", edge):
            raise ValueError(f"Invalid edge row: {edge}")

    polygon_flags[index] = flags
    _sync_flag_checkboxes_from_flags(settings, flags)
    polygon_edges[index] = edges
    polygon_edges_flags[index] = edges_flags
    polygon_portals[index] = [int(value) for value in re.split(r"[\s,]+", settings.polygon_portals.strip()) if value]
    _write_polygon_metadata(mesh_obj, polygon_flags, polygon_edges, polygon_edges_flags, polygon_portals)
    material = _create_material_for_flags(flags)
    material_index = next((idx for idx, mat in enumerate(mesh_obj.data.materials) if mat == material), None)
    if material_index is None:
        mesh_obj.data.materials.append(material)
        material_index = len(mesh_obj.data.materials) - 1
    mesh_obj.data.polygons[index].material_index = material_index


def _selected_polygon_indices(mesh_obj):
    if not mesh_obj or mesh_obj.type != "MESH":
        return []
    if mesh_obj.mode == "EDIT":
        try:
            import bmesh

            bm = bmesh.from_edit_mesh(mesh_obj.data)
            bm.faces.ensure_lookup_table()
            return [face.index for face in bm.faces if face.select]
        except Exception:
            pass
    return [polygon.index for polygon in mesh_obj.data.polygons if polygon.select]


def _set_polygon_flags(mesh_obj, polygon_indices, flags):
    polygon_flags, polygon_edges, polygon_edges_flags, polygon_portals = _ensure_polygon_metadata(mesh_obj)
    material = _create_material_for_flags(flags)
    material_index = next((idx for idx, mat in enumerate(mesh_obj.data.materials) if mat == material), None)
    if material_index is None:
        mesh_obj.data.materials.append(material)
        material_index = len(mesh_obj.data.materials) - 1

    for index in polygon_indices:
        if 0 <= index < len(mesh_obj.data.polygons):
            polygon_flags[index] = list(flags)
            mesh_obj.data.polygons[index].material_index = material_index
    _write_polygon_metadata(mesh_obj, polygon_flags, polygon_edges, polygon_edges_flags, polygon_portals)


def _build_local_edge_links(mesh_obj, area_id, existing_edges=None):
    mesh = mesh_obj.data
    metadata = _read_polygon_metadata(mesh_obj)
    if existing_edges is None:
        existing_edges = metadata[1]
    world_vertices = [mesh_obj.matrix_world @ vertex.co for vertex in mesh.vertices]
    edge_map = {}
    face_edge_keys = []

    def vertex_key(vec):
        return (round(float(vec.x), 5), round(float(vec.y), 5), round(float(vec.z), 5))

    for polygon in mesh.polygons:
        vertices = list(polygon.vertices)
        keys = []
        for edge_index, start_index in enumerate(vertices):
            end_index = vertices[(edge_index + 1) % len(vertices)]
            start_key = vertex_key(world_vertices[start_index])
            end_key = vertex_key(world_vertices[end_index])
            key = tuple(sorted((start_key, end_key)))
            keys.append(key)
            edge_map.setdefault(key, []).append((polygon.index, edge_index))
        face_edge_keys.append(keys)

    polygon_edges = []
    changed_edges = 0
    for polygon in mesh.polygons:
        rows = []
        old_rows = existing_edges[polygon.index] if existing_edges and polygon.index < len(existing_edges) else []
        for edge_index, key in enumerate(face_edge_keys[polygon.index]):
            old_edge = old_rows[edge_index] if edge_index < len(old_rows) else DEFAULT_EDGE
            linked_faces = [face_index for face_index, _ in edge_map.get(key, []) if face_index != polygon.index]
            if linked_faces:
                linked_face = linked_faces[0]
                new_edge = f"{area_id}:{linked_face}, {area_id}:{linked_face}"
            else:
                new_edge = old_edge if old_edge != DEFAULT_EDGE else DEFAULT_EDGE
            if new_edge != old_edge:
                changed_edges += 1
            rows.append(new_edge)
        polygon_edges.append(rows)
    _write_edge_links(mesh_obj, polygon_edges, metadata)
    linked_edges = sum(1 for rows in polygon_edges for edge in rows if edge != DEFAULT_EDGE)
    total_edges = sum(len(rows) for rows in polygon_edges)
    return linked_edges, total_edges, changed_edges


def _navmesh_area_id(mesh_obj, source_navmesh=None):
    area_id = _get_int_prop(mesh_obj, "ynv_area_id", 0)
    if not area_id and mesh_obj.parent:
        area_id = _get_int_prop(mesh_obj.parent, "ynv_area_id", 0)
    if not area_id:
        area_id = _get_sollumz_navmesh_area_id(mesh_obj, 0)
    if source_navmesh and source_navmesh.area_id:
        area_id = source_navmesh.area_id
    return int(area_id)


def _edge_vertex_key(vec, precision=EDGE_MATCH_PRECISION):
    return (round(float(vec.x), precision), round(float(vec.y), precision), round(float(vec.z), precision))


def _edge_position_key(world_vertices, start_index, end_index, precision=EDGE_MATCH_PRECISION):
    start_key = _edge_vertex_key(world_vertices[start_index], precision)
    end_key = _edge_vertex_key(world_vertices[end_index], precision)
    return tuple(sorted((start_key, end_key)))


def _boundary_edge_records(mesh_obj):
    mesh = mesh_obj.data
    world_vertices = [mesh_obj.matrix_world @ vertex.co for vertex in mesh.vertices]
    edge_users = {}
    face_edge_keys = []
    for polygon in mesh.polygons:
        vertices = list(polygon.vertices)
        keys = []
        for edge_index, start_index in enumerate(vertices):
            end_index = vertices[(edge_index + 1) % len(vertices)]
            key = _edge_position_key(world_vertices, start_index, end_index)
            keys.append(key)
            edge_users.setdefault(key, []).append((polygon.index, edge_index))
        face_edge_keys.append(keys)

    records = {}
    for polygon in mesh.polygons:
        for edge_index, key in enumerate(face_edge_keys[polygon.index]):
            if len(edge_users.get(key, [])) == 1:
                records[(polygon.index, edge_index)] = key
    return records


def _write_edge_links(mesh_obj, polygon_edges, metadata=None):
    """Persist rebuilt edge rows without losing the v2 face metadata records."""
    if metadata is None:
        polygon_flags, _old_edges, polygon_edges_flags, polygon_portals = _read_polygon_metadata(mesh_obj)
    else:
        polygon_flags, _old_edges, polygon_edges_flags, polygon_portals = metadata
    return _write_polygon_metadata(
        mesh_obj,
        polygon_flags,
        polygon_edges,
        polygon_edges_flags,
        polygon_portals,
    )


def _build_cross_cell_index(mesh_area_pairs):
    index = {}
    for mesh_obj, area_id in mesh_area_pairs:
        if not area_id:
            continue
        for (polygon_index, edge_index), key in _boundary_edge_records(mesh_obj).items():
            # Keep the counterpart's exact corner and object so a one-cell
            # rebuild can update its loaded neighbour reciprocally.
            value = (int(area_id), polygon_index, edge_index, mesh_obj)
            if key in index:
                index[key].append(value)
            else:
                index[key] = [value]
    duplicates = {key for key, values in index.items() if len(values) > 2}
    return index, duplicates


def _apply_cross_cell_edge_links(mesh_obj, area_id, cross_index, duplicate_keys):
    if not area_id:
        return 0, 0
    polygon_edge_keys = _boundary_edge_records(mesh_obj)
    current_metadata = _read_polygon_metadata(mesh_obj)
    polygon_edges = [list(rows) for rows in current_metadata[1]]
    neighbour_states = {}

    def neighbour_state(other_mesh):
        state = neighbour_states.get(other_mesh.name)
        if state is None:
            metadata = _read_polygon_metadata(other_mesh)
            state = {
                "mesh": other_mesh,
                "metadata": metadata,
                "edges": [list(rows) for rows in metadata[1]],
                "changed": False,
            }
            neighbour_states[other_mesh.name] = state
        return state

    changed = 0
    matched = 0
    for (polygon_index, edge_index), key in polygon_edge_keys.items():
        if key in duplicate_keys:
            continue
        matches = [
            (match_area, match_poly, match_edge, match_mesh)
            for match_area, match_poly, match_edge, match_mesh in cross_index.get(key, [])
            if match_mesh is not mesh_obj
        ]
        if len(matches) != 1:
            continue
        match_area, match_poly, match_edge, match_mesh = matches[0]
        # Duplicate AreaIDs identify an invalid scene layout.  Do not forge a
        # same-cell cross reference; Export All reports those duplicates.
        if match_area == area_id:
            continue
        counterpart = neighbour_state(match_mesh)
        if match_poly >= len(counterpart["edges"]) or match_edge >= len(counterpart["edges"][match_poly]):
            continue
        new_edge = _edge_row(match_area, match_poly)
        old_edge = polygon_edges[polygon_index][edge_index]
        if old_edge != new_edge:
            polygon_edges[polygon_index][edge_index] = new_edge
            changed += 1

        reciprocal_edge = _edge_row(area_id, polygon_index)
        if counterpart["edges"][match_poly][match_edge] != reciprocal_edge:
            counterpart["edges"][match_poly][match_edge] = reciprocal_edge
            counterpart["changed"] = True
            changed += 1
        matched += 1

    if changed:
        _write_edge_links(mesh_obj, polygon_edges, current_metadata)
    for state in neighbour_states.values():
        if state["changed"]:
            _write_edge_links(state["mesh"], state["edges"], state["metadata"])
    return matched, changed


def _rebuild_edge_links_from_geometry(mesh_obj, area_id, loaded_area_ids=None, cross_index=None, duplicate_keys=None):
    if not area_id:
        raise ValueError("Set AreaID before rebuilding edge links.")
    loaded_area_ids = set(loaded_area_ids or [])
    duplicate_keys = set(duplicate_keys or [])
    mesh = mesh_obj.data
    world_vertices = [mesh_obj.matrix_world @ vertex.co for vertex in mesh.vertices]
    edge_users = {}
    face_edge_keys = []

    for polygon in mesh.polygons:
        vertices = list(polygon.vertices)
        keys = []
        for edge_index, start_index in enumerate(vertices):
            end_index = vertices[(edge_index + 1) % len(vertices)]
            key = _edge_position_key(world_vertices, start_index, end_index)
            keys.append(key)
            edge_users.setdefault(key, []).append((polygon.index, edge_index))
        face_edge_keys.append(keys)

    current_metadata = _read_polygon_metadata(mesh_obj)
    existing_edges = current_metadata[1]
    polygon_edges = []
    neighbour_states = {}

    def neighbour_state(other_mesh):
        state = neighbour_states.get(other_mesh.name)
        if state is None:
            metadata = _read_polygon_metadata(other_mesh)
            state = {
                "mesh": other_mesh,
                "metadata": metadata,
                "edges": [list(rows) for rows in metadata[1]],
                "changed": False,
            }
            neighbour_states[other_mesh.name] = state
        return state

    internal_links = 0
    cross_links = 0
    preserved_external = 0
    open_edges = 0
    changed_edges = 0
    ambiguous_edges = 0
    current_changed = False

    for polygon in mesh.polygons:
        rows = []
        old_rows = existing_edges[polygon.index] if polygon.index < len(existing_edges) else []
        for edge_index, key in enumerate(face_edge_keys[polygon.index]):
            old_edge = old_rows[edge_index] if edge_index < len(old_rows) else DEFAULT_EDGE
            linked_faces = [face_index for face_index, _ in edge_users.get(key, []) if face_index != polygon.index]
            if linked_faces:
                new_edge = _edge_row(area_id, linked_faces[0])
                internal_links += 1
            else:
                new_edge = None
                if cross_index and key not in duplicate_keys:
                    matches = [
                        (match_area, match_poly, match_edge, match_mesh)
                        for match_area, match_poly, match_edge, match_mesh in cross_index.get(key, [])
                        if match_mesh is not mesh_obj
                    ]
                    if len(matches) == 1 and matches[0][0] != area_id:
                        match_area, match_poly, match_edge, match_mesh = matches[0]
                        counterpart = neighbour_state(match_mesh)
                        if (
                            0 <= match_poly < len(counterpart["edges"])
                            and 0 <= match_edge < len(counterpart["edges"][match_poly])
                        ):
                            new_edge = _edge_row(match_area, match_poly)
                            reciprocal_edge = _edge_row(area_id, polygon.index)
                            if counterpart["edges"][match_poly][match_edge] != reciprocal_edge:
                                counterpart["edges"][match_poly][match_edge] = reciprocal_edge
                                counterpart["changed"] = True
                                changed_edges += 1
                            cross_links += 1
                        else:
                            ambiguous_edges += 1
                    elif len(matches) > 1:
                        ambiguous_edges += 1
                    elif len(matches) == 1:
                        # A neighbour with the same AreaID cannot be encoded as
                        # a distinct GTA navmesh cell safely.
                        ambiguous_edges += 1
                elif key in duplicate_keys:
                    ambiguous_edges += 1

                if new_edge is None:
                    old_area, old_poly = _first_edge_ref(old_edge)
                    if (
                        old_area is not None
                        and old_poly is not None
                        and old_area != 16383
                        and old_poly != 16383
                        and old_area != area_id
                        and old_area not in loaded_area_ids
                    ):
                        new_edge = _edge_row(old_area, old_poly)
                        preserved_external += 1
                    else:
                        new_edge = DEFAULT_EDGE
                        open_edges += 1
            if new_edge != old_edge:
                changed_edges += 1
                current_changed = True
            rows.append(new_edge)
        polygon_edges.append(rows)

    if current_changed:
        _write_edge_links(mesh_obj, polygon_edges, current_metadata)
    for state in neighbour_states.values():
        if state["changed"]:
            _write_edge_links(state["mesh"], state["edges"], state["metadata"])
    return {
        "internal": internal_links,
        "cross": cross_links,
        "preserved_external": preserved_external,
        "open": open_edges,
        "changed": changed_edges,
        "ambiguous": ambiguous_edges,
    }


def _read_collection_items(mesh_obj, source_navmesh=None):
    portals = []
    points = []
    root_obj = _navmesh_root(mesh_obj)
    if root_obj:
        objects = _children_recursive(root_obj)
    elif source_navmesh:
        return list(source_navmesh.portals), list(source_navmesh.points)
    else:
        collections = mesh_obj.users_collection or []
        objects = []
        for collection in collections:
            objects.extend(collection.objects)

    portal_objects = []
    point_objects = []
    for obj in objects:
        sollum_type = _get_sollum_type(obj)
        if obj.get(YNV_PORTAL_TAG) or sollum_type == SOLLUMZ_NAVMESH_PORTAL:
            portal_objects.append(obj)
        elif obj.get(YNV_POINT_TAG) or sollum_type == SOLLUMZ_NAVMESH_POINT:
            point_objects.append(obj)

    for index, obj in enumerate(sorted(portal_objects, key=_object_sort_key)):
        source_portal = source_navmesh.portals[index] if source_navmesh and index < len(source_navmesh.portals) else None
        from_child = next((child for child in obj.children if child.name.lower().startswith("from")), None)
        to_child = next((child for child in obj.children if child.name.lower().startswith("to")), None)
        if from_child and to_child:
            position_from = _world_vec(from_child)
            position_to = _world_vec(to_child)
        else:
            stored_center = _tuple_to_vec(obj.get("ynv_center", obj.location))
            offset = _vec_sub(_world_vec(obj), stored_center)
            position_from = _vec_add(_tuple_to_vec(obj.get("ynv_position_from", obj.location)), offset)
            position_to = _vec_add(_tuple_to_vec(obj.get("ynv_position_to", obj.location)), offset)
        portal = Portal(
            type=_as_int(
                _read_portal_property(obj, "portal_type", "ynv_type", source_portal.type if source_portal else 0),
                source_portal.type if source_portal else 0,
            ),
            angle=_as_float(
                _read_portal_property(
                    obj,
                    "angle",
                    "ynv_angle",
                    source_portal.angle if source_portal else _world_z_angle(obj),
                ),
                source_portal.angle if source_portal else _world_z_angle(obj),
            ),
            poly_from=_as_int(
                _read_portal_property(obj, "poly_from", "ynv_poly_from", source_portal.poly_from if source_portal else 0),
                source_portal.poly_from if source_portal else 0,
            ),
            poly_to=_as_int(
                _read_portal_property(obj, "poly_to", "ynv_poly_to", source_portal.poly_to if source_portal else 0),
                source_portal.poly_to if source_portal else 0,
            ),
            position_from=position_from,
            position_to=position_to,
        )
        # Migrate old custom-property-only objects and keep both editors in sync.
        _write_sollumz_portal_properties(obj, portal)
        portals.append(portal)

    for index, obj in enumerate(sorted(point_objects, key=_object_sort_key)):
        source_point = source_navmesh.points[index] if source_navmesh and index < len(source_navmesh.points) else None
        point = Point(
            type=_as_int(_read_point_type(obj, source_point.type if source_point else 0), source_point.type if source_point else 0),
            # Sollumz defines a point's heading by its object transform, not an RNA field.
            angle=_world_z_angle(obj, source_point.angle if source_point else obj.get("ynv_angle", 0.0)),
            position=_world_vec(obj),
        )
        _write_sollumz_point_properties(obj, point)
        points.append(point)
    return portals, points


def _portal_objects_for_mesh(mesh_obj):
    root_obj = _navmesh_root(mesh_obj)
    if root_obj:
        objects = _children_recursive(root_obj)
    else:
        objects = [obj for collection in (mesh_obj.users_collection or []) for obj in collection.objects]
    return sorted(
        [
            obj
            for obj in objects
            if obj.get(YNV_PORTAL_TAG) or _get_sollum_type(obj) == SOLLUMZ_NAVMESH_PORTAL
        ],
        key=_object_sort_key,
    )


def _reference_face_ids_from_owner(owner, key, fallback):
    values = _safe_json_loads(owner.get(key, "[]") if owner else "[]", [])
    if not isinstance(values, list) or not values:
        return list(fallback)
    return [_int_or_default(value, NO_SOURCE_POLYGON) for value in values]


def _sync_portal_objects(mesh_obj, portals):
    """Persist reindexed portal PolyFrom/PolyTo values for the next export.

    Portal polygon fields are positions, just like local edge rows.  Store the
    face-id order that those positions refer to on every editable portal so a
    later face reorder cannot silently point a portal at a different polygon.
    """
    face_ids, _source_indices = _current_face_identity(mesh_obj)
    for obj, portal in zip(_portal_objects_for_mesh(mesh_obj), portals):
        _write_sollumz_portal_properties(obj, portal)
        obj[YNV_PORTAL_REFERENCE_FACE_IDS] = json.dumps(face_ids, separators=(",", ":"))


def _remap_portal_objects_to_current_faces(mesh_obj, portals, fallback_reference_face_ids, current_face_ids):
    """Translate each portal's PolyFrom/PolyTo from its saved face order."""
    portal_objects = _portal_objects_for_mesh(mesh_obj)
    remapped = []
    changed = 0
    for index, portal in enumerate(portals):
        reference_face_ids = fallback_reference_face_ids
        if index < len(portal_objects):
            reference_face_ids = _reference_face_ids_from_owner(
                portal_objects[index],
                YNV_PORTAL_REFERENCE_FACE_IDS,
                fallback_reference_face_ids,
            )
        values, remapped_count = _remap_portal_polygon_indices(
            [portal],
            reference_face_ids,
            current_face_ids,
        )
        remapped.extend(values)
        changed += remapped_count
    return remapped, changed


def _reconcile_polygon_portal_links(polygons, portals):
    """Keep Polygon.Portals and Portal.PolyFrom/PolyTo mutually consistent."""
    removed = 0
    added = 0
    portal_count = len(portals)
    for polygon in polygons:
        seen = set()
        links = []
        for raw_index in getattr(polygon, "portals", []) or []:
            index = _int_or_default(raw_index, NO_SOURCE_POLYGON)
            if index < 0 or index >= portal_count or index in seen:
                removed += 1
                continue
            seen.add(index)
            links.append(index)
        polygon.portals = links

    for portal_index, portal in enumerate(portals):
        for polygon_index in {int(portal.poly_from), int(portal.poly_to)}:
            if 0 <= polygon_index < len(polygons) and portal_index not in polygons[polygon_index].portals:
                polygons[polygon_index].portals.append(portal_index)
                added += 1
    return added, removed


def _sanitize_portals_for_polygon_count(polygons, portals):
    polygon_count = len(polygons)
    valid_portals = []
    portal_index_map = {}
    removed = 0

    for old_index, portal in enumerate(portals):
        if 0 <= int(portal.poly_from) < polygon_count and 0 <= int(portal.poly_to) < polygon_count:
            portal_index_map[old_index] = len(valid_portals)
            valid_portals.append(portal)
        else:
            removed += 1

    removed_refs = 0
    for polygon in polygons:
        remapped = []
        for portal_index in getattr(polygon, "portals", []) or []:
            try:
                old_index = int(portal_index)
            except (TypeError, ValueError):
                removed_refs += 1
                continue
            if old_index in portal_index_map:
                remapped.append(portal_index_map[old_index])
            else:
                removed_refs += 1
        polygon.portals = remapped

    return valid_portals, removed, removed_refs


def _polygon_centroid_key_from_vertices(vertices, precision=4):
    if not vertices:
        return None
    return tuple(
        round(sum(float(getattr(vertex, axis)) for vertex in vertices) / len(vertices), precision)
        for axis in ("x", "y", "z")
    )


def _polygon_centroid_key_from_tuples(vertices, precision=4):
    if not vertices:
        return None
    return tuple(round(sum(float(vertex[i]) for vertex in vertices) / len(vertices), precision) for i in range(3))


def _source_reference_face_ids(source_navmesh, source_indices, face_ids):
    """Map source polygon positions to the stable IDs of live Blender faces."""
    if not source_navmesh:
        return []
    reference_face_ids = [NO_SOURCE_POLYGON] * len(source_navmesh.polygons)
    for face_index, source_index in enumerate(source_indices):
        if 0 <= source_index < len(reference_face_ids) and face_index < len(face_ids):
            reference_face_ids[source_index] = face_ids[face_index]
    return reference_face_ids


def _seed_missing_metadata_from_source(mesh_obj, source_navmesh, face_ids):
    """Bind an old/manual mesh to a source only where geometry actually matches.

    This migration path is intentionally conservative.  It never appends a
    source-only polygon and never applies source edges to an unmatched face.
    """
    mesh = mesh_obj.data
    source_by_key = {}
    for source_index, polygon in enumerate(source_navmesh.polygons):
        source_by_key.setdefault(_polygon_centroid_key_from_vertices(polygon.vertices), []).append(source_index)

    used_source_indices = set()
    source_indices = []
    for face in mesh.polygons:
        vertices = [_tuple_to_vec(mesh_obj.matrix_world @ mesh.vertices[vertex_index].co) for vertex_index in face.vertices]
        candidates = [
            source_index
            for source_index in source_by_key.get(_polygon_centroid_key_from_vertices(vertices), [])
            if source_index not in used_source_indices
            and len(source_navmesh.polygons[source_index].vertices) == len(vertices)
        ]
        source_index = candidates[0] if candidates else NO_SOURCE_POLYGON
        if source_index >= 0:
            used_source_indices.add(source_index)
        source_indices.append(source_index)

    source_reference_face_ids = _source_reference_face_ids(source_navmesh, source_indices, face_ids)
    polygon_flags = []
    polygon_edges = []
    polygon_edges_flags = []
    polygon_portals = []
    for face_index, face in enumerate(mesh.polygons):
        source_index = source_indices[face_index]
        if source_index >= 0:
            source_polygon = source_navmesh.polygons[source_index]
            polygon_flags.append(list(source_polygon.flags))
            polygon_edges.append(list(source_polygon.edges))
            polygon_edges_flags.append(list(source_polygon.edges_flags))
            polygon_portals.append(list(getattr(source_polygon, "portals", [])))
        else:
            polygon_flags.append(_default_flags_for_face(mesh, face))
            polygon_edges.append([DEFAULT_EDGE] * len(face.vertices))
            polygon_edges_flags.append([DEFAULT_EDGE_FLAGS] * len(face.vertices))
            polygon_portals.append([])
    polygon_edges, _changed = _remap_local_edge_rows(
        polygon_edges,
        source_navmesh.area_id,
        source_reference_face_ids,
        face_ids,
    )
    return polygon_flags, polygon_edges, polygon_edges_flags, polygon_portals, source_indices


def _build_navmesh_for_export(mesh_obj, filepath):
    """Build a NavMesh from the live mesh without retaining removed source faces."""
    filepath = _ynv_xml_path(filepath)
    if mesh_obj.mode == "EDIT":
        mesh_obj.update_from_editmode()
    # Newly created/imported objects can have stale matrix_world values until
    # the dependency graph is evaluated.  Bounds, portal endpoints and points
    # must be read after that update, otherwise a direct import→export can
    # incorrectly expand a source YNV's original bounds to the world origin.
    try:
        bpy.context.view_layer.update()
    except (AttributeError, RuntimeError):
        pass
    mesh = mesh_obj.data
    had_metadata = bool(_metadata_records(mesh_obj)) or any(_legacy_polygon_metadata(mesh_obj))
    source_navmesh = _load_source_navmesh_for_export(mesh_obj, filepath)
    polygon_flags, polygon_edges, polygon_edges_flags, polygon_portals = _read_polygon_metadata(mesh_obj)
    face_ids, source_indices = _current_face_identity(mesh_obj)

    area_id = _get_int_prop(mesh_obj, "ynv_area_id", 0)
    if not area_id and mesh_obj.parent:
        area_id = _get_int_prop(mesh_obj.parent, "ynv_area_id", 0)
    if not area_id:
        area_id = _get_sollumz_navmesh_area_id(mesh_obj, 0)
    if source_navmesh and source_navmesh.area_id:
        area_id = source_navmesh.area_id
    if not area_id and hasattr(bpy.context.scene, "cw_navmesh_settings"):
        area_id = int(bpy.context.scene.cw_navmesh_settings.area_id)

    content_flags = str(mesh_obj.get("ynv_content_flags", "")).strip()
    if not content_flags and mesh_obj.parent:
        content_flags = str(mesh_obj.parent.get("ynv_content_flags", "")).strip()
    if not content_flags:
        content_flags = _get_sollumz_navmesh_content_flags(mesh_obj, "")
    if source_navmesh and source_navmesh.content_flags:
        content_flags = source_navmesh.content_flags
    if not content_flags and hasattr(bpy.context.scene, "cw_navmesh_settings"):
        content_flags = bpy.context.scene.cw_navmesh_settings.content_flags.strip()
    if not content_flags:
        content_flags = DEFAULT_CONTENT_FLAGS

    auto_build_edges = True
    if hasattr(bpy.context.scene, "cw_navmesh_settings"):
        auto_build_edges = bool(bpy.context.scene.cw_navmesh_settings.auto_build_edges_on_export)

    mesh_obj["ynv_area_id"] = area_id
    mesh_obj["ynv_content_flags"] = content_flags
    if mesh_obj.parent:
        mesh_obj.parent["ynv_area_id"] = area_id
        mesh_obj.parent["ynv_content_flags"] = content_flags

    warnings = []
    if not area_id:
        warnings.append("AreaID metadata is missing; AreaID was written as 0")
    if source_navmesh:
        _store_source_navmesh_snapshot(mesh_obj, source_navmesh)

    # A pre-v2 mesh may only have Sollumz face attributes.  Import source data
    # only for exact geometry matches; otherwise it is new live geometry.
    seeded_from_source = False
    if source_navmesh and not had_metadata and not any(index >= 0 for index in source_indices):
        (
            polygon_flags,
            polygon_edges,
            polygon_edges_flags,
            polygon_portals,
            source_indices,
        ) = _seed_missing_metadata_from_source(mesh_obj, source_navmesh, face_ids)
        seeded_from_source = any(index >= 0 for index in source_indices)
        if seeded_from_source:
            warnings.append("bound matching live faces to source metadata")
    elif not had_metadata:
        attribute_flags = _polygon_flags_from_sollumz_attributes(mesh_obj)
        if len(attribute_flags) == len(mesh.polygons):
            polygon_flags = attribute_flags
            warnings.append("read polygon flags from Sollumz face attributes")

    # All local edge positions address the last exported face order.  Reindex
    # them through the face IDs, replacing links to deleted faces with open
    # boundaries instead of reviving source geometry.
    reference_face_ids = _stored_reference_face_ids(mesh_obj)
    polygon_edges, remapped_edges = _remap_local_edge_rows(
        polygon_edges,
        area_id,
        reference_face_ids,
        face_ids,
    )
    if remapped_edges:
        warnings.append(f"reindexed {remapped_edges} local edge reference(s) after face changes")

    # A brand-new mesh has no edge data at all.  Auto-build only in that case;
    # an existing open source edge can be intentional and must stay open.
    if auto_build_edges and area_id and not had_metadata and not seeded_from_source and _edges_are_all_open(polygon_edges):
        _write_polygon_metadata(
            mesh_obj,
            polygon_flags,
            polygon_edges,
            polygon_edges_flags,
            polygon_portals,
            source_indices=source_indices,
        )
        linked_edges, total_edges, changed_edges = _build_local_edge_links(mesh_obj, area_id, polygon_edges)
        if changed_edges:
            polygon_flags, polygon_edges, polygon_edges_flags, polygon_portals = _read_polygon_metadata(mesh_obj)
            warnings.append(f"auto-built {changed_edges} local edge links; {linked_edges} of {total_edges} edges are linked")

    unmatched_source_faces = sum(1 for index in source_indices if index < 0)
    if source_navmesh and unmatched_source_faces:
        warnings.append(
            f"{unmatched_source_faces} current face(s) have no source mapping; their topology uses live/default metadata"
        )

    polygon_flags, polygon_edges, polygon_edges_flags, polygon_portals = _write_polygon_metadata(
        mesh_obj,
        polygon_flags,
        polygon_edges,
        polygon_edges_flags,
        polygon_portals,
        source_indices=source_indices,
    )

    polygons = []
    sanitized_edge_rows = False
    for index, face in enumerate(mesh.polygons):
        vertices = [
            _tuple_to_vec(mesh_obj.matrix_world @ mesh.vertices[vertex_index].co)
            for vertex_index in face.vertices
        ]
        flags = polygon_flags[index]
        edges = list(polygon_edges[index])
        edges_flags = list(polygon_edges_flags[index])
        edges, sanitized_edges = _sanitize_edge_links(edges, area_id, len(mesh.polygons))
        if sanitized_edges:
            polygon_edges[index] = edges
            sanitized_edge_rows = True
        polygon = Polygon(flags=[int(value) for value in flags], vertices=vertices, edges=edges)
        polygon.edges_flags = edges_flags
        polygon.portals = list(polygon_portals[index])
        polygons.append(polygon)
    if sanitized_edge_rows:
        warnings.append("invalid local edge links were exported as open edges")

    portals, points = _read_collection_items(mesh_obj, source_navmesh)
    source_reference_face_ids = _source_reference_face_ids(source_navmesh, source_indices, face_ids)
    portal_objects = _portal_objects_for_mesh(mesh_obj)
    portal_reference_face_ids = reference_face_ids
    if not portal_objects and source_navmesh:
        portal_reference_face_ids = source_reference_face_ids
    portals, remapped_portals = _remap_portal_objects_to_current_faces(
        mesh_obj,
        portals,
        portal_reference_face_ids,
        face_ids,
    )
    if remapped_portals:
        warnings.append(f"reindexed {remapped_portals} portal polygon reference(s) after face changes")
        _sync_portal_objects(mesh_obj, portals)
    portals, removed_portals, removed_portal_refs = _sanitize_portals_for_polygon_count(polygons, portals)
    if removed_portals:
        warnings.append(f"removed {removed_portals} portal(s) that referenced deleted/missing polygons")
    if removed_portal_refs:
        warnings.append(f"removed {removed_portal_refs} invalid polygon portal reference(s)")
    added_portal_refs, duplicate_portal_refs = _reconcile_polygon_portal_links(polygons, portals)
    if added_portal_refs:
        warnings.append(f"linked {added_portal_refs} missing reciprocal polygon portal reference(s)")
    if duplicate_portal_refs:
        warnings.append(f"removed {duplicate_portal_refs} duplicate/invalid polygon portal reference(s)")

    # Persist exactly the live topology that will be serialized.  In
    # particular, this does not retain any unmatched source polygon.
    polygon_portals = [list(polygon.portals) for polygon in polygons]
    _write_polygon_metadata(
        mesh_obj,
        polygon_flags,
        polygon_edges,
        polygon_edges_flags,
        polygon_portals,
        source_indices=source_indices,
    )

    bb_min, bb_max, bb_size, preserved_bounds = _select_export_bounds(
        mesh_obj,
        source_navmesh,
        polygons,
        portals,
        points,
    )
    _store_navmesh_bounds(mesh_obj, bb_min, bb_max, bb_size)
    if source_navmesh and not preserved_bounds:
        warnings.append("recalculated bounds because edited data extends outside the source bounds")
    navmesh = NavMesh(
        content_flags=content_flags,
        area_id=area_id,
        bb_min=bb_min,
        bb_max=bb_max,
        bb_size=bb_size,
        polygons=polygons,
        portals=portals,
        points=points,
    )
    return navmesh, warnings, face_ids, filepath


def export_navmesh_xml(mesh_obj, filepath):
    navmesh, warnings, face_ids, filepath = _build_navmesh_for_export(mesh_obj, filepath)
    warnings.extend(validate_navmesh_for_codewalker(navmesh))
    write_navmesh_xml(navmesh, filepath)
    mesh_obj["ynv_last_export_xml"] = str(Path(filepath).resolve())
    _store_reference_face_ids(mesh_obj, face_ids)
    _sync_portal_objects(mesh_obj, navmesh.portals)
    return warnings


class CWNavmeshSettings(bpy.types.PropertyGroup):
    area_id: bpy.props.IntProperty(
        name="AreaID",
        description="CodeWalker YNV AreaID. Keep this equal to the GTA navmesh tile you replace.",
        default=0,
        min=0,
    )
    content_flags: bpy.props.StringProperty(
        name="ContentFlags",
        description="CodeWalker ContentFlags value written into the YNV XML.",
        default=DEFAULT_CONTENT_FLAGS,
    )
    source_xml_path: bpy.props.StringProperty(
        name="Source XML",
        description="Original CodeWalker .ynv.xml used to preserve source metadata. Select this explicitly whenever possible.",
        default="",
        subtype="FILE_PATH",
    )
    source_search_directory: bpy.props.StringProperty(
        name="Source Search Folder",
        description="Optional narrow folder used by Fix Sources and opt-in automatic source discovery.",
        default="",
        subtype="DIR_PATH",
    )
    auto_find_source_xml: bpy.props.BoolProperty(
        name="Auto Find Source",
        description="Only auto-attach a unique, high-confidence source match; manual Source XML always wins.",
        default=False,
    )
    auto_build_edges_on_export: bpy.props.BoolProperty(
        name="Auto Build Edges",
        description="When edge data is empty, rebuild same-tile edge links during export. Existing links are preserved.",
        default=True,
    )
    strict_validation: bpy.props.BoolProperty(
        name="Strict Validation",
        description=(
            "Treat compatibility warnings such as zero-area faces and one-way links as errors. "
            "Leave disabled when checking unmodified Rockstar source meshes."
        ),
        default=False,
    )
    compiler_path: bpy.props.StringProperty(
        name="YNV Compiler",
        description="Optional local ynv_compiler executable used only by the explicit Compile YNV command.",
        default="",
        subtype="FILE_PATH",
    )
    polygon_index: bpy.props.IntProperty(
        name="Polygon",
        description="Polygon row to inspect or edit.",
        default=0,
        min=0,
    )
    polygon_flags: bpy.props.StringProperty(
        name="Flags",
        description="Six CodeWalker polygon flag integers.",
        default="0 0 0 0 0 0",
    )
    polygon_edges: bpy.props.StringProperty(
        name="Edges",
        description="One edge link per polygon vertex, separated by new lines.",
        default="",
        subtype="NONE",
    )
    polygon_edges_flags: bpy.props.StringProperty(
        name="EdgesFlags",
        description="One edge flag row per polygon vertex, separated by new lines.",
        default="",
        subtype="NONE",
    )
    polygon_portals: bpy.props.StringProperty(
        name="Portals",
        description="Polygon portal indices, separated by spaces.",
        default="",
    )
    copied_polygon_flags: bpy.props.StringProperty(
        name="Copied Flags",
        description="Copied polygon flags ready to paste to selected faces.",
        default="",
    )
def _install_flag_properties(cls):
    annotations = dict(getattr(cls, "__annotations__", {}))
    for attr_name, label, bit in POLYGON_FLAG_BITS:
        annotations[attr_name] = bpy.props.BoolProperty(
            name=label,
            description=f"Set polygon flag bit {bit}.",
            default=False,
            update=_make_flag_checkbox_update(bit, attr_name),
        )
    cls.__annotations__ = annotations


_install_flag_properties(CWNavmeshSettings)


class CWNAVMESH_OT_use_selected(bpy.types.Operator):
    bl_idname = "cw_navmesh.use_selected"
    bl_label = "Use Selected Navmesh"
    bl_description = "Marks the selected mesh as a YNV navmesh and loads its metadata into the panel"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        try:
            mesh_obj = _selected_navmesh_object(context)
            _ensure_polygon_metadata(mesh_obj)
            _sync_settings_from_mesh(context, mesh_obj)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        self.report({"INFO"}, "Selected mesh is now a GTANAVMESH Edit navmesh")
        return {"FINISHED"}


class CWNAVMESH_OT_apply_settings(bpy.types.Operator):
    bl_idname = "cw_navmesh.apply_settings"
    bl_label = "Apply CW Metadata"
    bl_description = "Writes the AreaID, ContentFlags and Source XML path from the panel to the selected navmesh"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        try:
            mesh_obj = _selected_navmesh_object(context)
            _apply_settings_to_mesh(context, mesh_obj)
            _ensure_polygon_metadata(mesh_obj)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        self.report({"INFO"}, "GTANAVMESH Edit navmesh metadata applied")
        return {"FINISHED"}


class IMPORT_OT_ynv_xml(bpy.types.Operator, ImportHelper):
    bl_idname = "cw_navmesh.import_xml"
    bl_label = "Import YNV NavMesh XML"
    bl_description = "Imports a CodeWalker .ynv.xml with stable polygon metadata and source binding"
    bl_options = {"REGISTER", "UNDO"}

    filename_ext = ".ynv.xml"
    filter_glob: bpy.props.StringProperty(default="*.ynv.xml;*.xml", options={"HIDDEN"})

    def execute(self, context):
        try:
            mesh_obj = import_navmesh_xml(self.filepath, context)
            _sync_settings_from_mesh(context, mesh_obj)
        except (NavMeshValidationError, ValueError, OSError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        except Exception as exc:
            self.report({"ERROR"}, f"Could not import YNV XML: {exc}")
            return {"CANCELLED"}
        self.report({"INFO"}, f"Imported {Path(self.filepath).name}")
        return {"FINISHED"}


class CWNAVMESH_OT_load_source_xml(bpy.types.Operator, ImportHelper):
    bl_idname = "cw_navmesh.load_source_xml"
    bl_label = "Load Source XML Metadata"
    bl_description = "Loads an original CodeWalker .ynv.xml and binds metadata only to exactly matching live faces"
    bl_options = {"REGISTER", "UNDO"}

    filename_ext = ".xml"
    filter_glob: bpy.props.StringProperty(default="*.ynv.xml;*.xml", options={"HIDDEN"})

    def execute(self, context):
        try:
            mesh_obj = _selected_navmesh_object(context)
            navmesh = read_navmesh_xml(self.filepath)
            settings = _scene_settings(context)
            settings.area_id = navmesh.area_id
            settings.content_flags = navmesh.content_flags or DEFAULT_CONTENT_FLAGS
            settings.source_xml_path = self.filepath
            matched = _apply_source_navmesh_to_mesh(mesh_obj, self.filepath, navmesh)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        if matched:
            self.report({"INFO"}, "Loaded CW source XML metadata")
        else:
            self.report({"WARNING"}, "Loaded source identity; only exactly matching live faces received source metadata")
        return {"FINISHED"}


class CWNAVMESH_OT_fix_sources(bpy.types.Operator):
    bl_idname = "cw_navmesh.fix_sources"
    bl_label = "Fix Sources"
    bl_description = "Attempts only unique, high-confidence source matches and never replaces an existing source path"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        try:
            repaired = _repair_scene_navmesh_sources(context)
            mesh_obj = _selected_navmesh_object(context)
            _sync_settings_from_mesh(context, mesh_obj)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        if repaired:
            self.report({"INFO"}, f"Attached source XML to {repaired} navmesh(es)")
        else:
            self.report({"WARNING"}, "No unique high-confidence source match was found; choose Source XML manually.")
        return {"FINISHED"}


class CWNAVMESH_OT_pick_polygon(bpy.types.Operator):
    bl_idname = "cw_navmesh.pick_polygon"
    bl_label = "Load Active Polygon"
    bl_description = "Loads flags, edges, edge flags and portal refs from the active face into the polygon editor"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        try:
            mesh_obj = _selected_navmesh_object(context)
            if mesh_obj.mode == "EDIT":
                mesh_obj.update_from_editmode()
            _load_polygon_editor_from_mesh(context, mesh_obj)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        self.report({"INFO"}, "Loaded active polygon metadata")
        return {"FINISHED"}


class CWNAVMESH_OT_apply_polygon(bpy.types.Operator):
    bl_idname = "cw_navmesh.apply_polygon"
    bl_label = "Apply Polygon"
    bl_description = "Writes the current polygon editor values to the active face"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        try:
            mesh_obj = _selected_navmesh_object(context)
            _apply_polygon_editor_to_mesh(context, mesh_obj)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        self.report({"INFO"}, "Applied polygon metadata")
        return {"FINISHED"}


class CWNAVMESH_OT_copy_flags(bpy.types.Operator):
    bl_idname = "cw_navmesh.copy_flags"
    bl_label = "Copy Flags"
    bl_description = "Copies the flags from the active face so they can be pasted onto other faces"
    bl_options = {"REGISTER"}

    def execute(self, context):
        try:
            mesh_obj = _selected_navmesh_object(context)
            active_index = _active_polygon_index(mesh_obj)
            polygon_flags, _, _, _ = _read_polygon_metadata(mesh_obj)
            if active_index >= len(polygon_flags):
                raise ValueError("Active polygon has no flags.")
            flags = polygon_flags[active_index]
            _scene_settings(context).copied_polygon_flags = " ".join(str(value) for value in flags)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        self.report({"INFO"}, "Copied polygon flags")
        return {"FINISHED"}


class CWNAVMESH_OT_paste_flags(bpy.types.Operator):
    bl_idname = "cw_navmesh.paste_flags"
    bl_label = "Paste Flags"
    bl_description = "Pastes the copied flags onto all selected faces, or onto the active face when nothing is selected"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        try:
            mesh_obj = _selected_navmesh_object(context)
            flags = _normalize_flags_text(_scene_settings(context).copied_polygon_flags)
            selected_indices = _selected_polygon_indices(mesh_obj)
            if not selected_indices:
                selected_indices = [_active_polygon_index(mesh_obj)]
            was_edit_mode = mesh_obj.mode == "EDIT"
            if was_edit_mode:
                bpy.ops.object.mode_set(mode="OBJECT")
            _set_polygon_flags(mesh_obj, selected_indices, flags)
            if was_edit_mode:
                bpy.ops.object.mode_set(mode="EDIT")
            _load_polygon_editor_from_mesh(context, mesh_obj, selected_indices[0], ensure_metadata=False)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        self.report({"INFO"}, f"Pasted flags to {len(selected_indices)} face(s)")
        return {"FINISHED"}


class CWNAVMESH_OT_build_edges(bpy.types.Operator):
    bl_idname = "cw_navmesh.build_edges"
    bl_label = "Build Local Edges"
    bl_description = "Builds only local edge links between faces in the same navmesh; external cell links are left unchanged"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        try:
            mesh_obj = _selected_navmesh_object(context)
            area_id = _get_int_prop(mesh_obj, "ynv_area_id", 0)
            if not area_id and mesh_obj.parent:
                area_id = _get_int_prop(mesh_obj.parent, "ynv_area_id", 0)
            if not area_id:
                source_navmesh = _load_source_navmesh_for_export(mesh_obj, mesh_obj.name + ".ynv.xml")
                if source_navmesh:
                    area_id = source_navmesh.area_id
                    mesh_obj["ynv_area_id"] = area_id
                    if mesh_obj.parent:
                        mesh_obj.parent["ynv_area_id"] = area_id
            if not area_id:
                raise ValueError("Set AreaID before building local edge links.")
            linked, total, changed = _build_local_edge_links(mesh_obj, area_id)
            _ensure_polygon_metadata(mesh_obj)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        self.report({"INFO"}, f"Built {linked} local edge links out of {total} edges; changed {changed}")
        return {"FINISHED"}


class CWNAVMESH_OT_rebuild_edges_from_geometry(bpy.types.Operator):
    bl_idname = "cw_navmesh.rebuild_edges_from_geometry"
    bl_label = "Rebuild Edges From Geometry"
    bl_description = "Rebuilds edge links from geometry: internal links, matching loaded neighbour cells and preserved external links"
    bl_options = {"REGISTER", "UNDO"}

    include_loaded_neighbours: bpy.props.BoolProperty(
        name="Include Loaded Neighbours",
        description="Match boundary edges against other loaded navmesh cells in the scene.",
        default=True,
    )

    def execute(self, context):
        try:
            mesh_obj = _selected_navmesh_object(context)
            if mesh_obj.mode == "EDIT":
                mesh_obj.update_from_editmode()
            source_navmesh = _load_source_navmesh_for_export(mesh_obj, mesh_obj.name + ".ynv.xml")
            area_id = _navmesh_area_id(mesh_obj, source_navmesh)
            if not area_id:
                raise ValueError("Set AreaID before rebuilding edge links.")

            cross_index = None
            duplicate_keys = set()
            loaded_area_ids = set()
            if self.include_loaded_neighbours:
                mesh_area_pairs = []
                for other_mesh in _scene_navmesh_meshes(context):
                    other_source = _load_source_navmesh_for_export(other_mesh, other_mesh.name + ".ynv.xml")
                    other_area = _navmesh_area_id(other_mesh, other_source)
                    if other_area:
                        loaded_area_ids.add(other_area)
                    mesh_area_pairs.append((other_mesh, other_area))
                cross_index, duplicate_keys = _build_cross_cell_index(mesh_area_pairs)

            stats = _rebuild_edge_links_from_geometry(
                mesh_obj,
                area_id,
                loaded_area_ids=loaded_area_ids,
                cross_index=cross_index,
                duplicate_keys=duplicate_keys,
            )
            _ensure_polygon_metadata(mesh_obj)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        self.report(
            {"WARNING" if stats["ambiguous"] else "INFO"},
            "Rebuilt edges: "
            f"{stats['internal']} internal, {stats['cross']} cross-cell, "
            f"{stats['preserved_external']} preserved external, {stats['open']} open, "
            f"{stats['changed']} changed"
            + (f", {stats['ambiguous']} ambiguous skipped" if stats["ambiguous"] else ""),
        )
        return {"FINISHED"}


class CWNAVMESH_OT_create_navmesh(bpy.types.Operator):
    bl_idname = "cw_navmesh.create_navmesh"
    bl_label = "New GTANAVMESH Edit Navmesh"
    bl_description = "Creates a new simple navmesh mesh using the AreaID and ContentFlags from the panel"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = _scene_settings(context)
        root = _new_empty("GTANAVMESH Edit Navmesh", "sollumz_navmesh")
        root[YNV_COLLECTION_TAG] = True
        root["ynv_area_id"] = int(settings.area_id)
        root["ynv_content_flags"] = settings.content_flags.strip() or DEFAULT_CONTENT_FLAGS
        _collection_link(context.collection, root)
        mesh = bpy.data.meshes.new("GTANAVMESH Edit Navmesh Mesh")
        mesh.from_pydata(
            [(-1.0, -1.0, 0.0), (1.0, -1.0, 0.0), (0.0, 1.0, 0.0)],
            [],
            [(0, 1, 2)],
        )
        mesh.update(calc_edges=True)
        obj = bpy.data.objects.new("NavMesh Poly Mesh", mesh)
        obj.parent = root
        _collection_link(context.collection, obj)
        context.view_layer.objects.active = obj
        obj.select_set(True)
        obj[YNV_MESH_TAG] = True
        obj["ynv_area_id"] = int(settings.area_id)
        obj["ynv_content_flags"] = settings.content_flags.strip() or DEFAULT_CONTENT_FLAGS
        _write_polygon_metadata(
            obj,
            [[0, 0, 0, 0, 0, 0]],
            [[DEFAULT_EDGE, DEFAULT_EDGE, DEFAULT_EDGE]],
            [[DEFAULT_EDGE_FLAGS, DEFAULT_EDGE_FLAGS, DEFAULT_EDGE_FLAGS]],
            [[]],
            source_indices=[NO_SOURCE_POLYGON],
        )
        face_ids, _source_indices = _current_face_identity(obj)
        _store_reference_face_ids(obj, face_ids)
        _set_sollum_type(obj, SOLLUMZ_NAVMESH_POLY_MESH)
        self.report({"INFO"}, "Created new GTANAVMESH Edit navmesh mesh")
        return {"FINISHED"}


class CWNAVMESH_OT_add_point(bpy.types.Operator):
    bl_idname = "cw_navmesh.add_point"
    bl_label = "Add Point"
    bl_description = "Adds a YNV point at the 3D cursor position under the current navmesh root"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        try:
            mesh_obj = _selected_navmesh_object(context)
            parent = _child_empty(_navmesh_root(mesh_obj), "Points")
        except Exception:
            parent = None
        point = bpy.data.objects.new("NavMesh Point", _create_marker_mesh("GTANAVMESH Edit Point Marker"))
        point.location = context.scene.cursor.location
        point.parent = parent
        point[YNV_POINT_TAG] = True
        _write_sollumz_point_properties(
            point,
            Point(type=0, angle=0.0, position=_tuple_to_vec(point.location)),
        )
        _set_sollum_type(point, SOLLUMZ_NAVMESH_POINT)
        context.collection.objects.link(point)
        self.report({"INFO"}, "Added GTANAVMESH Edit navmesh point")
        return {"FINISHED"}


class CWNAVMESH_OT_add_portal(bpy.types.Operator):
    bl_idname = "cw_navmesh.add_portal"
    bl_label = "Add Portal"
    bl_description = "Adds a YNV portal at the 3D cursor position under the current navmesh root"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        mesh_obj = None
        try:
            mesh_obj = _selected_navmesh_object(context)
            parent = _child_empty(_navmesh_root(mesh_obj), "Portals")
        except Exception:
            parent = None
        loc = context.scene.cursor.location
        portal_data = Portal(
            type=0,
            angle=0.0,
            poly_from=0,
            poly_to=0,
            position_from=Vec3(loc.x - 0.5, loc.y, loc.z),
            position_to=Vec3(loc.x + 0.5, loc.y, loc.z),
        )
        portal, from_obj, to_obj = _create_portal_object(portal_data, len([obj for obj in bpy.data.objects if obj.get(YNV_PORTAL_TAG)]))
        portal.parent = parent
        context.collection.objects.link(portal)
        context.collection.objects.link(from_obj)
        context.collection.objects.link(to_obj)
        if mesh_obj:
            face_ids, _source_indices = _current_face_identity(mesh_obj)
            portal[YNV_PORTAL_REFERENCE_FACE_IDS] = json.dumps(face_ids, separators=(",", ":"))
        self.report({"INFO"}, "Added GTANAVMESH Edit navmesh portal")
        return {"FINISHED"}


class CWNAVMESH_OT_validate(bpy.types.Operator):
    bl_idname = "cw_navmesh.validate"
    bl_label = "Validate GTANAVMESH Edit Navmesh"
    bl_description = "Checks the current export for CodeWalker-compatible AreaID, polygon, edge and portal data"
    bl_options = {"REGISTER"}

    def execute(self, context):
        try:
            mesh_obj = _selected_navmesh_object(context)
            target = _last_export_xml_path(mesh_obj) or Path(mesh_obj.name + ".ynv.xml")
            navmesh, warnings, _face_ids, _filepath = _build_navmesh_for_export(mesh_obj, str(target))
            strict = bool(_scene_settings(context).strict_validation)
            warnings.extend(validate_navmesh_for_codewalker(navmesh, strict=strict))
        except (NavMeshValidationError, ValueError, OSError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        message = "GTANAVMESH Edit strict validation OK" if strict else "GTANAVMESH Edit compatibility validation OK"
        if warnings:
            message += ": " + "; ".join(dict.fromkeys(warnings))
        self.report({"INFO"}, message)
        return {"FINISHED"}


class EXPORT_OT_ynv_xml(bpy.types.Operator, ExportHelper):
    bl_idname = "export_scene.ynv_xml"
    bl_label = "Export YNV XML"
    bl_description = "Exports the selected navmesh as a CodeWalker-compatible .ynv.xml and preserves source data when possible"
    bl_options = {"REGISTER"}

    filename_ext = ".ynv.xml"
    filter_glob: bpy.props.StringProperty(default="*.ynv.xml;*.xml", options={"HIDDEN"})

    def check(self, context):
        normalized = _normalize_ynv_xml_filepath(self.filepath)
        if normalized != self.filepath:
            self.filepath = normalized
            return True
        return False

    def execute(self, context):
        try:
            mesh_obj = _selected_navmesh_object(context)
            self.filepath = _normalize_ynv_xml_filepath(self.filepath)
            warnings = export_navmesh_xml(mesh_obj, self.filepath)
        except NavMeshValidationError as exc:
            self.report({"ERROR"}, f"CodeWalker compatibility error: {exc}")
            return {"CANCELLED"}
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        if warnings:
            self.report({"WARNING"}, "; ".join(dict.fromkeys(warnings)))
        self.report({"INFO"}, f"Exported {self.filepath}")
        return {"FINISHED"}


def _bundled_ynv_compiler():
    addon_root = Path(__file__).resolve().parent.parent
    candidates = (
        addon_root / "ynv_compiler" / "bin" / "Release" / "net8.0" / "ynv_compiler.exe",
    )
    return next((candidate for candidate in candidates if candidate.is_file()), None)


def _resolve_ynv_compiler(settings):
    configured = str(getattr(settings, "compiler_path", "") or "").strip()
    if configured:
        try:
            candidate = Path(bpy.path.abspath(configured)).resolve()
        except (OSError, RuntimeError):
            candidate = Path(configured)
        if candidate.is_file():
            return candidate
        raise ValueError(f"YNV compiler was not found: {candidate}")
    bundled = _bundled_ynv_compiler()
    if bundled:
        return bundled
    raise ValueError("Set YNV Compiler in the GTANAVMESH Edit panel before compiling.")


def _last_export_xml_path(mesh_obj):
    raw_path = str(mesh_obj.get("ynv_last_export_xml", "") or "").strip()
    if not raw_path:
        return None
    try:
        path = Path(bpy.path.abspath(raw_path)).resolve()
    except (OSError, RuntimeError):
        path = Path(raw_path)
    return path if path.is_file() else None


class CWNAVMESH_OT_compile_ynv(bpy.types.Operator, ImportHelper):
    bl_idname = "cw_navmesh.compile_ynv"
    bl_label = "Compile YNV"
    bl_description = "Validate an XML export and explicitly compile it to native RSC7 .ynv"
    bl_options = {"REGISTER"}

    filename_ext = ".xml"
    filter_glob: bpy.props.StringProperty(default="*.ynv.xml;*.xml", options={"HIDDEN"})

    def invoke(self, context, event):
        try:
            mesh_obj = _selected_navmesh_object(context)
            last_export = _last_export_xml_path(mesh_obj)
        except Exception:
            last_export = None
        if last_export:
            self.filepath = str(last_export)
            return self.execute(context)
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        try:
            settings = _scene_settings(context)
            xml_path = Path(bpy.path.abspath(self.filepath)).resolve()
            if not xml_path.is_file():
                raise ValueError(f"XML export was not found: {xml_path}")
            if not xml_path.name.lower().endswith(".xml"):
                raise ValueError("Choose a .ynv.xml file to compile.")
            strict = bool(getattr(settings, "strict_validation", False))
            validate_navmesh_for_codewalker(read_navmesh_xml(xml_path), strict=strict)
            compiler = _resolve_ynv_compiler(settings)
            output_path = xml_path.with_suffix("")
            result = subprocess.run(
                [str(compiler), str(xml_path), str(output_path)],
                cwd=str(compiler.parent),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=180,
                shell=False,
            )
            detail = (result.stderr or result.stdout or "").strip().replace("\n", " ")
            if result.returncode != 0:
                raise RuntimeError(f"Compiler failed ({result.returncode}): {detail[:600]}")
            if not output_path.is_file():
                raise RuntimeError("Compiler reported success but did not produce a .ynv file.")
            with output_path.open("rb") as stream:
                if stream.read(4) != b"RSC7":
                    raise RuntimeError("Compiler output does not have an RSC7 header.")
        except subprocess.TimeoutExpired:
            self.report({"ERROR"}, "YNV compiler timed out after 180 seconds.")
            return {"CANCELLED"}
        except (NavMeshValidationError, ValueError, OSError, RuntimeError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        self.report({"INFO"}, f"Compiled native YNV: {output_path}")
        return {"FINISHED"}


class CWNAVMESH_OT_export_all_ynv_xml(bpy.types.Operator):
    bl_idname = "cw_navmesh.export_all_ynv_xml"
    bl_label = "Export All XML"
    bl_description = "Exports all loaded navmeshes to a folder while preserving AreaID, cells, bounds, points, flags and existing edge links"
    bl_options = {"REGISTER"}

    directory: bpy.props.StringProperty(
        name="Directory",
        description="Folder to write all loaded navmesh .ynv.xml files into.",
        default="",
        subtype="DIR_PATH",
    )
    filter_folder: bpy.props.BoolProperty(default=True, options={"HIDDEN"})

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        try:
            directory = Path(bpy.path.abspath(self.directory)).resolve()
            if not directory.exists() or not directory.is_dir():
                raise ValueError(f"Not a directory: {directory}")
            meshes = _scene_navmesh_meshes(context)
            if not meshes:
                raise ValueError("No navmesh meshes found in the scene.")

            filepaths = {}
            used_names = set()
            mesh_area_pairs = []
            warnings = []
            for mesh_obj in meshes:
                probe_name = mesh_obj.parent.name if mesh_obj.parent else mesh_obj.name
                probe_path = directory / _ynv_xml_path(probe_name)
                source_path, source_navmesh = _attach_source_xml_if_missing(mesh_obj, probe_path)
                area_id = _navmesh_area_id(mesh_obj, source_navmesh)
                if not area_id:
                    warnings.append(f"{mesh_obj.name}: missing AreaID")
                mesh_obj["ynv_area_id"] = area_id
                if mesh_obj.parent:
                    mesh_obj.parent["ynv_area_id"] = area_id
                mesh_area_pairs.append((mesh_obj, area_id))

                if source_path:
                    filename = source_path.name
                else:
                    root_name = mesh_obj.parent.name if mesh_obj.parent else mesh_obj.name
                    filename = Path(_ynv_xml_path(root_name)).name
                if filename in used_names:
                    suffix = f"_{area_id}" if area_id else f"_{len(used_names)}"
                    stem = filename[:-8] if filename.lower().endswith(".ynv.xml") else Path(filename).stem
                    filename = f"{stem}{suffix}.ynv.xml"
                    warnings.append(f"{mesh_obj.name}: duplicate export name, wrote {filename}")
                used_names.add(filename)
                filepaths[mesh_obj.name] = directory / filename

            area_counts = {}
            for _mesh_obj, area_id in mesh_area_pairs:
                if area_id:
                    area_counts[area_id] = area_counts.get(area_id, 0) + 1
            duplicate_areas = [area_id for area_id, count in area_counts.items() if count > 1]
            if duplicate_areas:
                warnings.append("duplicate AreaID(s): " + ", ".join(str(area_id) for area_id in sorted(duplicate_areas)))

            cross_index, duplicate_keys = _build_cross_cell_index(mesh_area_pairs)
            cross_changed = 0
            cross_matched = 0
            for mesh_obj, area_id in mesh_area_pairs:
                if not area_id:
                    continue
                polygon_flags, polygon_edges, polygon_edges_flags, polygon_portals = _read_polygon_metadata(mesh_obj)
                face_ids, source_indices = _current_face_identity(mesh_obj)
                polygon_edges, reindexed = _remap_local_edge_rows(
                    polygon_edges,
                    area_id,
                    _stored_reference_face_ids(mesh_obj),
                    face_ids,
                )
                if reindexed:
                    _write_polygon_metadata(
                        mesh_obj,
                        polygon_flags,
                        polygon_edges,
                        polygon_edges_flags,
                        polygon_portals,
                        source_indices=source_indices,
                    )
                    warnings.append(f"{mesh_obj.name}: reindexed {reindexed} local edge reference(s)")
                matched, changed = _apply_cross_cell_edge_links(
                    mesh_obj,
                    area_id,
                    cross_index,
                    duplicate_keys,
                )
                cross_matched += matched
                cross_changed += changed
            if duplicate_keys:
                warnings.append(f"skipped {len(duplicate_keys)} ambiguous boundary edge match(es)")
            if cross_changed:
                warnings.append(f"updated {cross_changed} cross-cell boundary edge link(s); {cross_matched} boundary match(es) found")

            exported = 0
            for mesh_obj in meshes:
                export_warnings = export_navmesh_xml(mesh_obj, str(filepaths[mesh_obj.name]))
                warnings.extend(f"{mesh_obj.name}: {warning}" for warning in export_warnings)
                exported += 1
        except NavMeshValidationError as exc:
            self.report({"ERROR"}, f"CodeWalker compatibility error: {exc}")
            return {"CANCELLED"}
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        message = f"Exported {exported} navmesh(es)"
        unique_warnings = list(dict.fromkeys(warnings))
        if unique_warnings:
            self.report({"WARNING"}, message + ": " + "; ".join(unique_warnings[:8]))
        else:
            self.report({"INFO"}, message)
        return {"FINISHED"}


class CWNAVMESH_PT_panel(bpy.types.Panel):
    bl_label = "GTANAVMESH Edit"
    bl_idname = "CWNAVMESH_PT_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "GTANAVMESH Edit"

    def draw(self, context):
        layout = self.layout
        settings = _scene_settings(context)
        active = getattr(context, "object", None)
        mesh_obj = None
        try:
            mesh_obj = _selected_navmesh_object(context)
        except Exception:
            pass

        layout.prop(settings, "area_id")
        layout.prop(settings, "content_flags")
        layout.prop(settings, "source_xml_path")
        layout.prop(settings, "source_search_directory")
        layout.prop(settings, "auto_find_source_xml")
        layout.prop(settings, "auto_build_edges_on_export")
        layout.prop(settings, "strict_validation")

        row = layout.row(align=True)
        row.operator(CWNAVMESH_OT_use_selected.bl_idname, text="Use Selected")
        row.operator(CWNAVMESH_OT_apply_settings.bl_idname, text="Apply")

        row = layout.row(align=True)
        row.operator(IMPORT_OT_ynv_xml.bl_idname, text="Import XML")
        row.operator(CWNAVMESH_OT_create_navmesh.bl_idname, text="New")

        row = layout.row(align=True)
        row.operator(CWNAVMESH_OT_load_source_xml.bl_idname, text="Load Source")
        row.operator(CWNAVMESH_OT_fix_sources.bl_idname, text="Fix Sources")

        row = layout.row(align=True)
        row.operator(CWNAVMESH_OT_validate.bl_idname, text="Validate")

        row = layout.row(align=True)
        row.operator(EXPORT_OT_ynv_xml.bl_idname, text="Export XML")
        row.operator(CWNAVMESH_OT_export_all_ynv_xml.bl_idname, text="Export All")

        layout.prop(settings, "compiler_path")
        layout.operator(CWNAVMESH_OT_compile_ynv.bl_idname, text="Compile YNV")

        row = layout.row(align=True)
        row.operator(CWNAVMESH_OT_build_edges.bl_idname, text="Build Edges")
        row.operator(CWNAVMESH_OT_rebuild_edges_from_geometry.bl_idname, text="Rebuild Edges")

        row = layout.row(align=True)
        row.operator(CWNAVMESH_OT_add_point.bl_idname, text="Add Point")
        row.operator(CWNAVMESH_OT_add_portal.bl_idname, text="Add Portal")

        if mesh_obj:
            mesh_source = str(mesh_obj.get("ynv_source_xml", mesh_obj.parent.get("ynv_source_xml", "") if mesh_obj.parent else "")).strip()
            mesh_area_id = _get_int_prop(mesh_obj, "ynv_area_id", _get_int_prop(mesh_obj.parent, "ynv_area_id", 0) if mesh_obj.parent else 0)
            if settings.source_xml_path != mesh_source or int(settings.area_id) != int(mesh_area_id):
                _schedule_settings_sync(context.scene, mesh_obj)
            active_polygon = _active_polygon_index(mesh_obj)
            if active_polygon != settings.polygon_index:
                _schedule_polygon_editor_load(context.scene, mesh_obj, active_polygon)
            box = layout.box()
            box.label(text="Selected")
            box.label(text=f"Mesh: {mesh_obj.name}")
            box.label(text=f"Polygons: {len(mesh_obj.data.polygons)}")
            box.label(text=f"Active polygon: {active_polygon}")
            flags, edges, edge_flags, polygon_portals = _read_polygon_metadata(mesh_obj)
            box.label(text=f"Flags rows: {len(flags)}")
            box.label(text=f"Edges rows: {len(edges)}")
            box.label(text=f"EdgesFlags rows: {len(edge_flags)}")
            box.label(text=f"Portal rows: {len(polygon_portals)}")

            poly = layout.box()
            poly.label(text="Polygon Editor")
            poly.prop(settings, "polygon_index")
            row = poly.row(align=True)
            row.operator(CWNAVMESH_OT_pick_polygon.bl_idname, text="Load Active")
            row.operator(CWNAVMESH_OT_apply_polygon.bl_idname, text="Apply")
            row = poly.row(align=True)
            row.operator(CWNAVMESH_OT_copy_flags.bl_idname, text="Copy Flags")
            row.operator(CWNAVMESH_OT_paste_flags.bl_idname, text="Paste Flags")
            poly.prop(settings, "copied_polygon_flags")
            poly.prop(settings, "polygon_flags")
            try:
                current_flags = _normalize_flags_text(settings.polygon_flags)
            except ValueError:
                current_flags = [0, 0, 0, 0, 0, 0]
            flags_box = poly.box()
            flags_box.label(text="Flag Bits")
            for index in range(0, len(POLYGON_FLAG_BITS), 2):
                row = flags_box.row(align=True)
                for attr_name, _label, _bit in POLYGON_FLAG_BITS[index:index + 2]:
                    row.prop(settings, attr_name)
            flags_box.label(text=f"Bitfield: {_polygon_flag_bits(current_flags)}")
            poly.prop(settings, "polygon_edges")
            poly.prop(settings, "polygon_edges_flags")
            poly.prop(settings, "polygon_portals")
        elif active:
            layout.label(text=f"Active: {active.name}")
        else:
            layout.label(text="No navmesh selected")

        if active and (active.get(YNV_POINT_TAG) or _get_sollum_type(active) == SOLLUMZ_NAVMESH_POINT):
            box = layout.box()
            box.label(text="Point")
            point_props = getattr(active, "sz_nav_point", None)
            if point_props and hasattr(point_props, "point_type"):
                box.prop(point_props, "point_type", text="Type")
            else:
                box.prop(active, '["ynv_type"]', text="Type")
            box.prop(active, "rotation_euler", text="Rotation")
            box.prop(active, "location", text="Position")

        if active and (active.get(YNV_PORTAL_TAG) or _get_sollum_type(active) == SOLLUMZ_NAVMESH_PORTAL):
            box = layout.box()
            box.label(text="Portal")
            portal_props = getattr(active, "sz_nav_portal", None)
            if portal_props and all(hasattr(portal_props, name) for name in ("portal_type", "angle", "poly_from", "poly_to")):
                box.prop(portal_props, "portal_type", text="Type")
                box.prop(portal_props, "angle", text="Angle")
                box.prop(portal_props, "poly_from", text="PolyFrom")
                box.prop(portal_props, "poly_to", text="PolyTo")
            else:
                box.prop(active, '["ynv_type"]', text="Type")
                box.prop(active, '["ynv_angle"]', text="Angle")
                box.prop(active, '["ynv_poly_from"]', text="PolyFrom")
                box.prop(active, '["ynv_poly_to"]', text="PolyTo")
            box.prop(active, "location", text="Center")


def _menu_export(self, context):
    self.layout.operator(EXPORT_OT_ynv_xml.bl_idname, text="YNV NavMesh XML (.ynv.xml)")


def _menu_import(self, context):
    self.layout.operator(IMPORT_OT_ynv_xml.bl_idname, text="YNV NavMesh XML (.ynv.xml)")


classes = (
    CWNavmeshSettings,
    CWNAVMESH_OT_use_selected,
    CWNAVMESH_OT_apply_settings,
    IMPORT_OT_ynv_xml,
    CWNAVMESH_OT_load_source_xml,
    CWNAVMESH_OT_fix_sources,
    CWNAVMESH_OT_pick_polygon,
    CWNAVMESH_OT_apply_polygon,
    CWNAVMESH_OT_copy_flags,
    CWNAVMESH_OT_paste_flags,
    CWNAVMESH_OT_build_edges,
    CWNAVMESH_OT_rebuild_edges_from_geometry,
    CWNAVMESH_OT_create_navmesh,
    CWNAVMESH_OT_add_point,
    CWNAVMESH_OT_add_portal,
    CWNAVMESH_OT_validate,
    EXPORT_OT_ynv_xml,
    CWNAVMESH_OT_compile_ynv,
    CWNAVMESH_OT_export_all_ynv_xml,
    CWNAVMESH_PT_panel,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.cw_navmesh_settings = bpy.props.PointerProperty(type=CWNavmeshSettings)
    bpy.types.TOPBAR_MT_file_export.append(_menu_export)
    bpy.types.TOPBAR_MT_file_import.append(_menu_import)
    _patch_sollumz_importer()
    if not bpy.app.timers.is_registered(_retry_sollumz_import_patch):
        bpy.app.timers.register(_retry_sollumz_import_patch, first_interval=0.5)
    if _cw_navmesh_auto_source_handler not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_cw_navmesh_auto_source_handler)


def unregister():
    bpy.types.TOPBAR_MT_file_export.remove(_menu_export)
    bpy.types.TOPBAR_MT_file_import.remove(_menu_import)
    if bpy.app.timers.is_registered(_retry_sollumz_import_patch):
        bpy.app.timers.unregister(_retry_sollumz_import_patch)
    if _cw_navmesh_auto_source_handler in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_cw_navmesh_auto_source_handler)
    _unpatch_sollumz_importer()
    del bpy.types.Scene.cw_navmesh_settings
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
