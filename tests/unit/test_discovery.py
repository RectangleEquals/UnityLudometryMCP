import asyncio
import os
import pathlib
import subprocess
import sys

from unity_ludometry_mcp.protocol import json_codec
from unity_ludometry_mcp.providers import discovery


def write(directory: pathlib.Path, pid: int, process_path: str, **overrides: object) -> pathlib.Path:
    info = {"provider": "agent", "pid": pid, "processName": "ExampleGame", "processPath": process_path, "transport": "pipe",
            "pipe": f"ulm-agent-{pid}", "port": None, "token": "ab" * 32, "protocol": {"major": 0, "minor": 1}, "agentVersion": "0.1.0",
            "loader": {"name": "BepInEx", "version": "5.4.23.5"}, "unityVersion": "2021.3.45f1", "mode": "ReadOnly",
            "startedAt": "2026-09-27T10:00:00.000Z", **overrides}
    path = directory / f"agent-{pid}.json"
    path.write_bytes(json_codec.dumps(info))
    return path


def dead_pid() -> int:
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


def test_process_alive() -> None:
    assert discovery.process_alive(os.getpid())
    assert not discovery.process_alive(dead_pid())
    assert not discovery.process_alive(0)


def test_scan_returns_live_agents_and_removes_only_dead_ones(tmp_path: pathlib.Path) -> None:
    game = tmp_path / "Game"
    live = write(tmp_path, os.getpid(), str(game / "Example.exe"))
    dead = write(tmp_path, dead_pid(), str(game / "Example.exe"))
    broken = tmp_path / "agent-1.json"
    broken.write_text("{not json", encoding="utf-8")

    found = discovery.scan(tmp_path)
    assert [a.path for a in found] == [live]
    assert found[0].info.pipe == f"ulm-agent-{os.getpid()}"
    assert not dead.exists(), "a dead agent's file is removed"
    assert broken.exists(), "unreadable files are never removed (they may be mid-write)"


def test_scan_matches_the_install_directory(tmp_path: pathlib.Path) -> None:
    write(tmp_path, os.getpid(), str(tmp_path / "GameA" / "A.exe"))
    assert discovery.scan(tmp_path, install_dir=tmp_path / "GameA")
    assert not discovery.scan(tmp_path, install_dir=tmp_path / "GameB")
    assert not discovery.scan(tmp_path, install_dir=tmp_path / "Game")  # a prefix of the name, not a parent directory
    assert not discovery.scan(tmp_path / "missing")


async def test_watch_reports_changes(tmp_path: pathlib.Path) -> None:
    watcher = discovery.watch(tmp_path, interval_s=0.01)
    assert await anext(watcher) == []
    write(tmp_path, os.getpid(), str(tmp_path / "Game" / "A.exe"))
    agents = await asyncio.wait_for(anext(watcher), 2)
    assert len(agents) == 1
    await watcher.aclose()
