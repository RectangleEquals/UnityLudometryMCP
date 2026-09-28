"""Frames: a 4-byte little-endian payload length followed by the UTF-8 JSON payload.

A frame that is empty, truncated or larger than the limit raises ProtocolException (INVALID_FRAME / FRAME_TOO_LARGE);
after that the stream is out of sync and the connection must be closed.
"""

from __future__ import annotations

import asyncio
import struct

from .errors import FRAME_TOO_LARGE, INVALID_FRAME, ProtocolException

DEFAULT_MAX_FRAME_BYTES = 16 * 1024 * 1024
HEADER_BYTES = 4


async def read_frame(reader: asyncio.StreamReader, max_frame_bytes: int = DEFAULT_MAX_FRAME_BYTES) -> bytes | None:
    """Reads the next frame's payload, or returns None when the stream ends cleanly between frames."""
    try:
        header = await reader.readexactly(HEADER_BYTES)
    except asyncio.IncompleteReadError as e:
        if not e.partial:
            return None
        raise ProtocolException(INVALID_FRAME, "The stream ended in the middle of a frame.") from e
    (length,) = struct.unpack("<I", header)
    if length == 0:
        raise ProtocolException(INVALID_FRAME, "Empty frame.")
    if length > max_frame_bytes:
        raise ProtocolException(FRAME_TOO_LARGE, f"Frame of {length} bytes exceeds the limit of {max_frame_bytes} bytes.")
    try:
        return await reader.readexactly(length)
    except asyncio.IncompleteReadError as e:
        raise ProtocolException(INVALID_FRAME, "The stream ended in the middle of a frame.") from e


def encode_frame(payload: bytes, max_frame_bytes: int = DEFAULT_MAX_FRAME_BYTES) -> bytes:
    """Header + payload. Refuses empty and oversized payloads, so a peer never receives a frame it must reject."""
    if not payload:
        raise ProtocolException(INVALID_FRAME, "Empty frame.")
    if len(payload) > max_frame_bytes:
        raise ProtocolException(FRAME_TOO_LARGE, f"Frame of {len(payload)} bytes exceeds the limit of {max_frame_bytes} bytes.")
    return struct.pack("<I", len(payload)) + payload


async def write_frame(writer: asyncio.StreamWriter, payload: bytes, max_frame_bytes: int = DEFAULT_MAX_FRAME_BYTES) -> None:
    """Writes one frame and drains. Callers must serialize writes per connection."""
    writer.write(encode_frame(payload, max_frame_bytes))
    await writer.drain()
