using UnityLudometry.Protocol.Json;

namespace UnityLudometry.Protocol.Conformance;

/// <summary>
/// One golden fixture file from <c>protocol/fixtures/agent</c>. Method fixtures live in <c>&lt;method&gt;/&lt;case&gt;.json</c>
/// with a request and its response (and, for job methods, the job's result); event fixtures in
/// <c>events/&lt;kind&gt;/&lt;case&gt;.json</c>; fixtures that aren't tied to one method in <c>_generic/&lt;case&gt;.json</c>.
/// </summary>
public sealed class FixtureCase
{
    /// <summary>Path relative to the fixture root, without extension, using '/' (e.g. <c>hello/ok</c>).</summary>
    public required string Id { get; init; }

    /// <summary>The method name, the event kind, or <c>_generic</c>.</summary>
    public required string Group { get; init; }

    /// <summary>Whether this is an event fixture.</summary>
    public bool IsEvent { get; init; }

    /// <summary>Whether the fixture belongs to <c>_generic</c> (not tied to one method's schema).</summary>
    public bool IsGeneric => Group == "_generic";

    /// <summary>What the fixture demonstrates.</summary>
    public required string Description { get; init; }

    /// <summary>False for fixtures whose request deliberately violates the params schema.</summary>
    public bool RequestValid { get; init; } = true;

    /// <summary>The request envelope.</summary>
    public JsonObject? Request { get; init; }

    /// <summary>The response envelope.</summary>
    public JsonObject? Response { get; init; }

    /// <summary>For job methods: the result of the finished job (what <c>job.get</c> reports once it succeeded).</summary>
    public JsonObject? JobResult { get; init; }

    /// <summary>The event envelope.</summary>
    public JsonObject? Event { get; init; }
}

/// <summary>Loads golden fixtures.</summary>
public static class FixtureCatalog
{
    /// <summary>Loads every fixture below <paramref name="agentFixturesDirectory"/> (<c>protocol/fixtures/agent</c>), sorted by id.</summary>
    public static IReadOnlyList<FixtureCase> Load(string agentFixturesDirectory)
    {
        if (!Directory.Exists(agentFixturesDirectory))
        {
            throw new DirectoryNotFoundException($"Fixture directory not found: {agentFixturesDirectory}");
        }

        var cases = new List<FixtureCase>();
        foreach (var file in Directory.EnumerateFiles(agentFixturesDirectory, "*.json", SearchOption.AllDirectories))
        {
            var id = Path.GetRelativePath(agentFixturesDirectory, file).Replace('\\', '/');
            id = id[..^".json".Length];
            cases.Add(Read(id, File.ReadAllBytes(file)));
        }

        cases.Sort((a, b) => string.CompareOrdinal(a.Id, b.Id));
        return cases;
    }

    private static FixtureCase Read(string id, byte[] bytes)
    {
        var parts = id.Split('/');
        var isEvent = parts[0] == "events";
        var expectedDepth = isEvent ? 3 : 2;
        if (parts.Length != expectedDepth)
        {
            throw new InvalidDataException($"Fixture '{id}' must be at <method>/<case>.json or events/<kind>/<case>.json.");
        }

        var r = new ObjectReader(JsonValue.Parse(bytes), id);
        var fixture = new FixtureCase
        {
            Id = id,
            Group = isEvent ? parts[1] : parts[0],
            IsEvent = isEvent,
            Description = r.RequiredString("description"),
            RequestValid = r.OptionalBoolean("requestValid") ?? true,
            Request = r.OptionalObject("request"),
            Response = r.OptionalObject("response"),
            JobResult = r.OptionalObject("jobResult"),
            Event = r.OptionalObject("event"),
        };
        if (r.Rest() is { } unknown)
        {
            throw new InvalidDataException($"Fixture '{id}' has unknown properties: {string.Join(", ", unknown.Keys)}.");
        }

        var complete = isEvent
            ? fixture.Event is not null && fixture.Request is null && fixture.Response is null && fixture.JobResult is null
            : fixture.Request is not null && fixture.Response is not null && fixture.Event is null;
        if (!complete)
        {
            throw new InvalidDataException($"Fixture '{id}' needs {(isEvent ? "only an event" : "a request and a response")}.");
        }

        return fixture;
    }
}
