"""The protocol version implemented by this package.

The protocol is versioned independently of the orchestrator and the agent, and changes only when the wire format does.
Before 1.0 (major 0) it is pre-release: peers must match major and minor exactly. From 1.0 on, minor versions are
additive and only the major has to match.
"""

PROTOCOL_MAJOR = 0
PROTOCOL_MINOR = 1
PROTOCOL_TEXT = f"{PROTOCOL_MAJOR}.{PROTOCOL_MINOR}"


def is_compatible(major: int, minor: int) -> bool:
    """Whether a peer speaking `major.minor` is compatible with this package."""
    return major == PROTOCOL_MAJOR and (PROTOCOL_MAJOR != 0 or minor == PROTOCOL_MINOR)
