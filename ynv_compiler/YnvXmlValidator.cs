// Copyright (c) 2026 devsanja

using System.Globalization;
using System.Text.RegularExpressions;
using System.Xml;
using CodeWalker.GameFiles;

internal readonly record struct YnvVector(float X, float Y, float Z);
internal readonly record struct EdgeTuple(int Area1, int Poly1, int Area2, int Poly2);

internal sealed class YnvValidationResult
{
    private const int MaxWarnings = 100;

    public List<string> Warnings { get; } = new();

    public void Warn(string message)
    {
        if (Warnings.Count < MaxWarnings)
        {
            Warnings.Add(message);
        }
    }
}

/// <summary>
/// Validates the XML representation before XmlYnv's permissive parser can
/// silently truncate a value into a packed YNV field.  The checks intentionally
/// mirror the relevant CodeWalker resource-field widths.
/// </summary>
internal static class YnvXmlValidator
{
    private const int NoNeighbour = 0x3FFF;
    private const int MaxAreaId = NoNeighbour - 1;
    private const int MaxPolygons = NoNeighbour;
    private const int MaxAdjacentAreaIds = 32;
    private const int MaxVerticesPerPolygon = 0x7FF;
    private const int MaxTotalIndices = 0x10000;
    private const int MaxPortalLinksPerPolygon = 0x7;
    private const int MaxPortals = 0x10000;
    private const float BoundsTolerance = 1e-3f;
    private const double GeometryEpsilonSquared = 1e-12;

    private static readonly Regex EdgeRow = new(
        @"^(?<area1>\d+):(?<poly1>\d+),\s*(?<area2>\d+):(?<poly2>\d+)$",
        RegexOptions.Compiled | RegexOptions.CultureInvariant);

