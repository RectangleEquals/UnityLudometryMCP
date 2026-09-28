"""The tool contract: what the LLM sees of every tool. Snapshots catch accidental changes to names, descriptions,
annotations and parameters; update them deliberately with `pytest --snapshot-update`."""

from typing import Any

from fastmcp import Client
from syrupy.assertion import SnapshotAssertion

from unity_ludometry_mcp.server import create_server
from unity_ludometry_mcp.session import GROUPS
from unity_ludometry_mcp.tools import CONSENT_RULE, session_of


async def _tools() -> list[dict[str, Any]]:
    tools = await create_server().list_tools(run_middleware=False)
    return [t.to_mcp_tool().model_dump(mode="json", by_alias=True, exclude_none=True) for t in tools]


async def test_every_tool_has_a_description_and_complete_annotations() -> None:
    tools = await _tools()
    assert tools
    for tool in tools:
        assert tool["description"].strip(), tool["name"]
        annotations = tool.get("annotations", {})
        for hint in ("readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint"):
            assert isinstance(annotations.get(hint), bool), f"{tool['name']} lacks {hint}"
        assert annotations["openWorldHint"] is False, f"{tool['name']} must not claim network access"
        assert not (annotations["readOnlyHint"] and annotations["destructiveHint"]), tool["name"]


async def test_tool_names_are_unique_snake_case() -> None:
    names = [t["name"] for t in await _tools()]
    assert len(names) == len(set(names))
    for name in names:
        assert name.replace("_", "").isalnum() and name == name.lower(), name


async def test_tool_definitions_match_the_snapshot(snapshot: SnapshotAssertion) -> None:
    tools = await _tools()
    for tool in tools:
        tool.pop("_meta", None)
    assert tools == snapshot


async def test_consent_parameter_and_rule_go_together() -> None:
    for tool in await _tools():
        has_param = "user_confirmed" in tool["inputSchema"].get("properties", {})
        assert has_param == (CONSENT_RULE in tool["description"]), tool["name"]
        if tool["annotations"]["readOnlyHint"]:
            assert not has_param, f"{tool['name']} is read-only and must not ask for consent"


async def test_the_listed_tools_follow_the_group_state() -> None:
    app = create_server()
    session = session_of(app)
    by_group = {t.name: next(tag for tag in t.tags if tag.startswith("group:"))[6:] for t in await app.list_tools(run_middleware=False)}
    async with Client(app, mode="legacy") as client:
        listed = {t.name for t in await client.list_tools()}
        assert listed == {name for name, group in by_group.items() if GROUPS[group]}
        await session.groups.disable(["runtime"])
        assert {t.name for t in await client.list_tools()} == {name for name, group in by_group.items() if GROUPS[group] and group != "runtime"}
    async with Client(create_server()) as modern:
        assert {t.name for t in await modern.list_tools()} == set(by_group), "without list_changed, every tool is listed"
