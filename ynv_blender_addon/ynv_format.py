# Copyright (c) 2026 devsanja

from __future__ import annotations

from dataclasses import dataclass, field
import math
from pathlib import Path
import re
from typing import List, Optional, Tuple, Union
import xml.etree.ElementTree as ET


# Edges are serialized as the *actual* neighbouring AreaID and polygon ID, not
# as an index into the binary AdjAreaIDs array.  Both values are packed into
# 14-bit fields by CodeWalker.  0x3FFF is the explicit "no neighbour" value.
EDGE_RE = re.compile(
    r"^(?P<area1>\d+):(?P<poly1>\d+),\s*(?P<area2>\d+):(?P<poly2>\d+)$"
)

NO_NEIGHBOUR = 0x3FFF
# 0x3FFF is the edge-boundary sentinel, not a usable navmesh AreaID.
MAX_AREA_ID = NO_NEIGHBOUR - 1
MAX_POLYGON_ID = NO_NEIGHBOUR
MAX_POLYGONS = NO_NEIGHBOUR  # 0x3FFF itself is reserved as the edge sentinel.
MAX_ADJACENT_AREA_IDS = 32  # NavMeshUintArray contains exactly v00..v31.
MAX_VERTICES_PER_POLYGON = 0x7FF  # NavMeshPoly.IndexCount is an 11-bit field.
MAX_TOTAL_INDICES = 0x10000  # NavMeshPoly.IndexID is a ushort.
MAX_PORTAL_INDEX = 0xFFFF  # PortalLinks entries are ushorts.
MAX_PORTALS = MAX_PORTAL_INDEX + 1
MAX_PORTAL_LINKS_PER_POLYGON = 0x7  # NavMeshPoly.PortalLinkCount is 3 bits.
MAX_BYTE = 0xFF
# CodeWalker's seventh XML Flags value (``Flags5``) occupies only bit 8 of
# ``NavMeshPoly.PolyFlags1``.  It is written as a byte for historical XML
# compatibility, but every bit except bit 0 would otherwise be discarded by
# the native compiler.
MAX_POLYGON_FLAGS5 = 0x1
MAX_EDGE_UNK2 = 0x3  # NavMeshEdgePart.Unk2 is 2 bits.
MAX_EDGE_UNK3 = 0x7FF  # NavMeshEdgePart.Unk3 is 11 bits.
ANGLE_LIMIT = math.tau
BOUNDS_TOLERANCE = 1e-3
GEOMETRY_EPSILON_SQUARED = 1e-12
MAX_REPORTED_ISSUES = 100
MAX_FLOAT32 = 3.4028234663852886e38
DEFAULT_EDGE_FLAGS = "0:0, 0:0"


@dataclass
class Vec3:
    x: float
    y: float
    z: float


@dataclass
class Polygon:
    flags: List[int]
    vertices: List[Vec3]
    edges: List[str]
    edges_flags: List[str] = field(default_factory=list)
    portals: List[int] = field(default_factory=list)


@dataclass
class Portal:
    type: int
    angle: float
    poly_from: int
    poly_to: int
    position_from: Vec3
    position_to: Vec3


@dataclass
class Point:
    type: int
    angle: float
    position: Vec3


@dataclass
class NavMesh:
    content_flags: str = ""
    area_id: int = 0
    bb_min: Vec3 = field(default_factory=lambda: Vec3(0.0, 0.0, 0.0))
    bb_max: Vec3 = field(default_factory=lambda: Vec3(0.0, 0.0, 0.0))
    bb_size: Vec3 = field(default_factory=lambda: Vec3(0.0, 0.0, 0.0))
    polygons: List[Polygon] = field(default_factory=list)
    portals: List[Portal] = field(default_factory=list)
    points: List[Point] = field(default_factory=list)


class NavMeshValidationError(ValueError):
    pass


def _vec_from_attrs(node: ET.Element) -> Vec3:
    return Vec3(float(node.attrib["x"]), float(node.attrib["y"]), float(node.attrib["z"]))


