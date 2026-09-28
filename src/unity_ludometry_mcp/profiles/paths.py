"""Where ULM keeps its data (the profile root) and where it writes for the user (output paths, resolved and validated)."""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import platformdirs

from ..errors import INVALID_ARGUMENT, PROJECT_NOT_OPEN, SETUP_REQUIRED, UlmError

if TYPE_CHECKING:
    from .facts import FactSet
    from .store import ProfileStore, ProjectProfile, TargetProfile

APP_DIR_NAME = "UnityLudometryMCP"
HOME_ENV = "ULM_HOME"


@dataclass(frozen=True)
class ProfileRoot:
    """The profile root and where its location came from."""

    path: Path
    source: Literal["ULM_HOME", "default"]

    @property
    def exists(self) -> bool:
        return self.path.is_dir()


def default_profile_root() -> Path:
    """The per-user default: `%LOCALAPPDATA%\\UnityLudometryMCP` on Windows (the platform's local data directory elsewhere)."""
    return Path(platformdirs.user_data_dir(APP_DIR_NAME, appauthor=False, roaming=False))


def resolve_profile_root(environ: Mapping[str, str] | None = None) -> ProfileRoot:
    """The profile root for this run. `ULM_HOME` overrides the default for one run and is never written back.

    Raises `ValueError` if `ULM_HOME` is set but isn't an absolute path.
    """
    env = os.environ if environ is None else environ
    override = env.get(HOME_ENV, "").strip()
    if not override:
        return ProfileRoot(default_profile_root(), "default")

    path = Path(override).expanduser()
    if not path.is_absolute():
        raise ValueError(f"{HOME_ENV} must be an absolute path, got {override!r}.")
    return ProfileRoot(path, "ULM_HOME")


# --- output paths (user-chosen facts, never hardcoded) ---------------------------------------------------------

PathScope = Literal["target", "project"]


@dataclass(frozen=True)
class PathFact:
    """An output path fact: where it may be set, and whether ULM falls back to a folder inside the profile."""

    key: str
    scopes: tuple[PathScope, ...]
    optional: bool
    purpose: str


PATH_FACTS: dict[str, PathFact] = {
    p.key: p
    for p in (
        PathFact("paths.asset_export", ("target", "project"), False, "exported assets"),
        PathFact("paths.decompiled_code", ("target", "project"), False, "decompiled code"),
        PathFact("paths.mod_project", ("project",), False, "the mod's source project"),
        PathFact("paths.mod_export", ("project",), False, "exported mod packages"),
        PathFact("paths.artifacts", ("project",), True, "captures, traces, test logs and spilled results"),
        PathFact("paths.cache", ("target",), True, "provider caches"),
    )
}

# Output paths whose files are recorded in an exports ledger (and so can be moved or cleaned).
EXPORT_PATHS = frozenset({"paths.asset_export", "paths.decompiled_code", "paths.mod_export"})


@dataclass(frozen=True)
class ResolvedPath:
    key: str
    path: Path
    source: Literal["project", "target", "default"]

    def to_json(self) -> dict[str, str]:
        return {"key": self.key, "path": str(self.path), "source": self.source}


def is_within(path: Path, folder: Path) -> bool:
    """Whether `path` is `folder` or inside it (symlinks resolved, case-insensitive on Windows)."""
    inner = os.path.normcase(str(path.resolve(strict=False)))
    outer = os.path.normcase(str(folder.resolve(strict=False))).rstrip(os.sep)
    return inner == outer or inner.startswith(outer + os.sep)


def _nearest_existing(path: Path) -> Path | None:
    for candidate in (path, *path.parents):
        if candidate.exists():
            return candidate
    return None


def _invalid(message: str, hint: str) -> UlmError:
    return UlmError(INVALID_ARGUMENT, message, hint)


