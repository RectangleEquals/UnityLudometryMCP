"""User-chosen output paths and exports."""

import shutil
from pathlib import Path
from typing import Annotated, Any, Literal

from fastmcp import FastMCP
from pydantic import Field

from ..errors import CONSENT_REQUIRED, INVALID_ARGUMENT, PROJECT_NOT_OPEN, UlmError
from ..profiles.facts import Source
from ..profiles.ledgers import ExportLedger, LedgerEntry
from ..profiles.paths import EXPORT_PATHS, PATH_FACTS, PathResolver
from ..profiles.store import ProjectProfile, TargetProfile
from . import ToolCall, register_tools, ulm_tool

PathKey = Annotated[str, Field(description=f"The path: {', '.join(PATH_FACTS)}.")]
ScopeParam = Annotated[Literal["target", "project"], Field(description="Set it for the whole target, or for the project only.")]
LedgerScope = Annotated[
    Literal["target", "project"] | None, Field(description="Whose exports: the target's or the project's (default: the project's when one is open).")
]
Filter = Annotated[str | None, Field(description="Only files whose path contains this text.")]


def _profiles(call: ToolCall) -> tuple[TargetProfile, ProjectProfile | None]:
    assert call.target is not None
    store = call.session.store
    target = store.open_target(call.target.key)
    project = store.open_project(call.target.key, call.project.key) if call.project else None
    return target, project


def _ledger(call: ToolCall, scope: str | None) -> tuple[str, ExportLedger]:
    target, project = _profiles(call)
    scope = scope or ("project" if project else "target")
    if scope == "project":
        if project is None:
            raise UlmError(PROJECT_NOT_OPEN, "No project is open.", "Open a project, or use scope='target'.", ["project"])
        return scope, project.exports_ledger
    return scope, target.exports_ledger


@ulm_tool(group="core", title="Get output paths", read_only=True, idempotent=True, scope="target_or_project")
def paths_get(call: ToolCall) -> dict[str, Any]:
    """Where ULM writes for the user: each output folder, and whether it's set on the project, the target, or is a
    default inside ULM's profile. Unset folders (null) are asked for when first needed."""
    target, project = _profiles(call)
    resolver = PathResolver(call.session.store, target, project)
    return {"paths": resolver.resolve_all(), "purposes": {k: p.purpose for k, p in PATH_FACTS.items()}}


@ulm_tool(
    group="core",
    title="Set an output path",
    destructive=True,
    needs_confirmation=True,
    scope="target_or_project",
    consent_question="Use {path} for {key} on the {scope}? (Move the files already exported there: {move_existing}.)",
)
def paths_set(
    call: ToolCall,
    scope: ScopeParam,
    key: PathKey,
    path: Annotated[str, Field(min_length=1, description="The folder, exactly as the user gave it (absolute).")],
    move_existing: Annotated[bool, Field(description="Move the files ULM already exported there to the new folder.")] = False,
    allow_overlap: Annotated[bool, Field(description="The user accepted that this folder overlaps another output folder.")] = False,
) -> dict[str, Any]:
    """Set an output folder the user chose. Only ever use a folder the user named; never pick one yourself. The folder
    must be absolute, outside the game install and writable; it's created now."""
    target, project = _profiles(call)
    resolver = PathResolver(call.session.store, target, project)
    new = Path(path)
    overlaps = resolver.validate(key, new, scope)
    if overlaps and not allow_overlap:
        raise UlmError(
            CONSENT_REQUIRED,
            f"{new} overlaps other output folders.",
            "Tell the user which folders overlap; call again with allow_overlap=true only if they accept it.",
            ["allow_overlap"],
            {"overlaps": overlaps},
        )
    if move_existing and key not in EXPORT_PATHS:
        raise UlmError(INVALID_ARGUMENT, f"{key} holds no exported files to move.", "Set it without move_existing.")
    owner = project if scope == "project" else target
    assert owner is not None
    previous = owner.facts.value(key)
    new.mkdir(parents=True, exist_ok=True)
    owner.set_fact(key, str(new), Source.USER)
    moved: list[dict[str, str]] = []
    if move_existing and previous and Path(previous) != new:
        moved = _move_exports(owner.exports_ledger, Path(previous), new)
    return {"key": key, "scope": scope, "path": str(new), "previous": previous, "moved": moved, "overlaps_accepted": overlaps}


def _move_exports(ledger: ExportLedger, old: Path, new: Path) -> list[dict[str, str]]:
    """Moves the ledgered files under `old` to the same place under `new`, keeping the ledger in step."""
    moved = []
    for entry in ledger.query(under=old):
        source = Path(entry.path)
        if ledger.verify(entry).status != "ok":
            moved.append({"from": entry.path, "status": "skipped (changed or missing since export)"})
            continue
        destination = new / source.relative_to(old)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(source, destination)
        ledger.record_removal(source, entry.source_ref)
        ledger.append(LedgerEntry("write", str(destination), entry.sha256, entry.size, entry.source_ref, entry.build_id))
        moved.append({"from": entry.path, "to": str(destination), "status": "moved"})
    return moved


@ulm_tool(group="core", title="List exported files", read_only=True, idempotent=True, scope="target_or_project")
def exports_list(call: ToolCall, scope: LedgerScope = None, filter: Filter = None) -> dict[str, Any]:
    """The files ULM exported to the user's folders (from the exports ledger), and whether each is still unchanged."""
    scope_used, ledger = _ledger(call, scope)
    files = []
    for entry in ledger.current():
        if filter and filter.casefold() not in entry.path.casefold():
            continue
        files.append({**entry.to_json(), "status": ledger.verify(entry).status})
    return {"scope": scope_used, "files": files, "count": len(files), "bytes": sum(f.get("size") or 0 for f in files)}


@ulm_tool(
    group="core",
    title="Delete exported files",
    destructive=True,
    needs_confirmation=True,
    scope="target_or_project",
    consent_question="Delete the files ULM exported ({scope} exports, matching {filter})?",
)
def exports_clean(call: ToolCall, scope: LedgerScope = None, filter: Filter = None) -> dict[str, Any]:
    """Delete files ULM exported (only those listed in its exports ledger, and only if unchanged since; changed files
    are kept and reported). Nothing else in the folders is touched."""
    scope_used, ledger = _ledger(call, scope)
    report = []
    for entry in ledger.current():
        if filter and filter.casefold() not in entry.path.casefold():
            continue
        status = ledger.verify(entry).status
        if status == "ok":
            Path(entry.path).unlink()
            ledger.record_removal(Path(entry.path), entry.source_ref)
            report.append({"path": entry.path, "status": "deleted"})
        elif status == "missing":
            ledger.record_removal(Path(entry.path), entry.source_ref)
            report.append({"path": entry.path, "status": "already gone"})
        else:
            report.append({"path": entry.path, "status": "kept (changed since export)"})
    ledger.compact()
    return {"scope": scope_used, "files": report}


def register(app: FastMCP[Any]) -> None:
    register_tools(app, [paths_get, paths_set, exports_list, exports_clean])
