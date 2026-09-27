using System;
using UnityLudometry.Protocol.Json;

namespace UnityLudometry.Protocol.Envelopes;

/// <summary>The kind of an envelope.</summary>
public enum EnvelopeKind
{
    /// <summary>A request from a client.</summary>
    Request,

    /// <summary>A response to a request, with either a result or an error.</summary>
    Response,

    /// <summary>An event pushed to a subscribed connection.</summary>
    Event,
}

/// <summary>
/// One protocol message (the payload of one frame). <see cref="Context"/> is an optional opaque object a client attaches
/// to a request; the agent echoes it unchanged on the response and on every event the request produces.
/// </summary>
public abstract class Envelope
{
    private protected Envelope()
    {
    }

    /// <summary>The protocol major version (<c>v</c>).</summary>
    public int V { get; set; } = ProtocolVersion.Major;

    /// <summary>The envelope kind.</summary>
    public abstract EnvelopeKind Kind { get; }

    /// <summary>Opaque client context, echoed by the agent.</summary>
    public JsonObject? Context { get; set; }

    /// <summary>Envelope properties this version doesn't know (kept for round-trips).</summary>
    public JsonObject? Extra { get; set; }

    /// <summary>Parses one frame's payload. Throws <see cref="ProtocolException"/> (<c>INVALID_FRAME</c>).</summary>
    public static Envelope Parse(byte[] utf8, JsonReaderOptions? options = null) => Parse(JsonValue.Parse(utf8, options));

    /// <summary>Parses an envelope from a JSON value. Throws <see cref="ProtocolException"/> (<c>INVALID_FRAME</c>).</summary>
    public static Envelope Parse(JsonValue value)
    {
        try
        {
            var r = new ObjectReader(value, "envelope");
            var v = r.RequiredInt32("v");
            var kind = r.RequiredString("kind");
            Envelope envelope = kind switch
            {
                "request" => RequestEnvelope.Read(r),
                "response" => ResponseEnvelope.Read(r),
                "event" => EventEnvelope.Read(r),
                _ => throw new ProtocolException(ErrorCodes.InvalidFrame, $"Unknown envelope kind '{kind}'."),
            };
            envelope.V = v;
            envelope.Context = r.OptionalObject("context");
            envelope.Extra = r.Rest();
            return envelope;
        }
        catch (ProtocolException e) when (e.Code == ErrorCodes.InvalidParams)
        {
            throw new ProtocolException(ErrorCodes.InvalidFrame, "Invalid envelope: " + e.Message, e.ErrorData, e);
        }
    }

    /// <summary>Serializes the envelope as compact UTF-8 JSON (one frame's payload).</summary>
    public byte[] ToUtf8Bytes()
    {
        using var writer = new JsonWriter();
        WriteJson(writer);
        return writer.ToArray();
    }

    /// <summary>Writes the envelope.</summary>
    public void WriteJson(JsonWriter writer)
    {
        writer.WriteStartObject();
        writer.WriteNumber("v", V);
        WriteBody(writer);
        if (Context is not null)
        {
            writer.WriteValue("context", Context);
        }

        writer.WriteProperties(Extra);
        writer.WriteEndObject();
    }

    private protected abstract void WriteBody(JsonWriter writer);

    private protected static string ValidateMethod(string method)
    {
        if (method.Length == 0)
        {
            throw new ProtocolException(ErrorCodes.InvalidFrame, "Invalid envelope: method is empty.");
        }

        return method;
    }
}

/// <summary>A request.</summary>
public sealed class RequestEnvelope : Envelope
{
    /// <summary>Client-chosen id, unique among the connection's in-flight requests.</summary>
    public string Id { get; set; } = string.Empty;

    /// <summary>The method name.</summary>
    public string Method { get; set; } = string.Empty;

    /// <summary>The params object; <c>null</c> when absent.</summary>
    public JsonObject? Params { get; set; }

    /// <summary>Per-request timeout in milliseconds, capped by the method's maximum.</summary>
    public long? TimeoutMs { get; set; }

    /// <inheritdoc />
    public override EnvelopeKind Kind => EnvelopeKind.Request;

    internal static RequestEnvelope Read(ObjectReader r)
    {
        var request = new RequestEnvelope
        {
            Id = r.RequiredString("id"),
            Method = ValidateMethod(r.RequiredString("method")),
            Params = r.OptionalObject("params"),
            TimeoutMs = r.OptionalInt64("timeoutMs"),
        };
        if (request.Id.Length == 0)
        {
            throw new ProtocolException(ErrorCodes.InvalidFrame, "Invalid envelope: id is empty.");
        }

        return request;
    }

