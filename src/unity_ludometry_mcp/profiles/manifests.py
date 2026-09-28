"""Manifests: indexes derived from the profile tree, rebuilt after every write (never edited by hand).

- root `manifest.json`: targets → projects, the active pair, schema versions;
- target `manifest.json`: builds, stores, caches, export summary, projects (with `needs_review`), ledgers;
- project `manifest.json`: deployments, exports, artifacts.
"""

from typing import TYPE_CHECKING, Any

from . import settings as settings_module
from .ledgers import SCHEMA_VERSION as LEDGER_SCHEMA

if TYPE_CHECKING:
    from .store import ProfileStore, ProjectProfile, TargetProfile

SCHEMA_VERSION = 1


def _schema_versions() -> dict[str, int]:
    from .store import SCHEMA_VERSION as FACTS_SCHEMA

    return {"manifest": SCHEMA_VERSION, "settings": settings_module.SCHEMA_VERSION, "facts": FACTS_SCHEMA, "ledgers": LEDGER_SCHEMA}


def root_manifest(store: "ProfileStore") -> dict[str, Any]:
    targets = {}
    for target in store.list_targets():
        targets[target.key] = {
            "name": target.name,
            "install_path": str(target.install_path) if target.install_path else None,
            "projects": [p.key for p in store.list_projects(target.key)],
        }
    active_target, active_project = store.active()
    return {
        "schema_versions": _schema_versions(),
        "targets": targets,
        "active": {"target": active_target, "project": active_project},
    }


def _exports_summary(entries: list[Any]) -> dict[str, int]:
    return {"files": len(entries), "bytes": sum(e.size or 0 for e in entries)}


def target_manifest(target: "TargetProfile", projects: list["ProjectProfile"]) -> dict[str, Any]:
    builds_dir = target.root / "builds"
    builds = sorted(d.name for d in builds_dir.iterdir() if d.is_dir()) if builds_dir.is_dir() else []
    return {
        "schema_versions": _schema_versions(),
        "key": target.key,
        "name": target.name,
        "builds": builds,
        "current_build": target.facts.value("build.current"),
        "stores": {"target.db": {"exists": (target.root / "knowledge" / "target.db").is_file()}},
        "caches": [b for b in builds if (builds_dir / b / "cache").is_dir()],
        "exports": _exports_summary(target.exports_ledger.current()),
        "projects": {p.key: {"name": p.name, "needs_review": bool(p.facts.value("status.needs_review", False))} for p in projects},
        "ledgers": {"install": "ledgers/install.json", "exports": "ledgers/exports.json"},
    }


def project_manifest(project: "ProjectProfile") -> dict[str, Any]:
    return {
        "schema_versions": _schema_versions(),
        "key": project.key,
        "target": project.target_key,
        "name": project.name,
        "deployments": _exports_summary(project.deploy_ledger.current()),
        "exports": _exports_summary(project.exports_ledger.current()),
        "artifacts": str(project.artifacts_dir),
        "stores": {"project.db": {"exists": (project.root / "knowledge" / "project.db").is_file()}},
        "ledgers": {"deploy": "ledgers/deploy.json", "exports": "ledgers/exports.json"},
    }
