namespace UnityLudometry.Protocol;

/// <summary>
/// Error codes defined by the protocol (<c>schema/common/error.schema.json</c>). Clients must treat unknown codes as
/// generic failures, because new codes may be added.
/// </summary>
public static class ErrorCodes
{
    /// <summary>The first request on a connection must be <c>hello</c>.</summary>
    public const string HandshakeRequired = "HANDSHAKE_REQUIRED";

    /// <summary>The <c>hello</c> token doesn't match the agent's session token.</summary>
    public const string BadToken = "BAD_TOKEN";

    /// <summary>The client's protocol version is incompatible with the agent's.</summary>
    public const string ProtocolMismatch = "PROTOCOL_MISMATCH";

    /// <summary>The frame or its JSON is malformed, or isn't a valid envelope.</summary>
    public const string InvalidFrame = "INVALID_FRAME";

    /// <summary>The frame exceeds the configured maximum size.</summary>
    public const string FrameTooLarge = "FRAME_TOO_LARGE";

    /// <summary>The agent doesn't implement this method.</summary>
    public const string MethodNotFound = "METHOD_NOT_FOUND";

    /// <summary>The params don't match the method's schema or can't be converted.</summary>
    public const string InvalidParams = "INVALID_PARAMS";

    /// <summary>The method needs a higher agent mode than the current one.</summary>
    public const string ModeForbidden = "MODE_FORBIDDEN";

    /// <summary>A capability or optional module is unavailable in this game or runtime.</summary>
    public const string Unsupported = "UNSUPPORTED";

    /// <summary>An anchor's module isn't loaded, or its token doesn't resolve in the loaded build.</summary>
    public const string IndexStale = "INDEX_STALE";

    /// <summary>The object, member, scene, variable or job wasn't found.</summary>
    public const string NotFound = "NOT_FOUND";

    /// <summary>The handle is unknown or released, or its Unity object was destroyed.</summary>
    public const string HandleExpired = "HANDLE_EXPIRED";

    /// <summary>A redaction ref was evicted; use the stub's locator instead.</summary>
    public const string RefExpired = "REF_EXPIRED";

    /// <summary>Exploratory resolution matched several members.</summary>
    public const string Ambiguous = "AMBIGUOUS";

    /// <summary>Game code threw during a get, set, invoke or UI action.</summary>
    public const string GameException = "GAME_EXCEPTION";

    /// <summary>Applying or removing a Harmony patch failed.</summary>
    public const string PatchFailed = "PATCH_FAILED";

    /// <summary>Loading, binding or running a snippet, patch or mod assembly failed.</summary>
    public const string ExecFailed = "EXEC_FAILED";

    /// <summary>An assembly with the same name was already loaded by the agent.</summary>
    public const string DuplicateAssembly = "DUPLICATE_ASSEMBLY";

    /// <summary>Writing an output file failed.</summary>
    public const string IoFailed = "IO_FAILED";

    /// <summary>A concurrency cap was reached; the request can be retried later.</summary>
    public const string Busy = "BUSY";

    /// <summary>The input session isn't active: counting down, paused by the user, or ended.</summary>
    public const string SessionInactive = "SESSION_INACTIVE";

    /// <summary>The request's timeout expired.</summary>
    public const string Timeout = "TIMEOUT";

    /// <summary>The request or job was cancelled.</summary>
    public const string Cancelled = "CANCELLED";

    /// <summary>The game's main thread isn't processing requests.</summary>
    public const string MainThreadUnavailable = "MAIN_THREAD_UNAVAILABLE";

    /// <summary>An agent defect.</summary>
    public const string Internal = "INTERNAL";
}
