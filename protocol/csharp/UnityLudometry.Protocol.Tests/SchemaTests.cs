using System.Reflection;
using System.Text.Json;
using Json.Schema;
using UnityLudometry.Protocol.Conformance;
using UnityLudometry.Protocol.Messages;

namespace UnityLudometry.Protocol.Tests;

public sealed class SchemaTests
{
    public static TheoryData<string> SchemaFileNames => new(ProtocolFiles.SchemaFiles());

    [Theory]
    [MemberData(nameof(SchemaFileNames))]
    public void Schema_is_valid_draft_2020_12_with_a_matching_id(string file)
    {
        var text = File.ReadAllText(Path.Combine(ProtocolFiles.SchemaDirectory, file));
        using var document = JsonDocument.Parse(text);
        var results = MetaSchemas.Draft202012.Evaluate(document.RootElement, new EvaluationOptions { OutputFormat = OutputFormat.List });
        Assert.True(results.IsValid, $"{file} is not a valid draft 2020-12 schema.");

        var root = document.RootElement;
        Assert.Equal("https://json-schema.org/draft/2020-12/schema", root.GetProperty("$schema").GetString());
        Assert.Equal(ProtocolFiles.SchemaBaseUri + file, root.GetProperty("$id").GetString());
        Assert.False(string.IsNullOrWhiteSpace(root.GetProperty("description").GetString()), $"{file} needs a description.");
    }

    [Theory]
    [MemberData(nameof(SchemaFileNames))]
    public void Every_reference_resolves(string file)
    {
        // Checked directly (file exists, JSON pointer exists) so references inside unused $defs are covered too.
        var baseUri = new Uri(ProtocolFiles.SchemaBaseUri + file);
        using var document = JsonDocument.Parse(File.ReadAllText(Path.Combine(ProtocolFiles.SchemaDirectory, file)));
        var problems = new List<string>();
        foreach (var reference in References(document.RootElement))
        {
            var target = new Uri(baseUri, reference);
            var targetFile = target.GetLeftPart(UriPartial.Path)[ProtocolFiles.SchemaBaseUri.Length..];
            var targetPath = Path.Combine(ProtocolFiles.SchemaDirectory, targetFile.Replace('/', Path.DirectorySeparatorChar));
            if (!File.Exists(targetPath))
            {
                problems.Add($"{reference}: file {targetFile} doesn't exist.");
                continue;
            }

            using var targetDocument = JsonDocument.Parse(File.ReadAllText(targetPath));
            var element = targetDocument.RootElement;
            foreach (var segment in Uri.UnescapeDataString(target.Fragment.TrimStart('#')).Split('/', StringSplitOptions.RemoveEmptyEntries))
            {
                if (!element.TryGetProperty(segment.Replace("~1", "/").Replace("~0", "~"), out element))
                {
                    problems.Add($"{reference}: pointer {target.Fragment} doesn't exist in {targetFile}.");
                    break;
                }
            }
        }

        Assert.True(problems.Count == 0, string.Join(Environment.NewLine, problems));
    }

    private static IEnumerable<string> References(JsonElement element)
    {
        if (element.ValueKind == JsonValueKind.Object)
        {
            foreach (var property in element.EnumerateObject())
            {
                if (property.Name == "$ref" && property.Value.ValueKind == JsonValueKind.String)
                {
                    yield return property.Value.GetString()!;
                }

                foreach (var nested in References(property.Value))
                {
                    yield return nested;
                }
            }
        }
        else if (element.ValueKind == JsonValueKind.Array)
        {
            foreach (var item in element.EnumerateArray())
            {
                foreach (var nested in References(item))
                {
                    yield return nested;
                }
            }
        }
    }

    [Fact]
    public void Methods_schemas_fixtures_and_message_types_cover_each_other()
    {
        var schemaMethods = ProtocolFiles.SchemaFiles().Where(f => f.StartsWith("methods/", StringComparison.Ordinal))
            .Select(f => f["methods/".Length..^".schema.json".Length]).ToHashSet();
        var fixtures = FixtureCatalog.Load(ProtocolFiles.AgentFixturesDirectory);
        var fixtureMethods = fixtures.Where(f => !f.IsEvent && !f.IsGeneric).Select(f => f.Group).ToHashSet();
        var constants = typeof(Methods).GetFields(BindingFlags.Public | BindingFlags.Static).Select(f => (string)f.GetValue(null)!).ToHashSet();
        var okFixtures = fixtures.Where(f => !f.IsEvent && !f.IsGeneric && f.Id.EndsWith("/ok", StringComparison.Ordinal)).Select(f => f.Group).ToHashSet();

        Assert.Equal(schemaMethods.Order(), fixtureMethods.Order());
        Assert.Equal(schemaMethods.Order(), okFixtures.Order());
        Assert.Equal(schemaMethods.Order(), MethodRegistry.All.Keys.Order());
        Assert.Equal(schemaMethods.Order(), constants.Order());
    }

