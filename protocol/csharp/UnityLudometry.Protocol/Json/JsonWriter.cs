using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;

namespace UnityLudometry.Protocol.Json;

/// <summary>
/// Writes compact UTF-8 JSON into a growable buffer. Validates call order (names only inside objects, one value per
/// name, balanced containers). Not thread-safe. Dispose returns the buffer to a per-thread cache for reuse.
/// </summary>
public sealed class JsonWriter : IDisposable
{
    private const int MaxCachedBufferBytes = 1024 * 1024;

    [ThreadStatic]
    private static byte[]? t_cachedBuffer;

    private static readonly byte[] HexDigits = System.Text.Encoding.ASCII.GetBytes("0123456789abcdef");

    private readonly Stack<Container> _stack = new();
    private byte[] _buffer;
    private int _length;
    private bool _rootWritten;

    /// <summary>Creates a writer.</summary>
    public JsonWriter(int initialCapacity = 256)
    {
        var cached = t_cachedBuffer;
        if (cached is not null && cached.Length >= initialCapacity)
        {
            t_cachedBuffer = null;
            _buffer = cached;
        }
        else
        {
            _buffer = new byte[Math.Max(16, initialCapacity)];
        }
    }

    private enum ContainerKind
    {
        Object,
        Array,
    }

    /// <summary>The number of bytes written so far.</summary>
    public int Length => _length;

    /// <summary>Whether a complete root value has been written.</summary>
    public bool IsComplete => _rootWritten && _stack.Count == 0;

    /// <summary>Copies the written JSON into a new array. The document must be complete.</summary>
    public byte[] ToArray()
    {
        EnsureComplete();
        var result = new byte[_length];
        Buffer.BlockCopy(_buffer, 0, result, 0, _length);
        return result;
    }

    /// <summary>Writes the complete JSON document to a stream.</summary>
    public void CopyTo(Stream stream)
    {
        EnsureComplete();
        stream.Write(_buffer, 0, _length);
    }

    /// <summary>Clears the writer for reuse.</summary>
    public void Reset()
    {
        _length = 0;
        _stack.Clear();
        _rootWritten = false;
    }

    /// <inheritdoc />
    public void Dispose()
    {
        if (_buffer.Length <= MaxCachedBufferBytes)
        {
            t_cachedBuffer = _buffer;
        }

        _buffer = Array.Empty<byte>();
        _length = 0;
    }

    /// <summary>Starts an object.</summary>
    public void WriteStartObject()
    {
        BeforeValue();
        WriteByte((byte)'{');
        _stack.Push(new Container(ContainerKind.Object));
    }

    /// <summary>Ends the current object.</summary>
    public void WriteEndObject()
    {
        if (_stack.Count == 0 || _stack.Peek().Kind != ContainerKind.Object || _stack.Peek().AwaitingValue)
        {
            throw new InvalidOperationException("No open object to end (or a property name is missing its value).");
        }

        _stack.Pop();
        WriteByte((byte)'}');
        AfterValue();
    }

    /// <summary>Starts an array.</summary>
    public void WriteStartArray()
    {
        BeforeValue();
        WriteByte((byte)'[');
        _stack.Push(new Container(ContainerKind.Array));
    }

    /// <summary>Ends the current array.</summary>
    public void WriteEndArray()
    {
        if (_stack.Count == 0 || _stack.Peek().Kind != ContainerKind.Array)
        {
            throw new InvalidOperationException("No open array to end.");
        }

        _stack.Pop();
        WriteByte((byte)']');
        AfterValue();
    }

    /// <summary>Writes a property name inside an object.</summary>
    public void WritePropertyName(string name)
    {
        if (name is null)
        {
            throw new ArgumentNullException(nameof(name));
        }

        if (_stack.Count == 0 || _stack.Peek().Kind != ContainerKind.Object || _stack.Peek().AwaitingValue)
        {
            throw new InvalidOperationException("A property name can only be written inside an object, before its value.");
        }

        var top = _stack.Peek();
        if (top.Count > 0)
        {
            WriteByte((byte)',');
        }

        WriteQuoted(name);
        WriteByte((byte)':');
        top.AwaitingValue = true;
    }

    /// <summary>Writes a string, or <c>null</c>.</summary>
    public void WriteString(string? value)
    {
        if (value is null)
        {
            WriteNull();
            return;
        }

        BeforeValue();
        WriteQuoted(value);
        AfterValue();
    }

    /// <summary>Writes a 64-bit integer.</summary>
    public void WriteNumber(long value) => WriteNumberText(value.ToString(CultureInfo.InvariantCulture));

