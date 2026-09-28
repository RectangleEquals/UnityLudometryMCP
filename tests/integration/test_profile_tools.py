"""The settings, target, project and path tools, through an MCP client against the real server."""

import pathlib
from typing import Any

import pytest
from fastmcp import Client, FastMCP

from unity_ludometry_mcp.server import create_server
from unity_ludometry_mcp.session import Session
from unity_ludometry_mcp.tools import session_of


async def call(client: Client[Any], tool: str, **args: Any) -> dict[str, Any]:
    result = (await client.call_tool(tool, args)).structured_content
    assert result is not None
    return result


@pytest.fixture
def app() -> FastMCP[Any]:
    return create_server(Session())


@pytest.fixture
def game(tmp_path: pathlib.Path) -> pathlib.Path:
    path = tmp_path / "Games" / "Some Game"
    path.mkdir(parents=True)
    return path


async def test_settings_tools(app: FastMCP[Any]) -> None:
    async with Client(app) as client:
        everything = await call(client, "config_get")
        assert everything["data"]["value"]["loader_pins"]["bepinex5"]["version"]
        assert everything["data"]["saved"] is False
        changed = await call(client, "config_set", key="limits.response.max_tokens", value=8000)
        assert changed["data"] == {"key": "limits.response.max_tokens", "previous": None, "value": 8000}
        assert (await call(client, "config_get", key="limits.response.max_tokens"))["data"]["value"] == 8000
        too_big = await call(client, "config_set", key="limits.response.max_tokens", value=10**9)
        bad_limit = await call(client, "config_set", key="limits.no.such", value=1)
        output_path = await call(client, "config_set", key="paths.asset_export", value="X:/Example/out")
        unknown = await call(client, "config_get", key="nope")
    assert too_big["data"]["effective"] == 50000, "values above the hard max are clamped, and the result says so"
    assert bad_limit["error"]["code"] == "NOT_FOUND"
    assert output_path["error"]["code"] == "INVALID_ARGUMENT" and "paths_set" in output_path["error"]["message"]
    assert unknown["error"]["code"] == "NOT_FOUND"
    assert session_of(app).limit("response.max_tokens").value == 50000


async def test_targets_projects_and_the_active_pair(app: FastMCP[Any], game: pathlib.Path) -> None:
    store = session_of(app).store
    target = store.create_target(game, "Some Game")
    async with Client(app) as client:
        assert (await call(client, "target_info"))["error"]["code"] == "TARGET_NOT_OPEN"
        info = await call(client, "target_info", target=target.key)
        assert info["target"] == target.key and info["data"]["facts"]["identity.name"]["source"] == "user"
        opened = await call(client, "project_open", target=target.key, name="Faster Crafting")
        assert opened["data"]["created"] is True and opened["data"]["active"] is True
        assert store.active() == (target.key, "faster-crafting")

        # With an active pair, tools default to it and say which they used.
        fact = await call(client, "project_set_fact", name="identity.goal", value="Craft twice as fast", note="the user's words")
        assert fact["target"] == target.key and fact["project"] == "faster-crafting"
        assert fact["data"]["fact"]["source"] == "user"
        assert (await call(client, "project_set_fact", name="engine.unity_version", value="x"))["error"]["code"] == "INVALID_ARGUMENT"
        assert (await call(client, "target_set_fact", name="paths.asset_export", value="x"))["error"]["code"] == "INVALID_ARGUMENT"
        assert (await call(client, "target_set_fact", name="identity.install_path", value="x"))["error"]["code"] == "INVALID_ARGUMENT"
        limits_fact = await call(client, "target_set_fact", name="limits.response.max_tokens", value=7000)
        assert limits_fact["error"]["code"] == "INVALID_ARGUMENT" and "config_set" in limits_fact["error"]["hint"]
        info = await call(client, "project_info")
        assert info["data"]["facts"]["identity.goal"]["value"] == "Craft twice as fast"

        listed = await call(client, "target_list")
        assert listed["data"]["active"] == {"target": target.key, "project": "faster-crafting"}
        assert [p["key"] for p in listed["data"]["targets"][0]["projects"]] == ["faster-crafting"]
        assert (await call(client, "project_open", name="faster crafting"))["data"]["created"] is False

        closed = await call(client, "project_close")
        assert closed["data"] == {"closed": "faster-crafting", "active": {"target": target.key, "project": None}}
        assert (await call(client, "project_info"))["error"]["code"] == "PROJECT_NOT_OPEN"

        refused = await call(client, "project_remove", name="Faster Crafting")
        assert refused["error"]["code"] == "CONSENT_REQUIRED"
        assert refused["error"]["details"]["question"] == "Delete the project Faster Crafting from ULM's profile (its notes and knowledge)?"
        removed = await call(client, "project_remove", name="Faster Crafting", user_confirmed=True)
        assert removed["data"]["project"] == "faster-crafting"
        assert (await call(client, "project_list"))["data"] == {"projects": []}

        question = (await call(client, "target_remove", key=target.key))["error"]["details"]["question"]
        assert target.key in question and "False" in question
        assert (await call(client, "target_remove", key=target.key, user_confirmed=True))["ok"] is True
        assert (await call(client, "target_list"))["data"]["targets"] == []