def _attr_int(parent: ET.Element, tag: str, default: int = 0) -> int:
    child = parent.find(tag)
    if child is None:
        return default
    return int(child.attrib.get("value", default))


def _attr_float(parent: ET.Element, tag: str, default: float = 0.0) -> float:
    child = parent.find(tag)
    if child is None:
        return default
    return float(child.attrib.get("value", default))


def _parse_vertices(text: Optional[str]) -> List[Vec3]:
    vertices = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        x, y, z = [float(part.strip()) for part in line.split(",")]
        vertices.append(Vec3(x, y, z))
    return vertices


def _parse_edges(text: Optional[str]) -> List[str]:
    return [line.strip() for line in (text or "").splitlines() if line.strip()]


def _append_issue(issues: List[str], message: str) -> None:
    """Keep a malformed large navmesh from producing an unbounded error string."""

    if len(issues) < MAX_REPORTED_ISSUES:
        issues.append(message)


def _is_int_in_range(value: object, minimum: int, maximum: int) -> bool:
    # bool is an int subclass, but it is never a meaningful navmesh field.
    return isinstance(value, int) and not isinstance(value, bool) and minimum <= value <= maximum


def _is_finite_number(value: object) -> bool:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        number = float(value)
    except (OverflowError, TypeError, ValueError):
        return False
    # CodeWalker writes single-precision resource fields.  Python doubles
    # larger than this otherwise look finite here but become Infinity in C#.
    return math.isfinite(number) and abs(number) <= MAX_FLOAT32


def _is_finite_vec(vec: object) -> bool:
    return isinstance(vec, Vec3) and all(
        _is_finite_number(value) for value in (vec.x, vec.y, vec.z)
    )


def _parse_edge_value(value: object) -> Optional[Tuple[int, int, int, int]]:
    if not isinstance(value, str):
        return None
    match = EDGE_RE.fullmatch(value)
    if match is None:
        return None
    return tuple(int(match.group(name)) for name in ("area1", "poly1", "area2", "poly2"))


def _polygon_area_squared(vertices: List[Vec3]) -> float:
    """Return the squared Newell area, which also works for non-horizontal faces."""

    nx = ny = nz = 0.0
    for current, following in zip(vertices, vertices[1:] + vertices[:1]):
        nx += (current.y - following.y) * (current.z + following.z)
        ny += (current.z - following.z) * (current.x + following.x)
        nz += (current.x - following.x) * (current.y + following.y)
    return (nx * nx + ny * ny + nz * nz) * 0.25


def _edge_length_squared(first: Vec3, second: Vec3) -> float:
    x = first.x - second.x
    y = first.y - second.y
    z = first.z - second.z
    return x * x + y * y + z * z


def _inside_bounds(vec: Vec3, bb_min: Vec3, bb_max: Vec3, tolerance: float) -> bool:
    return (
        bb_min.x - tolerance <= vec.x <= bb_max.x + tolerance
        and bb_min.y - tolerance <= vec.y <= bb_max.y + tolerance
        and bb_min.z - tolerance <= vec.z <= bb_max.z + tolerance
    )