    public static YnvValidationResult Validate(string xml)
    {
        var document = new XmlDocument { XmlResolver = null };
        document.LoadXml(xml);
        var root = document.DocumentElement;
        if (root is null || root.Name != "NavMesh")
        {
            throw new InvalidDataException("Expected a NavMesh XML root element.");
        }

        var result = new YnvValidationResult();
        var areaId = ReadValueInt(root, "AreaID", 0, MaxAreaId);
        var bbMin = ReadVector(root, "BBMin");
        var bbMax = ReadVector(root, "BBMax");
        var bbSize = ReadVector(root, "BBSize");
        ValidateBounds(bbMin, bbMax, bbSize);

        var polygonNodes = GetItems(root, "Polygons");
        if (polygonNodes.Count > MaxPolygons)
        {
            throw new InvalidDataException(
                $"The navmesh has {polygonNodes.Count} polygons; {NoNeighbour} is reserved as the no-neighbour ID.");
        }

        var totalIndices = 0;
        var localEdgeReferences = new List<(int Source, int Target)>();
        var adjacentAreaIds = CreateInitialAdjacentAreaIds(areaId);
        var polygonPortalLinks = new List<List<int>>(polygonNodes.Count);
        for (var polygonIndex = 0; polygonIndex < polygonNodes.Count; polygonIndex++)
        {
            var polygon = polygonNodes[polygonIndex];
            var flags = ReadWhitespaceIntegers(RequireChild(polygon, "Flags"), $"Polygon {polygonIndex} Flags");
            if (flags.Count is not (6 or 7))
            {
                throw new InvalidDataException($"Polygon {polygonIndex} must have 6 or 7 Flags values.");
            }
            for (var flagIndex = 0; flagIndex < flags.Count; flagIndex++)
            {
                // CodeWalker's seventh XML Flags value (Flags5) is stored in
                // a single bit of PolyFlags1.  Reject higher values here
                // rather than silently masking them during XmlYnv parsing.
                var maximum = flagIndex == 6 ? 1 : byte.MaxValue;
                RequireRange(
                    flags[flagIndex],
                    0,
                    maximum,
                    flagIndex == 6
                        ? $"Polygon {polygonIndex} Flags5"
                        : $"Polygon {polygonIndex} Flags value");
            }

            var vertices = ReadVertices(RequireChild(polygon, "Vertices"), polygonIndex);
            if (vertices.Count < 3)
            {
                throw new InvalidDataException($"Polygon {polygonIndex} has fewer than 3 vertices.");
            }
            if (vertices.Count > MaxVerticesPerPolygon)
            {
                throw new InvalidDataException(
                    $"Polygon {polygonIndex} has {vertices.Count} vertices; the packed IndexCount field supports {MaxVerticesPerPolygon}.");
            }
            totalIndices += vertices.Count;
            foreach (var vertex in vertices)
            {
                RequireInsideBounds(vertex, bbMin, bbMax, $"Polygon {polygonIndex} vertex");
            }
            ValidateGeometry(vertices, polygonIndex, result);

            var edgeRows = ReadRows(RequireChild(polygon, "Edges"));
            if (edgeRows.Count != vertices.Count)
            {
                throw new InvalidDataException(
                    $"Polygon {polygonIndex} has {vertices.Count} vertices but {edgeRows.Count} Edges rows.");
            }
            foreach (var edgeRow in edgeRows)
            {
                var edge = ParseEdgeTuple(edgeRow, $"Polygon {polygonIndex} Edges");
                ValidateNeighbourEdge(edge, areaId, polygonIndex, polygonNodes.Count, localEdgeReferences);
                if (edge.Area1 != NoNeighbour)
                {
                    adjacentAreaIds.Add((uint)edge.Area1);
                }
            }

            var edgeFlagRows = ReadRows(RequireChild(polygon, "EdgesFlags"));
            if (edgeFlagRows.Count != vertices.Count)
            {
                throw new InvalidDataException(
                    $"Polygon {polygonIndex} has {vertices.Count} vertices but {edgeFlagRows.Count} EdgesFlags rows.");
            }
            foreach (var edgeFlagRow in edgeFlagRows)
            {
                var edgeFlags = ParseEdgeTuple(edgeFlagRow, $"Polygon {polygonIndex} EdgesFlags");
                RequireRange(edgeFlags.Area1, 0, 0x3, $"Polygon {polygonIndex} EdgesFlags Unk2");
                RequireRange(edgeFlags.Area2, 0, 0x3, $"Polygon {polygonIndex} EdgesFlags Unk2");
                RequireRange(edgeFlags.Poly1, 0, 0x7FF, $"Polygon {polygonIndex} EdgesFlags Unk3");
                RequireRange(edgeFlags.Poly2, 0, 0x7FF, $"Polygon {polygonIndex} EdgesFlags Unk3");
            }

            var portalLinksNode = GetChild(polygon, "Portals");
            var portalLinks = portalLinksNode is null
                ? new List<int>()
                : ReadWhitespaceIntegers(portalLinksNode, $"Polygon {polygonIndex} Portals");
            if (portalLinks.Count > MaxPortalLinksPerPolygon)
            {
                throw new InvalidDataException(
                    $"Polygon {polygonIndex} has {portalLinks.Count} portal links; the packed field supports {MaxPortalLinksPerPolygon}.");
            }
            foreach (var portalLink in portalLinks)
            {
                RequireRange(portalLink, 0, ushort.MaxValue, $"Polygon {polygonIndex} portal index");
            }
            polygonPortalLinks.Add(portalLinks);
        }

        if (totalIndices > MaxTotalIndices)
        {
            throw new InvalidDataException(
                $"The navmesh has {totalIndices} polygon indices; the packed IndexID field supports at most {MaxTotalIndices}.");
        }

        if (adjacentAreaIds.Count > MaxAdjacentAreaIds)
        {
            throw new InvalidDataException(
                $"The navmesh needs {adjacentAreaIds.Count} AdjAreaIDs entries; the native YNV struct has only {MaxAdjacentAreaIds} slots.");
        }

        var localReferenceSet = new HashSet<(int Source, int Target)>(localEdgeReferences);
        var nonReciprocal = 0;
        foreach (var (source, target) in localEdgeReferences)
        {
            if (!localReferenceSet.Contains((target, source)))
            {
                nonReciprocal++;
            }
        }
        if (nonReciprocal > 0)
        {
            result.Warn(
                $"{nonReciprocal} local edge reference(s) have no direct reciprocal link; rebuild loaded neighbour cells before shipping edited geometry.");
        }

        var portalNodes = GetItems(root, "Portals");
        if (portalNodes.Count > MaxPortals)
        {
            throw new InvalidDataException($"The navmesh has {portalNodes.Count} portals; PortalLinks stores ushort indices.");
        }
        var portals = new List<(int PolyFrom, int PolyTo)>(portalNodes.Count);
        for (var portalIndex = 0; portalIndex < portalNodes.Count; portalIndex++)
        {
            var portal = portalNodes[portalIndex];
            var type = ReadValueInt(portal, "Type", 0, byte.MaxValue);
            if (type is not (1 or 2 or 3))
            {
                result.Warn($"Portal {portalIndex} Type {type} is not one of the known GTA V values 1, 2 or 3.");
            }
            var angle = ReadValueFloat(portal, "Angle");
            if (angle < -MathF.Tau || angle > MathF.Tau)
            {
                result.Warn($"Portal {portalIndex} Angle is outside the normal -2π..2π range and will be byte-quantized.");
            }
            var polyFrom = ReadValueInt(portal, "PolyFrom", 0, ushort.MaxValue);
            var polyTo = ReadValueInt(portal, "PolyTo", 0, ushort.MaxValue);
            if (polyFrom >= polygonNodes.Count || polyTo >= polygonNodes.Count)
            {
                throw new InvalidDataException($"Portal {portalIndex} refers to a polygon outside the local polygon range.");
            }
            RequireInsideBounds(ReadVector(portal, "PositionFrom"), bbMin, bbMax, $"Portal {portalIndex} PositionFrom");
            RequireInsideBounds(ReadVector(portal, "PositionTo"), bbMin, bbMax, $"Portal {portalIndex} PositionTo");
            portals.Add((polyFrom, polyTo));
        }

        var portalUsers = new List<HashSet<int>>(portalNodes.Count);
        for (var portalIndex = 0; portalIndex < portalNodes.Count; portalIndex++)
        {
            portalUsers.Add(new HashSet<int>());
        }
        for (var polygonIndex = 0; polygonIndex < polygonPortalLinks.Count; polygonIndex++)
        {
            var linksSeen = new HashSet<int>();
            foreach (var portalIndex in polygonPortalLinks[polygonIndex])
            {
                if (portalIndex >= portalNodes.Count)
                {
                    throw new InvalidDataException(
                        $"Polygon {polygonIndex} refers to portal {portalIndex}, which is outside the portal range.");
                }
                if (!linksSeen.Add(portalIndex))
                {
                    throw new InvalidDataException($"Polygon {polygonIndex} lists portal {portalIndex} more than once.");
                }
                portalUsers[portalIndex].Add(polygonIndex);
            }
        }
        for (var portalIndex = 0; portalIndex < portals.Count; portalIndex++)
        {
            var (polyFrom, polyTo) = portals[portalIndex];
            if (!portalUsers[portalIndex].Contains(polyFrom))
            {
                throw new InvalidDataException($"Portal {portalIndex} is not linked from PolyFrom polygon {polyFrom}.");
            }
            if (!portalUsers[portalIndex].Contains(polyTo))
            {
                throw new InvalidDataException($"Portal {portalIndex} is not linked from PolyTo polygon {polyTo}.");
            }
            foreach (var user in portalUsers[portalIndex])
            {
                if (user != polyFrom && user != polyTo)
                {
                    throw new InvalidDataException($"Portal {portalIndex} is linked from unrelated polygon {user}.");
                }
            }
        }

        var pointNodes = GetItems(root, "Points");
        for (var pointIndex = 0; pointIndex < pointNodes.Count; pointIndex++)
        {
            var point = pointNodes[pointIndex];
            var type = ReadValueInt(point, "Type", 0, byte.MaxValue);
            if (type is not (0 or 1 or 2 or 3 or 4 or 5 or 128 or 171 or 254))
            {
                result.Warn($"Point {pointIndex} Type {type} is not a commonly observed GTA V value.");
            }
            var angle = ReadValueFloat(point, "Angle");
            if (angle < -MathF.Tau || angle > MathF.Tau)
            {
                result.Warn($"Point {pointIndex} Angle is outside the normal -2π..2π range and will be byte-quantized.");
            }
            RequireInsideBounds(ReadVector(point, "Position"), bbMin, bbMax, $"Point {pointIndex} Position");
        }

        var contentFlags = (GetChild(root, "ContentFlags")?.InnerText ?? string.Empty)
            .Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries)
            .ToHashSet(StringComparer.Ordinal);
        if (polygonNodes.Count > 0 && !contentFlags.Contains("Polygons"))
        {
            result.Warn("ContentFlags does not include Polygons although polygon data is present.");
        }
        if (portalNodes.Count > 0 && !contentFlags.Contains("Portals"))
        {
            result.Warn("ContentFlags does not include Portals although portal data is present.");
        }

