using UnityLudometry.Protocol.Envelopes;
using UnityLudometry.Protocol.Json;
using UnityLudometry.Protocol.Messages;

namespace UnityLudometry.Protocol.Tests;

public sealed class EnvelopeTests
{
    [Fact]
    public void Parses_a_request_and_keeps_unknown_fields()
    {
        var envelope = Envelope.Parse(JsonValue.Parse(
            "{\"v\":0,\"id\":\"r-1\",\"kind\":\"request\",\"method\":\"ping\",\"params\":{\"echo\":\"x\",\"future\":1},\"timeoutMs\":500,\"context\":{\"task\":\"t\"},\"later\":true}"));
        var request = Assert.IsType<RequestEnvelope>(envelope);
        Assert.Equal("r-1", request.Id);
        Assert.Equal(Methods.Ping, request.Method);
        Assert.Equal(500, request.TimeoutMs);
        Assert.Equal("{\"task\":\"t\"}", request.Context!.ToString());
        Assert.Equal("{\"later\":true}", request.Extra!.ToString());

        var ping = PingParams.Read(request.Params, "params");
        Assert.Equal("x", ping.Echo);
        Assert.Equal("{\"echo\":\"x\",\"future\":1}", ping.ToJson().ToString());
    }

    [Fact]
    public void Success_and_failure_responses_serialize_as_specified()
    {
        var ok = ResponseEnvelope.Success("r-2", new CancelResult { Cancelled = true }.ToJson());
        Assert.Equal("{\"v\":0,\"id\":\"r-2\",\"kind\":\"response\",\"result\":{\"cancelled\":true}}", JsonValue.Parse(ok.ToUtf8Bytes()).ToString());

        var failure = ResponseEnvelope.Failure("r-3", ProtocolException.InvalidParams("params.id", "params.id is required.").ToError());
        var parsed = Assert.IsType<ResponseEnvelope>(Envelope.Parse(failure.ToUtf8Bytes()));
        Assert.True(parsed.IsError);
        Assert.Equal(ErrorCodes.InvalidParams, parsed.Error!.Code);
        Assert.Equal("params.id", ((JsonString)parsed.Error.Data!["param"]!).Value);
    }

    [Fact]
    public void A_null_result_is_a_valid_success()
    {
        var parsed = Assert.IsType<ResponseEnvelope>(Envelope.Parse(JsonValue.Parse("{\"v\":0,\"id\":\"a\",\"kind\":\"response\",\"result\":null}")));
        Assert.False(parsed.IsError);
        Assert.Equal(JsonKind.Null, parsed.Result!.Kind);
    }

    [Theory]
    [InlineData("[]")]
    [InlineData("{\"id\":\"a\",\"kind\":\"request\",\"method\":\"ping\"}")]
    [InlineData("{\"v\":\"0\",\"id\":\"a\",\"kind\":\"request\",\"method\":\"ping\"}")]
    [InlineData("{\"v\":0,\"id\":\"a\",\"kind\":\"notify\",\"method\":\"ping\"}")]
    [InlineData("{\"v\":0,\"id\":\"\",\"kind\":\"request\",\"method\":\"ping\"}")]
    [InlineData("{\"v\":0,\"id\":\"a\",\"kind\":\"request\",\"method\":\"\"}")]
    [InlineData("{\"v\":0,\"id\":\"a\",\"kind\":\"request\",\"method\":\"ping\",\"params\":[]}")]
    [InlineData("{\"v\":0,\"id\":\"a\",\"kind\":\"response\"}")]
    [InlineData("{\"v\":0,\"id\":\"a\",\"kind\":\"response\",\"result\":1,\"error\":{\"code\":\"X\",\"message\":\"m\"}}")]
    [InlineData("{\"v\":0,\"kind\":\"event\",\"method\":\"log\",\"params\":{}}")]
    public void Malformed_envelopes_are_invalid_frames(string json)
    {
        var e = Assert.Throws<ProtocolException>(() => Envelope.Parse(JsonValue.Parse(json)));
        Assert.Equal(ErrorCodes.InvalidFrame, e.Code);
    }

    [Fact]
    public void A_different_major_still_parses_so_the_agent_can_answer_PROTOCOL_MISMATCH()
    {
        var envelope = Envelope.Parse(JsonValue.Parse("{\"v\":7,\"id\":\"a\",\"kind\":\"request\",\"method\":\"hello\"}"));
        Assert.Equal(7, envelope.V);
    }

    [Theory]
    [InlineData(0, 1, true)]
    [InlineData(0, 0, false)]
    [InlineData(0, 2, false)]
    [InlineData(1, 1, false)]
    public void Pre_release_versions_must_match_exactly(int major, int minor, bool compatible)
    {
        Assert.Equal(0, ProtocolVersion.Major);
        Assert.Equal(compatible, ProtocolVersion.IsCompatible(major, minor));
    }

    [Fact]
    public void Message_readers_name_the_offending_parameter()
    {
        var e = Assert.Throws<ProtocolException>(() => HelloParams.Read(JsonValue.Parse("{\"token\":\"t\",\"client\":{\"name\":\"c\"},\"protocol\":{\"major\":0,\"minor\":1}}"), "params"));
        Assert.Equal(ErrorCodes.InvalidParams, e.Code);
        Assert.Equal("params.client.version", ((JsonString)e.ErrorData!["param"]!).Value);

        e = Assert.Throws<ProtocolException>(() => ObjectReader.ReadMode(new JsonString("Admin"), "result.mode"));
        Assert.Equal(ErrorCodes.InvalidParams, e.Code);
    }

    [Theory]
    [InlineData(AgentMode.ReadOnly, "ReadOnly")]
    [InlineData(AgentMode.ReadOnlyLoad, "ReadOnly+Load")]
    [InlineData(AgentMode.Full, "Full")]
    public void Agent_modes_use_their_wire_names(AgentMode mode, string wire)
    {
        Assert.Equal(wire, AgentModes.ToWire(mode));
        Assert.True(AgentModes.TryParse(wire, out var parsed));
        Assert.Equal(mode, parsed);
    }
}
