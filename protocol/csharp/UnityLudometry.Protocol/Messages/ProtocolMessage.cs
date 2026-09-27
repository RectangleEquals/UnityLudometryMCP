using System;
using System.Collections.Generic;
using UnityLudometry.Protocol.Json;

namespace UnityLudometry.Protocol.Messages;

/// <summary>
/// Base of all generated params, result, event and file record types. Each type reads itself with a static
/// <c>Read(JsonValue?, string path)</c> and keeps unknown properties in <see cref="Extra"/>, so a message from a newer
/// peer survives a round-trip unchanged.
/// </summary>
/// <remarks>
/// Canonical form: properties that may be JSON <c>null</c> are always written; optional properties that are absent
/// (<c>null</c> in C#) are omitted.
/// </remarks>
public abstract class ProtocolMessage
{
    /// <summary>Properties this protocol version doesn't know.</summary>
    public JsonObject? Extra { get; set; }

    /// <summary>Writes the message as a JSON object.</summary>
    public void WriteJson(JsonWriter writer)
    {
        writer.WriteStartObject();
        WriteProperties(writer);
        writer.WriteProperties(Extra);
        writer.WriteEndObject();
    }

    /// <summary>Converts the message to a JSON object (for an envelope's params or result).</summary>
    public JsonObject ToJson()
    {
        using var writer = new JsonWriter();
        WriteJson(writer);
        return (JsonObject)JsonValue.Parse(writer.ToArray());
    }

    /// <summary>Writes the known properties.</summary>
    protected abstract void WriteProperties(JsonWriter writer);
}

/// <summary>Reads a message of one type from JSON (<c>null</c> reads as an empty object).</summary>
public delegate ProtocolMessage MessageReader(JsonValue? value, string path);

/// <summary>Where a method executes.</summary>
public enum MethodThread
{
    /// <summary>Any thread (I/O or worker).</summary>
    Any,

    /// <summary>The game's main thread (through the agent's pump).</summary>
    Main,

    /// <summary>Partly on a worker, partly on the main thread.</summary>
    Mixed,
}

/// <summary>A method of the protocol: execution metadata and message types.</summary>
public sealed class MethodDescriptor
{
    /// <summary>Creates a descriptor.</summary>
    public MethodDescriptor(string name, MethodThread thread, AgentMode minMode, bool job, bool mutating, IReadOnlyList<string> requires,
        MessageReader readParams, MessageReader readResult, MessageReader? readJobResult)
    {
        Name = name;
        Thread = thread;
        MinMode = minMode;
        Job = job;
        Mutating = mutating;
        Requires = requires;
        ReadParams = readParams;
        ReadResult = readResult;
        ReadJobResult = readJobResult;
    }

    /// <summary>Method name.</summary>
    public string Name { get; }

    /// <summary>Where the method executes.</summary>
    public MethodThread Thread { get; }

    /// <summary>The lowest agent mode that allows the method (some methods check further conditions at runtime).</summary>
    public AgentMode MinMode { get; }

    /// <summary>Whether the method returns a job reference; the job's result has the type read by <see cref="ReadJobResult"/>.</summary>
    public bool Job { get; }

    /// <summary>Whether the method changes game state or loads or executes code.</summary>
    public bool Mutating { get; }

    /// <summary>Capability tags the method needs (e.g. <c>module:addressables</c>).</summary>
    public IReadOnlyList<string> Requires { get; }

    /// <summary>Reads the params.</summary>
    public MessageReader ReadParams { get; }

    /// <summary>Reads the result.</summary>
    public MessageReader ReadResult { get; }

    /// <summary>Reads the job result (job methods only).</summary>
    public MessageReader? ReadJobResult { get; }
}

/// <summary>An event kind of the protocol and its payload type.</summary>
public sealed class EventDescriptor
{
    /// <summary>Creates a descriptor.</summary>
    public EventDescriptor(string kind, MessageReader readParams)
    {
        Kind = kind;
        ReadParams = readParams;
    }

    /// <summary>Event kind.</summary>
    public string Kind { get; }

    /// <summary>Reads the payload.</summary>
    public MessageReader ReadParams { get; }
}

/// <summary>An exchanged file type: a single-document file (empty <see cref="Rec"/>) or one NDJSON record kind.</summary>
public sealed class FileRecordDescriptor
{
    /// <summary>Creates a descriptor.</summary>
    public FileRecordDescriptor(string schema, string rec, MessageReader read)
    {
        Schema = schema;
        Rec = rec;
        Read = read;
    }

    /// <summary>The schema name (file name under <c>schema/files</c> without extension).</summary>
    public string Schema { get; }

    /// <summary>The NDJSON record kind (<c>rec</c>), or empty for single-document files.</summary>
    public string Rec { get; }

    /// <summary>Reads the document or record.</summary>
    public MessageReader Read { get; }
}

/// <summary>Lookup helpers over the generated registries.</summary>
public static partial class MethodRegistry
{
    /// <summary>Finds a method, or returns <c>null</c>.</summary>
    public static MethodDescriptor? Find(string name) => All.TryGetValue(name, out var descriptor) ? descriptor : null;
}

/// <summary>Lookup helpers over the generated registries.</summary>
public static partial class EventRegistry
{
    /// <summary>Finds an event kind, or returns <c>null</c>.</summary>
    public static EventDescriptor? Find(string kind) => All.TryGetValue(kind, out var descriptor) ? descriptor : null;
}

/// <summary>Lookup helpers over the generated registries.</summary>
public static partial class FileRegistry
{
    /// <summary>Finds a file type by schema name and record kind (empty for single-document files), or returns <c>null</c>.</summary>
    public static FileRecordDescriptor? Find(string schema, string rec)
    {
        foreach (var descriptor in All)
        {
            if (string.Equals(descriptor.Schema, schema, StringComparison.Ordinal) && string.Equals(descriptor.Rec, rec, StringComparison.Ordinal))
            {
                return descriptor;
            }
        }

        return null;
    }
}

/// <summary>Convenience members for the generated protocol version type.</summary>
public sealed partial class ProtocolVersionInfo
{
    /// <summary>The version implemented by this package.</summary>
    public static ProtocolVersionInfo Current => new() { Major = ProtocolVersion.Major, Minor = ProtocolVersion.Minor };
}
