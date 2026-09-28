"""The profile store (tree, manifests, active pair), ledgers, and output paths."""

import json
import pathlib
import shutil

import pytest

from unity_ludometry_mcp.errors import UlmError
from unity_ludometry_mcp.profiles.facts import Source
from unity_ludometry_mcp.profiles.ledgers import ExportLedger, InstallLedger, LedgerEntry
from unity_ludometry_mcp.profiles.paths import PathResolver
from unity_ludometry_mcp.profiles.store import PROJECT_DIRS, TARGET_DIRS, ProfileStore


@pytest.fixture
def store(tmp_path: pathlib.Path) -> ProfileStore:
    return ProfileStore(tmp_path / "profile")


@pytest.fixture
def game(tmp_path: pathlib.Path) -> pathlib.Path:
    path = tmp_path / "Games" / "Some Game"
    path.mkdir(parents=True)
    return path


def manifest(path: pathlib.Path) -> dict:
    return json.loads((path / "manifest.json").read_text(encoding="utf-8"))


# --- store ------------------------------------------------------------------------------------------------------


def test_the_root_is_created_lazily(store: ProfileStore) -> None:
    assert store.list_targets() == [] and store.active() == (None, None)
    assert not store.root.exists()


def test_targets_and_projects(store: ProfileStore, game: pathlib.Path) -> None:
    target = store.create_target(game, "Some Game")
    assert store.create_target(str(game).upper() + "\\", "Another Name").key == target.key, "the same install is the same target"
    assert all((target.root / d).is_dir() for d in TARGET_DIRS)
    assert target.facts.get("identity.install_path").source == Source.USER  # type: ignore[union-attr]
    project = store.open_project(target.key, "Faster Crafting", create=True)
    assert project.key == "faster-crafting" and all((project.root / d).is_dir() for d in PROJECT_DIRS)
    assert store.open_project(target.key, "faster crafting").root == project.root
    with pytest.raises(UlmError, match="No project"):
        store.open_project(target.key, "missing")
    with pytest.raises(UlmError, match="No target"):
        store.open_target("missing-00000000")

    root = manifest(store.root)
    assert root["targets"] == {target.key: {"name": "Some Game", "install_path": str(game.resolve()), "projects": ["faster-crafting"]}}
    assert root["schema_versions"]["manifest"] == 1
    assert manifest(target.root)["projects"] == {"faster-crafting": {"name": "Faster Crafting", "needs_review": False}}
    assert manifest(project.root)["artifacts"] == str(project.root / "artifacts")
    assert not list(store.root.rglob("*.tmp")), "writes are atomic (no temp files left)"


def test_manifests_follow_the_tree(store: ProfileStore, game: pathlib.Path, tmp_path: pathlib.Path) -> None:
    target = store.create_target(game, "Some Game")
    store.open_project(target.key, "A", create=True)
    store.open_project(target.key, "B", create=True)
    other_game = tmp_path / "Other"
    other_game.mkdir()
    other = store.create_target(other_game, "Other")
    shutil.rmtree(target.root / "projects" / "b")  # deleted by hand
    shutil.rmtree(other.root)
    target.set_fact("identity.company", "Studio", Source.USER)  # any write rebuilds
    assert manifest(store.root)["targets"][target.key]["projects"] == ["a"]
    assert list(manifest(store.root)["targets"]) == [target.key]
    assert list(manifest(target.root)["projects"]) == ["a"]


def test_the_active_pair_is_validated(store: ProfileStore, game: pathlib.Path) -> None:
    target = store.create_target(game, "Some Game")
    store.open_project(target.key, "A", create=True)
    assert store.set_active(target.key, "a") == (target.key, "a")
    with pytest.raises(ValueError):
        store.set_active(None, "a")
    shutil.rmtree(target.root / "projects" / "a")
    assert store.active() == (target.key, None), "a deleted project clears only the project"
    store.open_project(target.key, "A", create=True)
    store.set_active(target.key, "a")
    shutil.rmtree(target.root)
    assert store.active() == (None, None), "a deleted target clears both"


def test_removal_keeps_the_game_restorable(store: ProfileStore, game: pathlib.Path, tmp_path: pathlib.Path) -> None:
    target = store.create_target(game, "Some Game")
    project = store.open_project(target.key, "A", create=True)
    plugin = game / "BepInEx" / "plugins" / "a.dll"
    plugin.parent.mkdir(parents=True)
    plugin.write_bytes(b"mod")
    project.deploy_ledger.record_file(plugin, "mod a")
    with pytest.raises(UlmError, match="deployed"):
        store.remove_project(target.key, "a")
    with pytest.raises(UlmError, match="put into the game"):
        store.remove_target(target.key)
    project.deploy_ledger.record_removal(plugin)

    exported = tmp_path / "exports" / "tex.png"
    exported.parent.mkdir()
    exported.write_bytes(b"png")
    changed = tmp_path / "exports" / "mesh.obj"
    changed.write_bytes(b"obj")
    target.exports_ledger.record_file(exported, "asset 1")
    target.exports_ledger.record_file(changed, "asset 2")
    changed.write_bytes(b"edited by the user")
    report = store.remove_target(target.key, delete_exports=True)
    assert {e["path"]: e["status"] for e in report["exports"]} == {str(exported): "deleted", str(changed): "changed"}
    assert not exported.exists() and changed.exists() and plugin.exists() and game.is_dir()
    assert store.list_targets() == []


# --- ledgers ----------------------------------------------------------------------------------------------------


