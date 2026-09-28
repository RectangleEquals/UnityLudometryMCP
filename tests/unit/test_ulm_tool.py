"""The @ulm_tool decorator: annotations, parameters, descriptions, consent, scope resolution and error mapping."""

import itertools
import pathlib
from typing import Any

import pytest
from fastmcp import Client, FastMCP
from fastmcp.client.elicitation import ElicitResult

from unity_ludometry_mcp.envelope import Result
from unity_ludometry_mcp.errors import NOT_FOUND, UlmError
from unity_ludometry_mcp.session import Ref, Session
from unity_ludometry_mcp.tools import CONFIRM_DESCRIPTION, CONSENT_RULE, GroupVisibility, ToolCall, attach_session, register_tools, ulm_tool


def make_app(*specs: Any, session: Session | None = None) -> tuple[FastMCP[Any], Session]:
    app: FastMCP[Any] = FastMCP("test", middleware=[GroupVisibility()])
    state = attach_session(app, session or Session())
    register_tools(app, list(specs))
    return app, state


async def tool_json(app: FastMCP[Any], name: str) -> dict[str, Any]:
    tool = next(t for t in await app.list_tools(run_middleware=False) if t.name == name)
    return tool.to_mcp_tool().model_dump(mode="json", by_alias=True, exclude_none=True)


FLAGS = [
    dict(read_only=r, destructive=d, idempotent=i, needs_confirmation=c, long_running=lr, scope=s)
    for r, d, i, c, lr, s in itertools.product([False, True], [False, True], [False, True], [False, True], [False, True], ["none", "target", "project"])
    if not (r and d) and not (c and r)
]


@pytest.mark.parametrize("flags", FLAGS, ids=lambda f: "-".join(f"{k}={v}" for k, v in f.items()))
async def test_flags_become_annotations_parameters_and_description(flags: dict[str, Any]) -> None:
    @ulm_tool(group="core", title="Do a thing", **flags)
    async def do_thing(call: ToolCall, amount: int) -> dict[str, Any]:
        """Does a thing."""
        return {"amount": amount}

    app, _ = make_app(do_thing)
    tool = await tool_json(app, "do_thing")
    annotations = tool["annotations"]
    assert annotations == {
        "title": "Do a thing",
        "readOnlyHint": flags["read_only"],
        "destructiveHint": flags["destructive"],
        "idempotentHint": flags["idempotent"],
        "openWorldHint": False,
    }
    properties = tool["inputSchema"]["properties"]
    expected = {"amount"} | ({"user_confirmed"} if flags["needs_confirmation"] else set())
    expected |= {"target"} if flags["scope"] in ("target", "project") else set()
    expected |= {"project"} if flags["scope"] == "project" else set()
    assert set(properties) == expected
    assert tool["inputSchema"]["required"] == ["amount"]
    if flags["needs_confirmation"]:
        assert properties["user_confirmed"] == {"default": False, "description": CONFIRM_DESCRIPTION, "type": "boolean"}
        assert CONSENT_RULE in tool["description"]
    else:
        assert CONSENT_RULE not in tool["description"]
    assert tool["description"].startswith("Does a thing.")
    assert ("task_wait" in tool["description"]) == flags["long_running"]


def test_invalid_declarations_are_rejected() -> None:
    with pytest.raises(ValueError, match="both"):
        ulm_tool(group="core", title="x", read_only=True, destructive=True)
    with pytest.raises(ValueError, match="never needs"):
        ulm_tool(group="core", title="x", read_only=True, needs_confirmation=True)
    with pytest.raises(ValueError, match="unknown tool group"):
        ulm_tool(group="nope", title="x")

    async def no_call(amount: int) -> None:
        """Doc."""

    async def no_doc(call: ToolCall) -> None:
        pass

    with pytest.raises(TypeError, match="call"):
        ulm_tool(group="core", title="x")(no_call)
    with pytest.raises(ValueError, match="docstring"):
        ulm_tool(group="core", title="x")(no_doc)


@ulm_tool(group="core", title="Delete the data", destructive=True, needs_confirmation=True, consent_question="Delete {what}?")
async def delete_data(call: ToolCall, what: str) -> dict[str, Any]:
    """Deletes some data."""
    return {"deleted": what, "confirmed_by": call.confirmed_by}


async def test_an_unconfirmed_call_returns_consent_required_with_a_ready_question() -> None:
    app, _ = make_app(delete_data)
    async with Client(app) as client:
        result = (await client.call_tool("delete_data", {"what": "the cache"})).structured_content
    assert result is not None
    assert result["ok"] is False
    assert result["error"]["code"] == "CONSENT_REQUIRED"
    assert result["error"]["needs"] == ["user_confirmed"]
    assert result["error"]["details"]["question"] == "Delete the cache?"
    assert result["advisories"] == [{"kind": "consent_request", "question": "Delete the cache?", "options": ["yes", "no"], "tool": "delete_data"}]


async def test_a_confirmed_call_or_a_grant_proceeds() -> None:
    app, session = make_app(delete_data)
    async with Client(app) as client:
        confirmed = (await client.call_tool("delete_data", {"what": "x", "user_confirmed": True})).structured_content
        session.consent_granted = lambda tool, args: tool == "delete_data" and args == {"what": "y"}
        granted = (await client.call_tool("delete_data", {"what": "y"})).structured_content
    assert confirmed == {"ok": True, "data": {"deleted": "x", "confirmed_by": "user_confirmed"}}
    assert granted == {"ok": True, "data": {"deleted": "y", "confirmed_by": "grant"}}


