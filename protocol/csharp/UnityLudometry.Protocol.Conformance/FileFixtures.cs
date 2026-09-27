using System.Security.Cryptography;
using System.Text;
using UnityLudometry.Protocol.Json;
using UnityLudometry.Protocol.Messages;

namespace UnityLudometry.Protocol.Conformance;

/// <summary>An example of an exchanged file: <c>protocol/fixtures/files/&lt;schema&gt;/&lt;case&gt;.json</c> or <c>.ndjson</c>.</summary>
public sealed class FileFixture
{
    /// <summary>Path relative to the fixture root, with extension, using '/'.</summary>
    public required string Id { get; init; }

    /// <summary>The schema name (file name under <c>schema/files</c> without extension).</summary>
    public required string Schema { get; init; }

    /// <summary>Whether the file is NDJSON (one record per line).</summary>
    public bool IsNdjson { get; init; }

    /// <summary>The raw file bytes.</summary>
    public required byte[] Bytes { get; init; }
}

/// <summary>Loads and replays file fixtures.</summary>
public static class FileFixtures
{
    /// <summary>Loads every file fixture below <paramref name="filesFixturesDirectory"/> (<c>protocol/fixtures/files</c>).</summary>
    public static IReadOnlyList<FileFixture> Load(string filesFixturesDirectory)
    {
        var fixtures = new List<FileFixture>();
        foreach (var file in Directory.EnumerateFiles(filesFixturesDirectory, "*.*", SearchOption.AllDirectories))
        {
            var id = Path.GetRelativePath(filesFixturesDirectory, file).Replace('\\', '/');
            var parts = id.Split('/');
            if (parts.Length != 2 || !(id.EndsWith(".json", StringComparison.Ordinal) || id.EndsWith(".ndjson", StringComparison.Ordinal)))
            {
                throw new InvalidDataException($"File fixture '{id}' must be at <schema>/<case>.json or <schema>/<case>.ndjson.");
            }

            fixtures.Add(new FileFixture { Id = id, Schema = parts[0], IsNdjson = id.EndsWith(".ndjson", StringComparison.Ordinal), Bytes = File.ReadAllBytes(file) });
        }

        fixtures.Sort((a, b) => string.CompareOrdinal(a.Id, b.Id));
        return fixtures;
    }

    /// <summary>Splits an NDJSON file into its lines (each must end with '\n').</summary>
    public static IReadOnlyList<string> Lines(FileFixture fixture)
    {
        var text = Encoding.UTF8.GetString(fixture.Bytes);
        if (!text.EndsWith('\n'))
        {
            throw new InvalidDataException($"{fixture.Id}: the last line must end with a newline.");
        }

        return text[..^1].Split('\n');
    }

    /// <summary>Replays a file fixture through the generated types. Returns the problems found.</summary>
    public static IReadOnlyList<string> Check(FileFixture fixture)
    {
        var problems = new List<string>();
        if (!fixture.IsNdjson)
        {
            if (FileRegistry.Find(fixture.Schema, string.Empty) is { } descriptor)
            {
                FixtureReplay.RoundTripMessage(JsonValue.Parse(fixture.Bytes), descriptor.Read, fixture.Id, problems);
            }
            else
            {
                problems.Add($"no single-document file type '{fixture.Schema}' in the registry.");
            }

            return problems;
        }

        var lines = Lines(fixture);
        var counts = new Dictionary<string, long>(StringComparer.Ordinal);
        var hashed = new StringBuilder();
        for (var i = 0; i < lines.Count; i++)
        {
            var line = JsonValue.Parse(lines[i]);
            var rec = line is JsonObject o && o["rec"] is JsonString s ? s.Value : null;
            var isHeader = rec == "header";
            var isFooter = rec == "footer";
            if (i == 0 != isHeader)
            {
                problems.Add($"line {i + 1}: the header must be the first line, and only the first.");
            }

            if (i == lines.Count - 1 != isFooter)
            {
                problems.Add($"line {i + 1}: the footer must be the last line, and only the last.");
            }

            var schema = isHeader || isFooter ? "ndjson" : fixture.Schema;
            if (rec is null || FileRegistry.Find(schema, rec) is not { } descriptor)
            {
                problems.Add($"line {i + 1}: unknown record kind '{rec}'.");
                continue;
            }

            FixtureReplay.RoundTripMessage(line, descriptor.Read, $"line {i + 1}", problems);
            if (isFooter)
            {
                var footer = (NdjsonFooter)descriptor.Read(line, "footer");
                var sha = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(hashed.ToString()))).ToLowerInvariant();
                if (footer.Sha256 != sha)
                {
                    problems.Add($"footer sha256 {footer.Sha256} doesn't match the preceding lines ({sha}).");
                }

                foreach (var count in footer.Counts)
                {
                    var expected = ((JsonNumber)count.Value).TryGetInt64(out var c) ? c : -1;
                    if (!counts.TryGetValue(count.Key, out var actual) || actual != expected)
                    {
                        problems.Add($"footer count for '{count.Key}' is {expected}, but the file has {(counts.TryGetValue(count.Key, out var a) ? a : 0)}.");
                    }
                }
            }
            else
            {
                hashed.Append(lines[i]).Append('\n');
                if (!isHeader)
                {
                    counts[rec] = counts.TryGetValue(rec, out var n) ? n + 1 : 1;
                }
            }
        }

        return problems;
    }
}