def test_ledgers_round_trip_compact_and_verify(tmp_path: pathlib.Path) -> None:
    ledger = InstallLedger(tmp_path / "install.json")
    config = tmp_path / "BepInEx.cfg"
    ledger.record_config(config, "Chainloader.HideManagerGameObject", False, True, "setup")
    ledger.record_config(config, "Chainloader.HideManagerGameObject", True, False, "later change")
    dll = tmp_path / "agent.dll"
    dll.write_bytes(b"v1")
    ledger.record_file(dll, "agent 0.1.0", "build-1")
    dll.write_bytes(b"v2")
    ledger.record_file(dll, "agent 0.1.1", "build-2")
    gone = tmp_path / "old.dll"
    gone.write_bytes(b"x")
    ledger.record_file(gone, "agent 0.1.0")
    ledger.record_removal(gone)

    assert len(ledger.entries()) == 6
    kept = ledger.compact()
    assert [(e.op, pathlib.Path(e.path).name) for e in kept] == [("config", "BepInEx.cfg"), ("write", "agent.dll")]
    assert kept[0].previous is False, "the original value survives repeated changes"
    assert kept[1].source_ref == "agent 0.1.1" and kept[1].build_id == "build-2"
    assert ledger.entries() == kept, "compaction is saved"
    assert [e.path for e in ledger.query(build_id="build-2")] == [str(dll)]
    assert ledger.query(source_ref="agent 0.1.0") == []
    assert ledger.verify(kept[1]).status == "ok"
    dll.write_bytes(b"tampered")
    assert ledger.verify(kept[1]).status == "changed"
    dll.unlink()
    assert ledger.verify(kept[1]).status == "missing"
    entry = LedgerEntry("config", "x", key="k", previous=None, value=1)
    assert entry.to_json()["previous"] is None, "a config change from 'unset' keeps previous=null"


def test_ledger_queries_by_folder(tmp_path: pathlib.Path) -> None:
    ledger = ExportLedger(tmp_path / "exports.json")
    for rel in ["a/one.png", "a/sub/two.png", "ab/three.png"]:
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")
        ledger.record_file(path)
    assert sorted(pathlib.Path(e.path).name for e in ledger.query(under=tmp_path / "a")) == ["one.png", "two.png"]


# --- paths ------------------------------------------------------------------------------------------------------


def test_resolution_chain_and_suggestions(store: ProfileStore, game: pathlib.Path, tmp_path: pathlib.Path) -> None:
    target = store.create_target(game, "Some Game")
    project = store.open_project(target.key, "A", create=True)
    resolver = PathResolver(store, target, project)

    with pytest.raises(UlmError) as e:
        resolver.resolve("paths.asset_export")
    assert e.value.code == "SETUP_REQUIRED"
    assert e.value.details == {"fact": "paths.asset_export", "scopes_allowed": ["target", "project"], "suggestions_from_profiles": []}

    target.set_fact("paths.asset_export", str(tmp_path / "t-assets"), Source.USER)
    assert resolver.resolve("paths.asset_export").source == "target"
    project.set_fact("paths.asset_export", str(tmp_path / "p-assets"), Source.USER)
    assert resolver.resolve("paths.asset_export").to_json() == {"key": "paths.asset_export", "path": str(tmp_path / "p-assets"), "source": "project"}
    assert resolver.resolve("paths.artifacts").path == project.root / "artifacts"
    assert PathResolver(store, target).resolve("paths.artifacts").path == target.root / "logs" / "captures"
    assert PathResolver(store, target).resolve("paths.cache").path == target.root / "builds" / "unknown" / "cache"
    with pytest.raises(UlmError) as e:
        PathResolver(store, target).resolve("paths.mod_project")
    assert e.value.code == "PROJECT_NOT_OPEN"

    other_game = tmp_path / "Other"
    other_game.mkdir()
    other = store.create_target(other_game, "Other")
    with pytest.raises(UlmError) as e:
        PathResolver(store, other).resolve("paths.asset_export")
    assert e.value.details["suggestions_from_profiles"] == [str(tmp_path / "t-assets"), str(tmp_path / "p-assets")]


def test_validation(store: ProfileStore, game: pathlib.Path, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = store.create_target(game, "Some Game")
    project = store.open_project(target.key, "A", create=True)
    resolver = PathResolver(store, target, project)

    def rejected(path: pathlib.Path | str, key: str = "paths.asset_export", scope: str = "target") -> str:
        with pytest.raises(UlmError) as e:
            resolver.validate(key, pathlib.Path(path), scope)  # type: ignore[arg-type]
        assert e.value.code in ("INVALID_ARGUMENT", "PROJECT_NOT_OPEN")
        return e.value.message

    assert "inside the game install" in rejected(game / "Exports")
    assert "inside the game install" in rejected(str(game).upper() + "\\x")
    assert "absolute" in rejected("relative\\exports")
    blocker = tmp_path / "a-file"
    blocker.write_bytes(b"")
    assert "not a folder" in rejected(blocker)
    assert "can't be set on the target" in rejected(tmp_path / "x", "paths.mod_project")
    assert "Unknown path" in rejected(tmp_path / "x", "paths.somewhere")
    monkeypatch.setattr("os.access", lambda path, mode: False)
    assert "can't be written" in rejected(tmp_path / "x")
    monkeypatch.undo()

    assert resolver.validate("paths.asset_export", tmp_path / "exports", "target") == []
    target.set_fact("paths.asset_export", str(tmp_path / "exports"), Source.USER)
    assert resolver.validate("paths.asset_export", tmp_path / "exports", "target") == [], "re-setting the same fact isn't an overlap"
    overlaps = resolver.validate("paths.mod_export", tmp_path / "exports" / "mods", "project")
    assert overlaps == [{"owner": target.key, "fact": "paths.asset_export", "path": str(tmp_path / "exports")}]
    assert not (tmp_path / "exports").exists(), "validation never creates folders"
