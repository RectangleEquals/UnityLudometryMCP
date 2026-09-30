"""Facts: what ULM knows about a target or project, each with its provenance.

A fact is stored as `"<section>.<name>": {value, source, note, at}`. Sources rank `user > runtime > static > research >
default`: a lower-ranked source never overwrites a higher-ranked one, and the refusal is returned to the caller. Only the
sections of the scope are accepted; names within a section are free.
"""

import hashlib
import logging
import re
import unicodedata
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import IntEnum
from pathlib import Path
from typing import Any, Literal

log = logging.getLogger(__name__)

Scope = Literal["target", "project"]

FACT_SECTIONS: dict[Scope, frozenset[str]] = {
    "target": frozenset({"identity", "engine", "content", "code", "build", "runtime", "providers", "analysis", "paths", "limits", "ui", "input"}),
    "project": frozenset({"identity", "mod", "basis", "paths", "limits", "status"}),
}


class Source(IntEnum):
    """Where a fact came from, ranked: a higher source wins."""

    DEFAULT = 0
    RESEARCH = 1
    STATIC = 2
    RUNTIME = 3
    USER = 4

    @property
    def label(self) -> str:
        return self.name.lower()

    @classmethod
    def parse(cls, value: str) -> "Source":
        try:
            return cls[value.upper()]
        except KeyError:
            raise ValueError(f"unknown fact source {value!r}") from None


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass(frozen=True)
class Fact:
    value: Any
    source: Source
    note: str | None = None
    at: str = ""

    def to_json(self) -> dict[str, Any]:
        return {"value": self.value, "source": self.source.label, "note": self.note, "at": self.at}

    @classmethod
    def from_json(cls, data: Any) -> "Fact":
        if not isinstance(data, dict) or "value" not in data or not isinstance(data.get("source"), str):
            raise ValueError("a fact needs a value and a source")
        note = data.get("note")
        at = data.get("at", "")
        if (note is not None and not isinstance(note, str)) or not isinstance(at, str):
            raise ValueError("note and at must be strings")
        return cls(data["value"], Source.parse(data["source"]), note, at)


@dataclass(frozen=True)
class Refusal:
    """A fact write that was refused because a higher-ranked source already set it."""

    name: str
    attempted: Source
    existing: Fact
    reason: str

    def to_json(self) -> dict[str, Any]:
        return {"name": self.name, "attempted_source": self.attempted.label, "existing": self.existing.to_json(), "reason": self.reason}


class FactError(ValueError):
    """An invalid fact name or section."""


class FactSet:
    """The facts of one target or project."""

    def __init__(self, scope: Scope, facts: Mapping[str, Fact] | None = None, on_refusal: Callable[[Refusal], None] | None = None):
        self.scope = scope
        self._facts: dict[str, Fact] = dict(facts or {})
        self.on_refusal = on_refusal

    def check_name(self, name: str) -> str:
        section, _, rest = name.partition(".")
        if not rest or not section:
            raise FactError(f"A fact name is '<section>.<name>', got {name!r}.")
        if section not in FACT_SECTIONS[self.scope]:
            raise FactError(f"Unknown {self.scope} fact section {section!r} (sections: {', '.join(sorted(FACT_SECTIONS[self.scope]))}).")
        return section

    def set(self, name: str, value: Any, source: Source, note: str | None = None) -> Fact | Refusal:
        """Sets a fact unless a higher-ranked source set it; returns the new fact or the refusal."""
        self.check_name(name)
        existing = self._facts.get(name)
        if existing is not None and existing.source > source:
            refusal = Refusal(name, source, existing, f"{existing.source.label} outranks {source.label}")
            log.info("Refused %s fact %s: %s", source.label, name, refusal.reason)
            if self.on_refusal is not None:
                self.on_refusal(refusal)
            return refusal
        fact = Fact(value, source, note, _now())
        self._facts[name] = fact
        return fact

    def remove(self, name: str) -> Fact | None:
        return self._facts.pop(name, None)

    def get(self, name: str) -> Fact | None:
        return self._facts.get(name)

    def value(self, name: str, default: Any = None) -> Any:
        fact = self._facts.get(name)
        return default if fact is None else fact.value

    def section(self, section: str) -> dict[str, Fact]:
        prefix = section + "."
        return {name[len(prefix) :]: fact for name, fact in self._facts.items() if name.startswith(prefix)}

    def __iter__(self) -> Iterator[str]:
        return iter(sorted(self._facts))

    def __len__(self) -> int:
        return len(self._facts)

    def to_json(self) -> dict[str, Any]:
        return {name: self._facts[name].to_json() for name in sorted(self._facts)}

    @classmethod
    def from_json(cls, scope: Scope, data: Any, origin: str = "") -> "FactSet":
        """Loads facts, skipping damaged or out-of-scope entries one by one (with a warning)."""
        facts = cls(scope)
        if not isinstance(data, dict):
            if data is not None:
                log.warning("Ignoring damaged facts in %s: not an object.", origin)
            return facts
        for name, raw in data.items():
            try:
                facts.check_name(name)
                facts._facts[name] = Fact.from_json(raw)
            except ValueError as e:
                log.warning("Skipping damaged fact %s in %s: %s", name, origin, e)
        return facts


# --- keys ---------------------------------------------------------------------------------------------------------


def slug(name: str, fallback: str) -> str:
    """Lower-case ASCII letters, digits and single hyphens (at most 48 characters)."""
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")[:48].strip("-")
    return s or fallback


def normalize_install_path(path: str | Path) -> str:
    """The install path as it identifies a game: absolute, symlinks resolved, no trailing separator, case-folded."""
    resolved = Path(path).expanduser().resolve(strict=False)
    return str(resolved).rstrip("\\/").casefold() or str(resolved).casefold()


def target_key(install_path: str | Path, name: str) -> str:
    """`slug(name)-<first 8 hex of sha256(normalized install path)>`: stable across spellings of the same path."""
    digest = hashlib.sha256(normalize_install_path(install_path).encode("utf-8")).hexdigest()[:8]
    return f"{slug(name, 'game')}-{digest}"


def project_key(name: str) -> str:
    """`slug(name)`, unique within its target."""
    return slug(name, "project")
