// Copyright (c) 2026 devsanja

using CodeWalker.GameFiles;
using System.Xml;

if (args.Length == 2 && args[0].Equals("--check", StringComparison.OrdinalIgnoreCase))
{
    return CheckYnv(args[1]);
}

if (args.Length == 2 && args[0].Equals("--validate", StringComparison.OrdinalIgnoreCase))
{
    return ValidateYnvXml(args[1]);
}

if (args.Length != 2)
{
    Console.Error.WriteLine("Usage: ynv_compiler <input.ynv.xml> <output.ynv>");
    Console.Error.WriteLine("       ynv_compiler --validate <input.ynv.xml>");
    Console.Error.WriteLine("       ynv_compiler --check <input.ynv>");
    return 2;
}

var xmlPath = Path.GetFullPath(args[0]);
var ynvPath = Path.GetFullPath(args[1]);

if (!File.Exists(xmlPath))
{
    Console.Error.WriteLine("Input XML not found: " + xmlPath);
    return 2;
}

try
{
    var xml = NormalizeYnvXml(File.ReadAllText(xmlPath));
    var validation = YnvXmlValidator.Validate(xml);
    PrintWarnings(validation);
    var ynv = XmlYnv.GetYnv(xml);
    ynv.Name = Path.GetFileName(ynvPath);
    ynv.BuildStructsOnSave = true;

    var data = ynv.Save();
    if (data.Length < 4 || data[0] != 0x52 || data[1] != 0x53 || data[2] != 0x43 || data[3] != 0x37)
    {
        Console.Error.WriteLine("Compiler wrote data without RSC7 header.");
        return 1;
    }

    var verification = new YnvFile();
    verification.Load(data);
    YnvXmlValidator.ValidateDecodedYnv(verification);

    // Do not overwrite a previously good native YNV until the freshly built
    // bytes have passed the in-memory RSC7 load/validation round trip.
    Directory.CreateDirectory(Path.GetDirectoryName(ynvPath)!);
    var temporaryPath = ynvPath + "." + Guid.NewGuid().ToString("N") + ".tmp";
    try
    {
        File.WriteAllBytes(temporaryPath, data);
        File.Move(temporaryPath, ynvPath, overwrite: true);
    }
    finally
    {
        if (File.Exists(temporaryPath))
        {
            File.Delete(temporaryPath);
        }
    }

    Console.WriteLine("Wrote " + ynvPath + " (" + data.Length + " bytes)");
    return 0;
}
catch (Exception ex)
{
    Console.Error.WriteLine(ex.ToString());
    return 1;
}

static string NormalizeYnvXml(string xml)
{
    var doc = new XmlDocument { XmlResolver = null };
    doc.LoadXml(xml);

    var polygonItems = doc.SelectNodes("/NavMesh/Polygons/Item");
    if (polygonItems != null)
    {
        foreach (XmlNode item in polygonItems)
        {
            var edges = item.SelectSingleNode("Edges");
            var edgesFlags = item.SelectSingleNode("EdgesFlags");
            if (edges == null)
            {
                continue;
            }

            var edgeRows = edges.InnerText
                .Split(new[] { '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries)
                .Select(row => row.Trim())
                .Where(row => row.Length > 0)
                .ToList();

            if (edgesFlags == null)
            {
                edgesFlags = doc.CreateElement("EdgesFlags");
                item.InsertAfter(edgesFlags, edges);
                // Older XML exports omit EdgesFlags altogether.  Fill only that
                // missing field; a present-but-mismatched field is invalid data
                // and is rejected by YnvXmlValidator instead of being erased.
                edgesFlags.InnerText = "\n    " + string.Join("\n    ", Enumerable.Repeat("0:0, 0:0", edgeRows.Count)) + "\n   ";
            }
        }
    }

    using var stringWriter = new StringWriter();
    using var xmlWriter = XmlWriter.Create(stringWriter, new XmlWriterSettings { OmitXmlDeclaration = false });
    doc.Save(xmlWriter);
    return stringWriter.ToString();
}

static int ValidateYnvXml(string inputPath)
{
    var xmlPath = Path.GetFullPath(inputPath);
    if (!File.Exists(xmlPath))
    {
        Console.Error.WriteLine("Input XML not found: " + xmlPath);
        return 2;
    }

    try
    {
        var xml = NormalizeYnvXml(File.ReadAllText(xmlPath));
        var validation = YnvXmlValidator.Validate(xml);
        PrintWarnings(validation);
        Console.WriteLine("Validated " + xmlPath);
        return 0;
    }
    catch (Exception ex)
    {
        Console.Error.WriteLine(ex.ToString());
        return 1;
    }
}

static void PrintWarnings(YnvValidationResult validation)
{
    const int maxWarningsToPrint = 20;
    for (var index = 0; index < validation.Warnings.Count && index < maxWarningsToPrint; index++)
    {
        Console.Error.WriteLine("Warning: " + validation.Warnings[index]);
    }
    if (validation.Warnings.Count > maxWarningsToPrint)
    {
        Console.Error.WriteLine(
            "Warning: " + (validation.Warnings.Count - maxWarningsToPrint) + " additional validation warnings omitted.");
    }
}

static int CheckYnv(string inputPath)
{
    var ynvPath = Path.GetFullPath(inputPath);
    if (!File.Exists(ynvPath))
    {
        Console.Error.WriteLine("Input YNV not found: " + ynvPath);
        return 2;
    }

    try
    {
        var data = File.ReadAllBytes(ynvPath);
        if (data.Length < 16 || data[0] != 0x52 || data[1] != 0x53 || data[2] != 0x43 || data[3] != 0x37)
        {
            Console.Error.WriteLine("File does not start with an RSC7 header.");
            return 1;
        }

        var ynv = new YnvFile();
        ynv.Load(data);
        YnvXmlValidator.ValidateDecodedYnv(ynv);
        var xml = YnvXml.GetXml(ynv);
        Console.WriteLine("RSC7 version: " + BitConverter.ToInt32(data, 4));
        Console.WriteLine("Area ID: " + ynv.AreaID);
        Console.WriteLine("Polygons: " + (ynv.Polys?.Count ?? 0));
        Console.WriteLine("Portals: " + (ynv.Portals?.Count ?? 0));
        Console.WriteLine("Points: " + (ynv.Points?.Count ?? 0));
        Console.WriteLine("XML length: " + xml.Length);
        return 0;
    }
    catch (Exception ex)
    {
        Console.Error.WriteLine(ex.ToString());
        return 1;
    }
}
