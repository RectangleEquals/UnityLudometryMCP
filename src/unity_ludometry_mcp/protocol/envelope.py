"""Envelopes: request, response (exactly one of result / error) and event.

`context` is an optional opaque object a client attaches to a request; the agent echoes it unchanged on the response and
on every event the request produces. Unknown envelope properties are kept in `extra`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, overload

from . import json_codec
from .errors import INVALID_FRAME, ProtocolException
from .version import PROTOCOL_MAJOR

_MISSING = object()


@dataclass
class Request:
    id: str
    method: str
    params: dict[str, Any] | None = None
    timeout_ms: int | None = None
    context: dict[str, Any] | None = None
    v: int = PROTOCOL_MAJOR
    extra: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        d: dict[str, Any] = {"v": self.v, "id": self.id, "kind": "request", "method": self.method}
        if self.params is not None:
            d["params"] = self.params
        if self.timeout_ms is not None:
            d["timeoutMs"] = self.timeout_ms
        if self.context is not None:
            d["context"] = self.context
        return {**d, **self.extra}


@dataclass
class Response:
    id: str
    result: Any = _MISSING
    error: dict[str, Any] | None = None
    context: dict[str, Any] | None = None
    v: int = PROTOCOL_MAJOR
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def is_error(self) -> bool:
        return self.error is not None

    def to_json(self) -> dict[str, Any]:
        d: dict[str, Any] = {"v": self.v, "id": self.id, "kind": "response"}
        if self.error is not None:
            d["error"] = self.error
        else:
            d["result"] = None if self.result is _MISSING else self.result
        if self.context is not None:
            d["context"] = self.context
        return {**d, **self.extra}


@dataclass
class Event:
    method: str
    seq: int
    params: dict[str, Any]
    context: dict[str, Any] | None = None
    v: int = PROTOCOL_MAJOR
    extra: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        d: dict[str, Any] = {"v": self.v, "kind": "event", "method": self.method, "seq": self.seq, "params": self.params}
        if self.context is not None:
            d["context"] = self.context
        return {**d, **self.extra}


Envelope = Request | Response | Event

_KNOWN = {
    "request": {"v", "id", "kind", "method", "params", "timeoutMs", "context"},
    "response": {"v", "id", "kind", "result", "error", "context"},
    "event": {"v", "kind", "method", "seq", "params", "context"},
}


def _fail(message: str) -> ProtocolException:
    return ProtocolException(INVALID_FRAME, f"Invalid envelope: {message}")


@overload
def _int(d: dict[str, Any], key: str, required: Literal[True]) -> int: ...
@overload
def _int(d: dict[str, Any], key: str, required: Literal[False]) -> int | None: ...
def _int(d: dict[str, Any], key: str, required: bool) -> int | None:
    value = d.get(key, _MISSING)
    if value is _MISSING:
        if required:
            raise _fail(f"{key} is required.")
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or (isinstance(value, float) and not value.is_integer()):
        raise _fail(f"{key} must be an integer.")
    return int(value)


def _str(d: dict[str, Any], key: str) -> str:
    value = d.get(key, _MISSING)
    if not isinstance(value, str) or not value:
        raise _fail(f"{key} must be a non-empty string.")
    return value


@overload
def _obj(d: dict[str, Any], key: str, required: Literal[True]) -> dict[str, Any]: ...
@overload
def _obj(d: dict[str, Any], key: str, required: Literal[False]) -> dict[str, Any] | None: ...
def _obj(d: dict[str, Any], key: str, required: bool) -> dict[str, Any] | None:
    value = d.get(key, _MISSING)
    if value is _MISSING and not required:
        return None
    if not isinstance(value, dict):
        raise _fail(f"{key} must be an object.")
    return value


def parse(data: bytes | dict[str, Any]) -> Envelope:
    """Parses one frame's payload (bytes) or an already-parsed JSON object. Raises ProtocolException(INVALID_FRAME)."""
    d = json_codec.loads(data) if isinstance(data, (bytes, str)) else data
    if not isinstance(d, dict):
        raise _fail("must be an object.")
    v = _int(d, "v", True)
    kind = d.get("kind")
    if kind not in _KNOWN:
        raise _fail(f"unknown kind {kind!r}.")
    extra = {k: val for k, val in d.items() if k not in _KNOWN[kind]}
    context = _obj(d, "context", False)
    if kind == "request":
        return Request(_str(d, "id"), _str(d, "method"), _obj(d, "params", False), _int(d, "timeoutMs", False), context, v, extra)
    if kind == "response":
        has_result, has_error = "result" in d, "error" in d
        if has_result == has_error:
            raise _fail("a response needs exactly one of result and error.")
        error = None
        if has_error:
            error = _obj(d, "error", True)
            if not isinstance(error.get("code"), str) or not isinstance(error.get("message"), str):
                raise _fail("error needs a string code and message.")
        return Response(_str(d, "id"), d["result"] if has_result else _MISSING, error, context, v, extra)
    return Event(_str(d, "method"), _int(d, "seq", True), _obj(d, "params", True), context, v, extra)


def serialize(envelope: Envelope) -> bytes:
    """One frame's payload."""
    return json_codec.dumps(envelope.to_json())
