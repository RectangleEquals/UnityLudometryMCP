using UnityLudometry.Protocol.Envelopes;
using UnityLudometry.Protocol.Json;
using UnityLudometry.Protocol.Messages;

namespace UnityLudometry.Protocol.Conformance;

/// <summary>
/// Replays a fixture through the envelope and message types and reports every difference. A fixture passes when each
/// envelope and each payload re-serializes to JSON that is structurally equal to the fixture (property order and number
/// spelling don't matter), and when a deliberately invalid request is rejected with <c>INVALID_PARAMS</c>.
/// </summary>
public static class FixtureReplay
{
    /// <summary>Replays one fixture. Returns the problems found (empty when it conforms).</summary>
    public static IReadOnlyList<string> Check(FixtureCase fixture)
    {
        var problems = new List<string>();
        if (fixture.IsEvent)
        {
            CheckEvent(fixture, problems);
        }
        else
        {
            CheckExchange(fixture, problems);
        }

        return problems;
    }

    private static void CheckEvent(FixtureCase fixture, List<string> problems)
    {
        if (RoundTripEnvelope(fixture.Event!, "event", problems) is not EventEnvelope envelope)
        {
            return;
        }

        if (envelope.Method != fixture.Group)
        {
            problems.Add($"event kind '{envelope.Method}' doesn't match the fixture folder '{fixture.Group}'.");
        }

        if (EventRegistry.Find(envelope.Method) is { } descriptor)
        {
            RoundTripMessage(envelope.Params, descriptor.ReadParams, "params", problems);
        }
        else
        {
            problems.Add($"event '{envelope.Method}' isn't in the registry.");
        }
    }

    private static void CheckExchange(FixtureCase fixture, List<string> problems)
    {
        var request = RoundTripEnvelope(fixture.Request!, "request", problems) as RequestEnvelope;
        var response = RoundTripEnvelope(fixture.Response!, "response", problems) as ResponseEnvelope;
        if (request is null || response is null)
        {
            problems.Add("the fixture needs a request envelope and a response envelope.");
            return;
        }

        if (request.Id != response.Id)
        {
            problems.Add($"response id '{response.Id}' doesn't match request id '{request.Id}'.");
        }

        if (!JsonValue.DeepEquals(request.Context, response.Context))
        {
            problems.Add("the response must echo the request's context unchanged.");
        }

        if (fixture.IsGeneric)
        {
            return;
        }

        if (request.Method != fixture.Group)
        {
            problems.Add($"request method '{request.Method}' doesn't match the fixture folder '{fixture.Group}'.");
        }

        if (MethodRegistry.Find(request.Method) is not { } method)
        {
            problems.Add($"method '{request.Method}' isn't in the registry.");
            return;
        }

        if (fixture.RequestValid)
        {
            RoundTripMessage(request.Params, method.ReadParams, "params", problems);
        }
        else
        {
            try
            {
                method.ReadParams(request.Params, "params");
                problems.Add("the invalid request was accepted by the params type.");
            }
            catch (ProtocolException e) when (e.Code == ErrorCodes.InvalidParams)
            {
                // Expected.
            }

            if (response.Error?.Code != ErrorCodes.InvalidParams)
            {
                problems.Add("an invalid request must be answered with INVALID_PARAMS.");
            }
        }

        if (!response.IsError)
        {
            RoundTripMessage(response.Result, method.ReadResult, "result", problems);
        }

        if (fixture.JobResult is not null)
        {
            if (method.ReadJobResult is { } readJobResult)
            {
                RoundTripMessage(fixture.JobResult, readJobResult, "jobResult", problems);
            }
            else
            {
                problems.Add($"'{request.Method}' isn't a job method but the fixture has a jobResult.");
            }
        }
        else if (method.Job && !response.IsError && fixture.RequestValid)
        {
            problems.Add($"'{request.Method}' is a job method: a success fixture needs a jobResult.");
        }
    }

    private static Envelope? RoundTripEnvelope(JsonObject json, string what, List<string> problems)
    {
        try
        {
            var envelope = Envelope.Parse(json);
            var written = JsonValue.Parse(envelope.ToUtf8Bytes());
            if (!JsonValue.DeepEquals(json, written))
            {
                problems.Add($"{what} envelope doesn't round-trip: expected {json}, wrote {written}.");
            }

            return envelope;
        }
        catch (ProtocolException e)
        {
            problems.Add($"{what} envelope failed to parse: {e.Code} {e.Message}");
            return null;
        }
    }

    /// <summary>Reads <paramref name="json"/> with <paramref name="read"/>, writes it back, and reports any difference.</summary>
    public static void RoundTripMessage(JsonValue? json, MessageReader read, string what, List<string> problems)
    {
        try
        {
            var message = read(json, what);
            var written = message.ToJson();
            var expected = json ?? new JsonObject();
            if (!JsonValue.DeepEquals(expected, written))
            {
                problems.Add($"{what} doesn't round-trip through {message.GetType().Name}: expected {expected}, wrote {written}.");
            }
        }
        catch (ProtocolException e)
        {
            problems.Add($"{what} failed to read: {e.Code} {e.Message}");
        }
    }
}
