"""Server logs (daily file, provider logs, mirroring to the client) and the resources."""

import logging
import pathlib
from datetime import date
from typing import Any

import pytest
from fastmcp import Client, FastMCP

from unity_ludometry_mcp.logging_setup import DailyFileHandler, configure_logging, provider_logger
from unity_ludometry_mcp.server import create_server
from unity_ludometry_mcp.session import Session
from unity_ludometry_mcp.tools import ToolCall, attach_session, register_tools, ulm_tool


def test_the_server_log_is_written_daily_and_old_files_are_pruned(tmp_path: pathlib.Path) -> None:
    for day in range(1, 20):
        (tmp_path / f"ulm-2020-01-{day:02d}.log").write_text("old", encoding="utf-8")
    log = configure_logging({"ULM_LOG_LEVEL": "INFO"}, log_dir=tmp_path)
    log.info("server started")
    for handler in log.handlers:
        handler.flush()
    today = tmp_path / f"ulm-{date.today().isoformat()}.log"
    assert "server started" in today.read_text(encoding="utf-8")
    assert len(list(tmp_path.glob("ulm-*.log"))) == DailyFileHandler(tmp_path).keep
    configure_logging({})  # detach the file handler so the folder can be removed


def test_an_unwritable_log_folder_is_reported_not_fatal(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("", encoding="utf-8")
    log = configure_logging({}, log_dir=blocker / "logs")
    assert not any(isinstance(h, DailyFileHandler) for h in log.handlers)
    assert "Can't write the server log" in capsys.readouterr().err


def test_provider_logs_go_to_the_target(tmp_path: pathlib.Path) -> None:
    logger = provider_logger(tmp_path / "logs", "assetstudio")
    logger.setLevel(logging.INFO)
    logger.info("exported 12 assets")
    assert provider_logger(tmp_path / "logs", "assetstudio") is logger
    assert len(logger.handlers) == 1
    logger.handlers[0].flush()
    assert "exported 12 assets" in (tmp_path / "logs" / "assetstudio.log").read_text(encoding="utf-8")
    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)


@ulm_tool(group="core", title="Warns", read_only=True)
async def warns(call: ToolCall) -> str:
    """Logs a warning."""
    logging.getLogger("unity_ludometry_mcp.test").warning("disk is nearly full")
    return "done"


async def test_warnings_during_a_tool_call_are_mirrored_to_the_client() -> None:
    configure_logging({})
    app: FastMCP[Any] = FastMCP("test")
    attach_session(app, Session())
    register_tools(app, [warns])
    messages: list[str] = []

    async def log_handler(message: Any) -> None:
        messages.append(str(message.data))

    async with Client(app, log_handler=log_handler, mode="legacy") as client:
        await client.call_tool("warns", {})
    assert any("disk is nearly full" in m for m in messages)


async def test_the_status_and_guide_resources(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ULM_HOME", str(tmp_path))
    async with Client(create_server()) as client:
        uris = {str(r.uri) for r in await client.list_resources()}
        templates = {t.uri_template for t in await client.list_resource_templates()}
        status = (await client.read_resource("ulm://status"))[0]
        with pytest.raises(Exception, match="No guide"):
            await client.read_resource("ulm://guide/no-such-topic")
    assert uris == {"ulm://status"}
    assert templates == {"ulm://guide/{topic}"}
    assert '"profile_root"' in getattr(status, "text", "")