    private protected override void WriteBody(JsonWriter writer)
    {
        writer.WriteString("id", Id);
        writer.WriteString("kind", "request");
        writer.WriteString("method", Method);
        if (Params is not null)
        {
            writer.WriteValue("params", Params);
        }

        if (TimeoutMs is { } timeout)
        {
            writer.WriteNumber("timeoutMs", timeout);
        }
    }
}

/// <summary>A response: exactly one of <see cref="Result"/> and <see cref="Error"/> is set.</summary>
public sealed class ResponseEnvelope : Envelope
{
    /// <summary>The id of the request being answered.</summary>
    public string Id { get; set; } = string.Empty;

    /// <summary>The result (any JSON value; JSON <c>null</c> is a valid result). <c>null</c> on failure.</summary>
    public JsonValue? Result { get; set; }

    /// <summary>The error; <c>null</c> on success.</summary>
    public ProtocolError? Error { get; set; }

    /// <summary>Whether this response is a failure.</summary>
    public bool IsError => Error is not null;

    /// <inheritdoc />
    public override EnvelopeKind Kind => EnvelopeKind.Response;

    /// <summary>Creates a success response.</summary>
    public static ResponseEnvelope Success(string id, JsonValue? result, JsonObject? context = null) =>
        new() { Id = id, Result = result ?? JsonNull.Instance, Context = context };

    /// <summary>Creates a failure response.</summary>
    public static ResponseEnvelope Failure(string id, ProtocolError error, JsonObject? context = null) =>
        new() { Id = id, Error = error ?? throw new ArgumentNullException(nameof(error)), Context = context };

    internal static ResponseEnvelope Read(ObjectReader r)
    {
        var response = new ResponseEnvelope { Id = r.RequiredString("id") };
        var result = r.OptionalValue("result");
        var error = r.Optional("error", ProtocolError.Read);
        if ((result is null) == (error is null))
        {
            throw new ProtocolException(ErrorCodes.InvalidFrame, "Invalid envelope: a response needs exactly one of result and error.");
        }

        response.Result = result;
        response.Error = error;
        return response;
    }

    private protected override void WriteBody(JsonWriter writer)
    {
        writer.WriteString("id", Id);
        writer.WriteString("kind", "response");
        if (Error is not null)
        {
            writer.WritePropertyName("error");
            Error.WriteJson(writer);
        }
        else
        {
            writer.WriteValue("result", Result ?? JsonNull.Instance);
        }
    }
}

/// <summary>An event.</summary>
public sealed class EventEnvelope : Envelope
{
    /// <summary>The event kind (e.g. <c>log</c>).</summary>
    public string Method { get; set; } = string.Empty;

    /// <summary>Per-connection sequence number, increasing across all events. A gap means dropped event batches.</summary>
    public long Seq { get; set; }

    /// <summary>The event payload.</summary>
    public JsonObject Params { get; set; } = new();

    /// <inheritdoc />
    public override EnvelopeKind Kind => EnvelopeKind.Event;

    internal static EventEnvelope Read(ObjectReader r) => new()
    {
        Method = ValidateMethod(r.RequiredString("method")),
        Seq = r.RequiredInt64("seq"),
        Params = r.RequiredObject("params"),
    };

    private protected override void WriteBody(JsonWriter writer)
    {
        writer.WriteString("kind", "event");
        writer.WriteString("method", Method);
        writer.WriteNumber("seq", Seq);
        writer.WriteValue("params", Params);
    }
}

/// <summary>The error object of a failed response.</summary>
public sealed class ProtocolError
{
    /// <summary>The error code (see <see cref="ErrorCodes"/>). Unknown codes must be treated as generic failures.</summary>
    public string Code { get; set; } = ErrorCodes.Internal;

    /// <summary>Human-readable description. Not for matching.</summary>
    public string Message { get; set; } = string.Empty;

    /// <summary>Structured details; keys depend on the code.</summary>
    public JsonObject? Data { get; set; }

    /// <summary>Properties this version doesn't know.</summary>
    public JsonObject? Extra { get; set; }

    /// <summary>Reads an error object.</summary>
    public static ProtocolError Read(JsonValue value, string path)
    {
        var r = new ObjectReader(value, path);
        return new ProtocolError
        {
            Code = r.RequiredString("code"),
            Message = r.RequiredString("message"),
            Data = r.OptionalObject("data"),
            Extra = r.Rest(),
        };
    }

    /// <summary>Writes the error object.</summary>
    public void WriteJson(JsonWriter writer)
    {
        writer.WriteStartObject();
        writer.WriteString("code", Code);
        writer.WriteString("message", Message);
        if (Data is not null)
        {
            writer.WriteValue("data", Data);
        }

        writer.WriteProperties(Extra);
        writer.WriteEndObject();
    }

    /// <summary>Converts the error to an exception.</summary>
    public ProtocolException ToException() => new(Code, Message, Data);
}
