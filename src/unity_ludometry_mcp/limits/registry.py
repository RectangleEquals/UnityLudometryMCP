"""The limit registry (read side): shipped definitions from `rules/limits.json` and the effective value of each limit.

Precedence, lowest to highest: shipped default < machine settings < target facts < project facts < a one-shot override.
A scope's value is either the plain value or `{"value": ..., "locked": true}`. `max` is a hard ceiling: nothing exceeds it.
"""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from ..package_data import rules_path

Scope = Literal["default", "settings", "target", "project", "one_shot"]
SCOPES: tuple[Scope, ...] = ("default", "settings", "target", "project", "one_shot")
LimitType = Literal["int", "float", "enum", "set", "preset_or_list"]
AFFECTS = frozenset({"cpu", "disk", "game_fps", "tokens", "time"})


@dataclass(frozen=True)
class LimitDef:
    """One limit as shipped."""

    key: str
    type: LimitType
    default: Any
    unit: str
    cost_model: str
    affects: tuple[str, ...]
    description: str
    min: float | None = None
    max: float | None = None
    values: tuple[str, ...] = ()

    def validate(self, value: Any) -> tuple[Any, bool]:
        """Checks a value's type and allowed values, and clamps numbers into [min, max].

        Returns the value to use and whether it was clamped. Raises ValueError for a value of the wrong type or kind.
        """
        match self.type:
            case "int" | "float":
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ValueError(f"{self.key} must be a number.")
                if self.type == "int" and not float(value).is_integer():
                    raise ValueError(f"{self.key} must be a whole number.")
                number: float = value
                clamped = False
                if self.min is not None and number < self.min:
                    number, clamped = self.min, True
                if self.max is not None and number > self.max:
                    number, clamped = self.max, True
                return (int(number) if self.type == "int" else float(number)), clamped
            case "enum":
                if value not in self.values:
                    raise ValueError(f"{self.key} must be one of {', '.join(self.values)}.")
                return value, False
            case "set":
                if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                    raise ValueError(f"{self.key} must be a list of strings.")
                unknown = [v for v in value if v not in self.values]
                if unknown:
                    raise ValueError(f"{self.key}: unknown {', '.join(unknown)}; allowed: {', '.join(self.values)}.")
                return sorted(set(value), key=self.values.index), False
            case "preset_or_list":
                if isinstance(value, str) and value in self.values:
                    return value, False
                if isinstance(value, list) and value and all(isinstance(v, str) and v for v in value):
                    return list(value), False
                raise ValueError(f"{self.key} must be one of {', '.join(self.values)} or a non-empty list of names.")


@dataclass(frozen=True)
class Resolved:
    """The effective value of a limit, where it comes from, and whether a scope locked it."""

    key: str
    value: Any
    source: Scope
    locked: bool = False
    locked_at: Scope | None = None
    clamped: bool = False
    ignored: tuple[str, ...] = field(default=())

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"key": self.key, "value": self.value, "source": self.source, "locked": self.locked}
        if self.locked_at:
            out["locked_at"] = self.locked_at
        if self.clamped:
            out["clamped"] = True
        if self.ignored:
            out["ignored"] = list(self.ignored)
        return out


class LimitRegistry:
    """The shipped limit definitions, and resolution across scopes."""

    def __init__(self, definitions: Mapping[str, LimitDef]):
        self._defs = dict(definitions)

    @classmethod
    def load(cls, path: Path | None = None) -> "LimitRegistry":
        raw = json.loads((path or rules_path("limits.json")).read_text(encoding="utf-8"))
        defs: dict[str, LimitDef] = {}
        for key, spec in raw["limits"].items():
            affects = tuple(spec["affects"])
            if not set(affects) <= AFFECTS:
                raise ValueError(f"{key}: unknown 'affects' {sorted(set(affects) - AFFECTS)}")
            definition = LimitDef(
                key=key,
                type=spec["type"],
                default=spec["default"],
                unit=spec["unit"],
                cost_model=spec["cost_model"],
                affects=affects,
                description=spec["description"],
                min=spec.get("min"),
                max=spec.get("max"),
                values=tuple(spec.get("values", ())),
            )
            value, clamped = definition.validate(definition.default)
            if clamped or value != definition.default:
                raise ValueError(f"{key}: the shipped default is outside its own bounds.")
            defs[key] = definition
        return cls(defs)

    def keys(self) -> list[str]:
        return sorted(self._defs)

    def get(self, key: str) -> LimitDef:
        try:
            return self._defs[key]
        except KeyError:
            raise KeyError(f"unknown limit {key!r}") from None

    def resolve(self, key: str, scopes: Mapping[Scope, Mapping[str, Any]] | None = None) -> Resolved:
        """The effective value of `key` given the per-scope overrides (each a mapping of limit key → value).

        The highest scope with a valid value wins. A lock doesn't change precedence: it marks the limit as the user's
        explicit choice, so nothing proposes changing it (reported as `locked` / `locked_at`, the highest locking scope).
        Invalid values are ignored and reported.
        """
        definition = self.get(key)
        value: Any = definition.default
        source: Scope = "default"
        locked_at: Scope | None = None
        clamped = False
        ignored: list[str] = []
        for scope in SCOPES[1:]:
            entry = (scopes or {}).get(scope, {}).get(key)
            if entry is None:
                continue
            is_lock = isinstance(entry, dict)
            raw = entry.get("value") if is_lock else entry
            try:
                value, clamped = definition.validate(raw)
            except ValueError as e:
                ignored.append(f"{scope}: {e}")
                continue
            source = scope
            if is_lock and entry.get("locked"):
                locked_at = scope
        return Resolved(key, value, source, locked_at is not None, locked_at, clamped, tuple(ignored))

    def resolve_all(self, scopes: Mapping[Scope, Mapping[str, Any]] | None = None) -> list[Resolved]:
        return [self.resolve(key, scopes) for key in self.keys()]

    def describe(self, keys: Sequence[str] | None = None) -> list[dict[str, Any]]:
        out = []
        for key in keys or self.keys():
            d = self.get(key)
            item: dict[str, Any] = {"key": key, "type": d.type, "default": d.default, "unit": d.unit, "affects": list(d.affects)}
            if d.min is not None:
                item["min"], item["max"] = d.min, d.max
            if d.values:
                item["values"] = list(d.values)
            item["cost_model"], item["description"] = d.cost_model, d.description
            out.append(item)
        return out
