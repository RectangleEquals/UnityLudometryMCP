"""The runtime session: installing, launching, connecting and surveying."""

from typing import Annotated, Any

from fastmcp import FastMCP
from pydantic import Field

from . import ToolCall, register_tools, ulm_tool


@ulm_tool(group="runtime", title="Runtime events", read_only=True, idempotent=True)
async def runtime_events(
    call: ToolCall,
    kinds: Annotated[list[str] | None, Field(description="Only these event kinds (e.g. rule.fired, exception).")] = None,
    since: Annotated[int, Field(ge=0, description="Only events after this seq (the last_seq of a previous call).")] = 0,
    limit: Annotated[int, Field(ge=1, le=1000, description="At most this many events.")] = 200,
) -> dict[str, Any]:
    """Recent events from the game and the other providers (oldest first), including ones summarised in notices.
    Pass the returned last_seq as `since` next time to get only newer events."""
    events = call.session.events.query(kinds, since, limit)
    return {"events": [e.to_json() for e in events], "last_seq": events[-1].seq if events else max(since, 0)}


def register(app: FastMCP[Any]) -> None:
    register_tools(app, [runtime_events])
