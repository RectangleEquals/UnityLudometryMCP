"""Logging setup.

- stderr: over the stdio transport, stdout carries the MCP messages and nothing else.
- The server log: `<profile root>\\logs\\ulm-<date>.log`, one file per day, the last `KEEP_DAYS` kept.
- Provider logs: `<target>\\logs\\<provider>.log` (installs, builds, tool output), via `provider_logger`.
- Warnings and errors are mirrored to the MCP client (`ctx.log`) while a tool call is running.
"""

import contextvars
import logging
import os
import sys
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import Literal

LOG_LEVEL_ENV = "ULM_LOG_LEVEL"
DEFAULT_LEVEL = logging.INFO
KEEP_DAYS = 14
_LEVELS = {"DEBUG": logging.DEBUG, "INFO": logging.INFO, "WARNING": logging.WARNING, "ERROR": logging.ERROR}
_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
_ROOT = "unity_ludometry_mcp"


class DailyFileHandler(logging.Handler):
    """Writes to `<dir>/ulm-<YYYY-MM-DD>.log`, switching files at midnight and keeping the last `keep` files."""

    def __init__(self, directory: Path, keep: int = KEEP_DAYS):
        super().__init__()
        self.directory = directory
        self.keep = keep
        self._day: date | None = None
        self._stream: logging.FileHandler | None = None

    @property
    def path(self) -> Path:
        return self.directory / f"ulm-{(self._day or date.today()).isoformat()}.log"

    def _roll(self) -> logging.FileHandler:
        today = date.today()
        if self._stream is None or self._day != today:
            if self._stream is not None:
                self._stream.close()
            self._day = today
            self.directory.mkdir(parents=True, exist_ok=True)
            self._stream = logging.FileHandler(self.path, encoding="utf-8")
            self._stream.setFormatter(self.formatter or logging.Formatter(_FORMAT))
            for old in sorted(self.directory.glob("ulm-*.log"))[: -self.keep]:
                old.unlink(missing_ok=True)
        return self._stream

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._roll().emit(record)
        except Exception:
            self.handleError(record)

    def close(self) -> None:
        if self._stream is not None:
            self._stream.close()
            self._stream = None
        super().close()


ClientLog = tuple[Literal["error", "warning"], str, str]

#: While a tool call runs, the warnings and errors it logs are collected here and sent to its client before it returns.
client_logs: contextvars.ContextVar[list[ClientLog] | None] = contextvars.ContextVar("ulm_client_logs", default=None)


class ClientLogHandler(logging.Handler):
    """Collects warnings and errors logged during a tool call, for mirroring to that call's MCP client."""

    def __init__(self) -> None:
        super().__init__(logging.WARNING)

    def emit(self, record: logging.LogRecord) -> None:
        pending = client_logs.get()
        if pending is not None:
            pending.append(("error" if record.levelno >= logging.ERROR else "warning", record.getMessage(), record.name))


def configure_logging(environ: Mapping[str, str] | None = None, log_dir: Path | None = None) -> logging.Logger:
    """Configures the package logger: level from `ULM_LOG_LEVEL` (DEBUG, INFO, WARNING or ERROR; default INFO), stderr,
    the daily server log in `log_dir` (when given), and mirroring to the MCP client. Returns the logger."""
    env = os.environ if environ is None else environ
    logger = logging.getLogger(_ROOT)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    formatter = logging.Formatter(_FORMAT)
    stderr = logging.StreamHandler(sys.stderr)
    stderr.setFormatter(formatter)
    logger.addHandler(stderr)
    logger.propagate = False

    requested = env.get(LOG_LEVEL_ENV, "").strip().upper()
    logger.setLevel(_LEVELS.get(requested, DEFAULT_LEVEL))
    if requested and requested not in _LEVELS:
        logger.warning("Ignoring %s=%r; expected one of %s.", LOG_LEVEL_ENV, requested, ", ".join(_LEVELS))

    if log_dir is not None:
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.warning("Can't write the server log to %s: %s", log_dir, e)
        else:
            daily = DailyFileHandler(log_dir)
            daily.setFormatter(formatter)
            logger.addHandler(daily)
    logger.addHandler(ClientLogHandler())
    return logger


def provider_logger(target_logs_dir: Path, provider: str) -> logging.Logger:
    """A logger that writes a provider's output to `<target logs>/<provider>.log` (and to the server log)."""
    logger = logging.getLogger(f"{_ROOT}.providers.{provider}.{abs(hash(str(target_logs_dir)))}")
    path = target_logs_dir / f"{provider}.log"
    if not any(isinstance(h, logging.FileHandler) and Path(h.baseFilename) == path for h in logger.handlers):
        target_logs_dir.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(path, encoding="utf-8")
        handler.setFormatter(logging.Formatter(_FORMAT))
        logger.addHandler(handler)
    return logger