    /// <summary>Writes an unsigned 64-bit integer.</summary>
    public void WriteNumber(ulong value) => WriteNumberText(value.ToString(CultureInfo.InvariantCulture));

    /// <summary>Writes a double (shortest round-trip form). Throws for NaN and infinities.</summary>
    public void WriteNumber(double value) => WriteNumberText(JsonNumber.FormatDouble(value));

    /// <summary>Writes a float (shortest round-trip form of the float). Throws for NaN and infinities.</summary>
    public void WriteNumber(float value) => WriteNumberText(JsonNumber.FormatSingle(value));

    /// <summary>Writes a decimal.</summary>
    public void WriteNumber(decimal value) => WriteNumberText(value.ToString(CultureInfo.InvariantCulture));

    /// <summary>Writes a number exactly as its JSON text.</summary>
    public void WriteNumber(JsonNumber value) => WriteNumberText(value.RawText);

    /// <summary>Writes <c>true</c> or <c>false</c>.</summary>
    public void WriteBoolean(bool value)
    {
        BeforeValue();
        WriteAscii(value ? "true" : "false");
        AfterValue();
    }

    /// <summary>Writes <c>null</c>.</summary>
    public void WriteNull()
    {
        BeforeValue();
        WriteAscii("null");
        AfterValue();
    }

    /// <summary>Writes a value tree (<c>null</c> writes JSON <c>null</c>).</summary>
    public void WriteValue(JsonValue? value)
    {
        switch (value)
        {
            case null:
            case JsonNull:
                WriteNull();
                break;
            case JsonBoolean b:
                WriteBoolean(b.Value);
                break;
            case JsonNumber n:
                WriteNumber(n);
                break;
            case JsonString s:
                WriteString(s.Value);
                break;
            case JsonArray a:
                WriteStartArray();
                foreach (var item in a)
                {
                    WriteValue(item);
                }

                WriteEndArray();
                break;
            case JsonObject o:
                WriteStartObject();
                foreach (var property in o)
                {
                    WritePropertyName(property.Key);
                    WriteValue(property.Value);
                }

                WriteEndObject();
                break;
            default:
                throw new ArgumentException($"Unknown JSON value type {value.GetType()}.", nameof(value));
        }
    }

    /// <summary>Writes a string property.</summary>
    public void WriteString(string name, string? value)
    {
        WritePropertyName(name);
        WriteString(value);
    }

    /// <summary>Writes an integer property.</summary>
    public void WriteNumber(string name, long value)
    {
        WritePropertyName(name);
        WriteNumber(value);
    }

    /// <summary>Writes an integer property, or <c>null</c>.</summary>
    public void WriteNumber(string name, long? value)
    {
        WritePropertyName(name);
        if (value.HasValue)
        {
            WriteNumber(value.Value);
        }
        else
        {
            WriteNull();
        }
    }

    /// <summary>Writes a double property.</summary>
    public void WriteNumber(string name, double value)
    {
        WritePropertyName(name);
        WriteNumber(value);
    }

    /// <summary>Writes a double property, or <c>null</c>.</summary>
    public void WriteNumber(string name, double? value)
    {
        WritePropertyName(name);
        if (value.HasValue)
        {
            WriteNumber(value.Value);
        }
        else
        {
            WriteNull();
        }
    }

    /// <summary>Writes a boolean property, or <c>null</c>.</summary>
    public void WriteBoolean(string name, bool? value)
    {
        WritePropertyName(name);
        if (value.HasValue)
        {
            WriteBoolean(value.Value);
        }
        else
        {
            WriteNull();
        }
    }

    /// <summary>Writes a boolean property.</summary>
    public void WriteBoolean(string name, bool value)
    {
        WritePropertyName(name);
        WriteBoolean(value);
    }

    /// <summary>Writes a property with a value tree.</summary>
    public void WriteValue(string name, JsonValue? value)
    {
        WritePropertyName(name);
        WriteValue(value);
    }

    /// <summary>Writes every property of <paramref name="properties"/> into the current object (no-op for <c>null</c>).</summary>
    public void WriteProperties(JsonObject? properties)
    {
        if (properties is null)
        {
            return;
        }

        foreach (var property in properties)
        {
            WritePropertyName(property.Key);
            WriteValue(property.Value);
        }
    }

    private void WriteNumberText(string text)
    {
        BeforeValue();
        WriteAscii(text);
        AfterValue();
    }

