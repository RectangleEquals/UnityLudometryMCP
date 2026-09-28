"""Ledgers: the authoritative record of every change ULM makes outside the profile.

- `install.json` (target): loader and agent files, the agent config, and config changes in other files, with their
  **previous values** so an uninstall restores them exactly;
- `exports.json` (target and project): files written to user-chosen export folders;
- `deploy.json` (project): mod files placed in the game's plugins folder.

Entries are appended; `compact()` keeps only the latest state of each file (or config value). Uninstall, undeploy,
export moves and cleaning are driven only by ledgers.
"""

import hashlib
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from . import read_json, write_json_atomic

SCHEMA_VERSION = 1
Op = Literal["write", "remove", "config"]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass(frozen=True)
class LedgerEntry:
    """One recorded change. `write`/`remove` are files; `config` is one value in a config file (`key`, `previous`, `value`)."""

    op: Op
    path: str
    sha256: str | None = None
    size: int | None = None
    source_ref: str | None = None
    build_id: str | None = None
    at: str = field(default_factory=_now)
    key: str | None = None
    previous: Any = None
    value: Any = None

    @property
    def identity(self) -> tuple[str, str | None]:
        """What the entry is about: the file, or the file + config key."""
        return (self.path.casefold(), self.key if self.op == "config" else None)

    def to_json(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None or (k in ("previous", "value") and self.op == "config")}

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "LedgerEntry":
        return cls(
            op=data["op"],
            path=str(data["path"]),
            sha256=data.get("sha256"),
            size=data.get("size"),
            source_ref=data.get("source_ref"),
            build_id=data.get("build_id"),
            at=data.get("at") or _now(),
            key=data.get("key"),
            previous=data.get("previous"),
            value=data.get("value"),
        )


@dataclass(frozen=True)
class Verification:
    entry: LedgerEntry
    status: Literal["ok", "missing", "changed"]


class Ledger:
    """A ledger file. Every change is saved at once (atomically)."""

    kind = "ledger"

    def __init__(self, path: Path):
        self.path = path

    def entries(self) -> list[LedgerEntry]:
        raw = read_json(self.path)
        if raw is None:
            return []
        return [LedgerEntry.from_json(e) for e in raw.get("entries", [])]

    def _save(self, entries: Iterable[LedgerEntry]) -> None:
        write_json_atomic(self.path, {"schema_version": SCHEMA_VERSION, "kind": self.kind, "entries": [e.to_json() for e in entries]})

    def append(self, entry: LedgerEntry) -> LedgerEntry:
        self._save([*self.entries(), entry])
        return entry

    def record_file(self, path: Path, source_ref: str | None = None, build_id: str | None = None) -> LedgerEntry:
        """Records a file ULM just wrote, with its hash and size."""
        return self.append(LedgerEntry("write", str(path), sha256_file(path), path.stat().st_size, source_ref, build_id))

    def record_removal(self, path: Path, source_ref: str | None = None) -> LedgerEntry:
        return self.append(LedgerEntry("remove", str(path), source_ref=source_ref))

    def compact(self) -> list[LedgerEntry]:
        """Keeps only the latest entry per file (or config value), dropping files whose latest entry is a removal.

        A config entry keeps the **first** recorded previous value, so the original state survives repeated changes.
        """
        latest: dict[tuple[str, str | None], LedgerEntry] = {}
        first_previous: dict[tuple[str, str | None], Any] = {}
        for entry in self.entries():
            if entry.op == "config" and entry.identity not in first_previous:
                first_previous[entry.identity] = entry.previous
            latest.pop(entry.identity, None)  # keep insertion order = order of the latest change
            latest[entry.identity] = entry
        kept = []
        for identity, entry in latest.items():
            if entry.op == "remove":
                continue
            if entry.op == "config":
                entry = LedgerEntry(**{**asdict(entry), "previous": first_previous[identity]})
            kept.append(entry)
        self._save(kept)
        return kept

    def current(self) -> list[LedgerEntry]:
        """The latest state (what `compact()` would keep), without rewriting the file."""
        latest: dict[tuple[str, str | None], LedgerEntry] = {}
        for entry in self.entries():
            latest.pop(entry.identity, None)
            latest[entry.identity] = entry
        return [e for e in latest.values() if e.op != "remove"]

    def query(self, build_id: str | None = None, source_ref: str | None = None, under: Path | None = None) -> list[LedgerEntry]:
        """Current entries, optionally for one build, one source, or files under a folder."""
        prefix = str(under).rstrip("\\/").casefold() if under is not None else None
        return [
            e
            for e in self.current()
            if (build_id is None or e.build_id == build_id)
            and (source_ref is None or e.source_ref == source_ref)
            and (prefix is None or e.path.casefold().startswith(prefix + "\\") or e.path.casefold().startswith(prefix + "/"))
        ]

    @staticmethod
    def verify(entry: LedgerEntry) -> Verification:
        """Whether a recorded file is still there, unchanged."""
        path = Path(entry.path)
        if not path.is_file():
            return Verification(entry, "missing")
        if entry.sha256 is not None and sha256_file(path) != entry.sha256:
            return Verification(entry, "changed")
        return Verification(entry, "ok")


class InstallLedger(Ledger):
    kind = "install"

    def record_config(self, path: Path, key: str, previous: Any, value: Any, source_ref: str | None = None) -> LedgerEntry:
        """Records a changed config value and what it was before (so it can be restored)."""
        return self.append(LedgerEntry("config", str(path), source_ref=source_ref, key=key, previous=previous, value=value))


class ExportLedger(Ledger):
    kind = "exports"


class DeployLedger(Ledger):
    kind = "deploy"
