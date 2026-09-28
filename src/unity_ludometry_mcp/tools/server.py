"""Server status and machine information."""

from typing import Any

from fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations

from .. import __version__
from ..profiles.paths import resolve_profile_root
from ..protocol import PROTOCOL_TEXT

SERVER_NAME = "unity-ludometry-mcp"


async def server_status(ctx: Context) -> dict[str, Any]:
    """Report this server's version, the agent protocol version it speaks, where it keeps its data (the profile root),
    and what the connected MCP client supports. Read-only; safe to call at any time."""
    try:
        root = resolve_profile_root()
        profile_root: dict[str, Any] = {"path": str(root.path), "source": root.source, "exists": root.exists}
    except ValueError as e:
        profile_root = {"error": str(e)}

    params = ctx.session.client_params
    client: dict[str, Any] | None = None
    if params is not None:
        client = {
            "name": params.client_info.name,
            "version": params.client_info.version,
            "protocol_version": params.protocol_version,
            "capabilities": params.capabilities.model_dump(mode="json", by_alias=True, exclude_none=True),
        }

    return {
        "server": {"name": SERVER_NAME, "version": __version__},
        "protocol": {"version": PROTOCOL_TEXT},
        "profile_root": profile_root,
        "client": client,
    }


def register(app: FastMCP[Any]) -> None:
    app.tool(
        server_status,
        name="server_status",
        title="Server status",
        annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False),
    )
