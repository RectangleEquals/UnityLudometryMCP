using System;

namespace UnityLudometry.Protocol;

/// <summary>What the agent may do. Each mode includes the ones before it.</summary>
public enum AgentMode
{
    /// <summary>Observe only (wire value <c>ReadOnly</c>).</summary>
    ReadOnly,

    /// <summary>Also load content, which changes memory but not game logic (wire value <c>ReadOnly+Load</c>).</summary>
    ReadOnlyLoad,

    /// <summary>Also mutate state, execute code, patch and hot-reload (wire value <c>Full</c>).</summary>
    Full,
}

/// <summary>Wire names of <see cref="AgentMode"/>.</summary>
public static class AgentModes
{
    /// <summary>Wire value of <see cref="AgentMode.ReadOnly"/>.</summary>
    public const string ReadOnly = "ReadOnly";

    /// <summary>Wire value of <see cref="AgentMode.ReadOnlyLoad"/>.</summary>
    public const string ReadOnlyLoad = "ReadOnly+Load";

    /// <summary>Wire value of <see cref="AgentMode.Full"/>.</summary>
    public const string Full = "Full";

    /// <summary>The wire name of a mode.</summary>
    public static string ToWire(AgentMode mode) => mode switch
    {
        AgentMode.ReadOnly => ReadOnly,
        AgentMode.ReadOnlyLoad => ReadOnlyLoad,
        AgentMode.Full => Full,
        _ => throw new ArgumentOutOfRangeException(nameof(mode)),
    };

    /// <summary>Parses a wire name (case-sensitive).</summary>
    public static bool TryParse(string? text, out AgentMode mode)
    {
        switch (text)
        {
            case ReadOnly:
                mode = AgentMode.ReadOnly;
                return true;
            case ReadOnlyLoad:
                mode = AgentMode.ReadOnlyLoad;
                return true;
            case Full:
                mode = AgentMode.Full;
                return true;
            default:
                mode = AgentMode.ReadOnly;
                return false;
        }
    }
}
