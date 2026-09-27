using System;
using UnityLudometry.Protocol.Envelopes;
using UnityLudometry.Protocol.Json;

namespace UnityLudometry.Protocol;

/// <summary>A protocol-level failure that maps directly to an error response.</summary>
public sealed class ProtocolException : Exception
{
    /// <summary>Creates an exception with a protocol error code.</summary>
    public ProtocolException(string code, string message, JsonObject? errorData = null, Exception? innerException = null)
        : base(message, innerException)
    {
        Code = code ?? throw new ArgumentNullException(nameof(code));
        ErrorData = errorData;
    }

    /// <summary>The protocol error code (see <see cref="ErrorCodes"/>).</summary>
    public string Code { get; }

    /// <summary>Structured details for the error's <c>data</c> field.</summary>
    public JsonObject? ErrorData { get; }

    /// <summary>Creates an <c>INVALID_PARAMS</c> exception naming the offending parameter.</summary>
    public static ProtocolException InvalidParams(string param, string message)
    {
        var data = new JsonObject();
        data.Add("param", new JsonString(param));
        return new ProtocolException(ErrorCodes.InvalidParams, message, data);
    }

    /// <summary>Converts this exception to the error object of a response.</summary>
    public ProtocolError ToError() => new() { Code = Code, Message = Message, Data = ErrorData };
}
