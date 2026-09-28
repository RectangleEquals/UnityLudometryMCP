"""Hand-written foundations of the generated protocol models."""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

JsonValue = Any
"""Any JSON value (unions, encoded live values, untyped fields)."""

AgentMode = Literal["ReadOnly", "ReadOnly+Load", "Full"]
"""What the agent may do. Each mode includes the ones before it."""

AGENT_MODES: tuple[AgentMode, ...] = ("ReadOnly", "ReadOnly+Load", "Full")

_INT64_MIN, _INT64_MAX = -(2**63), 2**63 - 1


def _integral(value: Any) -> Any:
    """Accepts JSON integers, and numbers written with a fraction or exponent that are integral (e.g. `5.0`, `5e0`),
    within the 64-bit range, the same rule as the C# package. Booleans and strings are left for strict validation to reject."""
    if isinstance(value, bool):
        return value
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, int) and not _INT64_MIN <= value <= _INT64_MAX:
        raise ValueError("integer outside the 64-bit range")
    return value


Int = Annotated[int, BeforeValidator(_integral)]
"""A protocol integer (64-bit)."""


class ProtocolModel(BaseModel):
    """Base of all generated message types.

    Strict validation (no silent type coercion); unknown properties are kept, so a message from a newer peer survives a
    round-trip. Canonical form: `to_json()` writes required fields (null ones too) and only the optional fields that were
    set.
    """

    model_config = ConfigDict(extra="allow", strict=True, validate_by_name=True, validate_by_alias=True, serialize_by_alias=True)

    def to_json(self) -> dict[str, Any]:
        """The JSON object for this message (canonical form)."""
        return self.model_dump(mode="json", by_alias=True, exclude_unset=True)


class ProtocolError(ProtocolModel):
    """The error object of a failed response. Unknown codes must be treated as generic failures."""

    code: str = Field(alias="code")
    message: str = Field(alias="message")
    data: dict[str, Any] | None = Field(default=None, alias="data")


class MethodThread(enum.Enum):
    """Where a method executes in the agent."""

    ANY = "any"
    MAIN = "main"
    MIXED = "mixed"


@dataclass(frozen=True)
class MethodDescriptor:
    """A method of the protocol: execution metadata and message types."""

    name: str
    thread: MethodThread
    min_mode: AgentMode
    job: bool
    mutating: bool
    requires: tuple[str, ...]
    params: type[ProtocolModel]
    result: type[ProtocolModel]
    job_result: type[ProtocolModel] | None


@dataclass(frozen=True)
class EventDescriptor:
    """An event kind of the protocol and its payload type."""

    kind: str
    params: type[ProtocolModel]


@dataclass(frozen=True)
class FileRecordDescriptor:
    """An exchanged file type: a single-document file (empty `rec`) or one NDJSON record kind."""

    schema: str
    rec: str
    model: type[ProtocolModel]


def mode_rank(mode: AgentMode) -> int:
    """Position of a mode in ReadOnly < ReadOnly+Load < Full."""
    return AGENT_MODES.index(mode)
