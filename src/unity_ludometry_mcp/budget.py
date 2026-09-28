"""Token budgeting for tool results.

A result whose `data` is estimated above `response.max_tokens` is cut down to fit: the full `data` is written to a spill
file, and each part that was left out is replaced by a redaction stub that says what's missing, why, and where it is
(the file and a JSON pointer into it). Nothing is dropped silently: every stub in `data`, including the agent's own, is
listed in the result's `redactions`.
"""

import json
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .envelope import Result

REASON = "maxTokens"
LIMIT_KEY = "response.max_tokens"


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def _pointer(path: tuple[str | int, ...]) -> str:
    return "".join("/" + str(p).replace("~", "~0").replace("/", "~1") for p in path)


@dataclass
class Budget:
    """Estimates tokens and fits results into a budget. `chars_per_token` tunes the estimate."""

    chars_per_token: float = 4.0

    def estimate(self, value: Any) -> int:
        """Estimated tokens of a value serialized as compact JSON."""
        return int(len(_dumps(value)) / self.chars_per_token) + 1

    def fit(self, result: Result, max_tokens: int, spill_dir: Path | None) -> Result:
        """Cuts `result.data` down to `max_tokens` if needed, spilling the full data to a file in `spill_dir`, and lists
        every redaction stub in `result.redactions`."""
        if result.ok and self.estimate(result.data) > max_tokens:
            spill = self._spill(result.data, spill_dir)
            fitter = _Fitter(self, spill)
            fitted = fitter.fit(result.data, max_tokens, ())
            # The per-part estimates can add up to slightly more than the whole; then the whole becomes one stub.
            result.data = fitted if self.estimate(fitted) <= max_tokens else fitter.stub((), result.data)
            result.hit(LIMIT_KEY)
            result.limits_applied[LIMIT_KEY] = max_tokens
        known = {json.dumps(r, sort_keys=True) for r in result.redactions}
        for stub in iter_redactions(result.data):
            if json.dumps(stub, sort_keys=True) not in known:
                result.redactions.append(stub)
        return result

    def _spill(self, data: Any, spill_dir: Path | None) -> str | None:
        if spill_dir is None:
            return None
        spill_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        path = spill_dir / f"result-{stamp}-{uuid.uuid4().hex[:8]}.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        tmp.replace(path)
        return str(path)


class _Fitter:
    def __init__(self, budget: Budget, spill: str | None):
        self._budget = budget
        self._spill = spill

    def stub(self, path: tuple[str | int, ...], value: Any, **extra: Any) -> dict[str, Any]:
        size: dict[str, Any] = {"estTokens": self._budget.estimate(value)}
        if isinstance(value, (list, dict)):
            size["count"] = len(value)
        elif isinstance(value, str):
            size["length"] = len(value)
        stub: dict[str, Any] = {"reason": REASON, "path": _pointer(path), "size": size}
        if self._spill:
            stub["file"] = self._spill
            stub["ref"] = f"{self._spill}#{_pointer(path)}"
        stub.update(extra)
        return {"redacted": stub}

    def fit(self, value: Any, allowance: int, path: tuple[str | int, ...]) -> Any:
        estimate = self._budget.estimate(value)
        if estimate <= allowance:
            return value
        stub_cost = self._budget.estimate(self.stub(path, value))
        if isinstance(value, dict) and value and allowance > stub_cost:
            return self._fit_dict(value, allowance, path)
        if isinstance(value, list) and value and allowance > stub_cost:
            return self._fit_list(value, allowance, path)
        if isinstance(value, str) and allowance > stub_cost + 8:
            keep = max(0, int((allowance - stub_cost) * self._budget.chars_per_token) - 16)
            return self.stub(path, value, preview=value[:keep])
        return self.stub(path, value)

    def _fit_dict(self, value: dict[str, Any], allowance: int, path: tuple[str | int, ...]) -> dict[str, Any]:
        # Small members are kept whole; the rest share what's left, smallest first.
        sizes = {k: self._budget.estimate(v) for k, v in value.items()}
        overhead = self._budget.estimate(dict.fromkeys(value, 0))
        remaining = allowance - overhead
        out: dict[str, Any] = {}
        order = sorted(value, key=lambda k: sizes[k])
        for i, key in enumerate(order):
            share = max(0, remaining // (len(order) - i))
            out[key] = self.fit(value[key], share, (*path, key))
            remaining -= self._budget.estimate(out[key])
        return {k: out[k] for k in value}

    def _fit_list(self, value: list[Any], allowance: int, path: tuple[str | int, ...]) -> list[Any]:
        # Items are kept in order while they fit; the tail becomes one range stub.
        tail_cost = self._budget.estimate(self.stub(path, value, range=[len(value), len(value)]))
        remaining = allowance - tail_cost - 1
        out: list[Any] = []
        for i, item in enumerate(value):
            cost = self._budget.estimate(item)
            if cost <= remaining:
                out.append(item)
                remaining -= cost
            elif not out and remaining > tail_cost:
                out.append(self.fit(item, remaining - tail_cost, (*path, i)))
                remaining -= self._budget.estimate(out[-1])
            else:
                break
        if len(out) < len(value):
            rest = value[len(out) :]
            out.append(self.stub(path, rest, range=[len(out), len(value)]))
        return out


def iter_redactions(value: Any) -> Iterator[dict[str, Any]]:
    """Every redaction stub (`{"redacted": {...}}`) in a value, depth first."""
    if isinstance(value, dict):
        stub = value.get("redacted")
        if len(value) == 1 and isinstance(stub, dict) and "reason" in stub:
            yield stub
            return
        for item in value.values():
            yield from iter_redactions(item)
    elif isinstance(value, list):
        for item in value:
            yield from iter_redactions(item)
