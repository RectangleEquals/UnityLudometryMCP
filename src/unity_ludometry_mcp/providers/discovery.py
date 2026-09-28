"""Provider discovery: `<profile root>/providers/agent-<pid>.json` (and later `dnspy-<pid>.json`).

A provider writes its discovery file once it listens and deletes it on shutdown. Files whose process is gone are stale:
they're ignored, and removed (only when the process is confirmed dead). The profile root is passed in.
"""

from __future__ import annotations

import asyncio
import contextlib
import ctypes
import os
import pathlib
import sys
from collections.abc import AsyncIterator
from dataclasses import dataclass

from pydantic import ValidationError

from ..protocol import json_codec
from ..protocol.errors import ProtocolException
from ..protocol.generated.models import DiscoveryFile

POLL_INTERVAL_S = 0.5


def _kernel32():  # pragma: no cover - Windows only
    from ctypes import wintypes

    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k.OpenProcess.restype = wintypes.HANDLE
    k.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    k.GetExitCodeProcess.restype = wintypes.BOOL
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    k.CloseHandle.restype = wintypes.BOOL
    return k


def process_alive(pid: int) -> bool:
    """Whether a process with this id is running."""
    if pid <= 0:
        return False
    if sys.platform == "win32":
        from ctypes import wintypes

        process_query_limited_information, still_active, error_access_denied = 0x1000, 259, 5
        kernel32 = _kernel32()
        handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
        if not handle:
            # Access denied still means the process exists.
            return ctypes.get_last_error() == error_access_denied
        try:
            code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return True
            return code.value == still_active
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def normalize(path: str | os.PathLike[str]) -> str:
    return os.path.normcase(os.path.normpath(os.path.abspath(os.fspath(path))))


def is_under(path: str, directory: str | os.PathLike[str]) -> bool:
    """Whether `path` is inside `directory` (after normalization)."""
    p, d = normalize(path), normalize(directory)
    return p == d or p.startswith(d.rstrip(os.sep) + os.sep)


@dataclass(frozen=True)
class DiscoveredAgent:
    """A live agent found in the providers directory."""

    path: pathlib.Path
    info: DiscoveryFile


def _read(path: pathlib.Path) -> DiscoveryFile | None:
    try:
        data = json_codec.loads(path.read_bytes())
        return DiscoveryFile.model_validate(data)
    except (OSError, ProtocolException, ValidationError):
        return None  # being written, or not a valid discovery file


def scan(providers_dir: str | os.PathLike[str], *, install_dir: str | os.PathLike[str] | None = None,
         remove_stale: bool = True) -> list[DiscoveredAgent]:
    """Live agents in `providers_dir`, optionally only those whose game runs from `install_dir`.

    Files of dead processes are removed when `remove_stale` (never files of live processes, never unreadable files).
    """
    directory = pathlib.Path(providers_dir)
    found: list[DiscoveredAgent] = []
    if not directory.is_dir():
        return found
    for path in sorted(directory.glob("agent-*.json")):
        info = _read(path)
        if info is None:
            continue
        if not process_alive(info.pid):
            if remove_stale:
                with contextlib.suppress(OSError):
                    path.unlink()
            continue
        if install_dir is not None and not is_under(info.process_path, install_dir):
            continue
        found.append(DiscoveredAgent(path, info))
    return found


async def watch(providers_dir: str | os.PathLike[str], *, install_dir: str | os.PathLike[str] | None = None,
                interval_s: float = POLL_INTERVAL_S) -> AsyncIterator[list[DiscoveredAgent]]:
    """Yields the live agents whenever the set changes (polling)."""
    last: tuple[tuple[str, int], ...] | None = None
    while True:
        agents = scan(providers_dir, install_dir=install_dir)
        key = tuple((str(a.path), a.info.pid) for a in agents)
        if key != last:
            last = key
            yield agents
        await asyncio.sleep(interval_s)
