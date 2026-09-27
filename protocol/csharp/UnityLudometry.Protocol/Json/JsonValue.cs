using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;

namespace UnityLudometry.Protocol.Json;

/// <summary>The kind of a <see cref="JsonValue"/>.</summary>
public enum JsonKind
{
    /// <summary>JSON <c>null</c>.</summary>
    Null,
    /// <summary>JSON <c>true</c> or <c>false</c>.</summary>
    Boolean,
    /// <summary>A JSON number (its text is preserved).</summary>
    Number,
    /// <summary>A JSON string.</summary>
    String,
    /// <summary>A JSON array.</summary>
    Array,
    /// <summary>A JSON object (property order is preserved).</summary>
    Object,
}

/// <summary>An immutable-by-convention JSON document tree node.</summary>
public abstract class JsonValue
{
    private protected JsonValue()
    {
    }

    /// <summary>The kind of this value.</summary>
    public abstract JsonKind Kind { get; }

    /// <summary>Parses UTF-8 JSON text. Throws <see cref="ProtocolException"/> (<c>INVALID_FRAME</c>) on malformed input.</summary>
    public static JsonValue Parse(byte[] utf8, JsonReaderOptions? options = null) => JsonReader.Parse(utf8, 0, utf8.Length, options);

    /// <summary>Parses UTF-8 JSON text from a slice of a buffer.</summary>
    public static JsonValue Parse(byte[] utf8, int offset, int count, JsonReaderOptions? options = null) => JsonReader.Parse(utf8, offset, count, options);

    /// <summary>Parses JSON text.</summary>
    public static JsonValue Parse(string json, JsonReaderOptions? options = null)
    {
        var bytes = JsonReader.StrictUtf8.GetBytes(json);
        return JsonReader.Parse(bytes, 0, bytes.Length, options);
    }

    /// <summary>Serializes this value as compact UTF-8 JSON.</summary>
    public byte[] ToUtf8Bytes()
    {
        using var writer = new JsonWriter();
        writer.WriteValue(this);
        return writer.ToArray();
    }

    /// <summary>Serializes this value as compact JSON text.</summary>
    public override string ToString() => JsonReader.StrictUtf8.GetString(ToUtf8Bytes());

    /// <summary>Creates a string value, or <see cref="JsonNull.Instance"/> for <c>null</c>.</summary>
    public static JsonValue From(string? value) => value is null ? JsonNull.Instance : new JsonString(value);

    /// <summary>Creates a boolean value.</summary>
    public static JsonValue From(bool value) => value ? JsonBoolean.True : JsonBoolean.False;

    /// <summary>Creates a number value.</summary>
    public static JsonValue From(long value) => new JsonNumber(value);

    /// <summary>Creates a number value. Throws for NaN and infinities, which JSON can't represent.</summary>
    public static JsonValue From(double value) => new JsonNumber(value);

    /// <summary>
    /// Structural equality: objects compare regardless of property order, arrays in order, and numbers by value
    /// (so <c>1</c>, <c>1.0</c> and <c>1e0</c> are equal).
    /// </summary>
    public static bool DeepEquals(JsonValue? a, JsonValue? b)
    {
        a ??= JsonNull.Instance;
        b ??= JsonNull.Instance;
        if (ReferenceEquals(a, b))
        {
            return true;
        }

        if (a.Kind != b.Kind)
        {
            return false;
        }

        switch (a)
        {
            case JsonNull:
                return true;
            case JsonBoolean ab:
                return ab.Value == ((JsonBoolean)b).Value;
            case JsonString sa:
                return string.Equals(sa.Value, ((JsonString)b).Value, StringComparison.Ordinal);
            case JsonNumber na:
                return JsonNumber.ValueEquals(na, (JsonNumber)b);
            case JsonArray aa:
            {
                var ba = (JsonArray)b;
                if (aa.Count != ba.Count)
                {
                    return false;
                }

                for (var i = 0; i < aa.Count; i++)
                {
                    if (!DeepEquals(aa[i], ba[i]))
                    {
                        return false;
                    }
                }

                return true;
            }

            case JsonObject oa:
            {
                var ob = (JsonObject)b;
                if (oa.Count != ob.Count)
                {
                    return false;
                }

                foreach (var property in oa)
                {
                    if (!ob.TryGetValue(property.Key, out var other) || !DeepEquals(property.Value, other))
                    {
                        return false;
                    }
                }

                return true;
            }

            default:
                return false;
        }
    }
}

/// <summary>JSON <c>null</c>.</summary>
public sealed class JsonNull : JsonValue
{
    /// <summary>The single instance.</summary>
    public static readonly JsonNull Instance = new();

    private JsonNull()
    {
    }

    /// <inheritdoc />
    public override JsonKind Kind => JsonKind.Null;
}