def validate_navmesh_for_codewalker(navmesh: NavMesh, *, strict: bool = False) -> List[str]:
    """Validate fields that CodeWalker's YNV serializer would otherwise truncate.

    Hard failures are always unsafe to serialize: packed-field overflow, invalid
    references, malformed edge rows, non-finite values, and mismatched bounds.
    Geometry and topology checks default to warnings because Rockstar's shipped
    YNVs can contain zero-length corners or one-way local links.  Pass
    ``strict=True`` to promote those compatibility warnings to errors when
    validating newly authored geometry.

    The returned warning strings are useful to UI callers; existing callers may
    continue to ignore the return value and only handle ``NavMeshValidationError``.
    """

    errors: List[str] = []
    warnings: List[str] = []

    def error(message: str) -> None:
        _append_issue(errors, message)

    def warning(message: str) -> None:
        if strict:
            error(message)
        else:
            _append_issue(warnings, message)

    if not _is_int_in_range(navmesh.area_id, 0, MAX_AREA_ID):
        error(f"AreaID must be an integer between 0 and {MAX_AREA_ID}")

    for name, vec in (("BBMin", navmesh.bb_min), ("BBMax", navmesh.bb_max), ("BBSize", navmesh.bb_size)):
        if not _is_finite_vec(vec):
            error(f"{name} must contain finite x, y and z values")

    bounds_valid = _is_finite_vec(navmesh.bb_min) and _is_finite_vec(navmesh.bb_max)
    size_valid = _is_finite_vec(navmesh.bb_size)
    if bounds_valid:
        if (
            navmesh.bb_max.x <= navmesh.bb_min.x
            or navmesh.bb_max.y <= navmesh.bb_min.y
            or navmesh.bb_max.z <= navmesh.bb_min.z
        ):
            error("BBMax must be greater than BBMin on every axis")
            bounds_valid = False
    if bounds_valid and size_valid:
        expected_size = (
            navmesh.bb_max.x - navmesh.bb_min.x,
            navmesh.bb_max.y - navmesh.bb_min.y,
            navmesh.bb_max.z - navmesh.bb_min.z,
        )
        supplied_size = (navmesh.bb_size.x, navmesh.bb_size.y, navmesh.bb_size.z)
        if any(
            not math.isclose(expected, supplied, rel_tol=1e-5, abs_tol=BOUNDS_TOLERANCE)
            for expected, supplied in zip(expected_size, supplied_size)
        ):
            error("BBSize must equal BBMax - BBMin (within export precision)")

    polygon_count = len(navmesh.polygons)
    if polygon_count > MAX_POLYGONS:
        error(
            f"Navmesh has {polygon_count} polygons; at most {MAX_POLYGONS} can be addressed "
            f"because {NO_NEIGHBOUR} is reserved as the no-neighbour ID"
        )

    total_indices = 0
    local_edge_references: List[Tuple[int, int]] = []
    # XmlYnv always reserves these six slots before it adds actual neighbours.
    # Keep the same unsigned arithmetic as CodeWalker's uint implementation.
    compiler_area_id = navmesh.area_id if _is_int_in_range(navmesh.area_id, 0, MAX_AREA_ID) else 0
    adjacent_area_ids = {
        compiler_area_id,
        NO_NEIGHBOUR,
        (compiler_area_id - 100) & 0xFFFFFFFF,
        (compiler_area_id - 1) & 0xFFFFFFFF,
        (compiler_area_id + 1) & 0xFFFFFFFF,
        (compiler_area_id + 100) & 0xFFFFFFFF,
    }
    for index, polygon in enumerate(navmesh.polygons):
        vertex_count = len(polygon.vertices)
        total_indices += vertex_count
        if vertex_count < 3:
            error(f"Polygon {index} has fewer than 3 vertices")
        elif vertex_count > MAX_VERTICES_PER_POLYGON:
            error(
                f"Polygon {index} has {vertex_count} vertices; the binary IndexCount field supports "
                f"at most {MAX_VERTICES_PER_POLYGON}"
            )

        if len(polygon.flags) not in (6, 7):
            error(f"Polygon {index} must have 6 or 7 flags")
        for flag_index, flag in enumerate(polygon.flags):
            maximum = MAX_POLYGON_FLAGS5 if flag_index == 6 else MAX_BYTE
            if not _is_int_in_range(flag, 0, maximum):
                if flag_index == 6:
                    error(f"Polygon {index} flag 6 (Flags5) must be 0 or 1")
                else:
                    error(f"Polygon {index} flag {flag_index} must be a byte (0..{MAX_BYTE})")

        if len(polygon.edges) != vertex_count:
            error(f"Polygon {index} has {vertex_count} vertices but {len(polygon.edges)} edges")
        if len(polygon.edges_flags) != vertex_count:
            error(
                f"Polygon {index} has {vertex_count} vertices but {len(polygon.edges_flags)} edge flag rows"
            )

        if len(polygon.portals) > MAX_PORTAL_LINKS_PER_POLYGON:
            error(
                f"Polygon {index} has {len(polygon.portals)} portal links; the binary field supports "
                f"at most {MAX_PORTAL_LINKS_PER_POLYGON}"
            )

        for vertex_index, vertex in enumerate(polygon.vertices):
            if not _is_finite_vec(vertex):
                error(f"Polygon {index} vertex {vertex_index} must contain finite x, y and z values")
                continue
            if bounds_valid and not _inside_bounds(vertex, navmesh.bb_min, navmesh.bb_max, BOUNDS_TOLERANCE):
                error(f"Polygon {index} vertex {vertex_index} lies outside BBMin/BBMax")

        # A zero-length edge or zero-area polygon is accepted as a warning by
        # default: a small number of Rockstar's own XML exports contain them.
        if vertex_count >= 3 and all(_is_finite_vec(vertex) for vertex in polygon.vertices):
            if _polygon_area_squared(polygon.vertices) <= GEOMETRY_EPSILON_SQUARED:
                warning(f"Polygon {index} has zero or near-zero area")
            for vertex_index, (first, second) in enumerate(
                zip(polygon.vertices, polygon.vertices[1:] + polygon.vertices[:1])
            ):
                if _edge_length_squared(first, second) <= GEOMETRY_EPSILON_SQUARED:
                    warning(f"Polygon {index} edge {vertex_index} has zero or near-zero length")

        for edge_index, edge in enumerate(polygon.edges):
            values = _parse_edge_value(edge)
            if values is None:
                error(f"Polygon {index} edge {edge_index} has invalid format: {edge!r}")
                continue
            area1, poly1, area2, poly2 = values
            if area1 > NO_NEIGHBOUR or area2 > NO_NEIGHBOUR:
                error(f"Polygon {index} edge {edge_index} has an AreaID outside 0..{NO_NEIGHBOUR}")
            if poly1 > MAX_POLYGON_ID or poly2 > MAX_POLYGON_ID:
                error(f"Polygon {index} edge {edge_index} has a polygon ID outside 0..{MAX_POLYGON_ID}")
            if (area1, poly1) != (area2, poly2):
                error(
                    f"Polygon {index} edge {edge_index} must duplicate the same neighbouring "
                    "area:polygon tuple in both halves"
                )
            if (area1 == NO_NEIGHBOUR) != (poly1 == NO_NEIGHBOUR):
                error(
                    f"Polygon {index} edge {edge_index} must use {NO_NEIGHBOUR}:{NO_NEIGHBOUR} "
                    "for an unlinked boundary"
                )
            elif area1 != NO_NEIGHBOUR:
                adjacent_area_ids.add(area1)
            if area1 == navmesh.area_id and poly1 != NO_NEIGHBOUR:
                if poly1 >= polygon_count:
                    error(
                        f"Polygon {index} edge {edge_index} refers to local polygon {poly1}, "
                        "which is outside the polygon range"
                    )
                elif poly1 == index:
                    warning(f"Polygon {index} edge {edge_index} refers to itself")
                else:
                    local_edge_references.append((index, poly1))

        for edge_index, edge_flags in enumerate(polygon.edges_flags):
            values = _parse_edge_value(edge_flags)
            if values is None:
                error(f"Polygon {index} edge flags {edge_index} has invalid format: {edge_flags!r}")
                continue
            unk2a, unk3a, unk2b, unk3b = values
            if unk2a > MAX_EDGE_UNK2 or unk2b > MAX_EDGE_UNK2:
                error(
                    f"Polygon {index} edge flags {edge_index} has an Unk2 value outside 0..{MAX_EDGE_UNK2}"
                )
            if unk3a > MAX_EDGE_UNK3 or unk3b > MAX_EDGE_UNK3:
                error(
                    f"Polygon {index} edge flags {edge_index} has an Unk3 value outside 0..{MAX_EDGE_UNK3}"
                )

    if total_indices > MAX_TOTAL_INDICES:
        error(
            f"Navmesh has {total_indices} polygon indices; the binary IndexID field supports "
            f"at most {MAX_TOTAL_INDICES}"
        )

    if len(adjacent_area_ids) > MAX_ADJACENT_AREA_IDS:
        error(
            f"Navmesh needs {len(adjacent_area_ids)} adjacent AreaID slots; the native YNV field supports "
            f"at most {MAX_ADJACENT_AREA_IDS}"
        )

    # A reciprocal link is desirable when all cells being edited are loaded,
    # but it cannot be a hard failure for legacy data: several vanilla YNVs
    # contain one-way local references after their original build pipeline.
    local_reference_set = set(local_edge_references)
    nonreciprocal_local_links = sum(
        1 for source, target in local_edge_references if (target, source) not in local_reference_set
    )
    if nonreciprocal_local_links:
        warning(
            f"{nonreciprocal_local_links} local edge reference(s) do not have a direct reciprocal link; "
            "run the cross-cell edge rebuild before shipping newly edited geometry"
        )

    portal_count = len(navmesh.portals)
    if portal_count > MAX_PORTALS:
        error(
            f"Navmesh has {portal_count} portals; PortalLinks can address at most {MAX_PORTALS}"
        )
    portal_users: List[set] = [set() for _ in navmesh.portals]
    for polygon_index, polygon in enumerate(navmesh.polygons):
        seen_portals = set()
        for portal_index in polygon.portals:
            if not _is_int_in_range(portal_index, 0, MAX_PORTAL_INDEX):
                error(f"Polygon {polygon_index} portal index {portal_index!r} is not a ushort")
                continue
            if portal_index >= portal_count:
                error(
                    f"Polygon {polygon_index} portal index {portal_index} is outside the portal range"
                )
                continue
            if portal_index in seen_portals:
                error(f"Polygon {polygon_index} lists portal {portal_index} more than once")
                continue
            seen_portals.add(portal_index)
            portal_users[portal_index].add(polygon_index)

    for index, portal in enumerate(navmesh.portals):
        if not _is_int_in_range(portal.type, 0, MAX_BYTE):
            error(f"Portal {index} Type must be a byte (0..{MAX_BYTE})")
        elif portal.type not in (1, 2, 3):
            warning(f"Portal {index} Type {portal.type} is not one of the known GTA V values 1, 2 or 3")
        if not _is_finite_number(portal.angle):
            error(f"Portal {index} Angle must be finite")
        elif not -ANGLE_LIMIT <= float(portal.angle) <= ANGLE_LIMIT:
            warning(f"Portal {index} Angle is outside the normal -2π..2π range and will be byte-quantized")
        if not 0 <= portal.poly_from < polygon_count:
            error(f"Portal {index} PolyFrom {portal.poly_from} is outside polygon range")
        if not 0 <= portal.poly_to < polygon_count:
            error(f"Portal {index} PolyTo {portal.poly_to} is outside polygon range")
        for name, position in (("PositionFrom", portal.position_from), ("PositionTo", portal.position_to)):
            if not _is_finite_vec(position):
                error(f"Portal {index} {name} must contain finite x, y and z values")
            elif bounds_valid and not _inside_bounds(position, navmesh.bb_min, navmesh.bb_max, BOUNDS_TOLERANCE):
                error(f"Portal {index} {name} lies outside BBMin/BBMax")

        if 0 <= portal.poly_from < polygon_count and portal.poly_from not in portal_users[index]:
            error(f"Portal {index} is not linked from its PolyFrom polygon {portal.poly_from}")
        if 0 <= portal.poly_to < polygon_count and portal.poly_to not in portal_users[index]:
            error(f"Portal {index} is not linked from its PolyTo polygon {portal.poly_to}")
        unrelated_users = portal_users[index] - {portal.poly_from, portal.poly_to}
        if unrelated_users:
            error(
                f"Portal {index} is linked from unrelated polygon(s): "
                + ", ".join(str(value) for value in sorted(unrelated_users))
            )

    for index, point in enumerate(navmesh.points):
        if not _is_int_in_range(point.type, 0, MAX_BYTE):
            error(f"Point {index} Type must be a byte (0..{MAX_BYTE})")
        elif point.type not in (0, 1, 2, 3, 4, 5, 128, 171, 254):
            warning(f"Point {index} Type {point.type} is not a commonly observed GTA V value")
        if not _is_finite_number(point.angle):
            error(f"Point {index} Angle must be finite")
        elif not -ANGLE_LIMIT <= float(point.angle) <= ANGLE_LIMIT:
            warning(f"Point {index} Angle is outside the normal -2π..2π range and will be byte-quantized")
        if not _is_finite_vec(point.position):
            error(f"Point {index} Position must contain finite x, y and z values")
        elif bounds_valid and not _inside_bounds(point.position, navmesh.bb_min, navmesh.bb_max, BOUNDS_TOLERANCE):
            error(f"Point {index} Position lies outside BBMin/BBMax")

    content_flags = {value.strip() for value in navmesh.content_flags.split(",") if value.strip()}
    if navmesh.polygons and "Polygons" not in content_flags:
        warning("ContentFlags does not include Polygons although polygon data is present")
    if navmesh.portals and "Portals" not in content_flags:
        warning("ContentFlags does not include Portals although portal data is present")

    if errors:
        suffix = "" if len(errors) < MAX_REPORTED_ISSUES else "; additional errors omitted"
        raise NavMeshValidationError("; ".join(errors[:10]) + suffix)
    return warnings