class PathResolver:
    """Resolves output paths for a target (and project): project fact → target fact → SETUP_REQUIRED.

    The only defaults are folders inside the profile (artifacts, cache). ULM never proposes a folder of its own: the
    suggestions in SETUP_REQUIRED are paths the user chose for other targets or projects.
    """

    def __init__(self, store: "ProfileStore", target: "TargetProfile", project: "ProjectProfile | None" = None):
        self.store = store
        self.target = target
        self.project = project

    def resolve(self, key: str) -> ResolvedPath:
        spec = self.spec(key)
        if self.project is not None and "project" in spec.scopes and (value := self.project.facts.value(key)):
            return ResolvedPath(key, Path(value), "project")
        if "target" in spec.scopes and (value := self.target.facts.value(key)):
            return ResolvedPath(key, Path(value), "target")
        if key == "paths.artifacts":
            return ResolvedPath(key, self.project.root / "artifacts" if self.project else self.target.captures_dir, "default")
        if key == "paths.cache":
            build = self.target.facts.value("build.current") or "unknown"
            return ResolvedPath(key, self.target.root / "builds" / str(build) / "cache", "default")
        if "target" not in spec.scopes and self.project is None:
            raise UlmError(PROJECT_NOT_OPEN, f"{key} belongs to a project.", "Open or create a project first.", ["project"])
        raise UlmError(
            SETUP_REQUIRED,
            f"No folder is set for {spec.purpose} ({key}).",
            "Ask the user where to put it (ULM never picks a folder), then call paths_set.",
            [key],
            {"fact": key, "scopes_allowed": list(spec.scopes), "suggestions_from_profiles": self.suggestions(key)},
        )

    def resolve_all(self) -> dict[str, dict[str, str] | None]:
        """Every path that applies here, resolved (`None` = not set yet)."""
        out: dict[str, dict[str, str] | None] = {}
        for key, spec in PATH_FACTS.items():
            if self.project is None and "target" not in spec.scopes and key != "paths.artifacts":
                continue
            try:
                out[key] = self.resolve(key).to_json()
            except UlmError:
                out[key] = None
        return out

    def _owners(self) -> list[tuple[str, "FactSet"]]:
        owners: list[tuple[str, FactSet]] = []
        for target in self.store.list_targets():
            owners.append((target.key, target.facts))
            owners += [(f"{target.key}/{p.key}", p.facts) for p in self.store.list_projects(target.key)]
        return owners

    def suggestions(self, key: str) -> list[str]:
        """Paths the user chose for this key elsewhere (other targets and projects), most common first."""
        seen: dict[str, int] = {}
        for _, facts in self._owners():
            value = facts.value(key)
            if value:
                seen[str(value)] = seen.get(str(value), 0) + 1
        return sorted(seen, key=lambda v: -seen[v])

    def validate(self, key: str, path: Path, scope: PathScope) -> list[dict[str, str]]:
        """Checks a proposed folder. Returns the overlaps with other output folders (they need the user's confirmation);
        raises for a relative path, a folder inside the game install, a file, or a folder that can't be written."""
        spec = self.spec(key)
        if scope not in spec.scopes:
            raise _invalid(f"{key} can't be set on the {scope}.", f"Allowed: {', '.join(spec.scopes)}.")
        if scope == "project" and self.project is None:
            raise UlmError(PROJECT_NOT_OPEN, f"{key} is set on a project, and none is open.", "Open or create a project first.", ["project"])
        if not path.is_absolute():
            raise _invalid(f"{key} must be an absolute path, got {str(path)!r}.", "Ask the user for the full path.")
        install = self.target.install_path
        if install is not None and is_within(path, install):
            raise _invalid(f"{path} is inside the game install.", "Outputs never go into the game folder; ask the user for another folder.")
        existing = _nearest_existing(path)
        if existing is not None and existing == path and not path.is_dir():
            raise _invalid(f"{path} is a file, not a folder.", "Ask the user for a folder.")
        if existing is None or not os.access(existing, os.W_OK):
            raise _invalid(f"{path} can't be written.", "Ask the user for a folder they can write to.")
        me = self.target.key if scope == "target" else f"{self.target.key}/{self.project.key if self.project else ''}"
        overlaps = []
        for owner, facts in self._owners():
            for other_key in PATH_FACTS:
                value = facts.value(other_key)
                if not value or (owner == me and other_key == key):
                    continue
                if is_within(path, Path(value)) or is_within(Path(value), path):
                    overlaps.append({"owner": owner, "fact": other_key, "path": str(value)})
        return overlaps

    @staticmethod
    def spec(key: str) -> PathFact:
        try:
            return PATH_FACTS[key]
        except KeyError:
            raise _invalid(f"Unknown path {key!r}.", f"Known: {', '.join(PATH_FACTS)}.") from None
