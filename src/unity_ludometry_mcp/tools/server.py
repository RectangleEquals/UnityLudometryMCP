"""Server status, machine information and tool groups."""

from typing import Annotated, Any

from fastmcp import FastMCP
from pydantic import Field

from .. import __version__
from ..errors import NOT_FOUND, UlmError
from ..profiles.paths import resolve_profile_root
from ..protocol import PROTOCOL_TEXT
from ..session import GROUPS, Session
from . import ToolCall, register_tools, ulm_tool

SERVER_NAME = "unity-ludometry-mcp"

Groups = Annotated[list[str], Field(min_length=1, description=f"Tool groups: {', '.join(GROUPS)}.")]


def status_data(session: Session) -> dict[str, Any]:
    """The server's status (shared by the tool and the `ulm://status` resource)."""
    try:
        root = resolve_profile_root()
        profile_root: dict[str, Any] = {"path": str(root.path), "source": root.source, "exists": root.exists}
    except ValueError as e:
        profile_root = {"error": str(e)}
    return {
        "server": {"name": SERVER_NAME, "version": __version__},
        "protocol": {"version": PROTOCOL_TEXT},
        "profile_root": profile_root,
        "client": session.client.to_json(),
        "tool_groups": {"mode": session.groups.mode, "enabled": session.groups.enabled()},
    }


@ulm_tool(group="core", title="Server status", read_only=True, idempotent=True)
async def server_status(call: ToolCall) -> dict[str, Any]:
    """Report this server's version, the agent protocol version it speaks, where it keeps its data (the profile root),
    what the connected MCP client supports, and which tool groups are enabled. Read-only; safe to call at any time."""
    return status_data(call.session)


@ulm_tool(group="core", title="Enable tool groups", read_only=True, idempotent=True)
async def tools_enable(call: ToolCall, groups: Groups) -> dict[str, Any]:
    """List the tools of more groups (code, assets, runtime, instrument, live_act, mods). Only listing changes: nothing
    in the game or on disk. Enabling live_act lists the tools; using them still needs the agent's mode and consent."""
    try:
        changed = await call.session.groups.enable(groups)
    except ValueError as e:
        raise _invalid(str(e)) from None
    return {"enabled": changed, **call.session.groups.state()}


@ulm_tool(group="core", title="Disable tool groups", read_only=True, idempotent=True)
async def tools_disable(call: ToolCall, groups: Groups) -> dict[str, Any]:
    """Stop listing the tools of some groups, to save context. The core group always stays."""
    try:
        changed = await call.session.groups.disable(groups)
    except ValueError as e:
        raise _invalid(str(e)) from None
    return {"disabled": changed, **call.session.groups.state()}


def _invalid(message: str) -> Exception:
    return UlmError(NOT_FOUND, message, "Check the group names.")


def register(app: FastMCP[Any]) -> None:
    register_tools(app, [server_status, tools_enable, tools_disable])
