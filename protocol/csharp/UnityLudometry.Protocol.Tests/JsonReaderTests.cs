using System.Text;
using UnityLudometry.Protocol.Json;

namespace UnityLudometry.Protocol.Tests;

public sealed class JsonReaderTests
{
    [Theory]
    [InlineData("null", JsonKind.Null)]
    [InlineData("true", JsonKind.Boolean)]
    [InlineData(" false ", JsonKind.Boolean)]
    [InlineData("-0.5e+10", JsonKind.Number)]
    [InlineData("\"x\"", JsonKind.String)]
    [InlineData("[]", JsonKind.Array)]
    [InlineData("{}", JsonKind.Object)]
    [InlineData("\r\n\t{ \"a\" : [ 1 , { } ] }\n", JsonKind.Object)]
    public void Parses_valid_documents(string json, JsonKind kind) => Assert.Equal(kind, JsonValue.Parse(json).Kind);

    [Theory]
    [InlineData("")]
    [InlineData("   ")]
    [InlineData("{")]
    [InlineData("[1,]")]
    [InlineData("{\"a\":1,}")]
    [InlineData("{a:1}")]
    [InlineData("{'a':1}")]
    [InlineData("01")]
    [InlineData("1.")]
    [InlineData(".5")]
    [InlineData("+1")]
    [InlineData("1e")]
    [InlineData("NaN")]
    [InlineData("Infinity")]
    [InlineData("tru")]
    [InlineData("nul")]
    [InlineData("\"\\x\"")]
    [InlineData("\"\\u12\"")]
    [InlineData("\"unterminated")]
    [InlineData("\"tab\there\"")]
    [InlineData("{\"a\":1,\"a\":2}")]
    [InlineData("[1] x")]
    [InlineData("1 2")]
    [InlineData("// comment\n1")]
    public void Rejects_invalid_documents(string json)
    {
        var e = Assert.Throws<ProtocolException>(() => JsonValue.Parse(json));
        Assert.Equal(ErrorCodes.InvalidFrame, e.Code);
    }

    [Fact]
    public void Rejects_invalid_utf8()
    {
        var bytes = new byte[] { (byte)'"', 0xC3, 0x28, (byte)'"' };
        var e = Assert.Throws<ProtocolException>(() => JsonValue.Parse(bytes));
        Assert.Equal(ErrorCodes.InvalidFrame, e.Code);
    }

    [Fact]
    public void Decodes_escapes_and_utf8()
    {
        var value = (JsonString)JsonValue.Parse("\"a\\\"b\\\\c\\/d\\b\\f\\n\\r\\t\\u00e9\\ud83d\\ude00 é 😀\"");
        Assert.Equal("a\"b\\c/d\b\f\n\r\t\u00e9\U0001F600 é 😀", value.Value);
    }

    [Fact]
    public void Keeps_escaped_unpaired_surrogates()
    {
        var value = (JsonString)JsonValue.Parse("\"x\\ud800y\"");
        Assert.Equal("x\ud800y", value.Value);
    }

    [Fact]
    public void Tolerates_a_byte_order_mark()
    {
        var bytes = new byte[] { 0xEF, 0xBB, 0xBF, (byte)'1' };
        Assert.Equal("1", ((JsonNumber)JsonValue.Parse(bytes)).RawText);
    }

    [Fact]
    public void Preserves_number_text_and_reads_typed_values()
    {
        var n = (JsonNumber)JsonValue.Parse("1.10");
        Assert.Equal("1.10", n.RawText);
        Assert.Equal(1.1m, n.TryGetDecimal(out var d) ? d : 0);

        Assert.True(((JsonNumber)JsonValue.Parse("9223372036854775807")).TryGetInt64(out var max));
        Assert.Equal(long.MaxValue, max);
        Assert.False(((JsonNumber)JsonValue.Parse("9223372036854775808")).TryGetInt64(out _));
        Assert.True(((JsonNumber)JsonValue.Parse("18446744073709551615")).TryGetUInt64(out var umax));
        Assert.Equal(ulong.MaxValue, umax);
        Assert.True(((JsonNumber)JsonValue.Parse("5e2")).TryGetInt64(out var fromExponent));
        Assert.Equal(500, fromExponent);
        Assert.False(((JsonNumber)JsonValue.Parse("5.5")).TryGetInt64(out _));
    }

    [Fact]
    public void Enforces_the_depth_limit()
    {
        var options = new JsonReaderOptions { MaxDepth = 4 };
        Assert.Equal(JsonKind.Array, JsonValue.Parse("[[[[1]]]]", options).Kind);
        var e = Assert.Throws<ProtocolException>(() => JsonValue.Parse("[[[[[1]]]]]", options));
        Assert.Contains("nesting", e.Message);
    }

    [Fact]
    public void Deep_nesting_beyond_the_default_limit_is_rejected_without_stack_overflow()
    {
        var json = new string('[', 100_000) + new string(']', 100_000);
        Assert.Throws<ProtocolException>(() => JsonValue.Parse(json));
    }

    [Fact]
    public void Enforces_the_size_limit()
    {
        var options = new JsonReaderOptions { MaxBytes = 8 };
        Assert.Throws<ProtocolException>(() => JsonValue.Parse(Encoding.UTF8.GetBytes("\"123456789\""), options));
    }

    [Fact]
    public void Object_keeps_property_order()
    {
        var obj = (JsonObject)JsonValue.Parse("{\"b\":1,\"a\":2,\"c\":3}");
        Assert.Equal(new[] { "b", "a", "c" }, obj.Keys);
        Assert.Equal("{\"b\":1,\"a\":2,\"c\":3}", obj.ToString());
    }

    [Fact]
    public void Deep_equality_ignores_property_order_and_number_spelling()
    {
        Assert.True(JsonValue.DeepEquals(JsonValue.Parse("{\"a\":1,\"b\":[1.0,2e0]}"), JsonValue.Parse("{\"b\":[1,2],\"a\":1.00}")));
        Assert.False(JsonValue.DeepEquals(JsonValue.Parse("[1,2]"), JsonValue.Parse("[2,1]")));
        Assert.False(JsonValue.DeepEquals(JsonValue.Parse("{\"a\":null}"), JsonValue.Parse("{}")));
        Assert.False(JsonValue.DeepEquals(JsonValue.Parse("1"), JsonValue.Parse("\"1\"")));
    }
}
