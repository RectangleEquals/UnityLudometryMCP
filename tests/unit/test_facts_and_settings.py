"""Facts (provenance, sections, damaged entries), keys, and machine settings."""

import json
import os
import pathlib
from typing import Any

import pytest

from unity_ludometry_mcp.errors import UlmError
from unity_ludometry_mcp.profiles.facts import FACT_SECTIONS, Fact, FactError, FactSet, Refusal, Source, project_key, slug, target_key
from unity_ludometry_mcp.profiles.settings import Settings, SettingsStore, shipped_pins

# --- facts ------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("first", list(Source))
@pytest.mark.parametrize("second", list(Source))
def test_provenance_matrix(first: Source, second: Source) -> None:
    refusals: list[Refusal] = []
    facts = FactSet("target", on_refusal=refusals.append)
    facts.set("engine.unity_version", "first", first)
    result = facts.set("engine.unity_version", "second", second)
    if second >= first:
        assert isinstance(result, Fact) and facts.value("engine.unity_version") == "second" and not refusals
    else:
        assert isinstance(result, Refusal) and facts.value("engine.unity_version") == "first"
        assert refusals == [result] and result.to_json()["attempted_source"] == second.label


def test_sections_are_checked_per_scope() -> None:
    target, project = FactSet("target"), FactSet("project")
    target.set("identity.company", "Studio", Source.RUNTIME)
    project.set("mod.name", "Faster crafting", Source.USER)
    with pytest.raises(FactError, match="Unknown target fact section 'mod'"):
        target.set("mod.name", "x", Source.USER)
    with pytest.raises(FactError, match="section"):
        project.set("engine.unity_version", "x", Source.USER)
    with pytest.raises(FactError, match=r"<section>.<name>"):
        target.set("identity", "x", Source.USER)
    assert FACT_SECTIONS["target"] >= {"paths", "limits"} and FACT_SECTIONS["project"] >= {"paths", "limits"}
    assert target.section("identity")["company"].source == Source.RUNTIME


def test_damaged_facts_are_skipped_one_by_one() -> None:
    raw: dict[str, Any] = {
        "identity.name": {"value": "Game", "source": "user", "note": None, "at": "2026-01-01T00:00:00+00:00"},
        "identity.company": {"value": "X", "source": "rumour"},
        "mod.name": {"value": "not a target section", "source": "user"},
        "engine.unity_version": "just a string",
        "engine.scripting_backend": {"value": "mono", "source": "static", "note": 5},
        "code.managed_assemblies": {"value": ["A.dll"], "source": "runtime"},
    }
    facts = FactSet.from_json("target", raw, "test")
    assert list(facts) == ["code.managed_assemblies", "identity.name"]
    assert FactSet.from_json("target", "not an object", "test").to_json() == {}
    assert FactSet.from_json("target", facts.to_json(), "round trip").to_json() == facts.to_json()


# --- keys -------------------------------------------------------------------------------------------------------


def test_keys_are_stable_across_spellings_of_the_same_path(tmp_path: pathlib.Path) -> None:
    game = tmp_path / "Games" / "My Game"
    game.mkdir(parents=True)
    key = target_key(game, "My Game")
    assert key.startswith("my-game-") and len(key.rsplit("-", 1)[1]) == 8
    spellings = [str(game), str(game).upper(), str(game) + os.sep, str(game) + "/", str(game / ".." / "My Game"), game.as_posix()]
    assert {target_key(s, "My Game") for s in spellings} == {key}
    assert target_key(tmp_path / "Games" / "Other", "My Game") != key
    link = tmp_path / "link"
    try:
        link.symlink_to(game, target_is_directory=True)
    except OSError:
        pytest.skip("creating symlinks needs Developer Mode or admin rights on Windows")
    assert target_key(link, "My Game") == key


def test_slugs() -> None:
    assert slug("Space Pirates: Remastered 2!", "x") == "space-pirates-remastered-2"
    assert slug("Ünïcödé Gämé", "x") == "unicode-game"
    assert slug("!!!", "fallback") == "fallback"
    assert len(slug("a" * 200, "x")) == 48
    assert project_key("Faster Crafting") == project_key("faster crafting ") == "faster-crafting"


# --- settings ---------------------------------------------------------------------------------------------------


def test_first_run_uses_the_shipped_pins(tmp_path: pathlib.Path) -> None:
    store = SettingsStore(tmp_path / "settings.json")
    settings = store.load()
    pins = shipped_pins()
    assert pins["agent_package"] is None
    assert settings.loader_pins.bepinex5 is not None
    assert settings.loader_pins.bepinex5.version == pins["loader_pins"]["bepinex5"]["version"]
    assert set(settings.loader_pins.bepinex5.variants) == {"win_x64", "win_x86"}
    assert not store.path.exists(), "nothing is written until something changes"


def test_set_get_and_validation(tmp_path: pathlib.Path) -> None:
    store = SettingsStore(tmp_path / "settings.json")
    assert store.set("limits.response.max_tokens", 9000) == (None, 9000)
    assert store.set("limits.response.max_tokens", 12000) == (9000, 12000)
    assert store.get("limits.response.max_tokens") == 12000
    store.set("ui.hotkey", "F8")
    store.set("log_level", "DEBUG")
    assert store.get("ui") == {"hotkey": "F8"} and store.get("log_level") == "DEBUG"
    assert store.set("limits.response.max_tokens", None) == (12000, None)
    assert "response.max_tokens" not in store.get("limits")

    dotnet = tmp_path / "dotnet.exe"
    dotnet.write_bytes(b"")
    store.set("dotnet_path", str(dotnet))
    assert store.load().dotnet() == dotnet

    with pytest.raises(ValueError, match="facts"):
        store.set("paths.asset_export", str(tmp_path))
    with pytest.raises(KeyError):
        store.set("favourite_colour", "blue")
    with pytest.raises(ValueError, match="exists"):
        store.set("dnspy_path", str(tmp_path / "missing.exe"))
    with pytest.raises(ValueError, match="log_level"):
        store.set("log_level", "LOUD")
    with pytest.raises(ValueError, match="sha256"):
        store.set("agent_package", {"version": "0.1.0", "url": "https://example.invalid/a.zip", "sha256": "nope"})
    with pytest.raises(ValueError, match="https"):
        store.set("agent_package", {"version": "0.1.0", "url": "http://example.invalid/a.zip", "sha256": "0" * 64})
    store.set("agent_package", {"version": "0.1.0", "path": str(tmp_path / "agent.zip"), "sha256": "0" * 64})
    assert json.loads(store.path.read_text(encoding="utf-8"))["agent_package"]["version"] == "0.1.0"


def test_a_damaged_settings_file_is_reported(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"dotnet_path": "relative\\dotnet.exe"}), encoding="utf-8")
    with pytest.raises(UlmError) as e:
        SettingsStore(path).load()
    assert e.value.code == "SETUP_REQUIRED" and e.value.details["path"] == str(path)


def test_dotnet_is_detected_or_setup_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: None)
    with pytest.raises(UlmError) as e:
        Settings().dotnet()
    assert e.value.code == "SETUP_REQUIRED" and e.value.needs == ["dotnet_path"]
    monkeypatch.setattr("shutil.which", lambda name: "X:/Example/dotnet/dotnet.exe")
    assert Settings().dotnet() == pathlib.Path("X:/Example/dotnet/dotnet.exe")
