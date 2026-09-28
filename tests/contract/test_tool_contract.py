"""The tool contract: what the LLM sees of every tool. Snapshots catch accidental changes to names, descriptions,
annotations and parameters; update them deliberately with `pytest --snapshot-update`."""

from typing import Any

import pytest
from syrupy.assertion import SnapshotAssertion

from unity_ludometry_mcp.server import create_server


async def _tools() -> list[dict[str, Any]]:
    tools = await create_server().list_tools()
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


@pytest.mark.parametrize("name", ["server_status"])
async def test_read_only_tools_take_no_consent_parameter(name: str) -> None:
    tool = next(t for t in await _tools() if t["name"] == name)
    assert "user_confirmed" not in tool["inputSchema"].get("properties", {})