@pytest.mark.parametrize(("answer", "action", "ok"), [("yes", "accept", True), ("no", "accept", False), (None, "decline", False)])
async def test_with_elicitation_the_user_is_asked_directly(answer: str | None, action: str, ok: bool) -> None:
    asked: list[str] = []

    async def elicitation_handler(message: str, response_type: Any, params: Any, context: Any) -> Any:
        asked.append(message)
        return ElicitResult(action=action, content={"value": answer} if answer else None)

    app, _ = make_app(delete_data)
    # Handshake-era connections (like Claude Code's) let the server ask the client.
    async with Client(app, elicitation_handler=elicitation_handler, mode="legacy") as client:
        result = (await client.call_tool("delete_data", {"what": "the cache"})).structured_content
    assert asked == ["Delete the cache?"]
    assert result is not None
    if ok:
        assert result == {"ok": True, "data": {"deleted": "the cache", "confirmed_by": "elicitation"}}
    else:
        assert result["error"]["code"] == "CONSENT_REQUIRED"
        assert result["error"]["details"]["declined"] is True
        assert "advisories" not in result


@ulm_tool(group="core", title="Target thing", read_only=True, scope="project")
async def project_thing(call: ToolCall) -> dict[str, Any]:
    """Uses the project."""
    assert call.target is not None and call.project is not None
    return {"target": call.target.key, "project": call.project.key}


async def test_scope_resolution(tmp_path: pathlib.Path) -> None:
    app, session = make_app(project_thing)
    async with Client(app) as client:
        no_target = (await client.call_tool("project_thing", {})).structured_content
        session.resolve_target = lambda key: Ref(key or "game-1234abcd", tmp_path) if key != "missing" else None
        missing = (await client.call_tool("project_thing", {"target": "missing"})).structured_content
        no_project = (await client.call_tool("project_thing", {})).structured_content
        session.resolve_project = lambda target, key: Ref(key or "my-mod", tmp_path / "p")
        ok = (await client.call_tool("project_thing", {"project": "other-mod"})).structured_content
    assert no_target is not None and no_target["error"]["code"] == "TARGET_NOT_OPEN"
    assert missing is not None and "'missing'" in missing["error"]["message"]
    assert no_project is not None and no_project["error"]["code"] == "PROJECT_NOT_OPEN"
    assert ok == {"ok": True, "data": {"target": "game-1234abcd", "project": "other-mod"}}


@ulm_tool(group="core", title="Fails", read_only=True)
async def fails(call: ToolCall, how: str) -> Result:
    """Fails in some way."""
    if how == "ulm":
        raise UlmError(NOT_FOUND, "No such thing.", "Look elsewhere.", details={"name": "x"})
    if how == "crash":
        raise RuntimeError("secret internals")
    return Result(data={"fine": True}, depth="runtime-only").add_evidence("live://x", "runtime:live")


async def test_errors_become_ok_false_results() -> None:
    app, _ = make_app(fails)
    async with Client(app) as client:
        ulm = (await client.call_tool("fails", {"how": "ulm"})).structured_content
        crash = (await client.call_tool("fails", {"how": "crash"})).structured_content
        fine = (await client.call_tool("fails", {"how": "none"})).structured_content
    assert ulm == {"ok": False, "error": {"code": "NOT_FOUND", "message": "No such thing.", "hint": "Look elsewhere.", "details": {"name": "x"}}}
    assert crash is not None and crash["error"]["code"] == "INTERNAL"
    assert "secret" not in str(crash)
    assert fine == {"ok": True, "data": {"fine": True}, "evidence": [{"locator": "live://x", "source": "runtime:live"}], "depth": "runtime-only"}


@ulm_tool(group="mods", title="Mod thing", read_only=True)
async def mod_thing(call: ToolCall) -> str:
    """A tool in a group that's hidden by default."""
    return "done"


async def test_a_hidden_group_is_not_listed_and_says_how_to_enable_it() -> None:
    app, session = make_app(mod_thing)
    notifications: list[str] = []

    async def message_handler(message: Any) -> None:
        notifications.append(type(getattr(message, "root", message)).__name__)

    async with Client(app, message_handler=message_handler, mode="legacy") as client:
        assert [t.name for t in await client.list_tools()] == []
        hidden = (await client.call_tool("mod_thing", {})).structured_content
        assert await session.groups.enable(["mods"]) == ["mods"]
        assert [t.name for t in await client.list_tools()] == ["mod_thing"]
        shown = (await client.call_tool("mod_thing", {})).structured_content
    assert hidden is not None and hidden["error"]["code"] == "CAPABILITY_UNAVAILABLE"
    assert hidden["error"]["needs"] == ["tools_enable:mods"]
    assert shown == {"ok": True, "data": "done"}
    assert "ToolListChangedNotification" in notifications


async def test_without_a_back_channel_every_tool_is_listed_and_consent_is_asked_through_the_llm() -> None:
    async def elicitation_handler(message: str, response_type: Any, params: Any, context: Any) -> Any:
        raise AssertionError("a 2026-07-28 connection has no back-channel for elicitation")

    app, session = make_app(mod_thing, delete_data)
    async with Client(app, elicitation_handler=elicitation_handler) as client:
        names = sorted(t.name for t in await client.list_tools())
        consent = (await client.call_tool("delete_data", {"what": "x"})).structured_content
    assert names == ["delete_data", "mod_thing"]
    assert session.groups.mode == "all"
    assert session.client.push is False and session.client.elicitation is False
    assert consent is not None and consent["error"]["code"] == "CONSENT_REQUIRED"
    assert consent["advisories"][0]["kind"] == "consent_request"


async def test_ulm_tool_groups_all_lists_everything(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ULM_TOOL_GROUPS", "all")
    app, session = make_app(mod_thing)
    async with Client(app, mode="legacy") as client:
        assert [t.name for t in await client.list_tools()] == ["mod_thing"]
    assert session.groups.mode == "all"
