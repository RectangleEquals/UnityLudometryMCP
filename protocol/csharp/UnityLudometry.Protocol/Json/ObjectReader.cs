using System;
using System.Collections.Generic;

namespace UnityLudometry.Protocol.Json;

/// <summary>
/// Reads the properties of a JSON object into a message type. Missing or mistyped properties throw
/// <see cref="ProtocolException"/> (<c>INVALID_PARAMS</c>) naming the property path. Properties that weren't read are
/// returned by <see cref="Rest"/>, so unknown fields from newer peers survive a round-trip.
/// </summary>
/// <remarks>
/// Naming: <c>Required*</c> throws when the property is absent; <c>RequiredNullable*</c> also accepts JSON <c>null</c>;
/// <c>Optional*</c> returns <c>null</c> when the property is absent or JSON <c>null</c>.
/// </remarks>
public sealed class ObjectReader
{
    private readonly JsonObject _object;
    private readonly string _path;
    private readonly HashSet<string> _consumed = new(StringComparer.Ordinal);

    /// <summary>Creates a reader. <c>null</c> (absent) is read as an empty object.</summary>
    public ObjectReader(JsonValue? value, string path)
    {
        _path = path;
        _object = value switch
        {
            null => new JsonObject(),
            JsonObject o => o,
            _ => throw ProtocolException.InvalidParams(path, $"{path} must be an object."),
        };
    }

    // ------------------------------------------------------------------ strings

    /// <summary>A required string.</summary>
    public string RequiredString(string name) => ReadString(Required(name), PathOf(name));

    /// <summary>A required string that may be JSON <c>null</c>.</summary>
    public string? RequiredNullableString(string name) => RequiredOrNull(name) is { } v ? ReadString(v, PathOf(name)) : null;

    /// <summary>An optional string.</summary>
    public string? OptionalString(string name) => Optional(name) is { } v ? ReadString(v, PathOf(name)) : null;

    // ------------------------------------------------------------------ integers

    /// <summary>A required integer.</summary>
    public long RequiredInt64(string name) => ReadInt64(Required(name), PathOf(name));

    /// <summary>A required integer that may be JSON <c>null</c>.</summary>
    public long? RequiredNullableInt64(string name) => RequiredOrNull(name) is { } v ? ReadInt64(v, PathOf(name)) : null;

    /// <summary>An optional integer.</summary>
    public long? OptionalInt64(string name) => Optional(name) is { } v ? ReadInt64(v, PathOf(name)) : null;

    /// <summary>A required 32-bit integer.</summary>
    public int RequiredInt32(string name) => ToInt32(RequiredInt64(name), name);

    /// <summary>An optional 32-bit integer.</summary>
    public int? OptionalInt32(string name) => OptionalInt64(name) is { } v ? ToInt32(v, name) : null;

    // ------------------------------------------------------------------ numbers

    /// <summary>A required number.</summary>
    public double RequiredDouble(string name) => ReadDouble(Required(name), PathOf(name));

    /// <summary>A required number that may be JSON <c>null</c>.</summary>
    public double? RequiredNullableDouble(string name) => RequiredOrNull(name) is { } v ? ReadDouble(v, PathOf(name)) : null;

    /// <summary>An optional number.</summary>
    public double? OptionalDouble(string name) => Optional(name) is { } v ? ReadDouble(v, PathOf(name)) : null;

    // ------------------------------------------------------------------ booleans

    /// <summary>A required boolean.</summary>
    public bool RequiredBoolean(string name) => ReadBoolean(Required(name), PathOf(name));

    /// <summary>A required boolean that may be JSON <c>null</c>.</summary>
    public bool? RequiredNullableBoolean(string name) => RequiredOrNull(name) is { } v ? ReadBoolean(v, PathOf(name)) : null;

    /// <summary>An optional boolean.</summary>
    public bool? OptionalBoolean(string name) => Optional(name) is { } v ? ReadBoolean(v, PathOf(name)) : null;

    // ------------------------------------------------------------------ agent mode

    /// <summary>A required agent mode (wire names <c>ReadOnly</c>, <c>ReadOnly+Load</c>, <c>Full</c>).</summary>
    public AgentMode RequiredMode(string name) => ReadMode(Required(name), PathOf(name));

    /// <summary>An optional agent mode.</summary>
    public AgentMode? OptionalMode(string name) => Optional(name) is { } v ? ReadMode(v, PathOf(name)) : null;

    // ------------------------------------------------------------------ nested messages

    /// <summary>A required nested message.</summary>
    public T Required<T>(string name, Func<JsonValue, string, T> read) => read(Required(name), PathOf(name));

    /// <summary>A required nested message that may be JSON <c>null</c>.</summary>
    public T? RequiredNullable<T>(string name, Func<JsonValue, string, T> read)
        where T : class => RequiredOrNull(name) is { } v ? read(v, PathOf(name)) : null;

