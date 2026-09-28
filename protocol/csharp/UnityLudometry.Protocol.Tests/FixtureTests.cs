using UnityLudometry.Protocol.Conformance;
using UnityLudometry.Protocol.Json;

namespace UnityLudometry.Protocol.Tests;

public sealed class FixtureTests
{
    private static readonly IReadOnlyDictionary<string, FixtureCase> Fixtures =
        FixtureCatalog.Load(ProtocolFiles.AgentFixturesDirectory).ToDictionary(f => f.Id);

    public static TheoryData<string> FixtureIds => new(Fixtures.Keys.Order(StringComparer.Ordinal));

    [Theory]
    [MemberData(nameof(FixtureIds))]
    public void Fixture_round_trips_through_the_message_types(string id)
    {
        var problems = FixtureReplay.Check(Fixtures[id]);
        Assert.True(problems.Count == 0, string.Join(Environment.NewLine, problems));
    }

    [Theory]
    [MemberData(nameof(FixtureIds))]
    public void Fixture_matches_the_schemas(string id)
    {
        var fixture = Fixtures[id];
        var problems = new List<string>();

        void Check(JsonValue? json, string schemaReference, string what)
        {
            if (json is not null)
            {
                problems.AddRange(ProtocolFiles.Validate(json.ToString(), schemaReference).Select(p => $"{what}: {p}"));
            }
        }

        if (fixture.IsEvent)
        {
            Check(fixture.Event, "envelope.schema.json#/$defs/event", "event envelope");
            Check(fixture.Event!["params"], $"events/{fixture.Group}.schema.json#/$defs/params", "event params");
        }
        else
        {
            Check(fixture.Request, "envelope.schema.json#/$defs/request", "request envelope");
            Check(fixture.Response, "envelope.schema.json#/$defs/response", "response envelope");
            if (!fixture.IsGeneric)
            {
                var methodSchema = $"methods/{fixture.Group}.schema.json";
                var @params = fixture.Request!["params"] ?? new JsonObject();
                var paramsProblems = ProtocolFiles.Validate(@params.ToString(), methodSchema + "#/$defs/params");
                if (fixture.RequestValid)
                {
                    problems.AddRange(paramsProblems.Select(p => $"params: {p}"));
                }
                else if (paramsProblems.Count == 0)
                {
                    problems.Add("params: a fixture marked requestValid:false must violate the params schema.");
                }

                Check(fixture.Response!["result"], methodSchema + "#/$defs/result", "result");
                Check(fixture.JobResult, methodSchema + "#/$defs/jobResult", "jobResult");
            }
        }

        Assert.True(problems.Count == 0, string.Join(Environment.NewLine, problems));
    }

    public static TheoryData<string> FileFixtureIds => new(FileFixtures.Load(ProtocolFiles.FileFixturesDirectory).Select(f => f.Id));

    [Theory]
    [MemberData(nameof(FileFixtureIds))]
    public void File_fixture_round_trips_and_matches_its_schema(string id)
    {
        var fixture = FileFixtures.Load(ProtocolFiles.FileFixturesDirectory).Single(f => f.Id == id);
        var problems = FileFixtures.Check(fixture).ToList();
        var schema = $"files/{fixture.Schema}.schema.json";
        if (fixture.IsNdjson)
        {
            var lines = FileFixtures.Lines(fixture);
            for (var i = 0; i < lines.Count; i++)
            {
                problems.AddRange(ProtocolFiles.Validate(lines[i], schema).Select(p => $"line {i + 1}: {p}"));
            }
        }
        else
        {
            problems.AddRange(ProtocolFiles.Validate(System.Text.Encoding.UTF8.GetString(fixture.Bytes), schema));
        }

        Assert.True(problems.Count == 0, string.Join(Environment.NewLine, problems));
    }

    [Fact]
    public void Fixtures_name_the_current_protocol_version()
    {
        // Example data must be semantically right, not just valid; only the mismatch fixture differs on purpose.
        var wrong = new List<string>();

        void Walk(JsonValue? value, string where)
        {
            switch (value)
            {
                case JsonObject o:
                    if (o["major"] is JsonNumber major && o["minor"] is JsonNumber minor
                        && !(major.TryGetInt32(out var a) && a == ProtocolVersion.Major && minor.TryGetInt32(out var b) && b == ProtocolVersion.Minor))
                    {
                        wrong.Add($"{where}: {major.RawText}.{minor.RawText}");
                    }

                    foreach (var property in o)
                    {
                        Walk(property.Value, where);
                    }

                    break;
                case JsonArray array:
                    foreach (var item in array)
                    {
                        Walk(item, where);
                    }

                    break;
            }
        }

        foreach (var fixture in Fixtures.Values.Where(f => f.Id != "hello/protocol-mismatch"))
        {
            Walk(fixture.Request, fixture.Id);
            Walk(fixture.Response, fixture.Id);
            Walk(fixture.JobResult, fixture.Id);
            Walk(fixture.Event, fixture.Id);
        }

        foreach (var file in FileFixtures.Load(ProtocolFiles.FileFixturesDirectory))
        {
            var lines = file.IsNdjson ? FileFixtures.Lines(file) : new[] { System.Text.Encoding.UTF8.GetString(file.Bytes) };
            foreach (var line in lines)
            {
                Walk(JsonValue.Parse(line), file.Id);
            }
        }

        Assert.True(wrong.Count == 0, string.Join(Environment.NewLine, wrong));
    }

    [Fact]
    public void Fixtures_use_the_current_protocol_major()
    {
        foreach (var fixture in Fixtures.Values)
        {
            foreach (var envelope in new[] { fixture.Request, fixture.Response, fixture.Event }.OfType<JsonObject>())
            {
                Assert.True(((JsonNumber)envelope["v"]!).TryGetInt32(out var v) && v == ProtocolVersion.Major, fixture.Id);
            }
        }
    }

    [Fact]
    public void Schema_validation_catches_violations()
    {
        Assert.NotEmpty(ProtocolFiles.Validate("{\"kinds\":[]}", "methods/events.subscribe.schema.json#/$defs/params"));
        Assert.NotEmpty(ProtocolFiles.Validate("{\"v\":0,\"id\":\"a\",\"kind\":\"response\"}", "envelope.schema.json#/$defs/response"));
        Assert.NotEmpty(ProtocolFiles.Validate("{\"mvid\":\"not-a-guid\",\"token\":1}", "common/anchor.schema.json"));
        Assert.NotEmpty(ProtocolFiles.Validate("{\"t\":\"list\",\"count\":1}", "common/value.schema.json"));
        Assert.Empty(ProtocolFiles.Validate("{\"t\":\"list\",\"count\":1,\"items\":[{\"redacted\":{\"reason\":\"maxItems\",\"range\":[0,1]}}]}", "common/value.schema.json"));
    }
}
