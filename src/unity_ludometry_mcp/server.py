"""The FastMCP application: creates the server and registers the tools of every tool group."""

import importlib
from typing import Any

from fastmcp import FastMCP

from . import __version__
from .tools.server import SERVER_NAME

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
    "state. Questions that need the user's decision are never answered on the user's behalf."
)


def create_server() -> FastMCP[Any]:
    """Creates the server and registers every tool group that has tools."""
    app: FastMCP[Any] = FastMCP(SERVER_NAME, instructions=INSTRUCTIONS, version=__version__)
    for name in TOOL_MODULES:
        module = importlib.import_module(f"{__package__}.tools.{name}")
        register = getattr(module, "register", None)
        if register is not None:
            register(app)
    return app
