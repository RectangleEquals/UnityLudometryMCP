"""The orchestrator's error model: codes used across tools, and the mapping from agent error codes.

Errors carry `{code, message, hint, needs?, details?}`. Provider errors are mapped, never passed through raw.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .envelope import Result, failure

SETUP_REQUIRED = "SETUP_REQUIRED"
TARGET_NOT_OPEN = "TARGET_NOT_OPEN"
PROJECT_NOT_OPEN = "PROJECT_NOT_OPEN"
STATIC_PENDING = "STATIC_PENDING"
INDEX_STALE = "INDEX_STALE"
PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
CAPABILITY_UNAVAILABLE = "CAPABILITY_UNAVAILABLE"
GAME_NOT_RUNNING = "GAME_NOT_RUNNING"
AGENT_NOT_CONNECTED = "AGENT_NOT_CONNECTED"
MODE_FORBIDDEN = "MODE_FORBIDDEN"
CONSENT_REQUIRED = "CONSENT_REQUIRED"
LIMIT_ADVISORY = "LIMIT_ADVISORY"
NOT_FOUND = "NOT_FOUND"
INVALID_ARGUMENT = "INVALID_ARGUMENT"
AMBIGUOUS = "AMBIGUOUS"
HANDLE_EXPIRED = "HANDLE_EXPIRED"
REF_EXPIRED = "REF_EXPIRED"
GAME_EXCEPTION = "GAME_EXCEPTION"
BUILD_FAILED = "BUILD_FAILED"
TEST_FAILED = "TEST_FAILED"
TIMEOUT = "TIMEOUT"
CANCELLED = "CANCELLED"
ESTOPPED = "ESTOPPED"
PROVIDER_FAILED = "PROVIDER_FAILED"
INTERNAL = "INTERNAL"

CODES = frozenset(
    {
        SETUP_REQUIRED,
        TARGET_NOT_OPEN,
        PROJECT_NOT_OPEN,
        STATIC_PENDING,
        INDEX_STALE,
        PROVIDER_UNAVAILABLE,
        CAPABILITY_UNAVAILABLE,
        GAME_NOT_RUNNING,
        AGENT_NOT_CONNECTED,
        MODE_FORBIDDEN,
        CONSENT_REQUIRED,
        LIMIT_ADVISORY,
        NOT_FOUND,
        INVALID_ARGUMENT,
        AMBIGUOUS,
        HANDLE_EXPIRED,
        REF_EXPIRED,
        GAME_EXCEPTION,
        BUILD_FAILED,
        TEST_FAILED,
        TIMEOUT,
        CANCELLED,
        ESTOPPED,
        PROVIDER_FAILED,
        INTERNAL,
    }
)


@dataclass
class UlmError(Exception):
    """An error as tools report it."""

    code: str
    message: str
    hint: str = ""
    needs: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)
    retryable: bool = False

    def __post_init__(self) -> None:
        if self.code not in CODES:
            raise ValueError(f"unknown ULM error code {self.code}")
        super().__init__(self.message)

    def to_json(self) -> dict[str, Any]:
        d: dict[str, Any] = {"code": self.code, "message": self.message, "hint": self.hint}
        if self.needs:
            d["needs"] = self.needs
        if self.details:
            d["details"] = self.details
        return d

    def to_result(self) -> Result:
        """This error as an `ok:false` tool result."""
        return failure(self.to_json())


def internal_error(exc: BaseException) -> UlmError:
    """An unexpected exception inside a tool, reported without leaking a traceback to the LLM (it goes to the log)."""
    return UlmError(
        INTERNAL,
        "The tool failed unexpectedly; the server log has the details.",
        "This is a ULM defect.",
        details={"exceptionType": type(exc).__name__},
    )


# agent code -> (ULM code, hint, retryable)
_AGENT_MAP: dict[str, tuple[str, str, bool]] = {
    "BAD_TOKEN": (PROVIDER_UNAVAILABLE, "The agent rejected the session token; re-read its discovery file (the game may have restarted).", False),
    "HANDSHAKE_REQUIRED": (PROVIDER_UNAVAILABLE, "The connection wasn't authenticated; reconnect.", False),
    "PROTOCOL_MISMATCH": (
        PROVIDER_UNAVAILABLE,
        "The agent speaks a different protocol version; install matching releases of the orchestrator and the agent.",
        False,
    ),
    "MODE_FORBIDDEN": (MODE_FORBIDDEN, "The agent's mode doesn't allow this; ask the user whether to raise it (runtime_set_mode).", False),
    "UNSUPPORTED": (CAPABILITY_UNAVAILABLE, "This game or runtime lacks the optional module this needs (see agent.capabilities).", False),
    "INDEX_STALE": (INDEX_STALE, "The code reference is from another build; check for a build change and refresh the survey.", False),
    "NOT_FOUND": (NOT_FOUND, "", False),
    "AMBIGUOUS": (AMBIGUOUS, "Several members match; pick one of the candidates.", False),
    "HANDLE_EXPIRED": (HANDLE_EXPIRED, "The object was destroyed or released; find it again.", False),
    "REF_EXPIRED": (REF_EXPIRED, "The expansion ref was evicted; resolve the stub's locator instead.", False),
    "GAME_EXCEPTION": (GAME_EXCEPTION, "The game threw; this is evidence about the game, not a tool failure. Not retried automatically.", False),
    "PATCH_FAILED": (PROVIDER_FAILED, "Applying or removing a patch failed; see details.", False),
    "EXEC_FAILED": (PROVIDER_FAILED, "Loading, binding or running the compiled code failed; see details.", False),
    "DUPLICATE_ASSEMBLY": (INTERNAL, "An assembly name was reused; generated assemblies must have unique names.", False),
    "BUSY": (PROVIDER_FAILED, "The agent is at a concurrency limit; retry later or lower the load.", True),
    "TIMEOUT": (TIMEOUT, "The agent didn't finish in time; the game may be loading or hung (check agent health).", False),
    "CANCELLED": (CANCELLED, "", False),
    "MAIN_THREAD_UNAVAILABLE": (TIMEOUT, "The game's main thread isn't responding (loading or hung).", False),
    "IO_FAILED": (PROVIDER_FAILED, "The agent couldn't write the output file; check the path.", False),
    "INTERNAL": (PROVIDER_FAILED, "The agent hit an internal error; see its log.", False),
    "INVALID_FRAME": (INTERNAL, "Protocol defect or version skew between the orchestrator and the agent.", False),
    "FRAME_TOO_LARGE": (INTERNAL, "Protocol defect or version skew between the orchestrator and the agent.", False),
    "METHOD_NOT_FOUND": (INTERNAL, "The agent doesn't implement this method (older agent?); capabilities are re-read.", False),
    "INVALID_PARAMS": (INTERNAL, "The orchestrator sent invalid params (a defect); see details.", False),
}


def map_agent_error(error: dict[str, Any], method: str = "") -> UlmError:
    """Maps an agent error object `{code, message, data?}` to a ULM error. Unknown agent codes become PROVIDER_FAILED."""
    agent_code = str(error.get("code", ""))
    code, hint, retryable = _AGENT_MAP.get(agent_code, (PROVIDER_FAILED, "The agent reported an unknown error code.", False))
    data = error.get("data") or {}
    details: dict[str, Any] = {"agentCode": agent_code, **({"method": method} if method else {}), **data}
    if isinstance(data, dict) and data.get("hint"):
        hint = f"{hint} {data['hint']}".strip()
    needs = ["consent:runtime_set_mode"] if code == MODE_FORBIDDEN else []
    return UlmError(code, str(error.get("message", "")), hint, needs, details, retryable)


AGENT_CODES_MAPPED = frozenset(_AGENT_MAP)
