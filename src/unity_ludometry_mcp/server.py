"""The FastMCP application: creates the server, its session state, and registers tools, resources and prompts."""

import contextlib
import importlib
import re
from collections.abc import AsyncIterator
from typing import Any

from fastmcp import Context, FastMCP
from fastmcp.exceptions import ResourceError

from . import __version__
from .package_data import rules_path
from .session import Session
from .tools import GroupVisibility, attach_session, session_of
from .tools.server import SERVER_NAME, status_data

# Every tool group module, in the order their tools are listed.
TOOL_MODULES = (
    "server",
    "setup",
    "consent",
    "providers",
    "targets",
    "projects",
    "paths",
    "limits",
    "pipeline",
    "research",
    "tasks",
    "ask",
    "knowledge",
    "code",
    "assets",
    "runtime",
    "probes",
    "live_read",
    "live_vision",
    "overlay",
    "instrument",
    "live_act",
    "mods",
)

INSTRUCTIONS = (
    "UnityLudometryMCP helps you understand a Unity game and build mods for it. Call server_status to see the server's "
    "state. Only some tool groups are listed at first: tools_enable lists more. Every result is an envelope "
    "{ok, data | error, ...}: read its notices and advisories. Questions that need the user's decision are never "
    "answered on the user's behalf: ask the user, and set user_confirmed only after an explicit yes. Whenever something "
    "has to be checked in the running game with the user, verify it interactively, one in-game prompt per step, as the "
    "guide ulm://guide/interactive-verification describes."
)

_GUIDE_TOPIC = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


def create_server(session: Session | None = None) -> FastMCP[Any]:
    """Creates the server, attaches its session state, and registers every tool group that has tools."""
    state = session or Session()

    @contextlib.asynccontextmanager
    async def lifespan(_: FastMCP[Any]) -> AsyncIterator[None]:
        try:
            yield
        finally:
            # The client disconnected: running tasks are stored as interrupted.
            await state.tasks.shutdown()

    app: FastMCP[Any] = FastMCP(SERVER_NAME, instructions=INSTRUCTIONS, version=__version__, middleware=[GroupVisibility()], lifespan=lifespan)
    attach_session(app, state)
    for name in TOOL_MODULES:
        module = importlib.import_module(f"{__package__}.tools.{name}")
        register = getattr(module, "register", None)
        if register is not None:
            register(app)
    _register_resources(app)
    return app


def _register_resources(app: FastMCP[Any]) -> None:
    @app.resource("ulm://status", name="status", title="Server status", mime_type="application/json")
    async def status(ctx: Context) -> dict[str, Any]:
        """The server's status (the same as the server_status tool)."""
        session = session_of(ctx.fastmcp)
        session.observe(ctx)
        return status_data(session)

    @app.resource("ulm://guide/{topic}", name="guide", title="Guide", mime_type="text/markdown")
    async def guide(topic: str) -> str:
        """A playbook for a common task, by topic."""
        path = rules_path("guides", f"{topic}.md")
        if not _GUIDE_TOPIC.match(topic) or not path.is_file():
            raise ResourceError(f"No guide {topic!r}.")
        return path.read_text(encoding="utf-8")
