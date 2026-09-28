"""Logging setup. Logs go to stderr: over the stdio transport, stdout carries the MCP messages and nothing else."""

import logging
import os
import sys
from collections.abc import Mapping

LOG_LEVEL_ENV = "ULM_LOG_LEVEL"
DEFAULT_LEVEL = logging.INFO
_LEVELS = {"DEBUG": logging.DEBUG, "INFO": logging.INFO, "WARNING": logging.WARNING, "ERROR": logging.ERROR}
_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def configure_logging(environ: Mapping[str, str] | None = None) -> logging.Logger:
    """Configures the package logger from `ULM_LOG_LEVEL` (DEBUG, INFO, WARNING or ERROR; default INFO) and returns it."""
    env = os.environ if environ is None else environ
    logger = logging.getLogger("unity_ludometry_mcp")
    for handler in list(logger.handlers):
        logger.removeHandler(handler)

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(_FORMAT))
    logger.addHandler(handler)
    logger.propagate = False

    requested = env.get(LOG_LEVEL_ENV, "").strip().upper()
    logger.setLevel(_LEVELS.get(requested, DEFAULT_LEVEL))
    if requested and requested not in _LEVELS:
        logger.warning("Ignoring %s=%r; expected one of %s.", LOG_LEVEL_ENV, requested, ", ".join(_LEVELS))
    return logger
