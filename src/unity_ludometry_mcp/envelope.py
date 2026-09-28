"""The result envelope every tool returns.

`{ok, data | error, evidence, redactions, advisories, notices, limits, depth, task_id}`. Empty parts are left out, so a
simple result costs few tokens; `ok` and either `data` or `error` are always present.
"""

from dataclasses import dataclass, field
from typing import Any, Literal

Depth = Literal["runtime-only", "+code", "+assets", "full"]
AdvisoryKind = Literal["capability_advisory", "limit_advisory", "setup_question", "consent_request"]


@dataclass
class Result:
    """A tool result. Tools return one (or plain data, which becomes `Result(data=...)`)."""

    data: Any = None
    ok: bool = True
    error: dict[str, Any] | None = None
    evidence: list[dict[str, Any]] = field(default_factory=list)
    redactions: list[dict[str, Any]] = field(default_factory=list)
    advisories: list[dict[str, Any]] = field(default_factory=list)
    notices: list[dict[str, Any]] = field(default_factory=list)
    limits_applied: dict[str, Any] = field(default_factory=dict)
    limits_hit: list[str] = field(default_factory=list)
    depth: Depth | None = None
    task_id: str | None = None

    def add_evidence(self, locator: str, source: str, excerpt: str | None = None) -> "Result":
        item: dict[str, Any] = {"locator": locator, "source": source}
        if excerpt is not None:
            item["excerpt"] = excerpt
        self.evidence.append(item)
        return self

    def advise(self, kind: AdvisoryKind, **fields: Any) -> "Result":
        self.advisories.append({"kind": kind, **fields})
        return self

    def hit(self, limit_key: str) -> "Result":
        if limit_key not in self.limits_hit:
            self.limits_hit.append(limit_key)
        return self

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"ok": self.ok}
        if self.ok:
            out["data"] = self.data
        else:
            out["error"] = self.error
        for name in ("evidence", "redactions", "advisories", "notices"):
            value = getattr(self, name)
            if value:
                out[name] = value
        if self.limits_applied or self.limits_hit:
            out["limits"] = {"applied": self.limits_applied, "hit": self.limits_hit}
        if self.depth is not None:
            out["depth"] = self.depth
        if self.task_id is not None:
            out["task_id"] = self.task_id
        return out


def as_result(value: Any) -> Result:
    """A tool's return value as a Result."""
    return value if isinstance(value, Result) else Result(data=value)


def failure(error: dict[str, Any], **parts: Any) -> Result:
    """An `ok:false` result carrying `{code, message, hint, needs?, details?}`."""
    return Result(ok=False, error=error, **parts)
