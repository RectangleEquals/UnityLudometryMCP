"""The profile store: the on-disk home of targets (games) and their projects (pieces of work).

```
<profile root>/settings.json · manifest.json · providers/ · packages/ · logs/ · targets/
targets/<key>/target.json · manifest.json · builds/ · knowledge/ · ledgers/ · runtime/ · logs/ · projects/
targets/<key>/projects/<project>/project.json · manifest.json · knowledge/ · ledgers/ · artifacts/ · logs/
```

The tree is the truth: listings read the folders, and the manifests are rebuilt from the tree after every write. The
root folders are created lazily, on the first write that needs them.
"""

import logging
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..errors import INVALID_ARGUMENT, NOT_FOUND, UlmError
from . import read_json, write_json_atomic
from .facts import FactSet, Refusal, Source, normalize_install_path, project_key, target_key
from .ledgers import DeployLedger, ExportLedger, InstallLedger, Verification
from .settings import SettingsStore

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1
ROOT_DIRS = ("providers", "packages", "logs", "targets")
TARGET_DIRS = ("builds", "knowledge", "ledgers", "runtime", "logs", "projects")
PROJECT_DIRS = ("knowledge", "ledgers", "artifacts", "logs")


@dataclass
class ProjectProfile:
    key: str
    target_key: str
    root: Path
    facts: FactSet
    store: "ProfileStore" = field(repr=False)

    @property
    def name(self) -> str:
        return str(self.facts.value("identity.name", self.key))

    @property
    def deploy_ledger(self) -> DeployLedger:
        return DeployLedger(self.root / "ledgers" / "deploy.json")

    @property
    def exports_ledger(self) -> ExportLedger:
        return ExportLedger(self.root / "ledgers" / "exports.json")

    @property
    def artifacts_dir(self) -> Path:
        """`paths.artifacts` if the user relocated it, else the project's `artifacts` folder."""
        custom = self.facts.value("paths.artifacts")
        return Path(custom) if custom else self.root / "artifacts"

    def set_fact(self, name: str, value: Any, source: Source, note: str | None = None) -> Any:
        result = self.facts.set(name, value, source, note)
        if not isinstance(result, Refusal):
            self.save()
        return result

    def save(self) -> None:
        write_json_atomic(self.root / "project.json", {"schema_version": SCHEMA_VERSION, "key": self.key, "facts": self.facts.to_json()})
        self.store.rebuild_manifests(self.target_key)


@dataclass
class TargetProfile:
    key: str
    root: Path
    facts: FactSet
    store: "ProfileStore" = field(repr=False)

    @property
    def name(self) -> str:
        return str(self.facts.value("identity.name", self.key))

    @property
    def install_path(self) -> Path | None:
        value = self.facts.value("identity.install_path")
        return Path(value) if value else None

    @property
    def install_ledger(self) -> InstallLedger:
        return InstallLedger(self.root / "ledgers" / "install.json")

    @property
    def exports_ledger(self) -> ExportLedger:
        return ExportLedger(self.root / "ledgers" / "exports.json")

    @property
    def captures_dir(self) -> Path:
        """Where artifacts go when no project is open."""
        return self.root / "logs" / "captures"

    def set_fact(self, name: str, value: Any, source: Source, note: str | None = None) -> Any:
        result = self.facts.set(name, value, source, note)
        if not isinstance(result, Refusal):
            self.save()
        return result

    def save(self) -> None:
        write_json_atomic(self.root / "target.json", {"schema_version": SCHEMA_VERSION, "key": self.key, "facts": self.facts.to_json()})
        self.store.rebuild_manifests(self.key)