        return result;
    }

    public static void ValidateDecodedYnv(YnvFile ynv)
    {
        var areaId = ynv.AreaID;
        RequireRange(areaId, 0, MaxAreaId, "Native YNV AreaID");
        if ((ynv.Nav?.AdjAreaIDs.Count ?? 0) > MaxAdjacentAreaIds)
        {
            throw new InvalidDataException($"Native YNV has more than {MaxAdjacentAreaIds} AdjAreaIDs entries.");
        }
        var polygons = ynv.Polys ?? new List<YnvPoly>();
        if (polygons.Count > MaxPolygons)
        {
            throw new InvalidDataException($"Native YNV has {polygons.Count} polygons, exceeding the addressable range.");
        }
        foreach (var polygon in polygons)
        {
            var vertices = polygon.Vertices?.Length ?? 0;
            var edges = polygon.Edges?.Length ?? 0;
            if (vertices < 3 || vertices > MaxVerticesPerPolygon || edges != vertices)
            {
                throw new InvalidDataException("Native YNV contains a polygon with invalid vertex or edge counts.");
            }
            if ((polygon.PortalLinks?.Length ?? 0) > MaxPortalLinksPerPolygon)
            {
                throw new InvalidDataException("Native YNV contains a polygon with too many portal links.");
            }
            foreach (var edge in polygon.Edges!)
            {
                if (edge.AreaID1 > NoNeighbour || edge.AreaID2 > NoNeighbour ||
                    edge.PolyID1 > NoNeighbour || edge.PolyID2 > NoNeighbour)
                {
                    throw new InvalidDataException("Native YNV contains an edge outside the 14-bit AreaID/PolyID range.");
                }
            }
        }
        var portals = ynv.Portals ?? new List<YnvPortal>();
        foreach (var portal in portals)
        {
            if (portal.PolyIDFrom1 >= polygons.Count || portal.PolyIDTo1 >= polygons.Count)
            {
                throw new InvalidDataException("Native YNV contains a portal with an out-of-range polygon reference.");
            }
        }
    }

    private static void ValidateBounds(YnvVector bbMin, YnvVector bbMax, YnvVector bbSize)
    {
        if (bbMax.X <= bbMin.X || bbMax.Y <= bbMin.Y || bbMax.Z <= bbMin.Z)
        {
            throw new InvalidDataException("BBMax must be greater than BBMin on every axis.");
        }
        if (!NearlyEqual(bbMax.X - bbMin.X, bbSize.X) ||
            !NearlyEqual(bbMax.Y - bbMin.Y, bbSize.Y) ||
            !NearlyEqual(bbMax.Z - bbMin.Z, bbSize.Z))
        {
            throw new InvalidDataException("BBSize must equal BBMax - BBMin within export precision.");
        }
    }

    private static HashSet<uint> CreateInitialAdjacentAreaIds(int areaId)
    {
        // XmlYnv reserves these values before it adds the areas used by edges.
        // Match its uint arithmetic exactly, including values below AreaID 0.
        return new HashSet<uint>
        {
            (uint)areaId,
            NoNeighbour,
            unchecked((uint)(areaId - 100)),
            unchecked((uint)(areaId - 1)),
            unchecked((uint)(areaId + 1)),
            unchecked((uint)(areaId + 100)),
        };
    }

    private static void ValidateGeometry(IReadOnlyList<YnvVector> vertices, int polygonIndex, YnvValidationResult result)
    {
        double nx = 0, ny = 0, nz = 0;
        for (var index = 0; index < vertices.Count; index++)
        {
            var current = vertices[index];
            var following = vertices[(index + 1) % vertices.Count];
            nx += (current.Y - following.Y) * (current.Z + following.Z);
            ny += (current.Z - following.Z) * (current.X + following.X);
            nz += (current.X - following.X) * (current.Y + following.Y);
            var dx = current.X - following.X;
            var dy = current.Y - following.Y;
            var dz = current.Z - following.Z;
            if (dx * dx + dy * dy + dz * dz <= GeometryEpsilonSquared)
            {
                result.Warn($"Polygon {polygonIndex} contains a zero or near-zero length edge.");
            }
        }
        if ((nx * nx + ny * ny + nz * nz) * 0.25 <= GeometryEpsilonSquared)
        {
            result.Warn($"Polygon {polygonIndex} has zero or near-zero area.");
        }
    }

    private static void ValidateNeighbourEdge(
        EdgeTuple edge,
        int areaId,
        int sourcePolygon,
        int polygonCount,
        List<(int Source, int Target)> localEdgeReferences)
    {
        RequireRange(edge.Area1, 0, NoNeighbour, $"Polygon {sourcePolygon} edge AreaID");
        RequireRange(edge.Area2, 0, NoNeighbour, $"Polygon {sourcePolygon} edge AreaID");
        RequireRange(edge.Poly1, 0, NoNeighbour, $"Polygon {sourcePolygon} edge polygon ID");
        RequireRange(edge.Poly2, 0, NoNeighbour, $"Polygon {sourcePolygon} edge polygon ID");
        if (edge.Area1 != edge.Area2 || edge.Poly1 != edge.Poly2)
        {
            throw new InvalidDataException(
                $"Polygon {sourcePolygon} edge must duplicate the same neighbouring area:polygon tuple in both halves.");
        }
        if ((edge.Area1 == NoNeighbour) != (edge.Poly1 == NoNeighbour))
        {
            throw new InvalidDataException(
                $"Polygon {sourcePolygon} edge must use {NoNeighbour}:{NoNeighbour} for an unlinked boundary.");
        }
        if (edge.Area1 != areaId || edge.Poly1 == NoNeighbour)
        {
            return;
        }
        if (edge.Poly1 >= polygonCount)
        {
            throw new InvalidDataException(
                $"Polygon {sourcePolygon} edge refers to local polygon {edge.Poly1}, which is outside the polygon range.");
        }
        if (edge.Poly1 == sourcePolygon)
        {
            return;
        }
        localEdgeReferences.Add((sourcePolygon, edge.Poly1));
    }

    private static EdgeTuple ParseEdgeTuple(string row, string fieldName)
    {
        var match = EdgeRow.Match(row);
        if (!match.Success)
        {
            throw new InvalidDataException($"{fieldName} has invalid row format: '{row}'.");
        }
        return new EdgeTuple(
            ParseInteger(match.Groups["area1"].Value, fieldName),
            ParseInteger(match.Groups["poly1"].Value, fieldName),
            ParseInteger(match.Groups["area2"].Value, fieldName),
            ParseInteger(match.Groups["poly2"].Value, fieldName));
    }

    private static List<YnvVector> ReadVertices(XmlElement node, int polygonIndex)
    {
        var vertices = new List<YnvVector>();
        foreach (var row in ReadRows(node))
        {
            var values = row.Split(',');
            if (values.Length != 3)
            {
                throw new InvalidDataException($"Polygon {polygonIndex} has an invalid vertex row: '{row}'.");
            }
            vertices.Add(new YnvVector(
                ParseFiniteFloat(values[0], $"Polygon {polygonIndex} vertex x"),
                ParseFiniteFloat(values[1], $"Polygon {polygonIndex} vertex y"),
                ParseFiniteFloat(values[2], $"Polygon {polygonIndex} vertex z")));
        }
        return vertices;
    }

    private static List<string> ReadRows(XmlElement node)
    {
        var rows = new List<string>();
        foreach (var row in node.InnerText.Split(new[] { '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries))
        {
            var trimmed = row.Trim();
            if (trimmed.Length > 0)
            {
                rows.Add(trimmed);
            }
        }
        return rows;
    }

    private static List<int> ReadWhitespaceIntegers(XmlElement node, string fieldName)
    {
        var values = new List<int>();
        if (string.IsNullOrWhiteSpace(node.InnerText))
        {
            return values;
        }
        foreach (var value in Regex.Split(node.InnerText.Trim(), @"\s+"))
        {
            values.Add(ParseInteger(value, fieldName));
        }
        return values;
    }

    private static int ReadValueInt(XmlElement parent, string name, int minimum, int maximum)
    {
        var child = RequireChild(parent, name);
        var value = ParseInteger(child.GetAttribute("value"), name);
        RequireRange(value, minimum, maximum, name);
        return value;
    }

    private static float ReadValueFloat(XmlElement parent, string name)
    {
        return ParseFiniteFloat(RequireChild(parent, name).GetAttribute("value"), name);
    }

    private static YnvVector ReadVector(XmlElement parent, string name)
    {
        var child = RequireChild(parent, name);
        return new YnvVector(
            ParseFiniteFloat(child.GetAttribute("x"), $"{name} x"),
            ParseFiniteFloat(child.GetAttribute("y"), $"{name} y"),
            ParseFiniteFloat(child.GetAttribute("z"), $"{name} z"));
    }

    private static int ParseInteger(string value, string fieldName)
    {
        if (!int.TryParse(value, NumberStyles.Integer, CultureInfo.InvariantCulture, out var parsed))
        {
            throw new InvalidDataException($"{fieldName} must be an integer.");
        }
        return parsed;
    }

    private static float ParseFiniteFloat(string value, string fieldName)
    {
        if (!float.TryParse(value, NumberStyles.Float, CultureInfo.InvariantCulture, out var parsed) || !float.IsFinite(parsed))
        {
            throw new InvalidDataException($"{fieldName} must be a finite floating-point value.");
        }
        return parsed;
    }

    private static void RequireRange(int value, int minimum, int maximum, string fieldName)
    {
        if (value < minimum || value > maximum)
        {
            throw new InvalidDataException($"{fieldName} must be between {minimum} and {maximum}; got {value}.");
        }
    }

    private static void RequireInsideBounds(YnvVector value, YnvVector bbMin, YnvVector bbMax, string fieldName)
    {
        if (value.X < bbMin.X - BoundsTolerance || value.X > bbMax.X + BoundsTolerance ||
            value.Y < bbMin.Y - BoundsTolerance || value.Y > bbMax.Y + BoundsTolerance ||
            value.Z < bbMin.Z - BoundsTolerance || value.Z > bbMax.Z + BoundsTolerance)
        {
            throw new InvalidDataException($"{fieldName} lies outside BBMin/BBMax.");
        }
    }

    private static bool NearlyEqual(float first, float second)
    {
        return MathF.Abs(first - second) <= MathF.Max(BoundsTolerance, MathF.Max(MathF.Abs(first), MathF.Abs(second)) * 1e-5f);
    }

    private static XmlElement RequireChild(XmlElement parent, string name)
    {
        return GetChild(parent, name)
               ?? throw new InvalidDataException($"Missing required {name} element.");
    }

    private static XmlElement? GetChild(XmlElement parent, string name)
    {
        foreach (XmlNode child in parent.ChildNodes)
        {
            if (child is XmlElement element && element.Name == name)
            {
                return element;
            }
        }
        return null;
    }

    private static List<XmlElement> GetItems(XmlElement root, string collectionName)
    {
        var collection = GetChild(root, collectionName);
        var items = new List<XmlElement>();
        if (collection is null)
        {
            return items;
        }
        foreach (XmlNode child in collection.ChildNodes)
        {
            if (child is XmlElement element && element.Name == "Item")
            {
                items.Add(element);
            }
        }
        return items;
    }
}