def validate_navmesh_xml(path: Union[str, Path], *, strict: bool = False) -> List[str]:
    """Read and validate a CodeWalker YNV XML file without writing it."""

    navmesh = read_navmesh_xml(path, validate=False)
    return validate_navmesh_for_codewalker(navmesh, strict=strict)


def read_navmesh_xml(
    path: Union[str, Path], *, validate: bool = True, strict: bool = False
) -> NavMesh:
    root = ET.parse(path).getroot()
    if root.tag != "NavMesh":
        raise ValueError(f"Expected NavMesh XML root, got {root.tag!r}")

    navmesh = NavMesh()
    navmesh.content_flags = (root.findtext("ContentFlags") or "").strip()
    navmesh.area_id = _attr_int(root, "AreaID")

    for tag, attr in (("BBMin", "bb_min"), ("BBMax", "bb_max"), ("BBSize", "bb_size")):
        node = root.find(tag)
        if node is not None:
            setattr(navmesh, attr, _vec_from_attrs(node))

    polygons = root.find("Polygons")
    if polygons is not None:
        for item in polygons.findall("Item"):
            flags = [int(value) for value in (item.findtext("Flags") or "").split()]
            vertices = _parse_vertices(item.findtext("Vertices"))
            edges = _parse_edges(item.findtext("Edges"))
            edges_flags_node = item.find("EdgesFlags")
            edges_flags = _parse_edges(edges_flags_node.text if edges_flags_node is not None else None)
            portals = [int(value) for value in (item.findtext("Portals") or "").split()]
            if len(vertices) != len(edges):
                raise ValueError("Polygon vertex/edge count mismatch")
            # Keep parity with the bundled compiler: older exports sometimes
            # omit the entire optional element.  A present-but-empty/mismatched
            # EdgesFlags element stays invalid and is rejected by validation.
            if edges_flags_node is None:
                edges_flags = [DEFAULT_EDGE_FLAGS] * len(edges)
            polygon = Polygon(flags=flags, vertices=vertices, edges=edges)
            polygon.edges_flags = edges_flags
            polygon.portals = portals
            navmesh.polygons.append(polygon)

    portals = root.find("Portals")
    if portals is not None:
        for item in portals.findall("Item"):
            position_from = item.find("PositionFrom")
            position_to = item.find("PositionTo")
            if position_from is None or position_to is None:
                continue
            navmesh.portals.append(
                Portal(
                    type=_attr_int(item, "Type"),
                    angle=_attr_float(item, "Angle"),
                    poly_from=_attr_int(item, "PolyFrom"),
                    poly_to=_attr_int(item, "PolyTo"),
                    position_from=_vec_from_attrs(position_from),
                    position_to=_vec_from_attrs(position_to),
                )
            )

    points = root.find("Points")
    if points is not None:
        for item in points.findall("Item"):
            position = item.find("Position")
            if position is None:
                continue
            navmesh.points.append(
                Point(
                    type=_attr_int(item, "Type"),
                    angle=_attr_float(item, "Angle"),
                    position=_vec_from_attrs(position),
                )
            )

    if validate:
        validate_navmesh_for_codewalker(navmesh, strict=strict)
    return navmesh


