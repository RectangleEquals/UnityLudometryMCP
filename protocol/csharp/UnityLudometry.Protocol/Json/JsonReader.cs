using System;
using System.Text;

namespace UnityLudometry.Protocol.Json;

/// <summary>Limits applied while parsing untrusted JSON.</summary>
public sealed class JsonReaderOptions
{
    /// <summary>The defaults: depth 128, 16 MiB input.</summary>
    public static readonly JsonReaderOptions Default = new();

    /// <summary>Maximum nesting depth of arrays and objects.</summary>
    public int MaxDepth { get; set; } = 128;

    /// <summary>Maximum input size in bytes.</summary>
    public int MaxBytes { get; set; } = Framing.FrameLimits.DefaultMaxFrameBytes;
}

/// <summary>
/// Strict RFC 8259 parser for UTF-8 input. Rejects invalid UTF-8, unescaped control characters, duplicate
/// property names, trailing content and anything beyond the configured limits. Escaped unpaired surrogates
/// (<c>\ud800</c>) are accepted and kept, because strings read from games can contain them.
/// </summary>
public static class JsonReader
{
    internal static readonly UTF8Encoding StrictUtf8 = new(encoderShouldEmitUTF8Identifier: false, throwOnInvalidBytes: true);

    /// <summary>Parses a complete JSON document. Throws <see cref="ProtocolException"/> with <c>INVALID_FRAME</c>.</summary>
    public static JsonValue Parse(byte[] utf8, int offset, int count, JsonReaderOptions? options = null)
    {
        if (utf8 is null)
        {
            throw new ArgumentNullException(nameof(utf8));
        }

        if (offset < 0 || count < 0 || offset + count > utf8.Length)
        {
            throw new ArgumentOutOfRangeException(nameof(count));
        }

        options ??= JsonReaderOptions.Default;
        if (count > options.MaxBytes)
        {
            throw Fail($"JSON input of {count} bytes exceeds the limit of {options.MaxBytes} bytes.", -1);
        }

        var parser = new Parser(utf8, offset, offset + count, options.MaxDepth);
        return parser.ParseDocument();
    }

    /// <summary>Whether <paramref name="text"/> is a valid JSON number.</summary>
    public static bool IsValidNumber(string text)
    {
        if (string.IsNullOrEmpty(text))
        {
            return false;
        }

        var bytes = Encoding.ASCII.GetBytes(text);
        var end = ScanNumber(bytes, 0, bytes.Length);
        return end == bytes.Length;
    }

    private static ProtocolException Fail(string message, int position) =>
        new(ErrorCodes.InvalidFrame, position >= 0 ? $"Invalid JSON at byte {position}: {message}" : $"Invalid JSON: {message}");

    /// <summary>Returns the end index of a number starting at <paramref name="i"/>, or -1 if it isn't a valid number.</summary>
    private static int ScanNumber(byte[] b, int i, int end)
    {
        if (i < end && b[i] == (byte)'-')
        {
            i++;
        }

        if (i >= end)
        {
            return -1;
        }

        if (b[i] == (byte)'0')
        {
            i++;
        }
        else if (b[i] >= (byte)'1' && b[i] <= (byte)'9')
        {
            while (i < end && IsDigit(b[i]))
            {
                i++;
            }
        }
        else
        {
            return -1;
        }

        if (i < end && b[i] == (byte)'.')
        {
            i++;
            if (i >= end || !IsDigit(b[i]))
            {
                return -1;
            }

            while (i < end && IsDigit(b[i]))
            {
                i++;
            }
        }

        if (i < end && (b[i] == (byte)'e' || b[i] == (byte)'E'))
        {
            i++;
            if (i < end && (b[i] == (byte)'+' || b[i] == (byte)'-'))
            {
                i++;
            }

            if (i >= end || !IsDigit(b[i]))
            {
                return -1;
            }

            while (i < end && IsDigit(b[i]))
            {
                i++;
            }
        }

        return i;
    }

    private static bool IsDigit(byte c) => c >= (byte)'0' && c <= (byte)'9';