    private void BeforeValue()
    {
        if (_stack.Count == 0)
        {
            if (_rootWritten)
            {
                throw new InvalidOperationException("The JSON document already has a root value.");
            }

            return;
        }

        var top = _stack.Peek();
        if (top.Kind == ContainerKind.Object)
        {
            if (!top.AwaitingValue)
            {
                throw new InvalidOperationException("Write a property name before a value inside an object.");
            }
        }
        else if (top.Count > 0)
        {
            WriteByte((byte)',');
        }
    }

    private void AfterValue()
    {
        if (_stack.Count == 0)
        {
            _rootWritten = true;
            return;
        }

        var top = _stack.Peek();
        top.AwaitingValue = false;
        top.Count++;
    }

    private void EnsureComplete()
    {
        if (!IsComplete)
        {
            throw new InvalidOperationException("The JSON document is incomplete.");
        }
    }

    private void WriteQuoted(string s)
    {
        // Worst case: 6 bytes per UTF-16 unit (\uXXXX) plus quotes.
        Ensure((long)s.Length * 6 + 2);
        var b = _buffer;
        var n = _length;
        b[n++] = (byte)'"';
        for (var i = 0; i < s.Length; i++)
        {
            var c = s[i];
            if (c < 0x80)
            {
                switch (c)
                {
                    case '"': b[n++] = (byte)'\\'; b[n++] = (byte)'"'; break;
                    case '\\': b[n++] = (byte)'\\'; b[n++] = (byte)'\\'; break;
                    case '\n': b[n++] = (byte)'\\'; b[n++] = (byte)'n'; break;
                    case '\r': b[n++] = (byte)'\\'; b[n++] = (byte)'r'; break;
                    case '\t': b[n++] = (byte)'\\'; b[n++] = (byte)'t'; break;
                    case '\b': b[n++] = (byte)'\\'; b[n++] = (byte)'b'; break;
                    case '\f': b[n++] = (byte)'\\'; b[n++] = (byte)'f'; break;
                    default:
                        if (c < 0x20)
                        {
                            n = WriteUnicodeEscape(b, n, c);
                        }
                        else
                        {
                            b[n++] = (byte)c;
                        }

                        break;
                }
            }
            else if (c < 0x800)
            {
                b[n++] = (byte)(0xC0 | (c >> 6));
                b[n++] = (byte)(0x80 | (c & 0x3F));
            }
            else if (char.IsHighSurrogate(c) && i + 1 < s.Length && char.IsLowSurrogate(s[i + 1]))
            {
                var cp = char.ConvertToUtf32(c, s[++i]);
                b[n++] = (byte)(0xF0 | (cp >> 18));
                b[n++] = (byte)(0x80 | ((cp >> 12) & 0x3F));
                b[n++] = (byte)(0x80 | ((cp >> 6) & 0x3F));
                b[n++] = (byte)(0x80 | (cp & 0x3F));
            }
            else if (char.IsSurrogate(c))
            {
                // Unpaired surrogate: not encodable as UTF-8, so keep it losslessly as an escape.
                n = WriteUnicodeEscape(b, n, c);
            }
            else
            {
                b[n++] = (byte)(0xE0 | (c >> 12));
                b[n++] = (byte)(0x80 | ((c >> 6) & 0x3F));
                b[n++] = (byte)(0x80 | (c & 0x3F));
            }
        }

        b[n++] = (byte)'"';
        _length = n;
    }

    private static int WriteUnicodeEscape(byte[] b, int n, char c)
    {
        b[n++] = (byte)'\\';
        b[n++] = (byte)'u';
        b[n++] = HexDigits[(c >> 12) & 0xF];
        b[n++] = HexDigits[(c >> 8) & 0xF];
        b[n++] = HexDigits[(c >> 4) & 0xF];
        b[n++] = HexDigits[c & 0xF];
        return n;
    }

    private void WriteAscii(string s)
    {
        Ensure(s.Length);
        for (var i = 0; i < s.Length; i++)
        {
            _buffer[_length++] = (byte)s[i];
        }
    }

    private void WriteByte(byte c)
    {
        Ensure(1);
        _buffer[_length++] = c;
    }

    private void Ensure(long extra)
    {
        var needed = _length + extra;
        if (needed <= _buffer.Length)
        {
            return;
        }

        var size = Math.Max(needed, (long)_buffer.Length * 2);
        if (size > int.MaxValue)
        {
            throw new InvalidOperationException("JSON output exceeds 2 GiB.");
        }

        var next = new byte[size];
        Buffer.BlockCopy(_buffer, 0, next, 0, _length);
        _buffer = next;
    }

    private sealed class Container
    {
        public Container(ContainerKind kind) => Kind = kind;

        public ContainerKind Kind { get; }

        public int Count { get; set; }

        public bool AwaitingValue { get; set; }
    }
}
