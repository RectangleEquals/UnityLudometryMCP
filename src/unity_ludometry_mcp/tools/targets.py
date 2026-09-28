"""Discovering, opening and describing target games."""

from typing import Annotated, Any

from fastmcp import FastMCP
from pydantic import Field, JsonValue

from ..errors import INVALID_ARGUMENT, UlmError
from ..profiles.facts import FactError, FactSet, Refusal, Source
from ..profiles.store import TargetProfile
from . import ToolCall, register_tools, ulm_tool

FactName = Annotated[str, Field(min_length=3, description="The fact, as '<section>.<name>' (e.g. identity.company).")]
Note = Annotated[str | None, Field(description="Why, or where the value comes from.")]

# Facts that identify the profile, and fact sections with their own, checked ways of changing them.
_FIXED = {"identity.install_path"}


def check_settable(name: str) -> None:
    if name.startswith("paths."):
        raise UlmError(INVALID_ARGUMENT, f"{name} is set with paths_set, which checks the folder.", "Use paths_set.")
    if name.startswith("limits."):
        raise UlmError(
            INVALID_ARGUMENT,
            f"{name}: per-game and per-project limits aren't changeable yet (they need bound and lock checks).",
            "config_set limits.<key> sets this machine's default for every game.",
        )
    if name in _FIXED:
        raise UlmError(INVALID_ARGUMENT, f"{name} identifies the profile and can't change.", "Open the other install as its own target.")


def set_user_fact(facts: FactSet, save: Any, name: str, value: Any, note: str | None) -> dict[str, Any]:
    check_settable(name)
    try:
        result = facts.set(name, value, Source.USER, note)
    except FactError as e:
        raise UlmError(INVALID_ARGUMENT, str(e), "Check the section name.") from None
    if isinstance(result, Refusal):  # can't happen for user facts (the top rank), but kept honest
        return {"refused": result.to_json()}
    save()
    return {"name": name, "fact": result.to_json()}


def facts_json(facts: FactSet) -> dict[str, Any]:
    return facts.to_json()


def target_summary(call: ToolCall, target: TargetProfile) -> dict[str, Any]:
    store = call.session.store
    active_target, active_project = store.active()
    return {
        "key": target.key,
        "name": target.name,
        "install_path": str(target.install_path) if target.install_path else None,
        "active": target.key == active_target,
        "projects": [
            {"key": p.key, "name": p.name, "active": target.key == active_target and p.key == active_project} for p in store.list_projects(target.key)
        ],
    }


@ulm_tool(group="core", title="List targets", read_only=True, idempotent=True)
def target_list(call: ToolCall) -> dict[str, Any]:
    """The games ULM has a profile for, with their projects, and which ones are active."""
    store = call.session.store
    active_target, active_project = store.active()
    return {"targets": [target_summary(call, t) for t in store.list_targets()], "active": {"target": active_target, "project": active_project}}


@ulm_tool(group="core", title="Describe a target", read_only=True, idempotent=True, scope="target")
def target_info(call: ToolCall) -> dict[str, Any]:
    """Everything known about a target: its facts with provenance (source user > runtime > static > research >
    default), builds, analysis depth, optional providers and projects."""
    assert call.target is not None
    target = call.session.store.open_target(call.target.key)
    builds_dir = target.root / "builds"
    return {
        **target_summary(call, target),
        "facts": facts_json(target.facts),
        "builds": sorted(d.name for d in builds_dir.iterdir() if d.is_dir()) if builds_dir.is_dir() else [],
        "current_build": target.facts.value("build.current"),
        "depth": target.facts.value("analysis.depth"),
        "providers": {name: fact.value for name, fact in target.facts.section("providers").items()},
    }


@ulm_tool(group="core", title="Set a target fact", destructive=True, idempotent=True, scope="target")
def target_set_fact(call: ToolCall, name: FactName, value: Annotated[JsonValue, Field(description="The value.")], note: Note = None) -> dict[str, Any]:
    """Record something the user told you about the game, as a `user` fact (it outranks everything ULM found itself).
    Only record what the user actually said."""
    assert call.target is not None
    target = call.session.store.open_target(call.target.key)
    return set_user_fact(target.facts, target.save, name, value, note)


@ulm_tool(
    group="core",
    title="Remove a target",
    destructive=True,
    needs_confirmation=True,
    consent_question="Delete ULM's profile of {key}, with its knowledge and projects? (Delete its exported files too: {delete_exports}.)",
)
def target_remove(
    call: ToolCall,
    key: Annotated[str, Field(min_length=1, description="The target key (target_list shows them).")],
    delete_exports: Annotated[bool, Field(description="Also delete files ULM exported for it (only ones unchanged since).")] = False,
) -> dict[str, Any]:
    """Delete a target's profile: its facts, knowledge and projects. Refused while ULM's runtime or mods are still
    installed in the game. The game itself is never touched, and exported files stay unless delete_exports is set."""
    return call.session.store.remove_target(key, delete_exports)


def register(app: FastMCP[Any]) -> None:
    register_tools(app, [target_list, target_info, target_set_fact, target_remove])