async def test_paths_and_exports(app: FastMCP[Any], game: pathlib.Path, tmp_path: pathlib.Path) -> None:
    store = session_of(app).store
    target = store.create_target(game, "Some Game")
    store.set_active(target.key)
    old, new = tmp_path / "exports-old", tmp_path / "exports-new"
    async with Client(app) as client:
        paths = await call(client, "paths_get")
        assert paths["data"]["paths"]["paths.asset_export"] is None
        assert paths["data"]["paths"]["paths.artifacts"]["source"] == "default"

        inside = await call(client, "paths_set", scope="target", key="paths.asset_export", path=str(game / "out"), user_confirmed=True)
        assert inside["error"]["code"] == "INVALID_ARGUMENT"
        assert not (game / "out").exists()
        unconfirmed = await call(client, "paths_set", scope="target", key="paths.asset_export", path=str(old))
        assert unconfirmed["error"]["code"] == "CONSENT_REQUIRED" and not old.exists()
        assert "Use " + str(old) in unconfirmed["error"]["details"]["question"]
        await call(client, "paths_set", scope="target", key="paths.asset_export", path=str(old), user_confirmed=True)
        assert old.is_dir()

        # ULM exports two files there; the user edits one of them.
        for name in ("a.png", "b.png"):
            (old / name).write_bytes(name.encode())
            store.open_target(target.key).exports_ledger.record_file(old / name, f"asset {name}")
        listed = await call(client, "exports_list")
        assert listed["data"]["scope"] == "target" and listed["data"]["count"] == 2
        (old / "b.png").write_bytes(b"edited")

        moved = await call(client, "paths_set", scope="target", key="paths.asset_export", path=str(new), move_existing=True, user_confirmed=True)
        statuses = {pathlib.Path(m["from"]).name: m["status"] for m in moved["data"]["moved"]}
        assert statuses == {"a.png": "moved", "b.png": "skipped (changed or missing since export)"}
        assert (new / "a.png").is_file() and (old / "b.png").is_file()

        overlap = await call(client, "paths_set", scope="target", key="paths.decompiled_code", path=str(new / "code"), user_confirmed=True)
        assert overlap["error"]["code"] == "CONSENT_REQUIRED" and overlap["error"]["details"]["overlaps"][0]["fact"] == "paths.asset_export"
        accepted = await call(client, "paths_set", scope="target", key="paths.decompiled_code", path=str(new / "code"), allow_overlap=True, user_confirmed=True)
        assert accepted["ok"] is True

        cleaned = await call(client, "exports_clean", user_confirmed=True)
        assert {pathlib.Path(f["path"]).name: f["status"] for f in cleaned["data"]["files"]} == {"a.png": "deleted", "b.png": "kept (changed since export)"}
        assert not (new / "a.png").exists() and (old / "b.png").exists()
        no_project = await call(client, "exports_list", scope="project")
        assert no_project["error"]["code"] == "PROJECT_NOT_OPEN"
