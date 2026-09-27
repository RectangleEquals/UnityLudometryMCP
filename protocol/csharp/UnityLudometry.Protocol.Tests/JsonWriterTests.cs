using System.Globalization;
using System.Text;
using UnityLudometry.Protocol.Json;

namespace UnityLudometry.Protocol.Tests;

public sealed class JsonWriterTests
{
    private static string Write(Action<JsonWriter> write)
    {
        using var writer = new JsonWriter();
        write(writer);
        return Encoding.UTF8.GetString(writer.ToArray());
    }

    [Fact]
    public void Escapes_strings()
    {
        var json = Write(w => w.WriteString("q\" b\\ n\n r\r t\t bs\b ff\f nul\0 us\u001f é 😀 \u2028"));
        Assert.Equal("\"q\\\" b\\\\ n\\n r\\r t\\t bs\\b ff\\f nul\\u0000 us\\u001f é 😀 \u2028\"", json);
    }

    [Fact]
    public void Writes_unpaired_surrogates_as_escapes_that_round_trip()
    {
        var original = "a\ud800b\udc00c";
        var json = Write(w => w.WriteString(original));
        Assert.Equal("\"a\\ud800b\\udc00c\"", json);
        Assert.Equal(original, ((JsonString)JsonValue.Parse(json)).Value);
    }

    [Fact]
    public void Writes_numbers_in_invariant_round_trip_form()
    {
        var previous = CultureInfo.CurrentCulture;
        try
        {
            CultureInfo.CurrentCulture = new CultureInfo("de-DE");
            Assert.Equal("0.1", Write(w => w.WriteNumber(0.1)));
            Assert.Equal("0.1", Write(w => w.WriteNumber(0.1f)));
            Assert.Equal("1.5", Write(w => w.WriteNumber(1.5m)));
            Assert.Equal("-9223372036854775808", Write(w => w.WriteNumber(long.MinValue)));
            Assert.Equal("18446744073709551615", Write(w => w.WriteNumber(ulong.MaxValue)));
        }
        finally
        {
            CultureInfo.CurrentCulture = previous;
        }

        foreach (var d in new[] { double.MaxValue, double.Epsilon, -0.0, 1e-7, 123456789.123456789, Math.PI })
        {
            var text = Write(w => w.WriteNumber(d));
            Assert.Equal(d, ((JsonNumber)JsonValue.Parse(text)).GetDouble());
        }
    }

    [Theory]
    [InlineData(double.NaN)]
    [InlineData(double.PositiveInfinity)]
    [InlineData(double.NegativeInfinity)]
    public void Refuses_non_finite_numbers(double value) =>
        Assert.Throws<ArgumentOutOfRangeException>(() => Write(w => w.WriteNumber(value)));

    [Fact]
    public void Writes_nested_structures()
    {
        var json = Write(w =>
        {
            w.WriteStartObject();
            w.WriteString("a", "x");
            w.WritePropertyName("b");
            w.WriteStartArray();
            w.WriteNumber(1);
            w.WriteNull();
            w.WriteStartObject();
            w.WriteEndObject();
            w.WriteEndArray();
            w.WriteNumber("c", (long?)null);
            w.WriteEndObject();
        });
        Assert.Equal("{\"a\":\"x\",\"b\":[1,null,{}],\"c\":null}", json);
    }

    [Fact]
    public void Rejects_invalid_call_sequences()
    {
        using var writer = new JsonWriter();
        writer.WriteStartObject();
        Assert.Throws<InvalidOperationException>(() => writer.WriteNumber(1));
        writer.WritePropertyName("a");
        Assert.Throws<InvalidOperationException>(() => writer.WritePropertyName("b"));
        Assert.Throws<InvalidOperationException>(() => writer.WriteEndObject());
        writer.WriteNumber(1);
        Assert.Throws<InvalidOperationException>(() => writer.WriteEndArray());
        Assert.Throws<InvalidOperationException>(() => writer.ToArray());
        writer.WriteEndObject();
        Assert.Throws<InvalidOperationException>(() => writer.WriteNumber(2));
        Assert.Equal("{\"a\":1}", Encoding.UTF8.GetString(writer.ToArray()));
    }

    [Fact]
    public void Reuses_buffers_across_writers_without_leaking_content()
    {
        Assert.Equal("\"first-document\"", Write(w => w.WriteString("first-document")));
        Assert.Equal("1", Write(w => w.WriteNumber(1)));
    }
}