class ProfileStore:
    """Targets, projects, the active pair and the manifests, below one profile root."""

    def __init__(self, root: Path, on_refusal: Callable[[str, Refusal], None] | None = None):
        self.root = root
        self.settings = SettingsStore(root / "settings.json")
        self.on_refusal = on_refusal

    # --- layout -------------------------------------------------------------------------------------------------

    @property
    def targets_dir(self) -> Path:
        return self.root / "targets"

    def ensure_root(self) -> None:
        for name in ROOT_DIRS:
            (self.root / name).mkdir(parents=True, exist_ok=True)

    # --- targets ------------------------------------------------------------------------------------------------

    def _facts(self, scope: str, raw: Any, origin: str, owner: str) -> FactSet:
        facts = FactSet.from_json(scope, (raw or {}).get("facts"), origin)  # type: ignore[arg-type]
        if self.on_refusal is not None:
            callback = self.on_refusal
            facts.on_refusal = lambda refusal: callback(owner, refusal)
        return facts

    def find_target(self, install_path: str | Path) -> TargetProfile | None:
        """The target for an install path, whatever its name (keys end with the path's hash)."""
        suffix = target_key(install_path, "x").rsplit("-", 1)[1]
        normalized = normalize_install_path(install_path)
        for target in self.list_targets():
            if target.key.endswith("-" + suffix) and normalize_install_path(target.facts.value("identity.install_path", "")) == normalized:
                return target
        return None

    def create_target(self, install_path: str | Path, name: str) -> TargetProfile:
        """Creates the profile of a game install (or returns the existing one for that path)."""
        existing = self.find_target(install_path)
        if existing is not None:
            return existing
        key = target_key(install_path, name)
        root = self.targets_dir / key
        self.ensure_root()
        for sub in TARGET_DIRS:
            (root / sub).mkdir(parents=True, exist_ok=True)
        target = TargetProfile(key, root, self._facts("target", None, str(root), key), self)
        target.facts.set("identity.name", name, Source.USER)
        target.facts.set("identity.install_path", str(Path(install_path).expanduser().resolve(strict=False)), Source.USER)
        target.save()
        return target

    def open_target(self, key: str) -> TargetProfile:
        root = self.targets_dir / key
        raw = read_json(root / "target.json")
        if raw is None:
            raise UlmError(NOT_FOUND, f"No target {key!r}.", "target_list shows the known targets.", details={"target": key})
        return TargetProfile(key, root, self._facts("target", raw, str(root / "target.json"), key), self)

    def list_targets(self) -> list[TargetProfile]:
        if not self.targets_dir.is_dir():
            return []
        return [self.open_target(d.name) for d in sorted(self.targets_dir.iterdir()) if (d / "target.json").is_file()]

    def remove_target(self, key: str, delete_exports: bool = False) -> dict[str, Any]:
        """Deletes a target's profile (and its projects); refused while ULM's installs or deployments are still in the
        game. Exported files stay unless `delete_exports`: then only files still unchanged since ULM wrote them are
        deleted. The game install is never touched."""
        target = self.open_target(key)
        installed = target.install_ledger.current()
        deployed = [(p.key, len(p.deploy_ledger.current())) for p in self.list_projects(key) if p.deploy_ledger.current()]
        if installed or deployed:
            # The ledgers are the only record of what to restore in the game: they must outlive what they describe.
            raise UlmError(
                INVALID_ARGUMENT,
                f"{key} still has files ULM put into the game ({len(installed)} installed, {sum(n for _, n in deployed)} deployed).",
                "Uninstall the runtime and undeploy the mods first, so the game is restored exactly; then remove the target.",
                details={"installed": len(installed), "deployed": dict(deployed)},
            )
        report: dict[str, Any] = {"target": key, "profile_removed": str(target.root), "exports": []}
        ledgers = [target.exports_ledger, *(p.exports_ledger for p in self.list_projects(key))]
        for ledger in ledgers:
            for entry in ledger.current():
                check = ledger.verify(entry)
                if delete_exports and check.status == "ok":
                    Path(entry.path).unlink()
                    report["exports"].append({"path": entry.path, "status": "deleted"})
                else:
                    report["exports"].append({"path": entry.path, "status": "kept" if not delete_exports else check.status})
        shutil.rmtree(target.root)
        self.rebuild_manifests()
        return report

    # --- projects -----------------------------------------------------------------------------------------------

    def open_project(self, target: str, name: str, create: bool = False) -> ProjectProfile:
        self.open_target(target)
        key = project_key(name)
        root = self.targets_dir / target / "projects" / key
        raw = read_json(root / "project.json")
        if raw is None:
            if not create:
                raise UlmError(NOT_FOUND, f"No project {name!r} in {target}.", "project_list shows the projects.", details={"project": key})
            for sub in PROJECT_DIRS:
                (root / sub).mkdir(parents=True, exist_ok=True)
            project = ProjectProfile(key, target, root, self._facts("project", None, str(root), f"{target}/{key}"), self)
            project.facts.set("identity.name", name, Source.USER)
            project.save()
            return project
        return ProjectProfile(key, target, root, self._facts("project", raw, str(root / "project.json"), f"{target}/{key}"), self)

    def list_projects(self, target: str) -> list[ProjectProfile]:
        folder = self.targets_dir / target / "projects"
        if not folder.is_dir():
            return []
        return [self.open_project(target, d.name) for d in sorted(folder.iterdir()) if (d / "project.json").is_file()]

    def remove_project(self, target: str, key: str) -> dict[str, Any]:
        """Deletes a project's profile (refused while it has files deployed in the game). Files it exported are listed,
        not deleted."""
        project = self.open_project(target, key)
        deployed = project.deploy_ledger.current()
        if deployed:
            raise UlmError(
                INVALID_ARGUMENT,
                f"The project has {len(deployed)} files deployed into the game.",
                "Undeploy the mod first, so the game is restored exactly; then remove the project.",
                details={"deployed": [e.path for e in deployed]},
            )
        outside = [e.path for e in project.exports_ledger.current()]
        shutil.rmtree(project.root)
        self.rebuild_manifests(target)
        return {"target": target, "project": key, "profile_removed": str(project.root), "files_outside_kept": outside}

    # --- active pair --------------------------------------------------------------------------------------------

    def _root_manifest(self) -> dict[str, Any]:
        return read_json(self.root / "manifest.json") or {}

    def active(self) -> tuple[str | None, str | None]:
        """The active target and project, validated against the tree (dangling selections are dropped)."""
        active = self._root_manifest().get("active") or {}
        target, project = active.get("target"), active.get("project")
        if not target or not (self.targets_dir / target / "target.json").is_file():
            return None, None
        if not project or not (self.targets_dir / target / "projects" / project / "project.json").is_file():
            return target, None
        return target, project

    def set_active(self, target: str | None, project: str | None = None) -> tuple[str | None, str | None]:
        if target is not None:
            self.open_target(target)
            if project is not None:
                self.open_project(target, project)
        elif project is not None:
            raise ValueError("a project needs its target")
        self.ensure_root()
        manifest = self._root_manifest()
        manifest["active"] = {"target": target, "project": project}
        write_json_atomic(self.root / "manifest.json", manifest)
        self.rebuild_manifests()
        return self.active()

    # --- manifests ----------------------------------------------------------------------------------------------

    def rebuild_manifests(self, target: str | None = None) -> None:
        """Rebuilds the root manifest, and the manifests of one target (and its projects) when given."""
        from .manifests import project_manifest, root_manifest, target_manifest

        if target is not None and (self.targets_dir / target / "target.json").is_file():
            profile = self.open_target(target)
            projects = self.list_projects(target)
            for project in projects:
                write_json_atomic(project.root / "manifest.json", project_manifest(project))
            write_json_atomic(profile.root / "manifest.json", target_manifest(profile, projects))
        self.ensure_root()
        write_json_atomic(self.root / "manifest.json", root_manifest(self))

    def verify_exports(self, ledger: ExportLedger) -> list[Verification]:
        return [ledger.verify(e) for e in ledger.current()]
