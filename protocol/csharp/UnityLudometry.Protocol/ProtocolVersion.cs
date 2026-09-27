using System.Globalization;

namespace UnityLudometry.Protocol;

/// <summary>
/// The protocol version implemented by this package. The protocol is versioned independently of the agent and the
/// orchestrator, and changes only when the wire format does.
/// </summary>
public static class ProtocolVersion
{
    /// <summary>Major version. Also the envelope's <c>v</c> field.</summary>
    public const int Major = 0;

    /// <summary>Minor version.</summary>
    public const int Minor = 1;

    /// <summary>The version as <c>major.minor</c>.</summary>
    public static string Text => Major.ToString(CultureInfo.InvariantCulture) + "." + Minor.ToString(CultureInfo.InvariantCulture);

    /// <summary>
    /// Whether a peer speaking <paramref name="major"/>.<paramref name="minor"/> is compatible with this package.
    /// Before 1.0 (major 0) the protocol is pre-release, so both parts must match exactly. From 1.0 on, minor versions
    /// are additive and only the major has to match.
    /// </summary>
    public static bool IsCompatible(int major, int minor) =>
        major == Major && (Major != 0 || minor == Minor);
}