/// <summary>JSON <c>true</c> / <c>false</c>.</summary>
public sealed class JsonBoolean : JsonValue
{
    /// <summary><c>true</c>.</summary>
    public static readonly JsonBoolean True = new(true);

    /// <summary><c>false</c>.</summary>
    public static readonly JsonBoolean False = new(false);

    private JsonBoolean(bool value) => Value = value;

    /// <summary>The value.</summary>
    public bool Value { get; }

    /// <inheritdoc />
    public override JsonKind Kind => JsonKind.Boolean;
}

/// <summary>A JSON string.</summary>
public sealed class JsonString : JsonValue
{
    /// <summary>Creates a string value.</summary>
    public JsonString(string value) => Value = value ?? throw new ArgumentNullException(nameof(value));

    /// <summary>The value. May contain unpaired surrogates if the JSON text escaped them.</summary>
    public string Value { get; }

    /// <inheritdoc />
    public override JsonKind Kind => JsonKind.String;
}

/// <summary>A JSON number. Keeps its exact text so no precision is lost until a typed accessor is used.</summary>
public sealed class JsonNumber : JsonValue
{
    private JsonNumber(string rawText, bool _) => RawText = rawText;

    /// <summary>Creates a number from a 64-bit integer.</summary>
    public JsonNumber(long value) => RawText = value.ToString(CultureInfo.InvariantCulture);

    /// <summary>Creates a number from an unsigned 64-bit integer.</summary>
    public JsonNumber(ulong value) => RawText = value.ToString(CultureInfo.InvariantCulture);

    /// <summary>Creates a number from a decimal.</summary>
    public JsonNumber(decimal value) => RawText = value.ToString(CultureInfo.InvariantCulture);

    /// <summary>Creates a number from a double (shortest round-trip form). Throws for NaN and infinities.</summary>
    public JsonNumber(double value) => RawText = FormatDouble(value);

    /// <summary>The number's JSON text, exactly as read or written.</summary>
    public string RawText { get; }

    /// <inheritdoc />
    public override JsonKind Kind => JsonKind.Number;

    /// <summary>Creates a number from JSON number text. Throws <see cref="FormatException"/> if the text isn't a valid JSON number.</summary>
    public static JsonNumber FromRawText(string text)
    {
        if (!JsonReader.IsValidNumber(text))
        {
            throw new FormatException($"'{text}' is not a valid JSON number.");
        }

        return new JsonNumber(text, false);
    }

    internal static JsonNumber FromValidatedText(string text) => new(text, false);

    /// <summary>Reads the value as a 64-bit integer if it is an integer in range (e.g. <c>5</c>, <c>5.0</c>, <c>5e0</c>).</summary>
    public bool TryGetInt64(out long value)
    {
        if (long.TryParse(RawText, NumberStyles.AllowLeadingSign, CultureInfo.InvariantCulture, out value))
        {
            return true;
        }

        if (TryGetDecimal(out var d) && d == decimal.Truncate(d) && d >= long.MinValue && d <= long.MaxValue)
        {
            value = (long)d;
            return true;
        }

        value = 0;
        return false;
    }

    /// <summary>Reads the value as an unsigned 64-bit integer if it is a non-negative integer in range.</summary>
    public bool TryGetUInt64(out ulong value)
    {
        if (ulong.TryParse(RawText, NumberStyles.None, CultureInfo.InvariantCulture, out value))
        {
            return true;
        }

        if (TryGetDecimal(out var d) && d == decimal.Truncate(d) && d >= 0 && d <= ulong.MaxValue)
        {
            value = (ulong)d;
            return true;
        }

        value = 0;
        return false;
    }

    /// <summary>Reads the value as a 32-bit integer if it is an integer in range.</summary>
    public bool TryGetInt32(out int value)
    {
        if (TryGetInt64(out var l) && l >= int.MinValue && l <= int.MaxValue)
        {
            value = (int)l;
            return true;
        }

        value = 0;
        return false;
    }

    /// <summary>Reads the value as a decimal if it fits.</summary>
    public bool TryGetDecimal(out decimal value) =>
        decimal.TryParse(RawText, NumberStyles.Float, CultureInfo.InvariantCulture, out value);

    /// <summary>Reads the value as a double (may round; very large exponents give infinity).</summary>
    public double GetDouble() => double.Parse(RawText, NumberStyles.Float, CultureInfo.InvariantCulture);

    internal static bool ValueEquals(JsonNumber a, JsonNumber b)
    {
        if (string.Equals(a.RawText, b.RawText, StringComparison.Ordinal))
        {
            return true;
        }

        if (a.TryGetDecimal(out var da) && b.TryGetDecimal(out var db))
        {
            return da == db;
        }

        return a.GetDouble().Equals(b.GetDouble());
    }

