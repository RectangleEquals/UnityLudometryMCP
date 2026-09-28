"""Protocol-level failures (codes from the protocol's error schema)."""

from __future__ import annotations

from typing import Any

HANDSHAKE_REQUIRED = "HANDSHAKE_REQUIRED"
BAD_TOKEN = "BAD_TOKEN"
PROTOCOL_MISMATCH = "PROTOCOL_MISMATCH"
INVALID_FRAME = "INVALID_FRAME"
FRAME_TOO_LARGE = "FRAME_TOO_LARGE"
METHOD_NOT_FOUND = "METHOD_NOT_FOUND"
INVALID_PARAMS = "INVALID_PARAMS"


class ProtocolException(Exception):
    """A protocol-level failure carrying an agent error code (e.g. a malformed frame, or an error response)."""

    def __init__(self, code: str, message: str, data: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data

    def to_error(self) -> dict[str, Any]:
        """The error object of a response."""
        error: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.data is not None:
            error["data"] = self.data
        return error