def _format_float(value: float) -> str:
    return f"{value:.9g}"


def _set_value(parent: ET.Element, tag: str, value: Union[int, float, str]) -> None:
    ET.SubElement(parent, tag, {"value": str(value)})


def _set_vec(parent: ET.Element, tag: str, vec: Vec3) -> None:
    ET.SubElement(
        parent,
        tag,
        {"x": _format_float(vec.x), "y": _format_float(vec.y), "z": _format_float(vec.z)},
    )


def _indent(elem: ET.Element, level: int = 0) -> None:
    indent = "\n" + level * " "
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = indent + " "
        for child in elem:
            _indent(child, level + 1)
        if not child.tail or not child.tail.strip():
            child.tail = indent
    if level and (not elem.tail or not elem.tail.strip()):
        elem.tail = indent


def write_navmesh_xml(navmesh: NavMesh, path: Union[str, Path], *, strict: bool = False) -> None:
    validate_navmesh_for_codewalker(navmesh, strict=strict)

    root = ET.Element("NavMesh")
    ET.SubElement(root, "ContentFlags").text = navmesh.content_flags
    _set_value(root, "AreaID", navmesh.area_id)
    _set_vec(root, "BBMin", navmesh.bb_min)
    _set_vec(root, "BBMax", navmesh.bb_max)
    _set_vec(root, "BBSize", navmesh.bb_size)

    polygons = ET.SubElement(root, "Polygons")
    for polygon in navmesh.polygons:
        item = ET.SubElement(polygons, "Item")
        ET.SubElement(item, "Flags").text = " ".join(str(value) for value in polygon.flags)
        vertices = ET.SubElement(item, "Vertices")
        vertices.text = "\n" + "\n".join(
            f"    {_format_float(v.x)}, {_format_float(v.y)}, {_format_float(v.z)}"
            for v in polygon.vertices
        ) + "\n   "
        edges = ET.SubElement(item, "Edges")
        edges.text = "\n" + "\n".join(f"    {edge}" for edge in polygon.edges) + "\n   "
        edges_flags = ET.SubElement(item, "EdgesFlags")
        edges_flags.text = "\n" + "\n".join(f"    {edge_flags}" for edge_flags in polygon.edges_flags) + "\n   "
        polygon_portals = getattr(polygon, "portals", [])
        if polygon_portals:
            ET.SubElement(item, "Portals").text = " ".join(str(value) for value in polygon_portals)

    portals = ET.SubElement(root, "Portals")
    for portal in navmesh.portals:
        item = ET.SubElement(portals, "Item")
        _set_value(item, "Type", portal.type)
        _set_value(item, "Angle", _format_float(portal.angle))
        _set_value(item, "PolyFrom", portal.poly_from)
        _set_value(item, "PolyTo", portal.poly_to)
        _set_vec(item, "PositionFrom", portal.position_from)
        _set_vec(item, "PositionTo", portal.position_to)

    points = ET.SubElement(root, "Points")
    for point in navmesh.points:
        item = ET.SubElement(points, "Item")
        _set_value(item, "Type", point.type)
        _set_value(item, "Angle", _format_float(point.angle))
        _set_vec(item, "Position", point.position)

    _indent(root)
    tree = ET.ElementTree(root)
    tree.write(path, encoding="UTF-8", xml_declaration=True)