    internal static string FormatDouble(double value)
    {
        if (double.IsNaN(value) || double.IsInfinity(value))
        {
            throw new ArgumentOutOfRangeException(nameof(value), "JSON can't represent NaN or infinity.");
        }

        return value.ToString("R", CultureInfo.InvariantCulture);
    }

    internal static string FormatSingle(float value)
    {
        if (float.IsNaN(value) || float.IsInfinity(value))
        {
            throw new ArgumentOutOfRangeException(nameof(value), "JSON can't represent NaN or infinity.");
        }

        return value.ToString("R", CultureInfo.InvariantCulture);
    }
}

/// <summary>A JSON array.</summary>
public sealed class JsonArray : JsonValue, IReadOnlyList<JsonValue>
{
    private readonly List<JsonValue> _items;

    /// <summary>Creates an empty array.</summary>
    public JsonArray() => _items = new List<JsonValue>();

    /// <summary>Creates an array from items (<c>null</c> items become <see cref="JsonNull.Instance"/>).</summary>
    public JsonArray(IEnumerable<JsonValue?> items)
    {
        _items = new List<JsonValue>();
        foreach (var item in items)
        {
            _items.Add(item ?? JsonNull.Instance);
        }
    }

    /// <inheritdoc />
    public override JsonKind Kind => JsonKind.Array;

    /// <inheritdoc />
    public int Count => _items.Count;

    /// <inheritdoc />
    public JsonValue this[int index] => _items[index];

    /// <summary>Appends an item (<c>null</c> becomes <see cref="JsonNull.Instance"/>).</summary>
    public void Add(JsonValue? item) => _items.Add(item ?? JsonNull.Instance);

    /// <inheritdoc />
    public IEnumerator<JsonValue> GetEnumerator() => _items.GetEnumerator();

    IEnumerator IEnumerable.GetEnumerator() => GetEnumerator();
}

/// <summary>A JSON object. Property names are unique; insertion order is preserved.</summary>
public sealed class JsonObject : JsonValue, IEnumerable<KeyValuePair<string, JsonValue>>
{
    private readonly List<KeyValuePair<string, JsonValue>> _properties = new();
    private readonly Dictionary<string, int> _index = new(StringComparer.Ordinal);

    /// <inheritdoc />
    public override JsonKind Kind => JsonKind.Object;

    /// <summary>The number of properties.</summary>
    public int Count => _properties.Count;

    /// <summary>Property names in order.</summary>
    public IEnumerable<string> Keys
    {
        get
        {
            foreach (var property in _properties)
            {
                yield return property.Key;
            }
        }
    }

    /// <summary>Gets a property value, or <c>null</c> when absent (a JSON <c>null</c> is returned as <see cref="JsonNull.Instance"/>).</summary>
    public JsonValue? this[string name] => TryGetValue(name, out var value) ? value : null;

    /// <summary>Whether the property exists.</summary>
    public bool ContainsKey(string name) => _index.ContainsKey(name);

    /// <summary>Gets a property value.</summary>
    public bool TryGetValue(string name, out JsonValue value)
    {
        if (_index.TryGetValue(name, out var i))
        {
            value = _properties[i].Value;
            return true;
        }

        value = JsonNull.Instance;
        return false;
    }

    /// <summary>Adds a property. Throws <see cref="ArgumentException"/> if the name already exists.</summary>
    public void Add(string name, JsonValue? value)
    {
        if (name is null)
        {
            throw new ArgumentNullException(nameof(name));
        }

        if (_index.ContainsKey(name))
        {
            throw new ArgumentException($"Duplicate property '{name}'.", nameof(name));
        }

        _index[name] = _properties.Count;
        _properties.Add(new KeyValuePair<string, JsonValue>(name, value ?? JsonNull.Instance));
    }

    /// <summary>Sets a property, replacing an existing value in place or appending a new one.</summary>
    public void Set(string name, JsonValue? value)
    {
        if (_index.TryGetValue(name, out var i))
        {
            _properties[i] = new KeyValuePair<string, JsonValue>(name, value ?? JsonNull.Instance);
        }
        else
        {
            Add(name, value);
        }
    }

    /// <summary>Removes a property. Returns whether it existed.</summary>
    public bool Remove(string name)
    {
        if (!_index.TryGetValue(name, out var i))
        {
            return false;
        }

        _properties.RemoveAt(i);
        _index.Remove(name);
        for (var j = i; j < _properties.Count; j++)
        {
            _index[_properties[j].Key] = j;
        }

        return true;
    }

    /// <inheritdoc />
    public IEnumerator<KeyValuePair<string, JsonValue>> GetEnumerator() => _properties.GetEnumerator();

    IEnumerator IEnumerable.GetEnumerator() => GetEnumerator();
}
