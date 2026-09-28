"""Mod projects: creating, opening and listing them."""

from typing import Annotated, Any

from fastmcp import FastMCP
from pydantic import Field, JsonValue

from ..profiles.facts import project_key
from ..profiles.store import ProjectProfile
from . import ToolCall, register_tools, ulm_tool
from .targets import FactName, Note, facts_json, set_user_fact

ProjectName = Annotated[str, Field(min_length=1, max_length=80, description="The project's name (e.g. 'Faster crafting').")]


def project_summary(call: ToolCall, project: ProjectProfile) -> dict[str, Any]:
    active_target, active_project = call.session.store.active()
    return {
        "key": project.key,
        "name": project.name,
        "target": project.target_key,
        "active": (project.target_key, project.key) == (active_target, active_project),
        "needs_review": bool(project.facts.value("status.needs_review", False)),
    }


@ulm_tool(group="core", title="Open a project", destructive=True, idempotent=True, scope="target")
def project_open(call: ToolCall, name: ProjectName) -> dict[str, Any]:
    """Open a project (a piece of work on the target, usually a mod), creating it if it's new, and make it the active
    project. Creating one only adds a folder to ULM's profile."""
    assert call.target is not None
    store = call.session.store
    created = not (store.targets_dir / call.target.key / "projects" / project_key(name) / "project.json").is_file()
    project = store.open_project(call.target.key, name, create=True)
    store.set_active(call.target.key, project.key)
    return {**project_summary(call, project), "created": created}


@ulm_tool(group="core", title="List projects", read_only=True, idempotent=True, scope="target")
def project_list(call: ToolCall) -> dict[str, Any]:
    """The projects of a target."""
    assert call.target is not None
    return {"projects": [project_summary(call, p) for p in call.session.store.list_projects(call.target.key)]}


@ulm_tool(group="core", title="Describe a project", read_only=True, idempotent=True, scope="project")
def project_info(call: ToolCall) -> dict[str, Any]:
    """A project's facts with provenance, its mod status and whether it needs review after a game update."""
    assert call.target is not None and call.project is not None
    project = call.session.store.open_project(call.target.key, call.project.key)
    return {
        **project_summary(call, project),
        "facts": facts_json(project.facts),
        "mod": {name: fact.value for name, fact in project.facts.section("mod").items()},
        "status": {name: fact.value for name, fact in project.facts.section("status").items()},
        "artifacts": str(project.artifacts_dir),
    }


@ulm_tool(group="core", title="Set a project fact", destructive=True, idempotent=True, scope="project")
def project_set_fact(call: ToolCall, name: FactName, value: Annotated[JsonValue, Field(description="The value.")], note: Note = None) -> dict[str, Any]:
    """Record something the user decided about the project (e.g. identity.goal, mod.name) as a `user` fact. Only
    record what the user actually said."""
    assert call.target is not None and call.project is not None
    project = call.session.store.open_project(call.target.key, call.project.key)
    return set_user_fact(project.facts, project.save, name, value, note)


@ulm_tool(group="core", title="Close the project", destructive=True, idempotent=True)
def project_close(call: ToolCall) -> dict[str, Any]:
    """Stop working on the active project (the target stays active). Nothing is deleted."""
    store = call.session.store
    target, project = store.active()
    store.set_active(target, None)
    return {"closed": project, "active": {"target": target, "project": None}}


@ulm_tool(
    group="core",
    title="Remove a project",
    destructive=True,
    needs_confirmation=True,
    scope="target",
    consent_question="Delete the project {name} from ULM's profile (its notes and knowledge)?",
)
def project_remove(call: ToolCall, name: ProjectName) -> dict[str, Any]:
    """Delete a project's profile (its facts, notes and knowledge). Refused while the mod is deployed in the game.
    Files it exported are listed, not deleted."""
    assert call.target is not None
    return call.session.store.remove_project(call.target.key, project_key(name))


def register(app: FastMCP[Any]) -> None:
    register_tools(app, [project_open, project_list, project_info, project_set_fact, project_close, project_remove])