    private sealed class Parser
    {
        private readonly byte[] _b;
        private readonly int _end;
        private readonly int _maxDepth;
        private int _i;
        private int _depth;
        private StringBuilder? _sb;

        public Parser(byte[] buffer, int start, int end, int maxDepth)
        {
            _b = buffer;
            _i = start;
            _end = end;
            _maxDepth = maxDepth;
        }

        public JsonValue ParseDocument()
        {
            // A UTF-8 byte order mark is tolerated (RFC 8259 §8.1 allows ignoring it).
            if (_end - _i >= 3 && _b[_i] == 0xEF && _b[_i + 1] == 0xBB && _b[_i + 2] == 0xBF)
            {
                _i += 3;
            }

            SkipWhitespace();
            var value = ParseValue();
            SkipWhitespace();
            if (_i != _end)
            {
                throw Fail("unexpected content after the JSON value.", _i);
            }

            return value;
        }

        private JsonValue ParseValue()
        {
            if (_i >= _end)
            {
                throw Fail("unexpected end of input.", _i);
            }

            switch (_b[_i])
            {
                case (byte)'{':
                    return ParseObject();
                case (byte)'[':
                    return ParseArray();
                case (byte)'"':
                    return new JsonString(ParseString());
                case (byte)'t':
                    ExpectLiteral("true");
                    return JsonBoolean.True;
                case (byte)'f':
                    ExpectLiteral("false");
                    return JsonBoolean.False;
                case (byte)'n':
                    ExpectLiteral("null");
                    return JsonNull.Instance;
                default:
                    return ParseNumber();
            }
        }

        private JsonObject ParseObject()
        {
            Enter();
            _i++; // {
            var obj = new JsonObject();
            SkipWhitespace();
            if (Peek() == (byte)'}')
            {
                _i++;
                _depth--;
                return obj;
            }

            while (true)
            {
                SkipWhitespace();
                if (Peek() != (byte)'"')
                {
                    throw Fail("expected a property name.", _i);
                }

                var nameStart = _i;
                var name = ParseString();
                SkipWhitespace();
                Expect((byte)':');
                SkipWhitespace();
                var value = ParseValue();
                if (obj.ContainsKey(name))
                {
                    throw Fail($"duplicate property name '{name}'.", nameStart);
                }

                obj.Add(name, value);
                SkipWhitespace();
                var c = Next();
                if (c == (byte)'}')
                {
                    break;
                }

                if (c != (byte)',')
                {
                    throw Fail("expected ',' or '}'.", _i - 1);
                }
            }

            _depth--;
            return obj;
        }

        private JsonArray ParseArray()
        {
            Enter();
            _i++; // [
            var array = new JsonArray();
            SkipWhitespace();
            if (Peek() == (byte)']')
            {
                _i++;
                _depth--;
                return array;
            }

            while (true)
            {
                SkipWhitespace();
                array.Add(ParseValue());
                SkipWhitespace();
                var c = Next();
                if (c == (byte)']')
                {
                    break;
                }

                if (c != (byte)',')
                {
                    throw Fail("expected ',' or ']'.", _i - 1);
                }
            }

            _depth--;
            return array;
        }

