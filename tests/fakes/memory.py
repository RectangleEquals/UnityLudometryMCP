"""In-memory stream pairs and a scripted protocol peer for client unit tests (no sockets)."""

from __future__ import annotations

import asyncio
from typing import Any

from unity_ludometry_mcp.protocol import envelope
from unity_ludometry_mcp.protocol.framing import encode_frame, read_frame

Streams = tuple[asyncio.StreamReader, asyncio.StreamWriter]


class _MemoryTransport(asyncio.Transport):
    def __init__(self, loop: asyncio.AbstractEventLoop, own: asyncio.StreamReaderProtocol, peer: asyncio.StreamReaderProtocol) -> None:
        super().__init__()
        self._loop, self._own, self._peer = loop, own, peer
        self._closing = False
        self.peer_transport: _MemoryTransport | None = None

    def write(self, data: bytes | bytearray | memoryview) -> None:
        if not self._closing:
            self._loop.call_soon(self._peer.data_received, bytes(data))

    def is_closing(self) -> bool:
        return self._closing

    def close(self) -> None:
        if self._closing:
            return
        self._closing = True
        self._loop.call_soon(self._peer.eof_received)
        self._loop.call_soon(self._own.connection_lost, None)
        if self.peer_transport is not None and not self.peer_transport._closing:
            self.peer_transport._closing = True
            self._loop.call_soon(self._peer.connection_lost, None)

    def abort(self) -> None:
        self.close()

    def can_write_eof(self) -> bool:
        return False

    def get_write_buffer_size(self) -> int:
        return 0


def memory_pair() -> tuple[Streams, Streams]:
    """Two connected (reader, writer) pairs: what one side writes, the other reads."""
    loop = asyncio.get_running_loop()
    reader_a, reader_b = asyncio.StreamReader(), asyncio.StreamReader()
    proto_a, proto_b = asyncio.StreamReaderProtocol(reader_a), asyncio.StreamReaderProtocol(reader_b)
    transport_a = _MemoryTransport(loop, proto_a, proto_b)
    transport_b = _MemoryTransport(loop, proto_b, proto_a)
    transport_a.peer_transport, transport_b.peer_transport = transport_b, transport_a
    proto_a.connection_made(transport_a)
    proto_b.connection_made(transport_b)
    return ((reader_a, asyncio.StreamWriter(transport_a, proto_a, reader_a, loop)),
            (reader_b, asyncio.StreamWriter(transport_b, proto_b, reader_b, loop)))


class ScriptedPeer:
    """The agent side of a memory pair, driven step by step by a test."""

    def __init__(self, streams: Streams) -> None:
        self.reader, self.writer = streams
        self.seq = 0

    async def receive(self, timeout_s: float = 5.0) -> envelope.Request:
        payload = await asyncio.wait_for(read_frame(self.reader), timeout_s)
        assert payload is not None, "the client closed the connection"
        message = envelope.parse(payload)
        assert isinstance(message, envelope.Request)
        return message

    async def respond(self, request: envelope.Request, result: Any = None, *, error: dict[str, Any] | None = None) -> None:
        if error:
            response = envelope.Response(request.id, error=error, context=request.context)
        else:
            response = envelope.Response(request.id, result, context=request.context)
        self.writer.write(encode_frame(envelope.serialize(response)))
        await self.writer.drain()

    async def expect(self, method: str, result: Any = None, *, error: dict[str, Any] | None = None) -> envelope.Request:
        request = await self.receive()
        assert request.method == method, f"expected {method}, got {request.method}"
        await self.respond(request, result, error=error)
        return request

    async def event(self, kind: str, params: dict[str, Any], *, seq: int | None = None) -> None:
        self.seq = self.seq + 1 if seq is None else seq
        self.writer.write(encode_frame(envelope.serialize(envelope.Event(kind, self.seq, params))))
        await self.writer.drain()

    def close(self) -> None:
        self.writer.close()