    /// <summary>An optional nested message.</summary>
    public T? Optional<T>(string name, Func<JsonValue, string, T> read)
        where T : class => Optional(name) is { } v ? read(v, PathOf(name)) : null;

    // ------------------------------------------------------------------ raw JSON

    /// <summary>A required value of any kind (JSON <c>null</c> is returned as <see cref="JsonNull.Instance"/>).</summary>
    public JsonValue RequiredValue(string name) => Required(name);

    /// <summary>An optional value of any kind: <c>null</c> when absent, <see cref="JsonNull.Instance"/> for JSON <c>null</c>.</summary>
    public JsonValue? OptionalValue(string name)
    {
        _consumed.Add(name);
        return _object.TryGetValue(name, out var value) ? value : null;
    }

    /// <summary>A required object, kept as JSON.</summary>
    public JsonObject RequiredObject(string name) => ReadObject(Required(name), PathOf(name));

    /// <summary>An optional object, kept as JSON.</summary>
    public JsonObject? OptionalObject(string name) => Optional(name) is { } v ? ReadObject(v, PathOf(name)) : null;

    // ------------------------------------------------------------------ arrays

    /// <summary>A required array.</summary>
    public List<T> RequiredArray<T>(string name, Func<JsonValue, string, T> readItem) => ReadList(Required(name), PathOf(name), readItem);

    /// <summary>An optional array.</summary>
    public List<T>? OptionalArray<T>(string name, Func<JsonValue, string, T> readItem) =>
        Optional(name) is { } v ? ReadList(v, PathOf(name), readItem) : null;

    /// <summary>Properties that weren't read, or <c>null</c> if there are none.</summary>
    public JsonObject? Rest()
    {
        JsonObject? rest = null;
        foreach (var property in _object)
        {
            if (!_consumed.Contains(property.Key))
            {
                (rest ??= new JsonObject()).Add(property.Key, property.Value);
            }
        }

        return rest;
    }

    // ------------------------------------------------------------------ item readers

    /// <summary>Reads a string.</summary>
    public static string ReadString(JsonValue value, string path) =>
        value is JsonString s ? s.Value : throw ProtocolException.InvalidParams(path, $"{path} must be a string.");

    /// <summary>Reads an integer.</summary>
    public static long ReadInt64(JsonValue value, string path) =>
        value is JsonNumber n && n.TryGetInt64(out var result) ? result : throw ProtocolException.InvalidParams(path, $"{path} must be an integer.");

    /// <summary>Reads a number.</summary>
    public static double ReadDouble(JsonValue value, string path) =>
        value is JsonNumber n ? n.GetDouble() : throw ProtocolException.InvalidParams(path, $"{path} must be a number.");

    /// <summary>Reads a boolean.</summary>
    public static bool ReadBoolean(JsonValue value, string path) =>
        value is JsonBoolean b ? b.Value : throw ProtocolException.InvalidParams(path, $"{path} must be a boolean.");

    /// <summary>Reads an agent mode.</summary>
    public static AgentMode ReadMode(JsonValue value, string path) =>
        AgentModes.TryParse(ReadString(value, path), out var mode) ? mode : throw ProtocolException.InvalidParams(path, $"{path} is not a known agent mode.");

    /// <summary>Returns the value unchanged (for arrays of raw JSON).</summary>
    public static JsonValue ReadValue(JsonValue value, string path) => value;

    /// <summary>Reads an object, kept as JSON.</summary>
    public static JsonObject ReadObject(JsonValue value, string path) =>
        value as JsonObject ?? throw ProtocolException.InvalidParams(path, $"{path} must be an object.");

    /// <summary>Reads an array.</summary>
    public static List<T> ReadList<T>(JsonValue value, string path, Func<JsonValue, string, T> readItem)
    {
        if (value is not JsonArray array)
        {
            throw ProtocolException.InvalidParams(path, $"{path} must be an array.");
        }

        var list = new List<T>(array.Count);
        for (var i = 0; i < array.Count; i++)
        {
            list.Add(readItem(array[i], path + "[" + i + "]"));
        }

        return list;
    }

    // ------------------------------------------------------------------ internals

    private JsonValue Required(string name)
    {
        _consumed.Add(name);
        if (!_object.TryGetValue(name, out var value))
        {
            throw ProtocolException.InvalidParams(PathOf(name), $"{PathOf(name)} is required.");
        }

        return value;
    }

    private JsonValue? RequiredOrNull(string name)
    {
        var value = Required(name);
        return value.Kind == JsonKind.Null ? null : value;
    }

    private JsonValue? Optional(string name)
    {
        _consumed.Add(name);
        return _object.TryGetValue(name, out var value) && value.Kind != JsonKind.Null ? value : null;
    }

    private int ToInt32(long value, string name)
    {
        if (value < int.MinValue || value > int.MaxValue)
        {
            throw ProtocolException.InvalidParams(PathOf(name), $"{PathOf(name)} is out of range.");
        }

        return (int)value;
    }

    private string PathOf(string name) => _path + "." + name;
}
