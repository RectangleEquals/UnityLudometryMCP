"""The orchestrator side of the shared protocol: generated models, strict JSON, framing, envelopes and transports."""

from .errors import ProtocolException
from .version import PROTOCOL_MAJOR, PROTOCOL_MINOR, PROTOCOL_TEXT, is_compatible

__all__ = ["PROTOCOL_MAJOR", "PROTOCOL_MINOR", "PROTOCOL_TEXT", "ProtocolException", "is_compatible"]
