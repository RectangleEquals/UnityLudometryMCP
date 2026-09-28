"""The MCP server, driven through the FastMCP in-memory client and, end to end, over stdio."""

import os
import pathlib
import subprocess
import sys

import pytest
from fastmcp import Client
from fastmcp.client.transports import StdioTransport

from unity_ludometry_mcp import __version__
from unity_ludometry_mcp.protocol import PROTOCOL_TEXT
from unity_ludometry_mcp.server import create_server


async def test_server_status_in_memory(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ULM_HOME", str(tmp_path / "profile"))
    async with Client(create_server()) as client:
        assert client.server_info is not None
        assert client.server_info.name == "unity-ludometry-mcp"
        assert client.server_info.version == __version__
        result = await client.call_tool("server_status", {})

    status = result.structured_content
    assert status is not None
    assert status["server"] == {"name": "unity-ludometry-mcp", "version": __version__}
    assert status["protocol"] == {"version": PROTOCOL_TEXT}
    assert status["profile_root"] == {"path": str(tmp_path / "profile"), "source": "ULM_HOME", "exists": False}
    assert status["client"]["name"]
    assert isinstance(status["client"]["capabilities"], dict)
    assert not (tmp_path / "profile").exists(), "server_status must not create the profile root"


async def test_server_status_reports_a_bad_ulm_home(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ULM_HOME", "relative/profile")
    async with Client(create_server()) as client:
        result = await client.call_tool("server_status", {})
    assert result.structured_content is not None
    assert "absolute" in result.structured_content["profile_root"]["error"]


async def test_server_status_over_stdio(tmp_path: pathlib.Path) -> None:
    env = {**os.environ, "ULM_HOME": str(tmp_path), "ULM_LOG_LEVEL": "WARNING"}
    transport = StdioTransport(sys.executable, ["-m", "unity_ludometry_mcp"], env=env, cwd=str(tmp_path))
    async with Client(transport) as client:
        tools = await client.list_tools()
        result = await client.call_tool("server_status", {})
    assert [t.name for t in tools] == ["server_status"]
    assert result.structured_content is not None
    assert result.structured_content["profile_root"]["source"] == "ULM_HOME"


def test_the_command_line_prints_help_and_version() -> None:
    run = [sys.executable, "-m", "unity_ludometry_mcp"]
    help_text = subprocess.run([*run, "--help"], capture_output=True, text=True, check=True, timeout=60).stdout
    assert help_text.startswith("usage: unity-ludometry-mcp")
    assert "ULM_HOME" in help_text
    version = subprocess.run([*run, "--version"], capture_output=True, text=True, check=True, timeout=60).stdout
    assert version.strip() == f"unity-ludometry-mcp {__version__} (agent protocol {PROTOCOL_TEXT})"