    [Fact]
    public void Event_schemas_fixtures_and_message_types_cover_each_other()
    {
        var schemaEvents = ProtocolFiles.SchemaFiles().Where(f => f.StartsWith("events/", StringComparison.Ordinal))
            .Select(f => f["events/".Length..^".schema.json".Length]).ToHashSet();
        var fixtureEvents = FixtureCatalog.Load(ProtocolFiles.AgentFixturesDirectory).Where(f => f.IsEvent).Select(f => f.Group).ToHashSet();
        var constants = typeof(EventKinds).GetFields(BindingFlags.Public | BindingFlags.Static).Select(f => (string)f.GetValue(null)!).ToHashSet();

        Assert.Equal(schemaEvents.Order(), fixtureEvents.Order());
        Assert.Equal(schemaEvents.Order(), EventRegistry.All.Keys.Order());
        Assert.Equal(schemaEvents.Order(), constants.Order());
    }

    [Fact]
    public void Error_codes_in_the_schema_match_the_package_constants()
    {
        using var document = JsonDocument.Parse(File.ReadAllText(Path.Combine(ProtocolFiles.SchemaDirectory, "common", "error.schema.json")));
        var schemaCodes = document.RootElement.GetProperty("properties").GetProperty("code").GetProperty("examples")
            .EnumerateArray().Select(e => e.GetString()!).Order();
        var constants = typeof(ErrorCodes).GetFields(BindingFlags.Public | BindingFlags.Static).Select(f => (string)f.GetValue(null)!).Order();
        Assert.Equal(schemaCodes, constants);
    }

    [Fact]
    public void The_registry_matches_every_method_schema()
    {
        foreach (var file in ProtocolFiles.SchemaFiles().Where(f => f.StartsWith("methods/", StringComparison.Ordinal)))
        {
            using var document = JsonDocument.Parse(File.ReadAllText(Path.Combine(ProtocolFiles.SchemaDirectory, file)));
            var root = document.RootElement;
            var name = root.GetProperty("title").GetString()!;
            var meta = root.GetProperty("x-method");
            var descriptor = MethodRegistry.Find(name);
            Assert.NotNull(descriptor);

            var thread = meta.GetProperty("thread").GetString() switch { "any" => MethodThread.Any, "main" => MethodThread.Main, _ => MethodThread.Mixed };
            Assert.True(AgentModes.TryParse(meta.GetProperty("minMode").GetString(), out var minMode), file);
            Assert.Equal(thread, descriptor.Thread);
            Assert.Equal(minMode, descriptor.MinMode);
            Assert.Equal(meta.GetProperty("job").GetBoolean(), descriptor.Job);
            Assert.Equal(meta.GetProperty("mutating").GetBoolean(), descriptor.Mutating);
            Assert.Equal(meta.GetProperty("job").GetBoolean(), descriptor.ReadJobResult is not null);
            Assert.Equal(meta.GetProperty("job").GetBoolean(), root.GetProperty("$defs").TryGetProperty("jobResult", out _));
            var requires = meta.TryGetProperty("requires", out var r) ? r.EnumerateArray().Select(x => x.GetString()!).ToArray() : Array.Empty<string>();
            Assert.Equal(requires, descriptor.Requires);
            Assert.Equal(descriptor.Mutating, descriptor.MinMode != AgentMode.ReadOnly);
        }
    }

    [Fact]
    public void File_schemas_fixtures_and_registry_cover_each_other()
    {
        var schemaFiles = ProtocolFiles.SchemaFiles().Where(f => f.StartsWith("files/", StringComparison.Ordinal))
            .Select(f => f["files/".Length..^".schema.json".Length]).Where(f => f != "ndjson").ToHashSet();
        var fixtureFiles = FileFixtures.Load(ProtocolFiles.FileFixturesDirectory).Select(f => f.Schema).ToHashSet();
        var registryFiles = FileRegistry.All.Select(d => d.Schema).Where(s => s != "ndjson").ToHashSet();

        Assert.Equal(schemaFiles.Order(), fixtureFiles.Order());
        Assert.Equal(schemaFiles.Order(), registryFiles.Order());
    }
}