        private string ParseString()
        {
            var start = ++_i; // opening quote

            // Fast path: no escapes.
            var j = start;
            while (j < _end)
            {
                var c = _b[j];
                if (c == (byte)'"')
                {
                    _i = j + 1;
                    return Decode(start, j - start);
                }

                if (c == (byte)'\\')
                {
                    break;
                }

                if (c < 0x20)
                {
                    throw Fail("unescaped control character in string.", j);
                }

                j++;
            }

            if (j >= _end)
            {
                throw Fail("unterminated string.", start - 1);
            }

            // Slow path with escapes.
            var sb = _sb ??= new StringBuilder();
            sb.Clear();
            sb.Append(Decode(start, j - start));
            _i = j;
            while (true)
            {
                if (_i >= _end)
                {
                    throw Fail("unterminated string.", start - 1);
                }

                var c = _b[_i];
                if (c == (byte)'"')
                {
                    _i++;
                    return sb.ToString();
                }

                if (c == (byte)'\\')
                {
                    _i++;
                    if (_i >= _end)
                    {
                        throw Fail("unterminated escape.", _i);
                    }

                    var e = _b[_i++];
                    switch (e)
                    {
                        case (byte)'"': sb.Append('"'); break;
                        case (byte)'\\': sb.Append('\\'); break;
                        case (byte)'/': sb.Append('/'); break;
                        case (byte)'b': sb.Append('\b'); break;
                        case (byte)'f': sb.Append('\f'); break;
                        case (byte)'n': sb.Append('\n'); break;
                        case (byte)'r': sb.Append('\r'); break;
                        case (byte)'t': sb.Append('\t'); break;
                        case (byte)'u': sb.Append(ParseHex4()); break;
                        default: throw Fail("invalid escape sequence.", _i - 1);
                    }

                    continue;
                }

                if (c < 0x20)
                {
                    throw Fail("unescaped control character in string.", _i);
                }

                // A run of ordinary bytes up to the next quote or escape.
                var runStart = _i;
                while (_i < _end && _b[_i] != (byte)'"' && _b[_i] != (byte)'\\')
                {
                    if (_b[_i] < 0x20)
                    {
                        throw Fail("unescaped control character in string.", _i);
                    }

                    _i++;
                }

                sb.Append(Decode(runStart, _i - runStart));
            }
        }

        private char ParseHex4()
        {
            if (_end - _i < 4)
            {
                throw Fail("truncated \\u escape.", _i);
            }

            var value = 0;
            for (var k = 0; k < 4; k++)
            {
                var c = _b[_i++];
                int digit;
                if (c >= (byte)'0' && c <= (byte)'9')
                {
                    digit = c - '0';
                }
                else if (c >= (byte)'a' && c <= (byte)'f')
                {
                    digit = c - 'a' + 10;
                }
                else if (c >= (byte)'A' && c <= (byte)'F')
                {
                    digit = c - 'A' + 10;
                }
                else
                {
                    throw Fail("invalid hex digit in \\u escape.", _i - 1);
                }

                value = (value << 4) | digit;
            }

            return (char)value;
        }

        private string Decode(int start, int count)
        {
            if (count == 0)
            {
                return string.Empty;
            }

            try
            {
                return StrictUtf8.GetString(_b, start, count);
            }
            catch (DecoderFallbackException)
            {
                throw Fail("invalid UTF-8.", start);
            }
        }

        private JsonNumber ParseNumber()
        {
            var start = _i;
            var end = ScanNumber(_b, _i, _end);
            if (end < 0)
            {
                throw Fail("invalid value.", start);
            }

            _i = end;
            return JsonNumber.FromValidatedText(Encoding.ASCII.GetString(_b, start, end - start));
        }

        private void ExpectLiteral(string literal)
        {
            if (_end - _i < literal.Length)
            {
                throw Fail("invalid literal.", _i);
            }

            for (var k = 0; k < literal.Length; k++)
            {
                if (_b[_i + k] != (byte)literal[k])
                {
                    throw Fail("invalid literal.", _i);
                }
            }

            _i += literal.Length;
        }

        private void Enter()
        {
            if (++_depth > _maxDepth)
            {
                throw Fail($"nesting deeper than {_maxDepth} levels.", _i);
            }
        }

        private void SkipWhitespace()
        {
            while (_i < _end)
            {
                var c = _b[_i];
                if (c != (byte)' ' && c != (byte)'\t' && c != (byte)'\n' && c != (byte)'\r')
                {
                    return;
                }

                _i++;
            }
        }

        private int Peek() => _i < _end ? _b[_i] : -1;

        private int Next() => _i < _end ? _b[_i++] : throw Fail("unexpected end of input.", _i);

        private void Expect(byte c)
        {
            if (Peek() != c)
            {
                throw Fail($"expected '{(char)c}'.", _i);
            }

            _i++;
        }
    }
}
