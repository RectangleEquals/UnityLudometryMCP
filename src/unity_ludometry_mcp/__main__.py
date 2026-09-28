"""The `unity-ludometry-mcp` command (also `python -m unity_ludometry_mcp`): runs the MCP server over stdio."""

import argparse
import contextlib
import os
from collections.abc import Sequence

from . import __version__
from .protocol import PROTOCOL_TEXT


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="unity-ludometry-mcp",
        description=(
            "A local MCP server for understanding Unity games and building mods. It speaks MCP over stdio: register it "
            "with your MCP client (for example `claude mcp add unity-ludometry-mcp -- unity-ludometry-mcp`) rather than "
            "running it by hand."
        ),
        epilog="Environment: ULM_HOME overrides the profile root for one run; ULM_LOG_LEVEL sets the log level (logs go to stderr).",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__} (agent protocol {PROTOCOL_TEXT})")
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    _parser().parse_args(argv)

    from .logging_setup import configure_logging
    from .profiles.paths import resolve_profile_root
    from .profiles.settings import SettingsStore
    from .server import create_server

    environ = dict(os.environ)
    try:
        root = resolve_profile_root().path
    except ValueError:
        root = None  # reported by server_status
    if root is not None and not environ.get("ULM_LOG_LEVEL"):
        # ULM_LOG_LEVEL wins; otherwise the log_level machine setting applies.
        with contextlib.suppress(Exception):
            level = SettingsStore(root / "settings.json").load().log_level
            if level:
                environ["ULM_LOG_LEVEL"] = level
    log = configure_logging(environ, log_dir=root / "logs" if root else None)
    log.info("Starting unity-ludometry-mcp %s (agent protocol %s) over stdio.", __version__, PROTOCOL_TEXT)
    create_server().run(transport="stdio", show_banner=False)


if __name__ == "__main__":
    main()
