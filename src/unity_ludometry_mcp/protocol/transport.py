"""Client transports: a Windows named pipe (primary) or TCP on loopback (fallback)."""

from __future__ import annotations

import asyncio
import sys

PIPE_PREFIX = "\\\\.\\pipe\\"


async def open_pipe(name: str, *, limit: int = 2**16) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    """Connects to `\\\\.\\pipe\\<name>` (Windows, Proactor event loop)."""
    if sys.platform != "win32":
        raise OSError("Named pipes are only supported on Windows.")
    loop = asyncio.get_running_loop()
    reader = asyncio.StreamReader(limit=limit, loop=loop)
    protocol = asyncio.StreamReaderProtocol(reader, loop=loop)
    address = name if name.startswith(PIPE_PREFIX) else PIPE_PREFIX + name
    transport, _ = await loop.create_pipe_connection(lambda: protocol, address)  # type: ignore[attr-defined]
    writer = asyncio.StreamWriter(transport, protocol, reader, loop)
    return reader, writer


async def open_tcp(port: int, *, host: str = "127.0.0.1") -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    """Connects to the agent's TCP fallback (loopback only)."""
    if host not in ("127.0.0.1", "::1", "localhost"):
        raise ValueError("The agent only listens on loopback.")
    return await asyncio.open_connection(host, port)
