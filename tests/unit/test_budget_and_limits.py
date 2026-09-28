"""Token budgeting (split + spill + redactions) and the limit registry (definitions + precedence)."""

import json
import pathlib
from typing import Any

import pytest

from unity_ludometry_mcp.budget import Budget, iter_redactions
from unity_ludometry_mcp.envelope import Result
from unity_ludometry_mcp.limits.registry import LimitRegistry

# --- budget -----------------------------------------------------------------------------------------------------


def resolve_pointer(document: Any, pointer: str) -> Any:
    for part in pointer.split("/")[1:]:
        part = part.replace("~1", "/").replace("~0", "~")
        document = document[int(part)] if isinstance(document, list) else document[part]
    return document


def big_data() -> dict[str, Any]:
    return {
        "summary": "small",
        "types": [{"name": f"Game.Type{i}", "members": [f"m{j}" for j in range(20)]} for i in range(300)],
        "log": "x" * 40000,
        "nested": {"a/b": list(range(5000)), "tiny": 1},
    }


def test_a_small_result_is_unchanged() -> None:
    result = Budget().fit(Result(data={"a": 1}), 100, None)
    assert result.to_json() == {"ok": True, "data": {"a": 1}}


def test_an_oversized_result_is_split_and_spilled(tmp_path: pathlib.Path) -> None:
    budget = Budget()
    data = big_data()
    result = budget.fit(Result(data=json.loads(json.dumps(data))), 1500, tmp_path)

    assert budget.estimate(result.data) <= 1500
    assert result.limits_hit == ["response.max_tokens"] and result.limits_applied == {"response.max_tokens": 1500}
    assert result.data["summary"] == "small" and result.data["nested"]["tiny"] == 1
    spilled = list(tmp_path.glob("result-*.json"))
    assert len(spilled) == 1
    full = json.loads(spilled[0].read_text(encoding="utf-8"))
    assert full == data

    stubs = list(iter_redactions(result.data))
    assert stubs and result.redactions == stubs
    for stub in stubs:
        assert stub["reason"] == "maxTokens" and stub["file"] == str(spilled[0])
        assert stub["ref"] == f"{spilled[0]}#{stub['path']}"
        original = resolve_pointer(full, stub["path"])
        if "range" in stub:
            start, end = stub["range"]
            assert end == len(original) and stub["size"]["count"] == end - start
            assert resolve_pointer(result.data, stub["path"])[:start] == original[:start]
        elif "preview" in stub:
            assert original.startswith(stub["preview"]) and stub["size"]["length"] == len(original)
    assert any(s["path"] == "/nested/a~1b" for s in stubs), "JSON pointers escape '/'"


def test_without_a_spill_folder_stubs_still_say_what_was_left_out() -> None:
    result = Budget().fit(Result(data={"log": "y" * 20000}), 200, None)
    stub = result.data["log"]["redacted"]
    assert stub["reason"] == "maxTokens" and stub["size"]["length"] == 20000
    assert "file" not in stub and "ref" not in stub and stub["preview"].startswith("y")


def test_existing_stubs_are_listed_even_when_nothing_is_cut() -> None:
    agent_stub = {"redacted": {"reason": "maxItems", "ref": "x7:42", "range": [64, 3120]}}
    result = Budget().fit(Result(data={"items": [1, 2, agent_stub]}, redactions=[agent_stub["redacted"]]), 1000, None)
    assert result.redactions == [agent_stub["redacted"]]
    assert Budget().fit(Result(data={"deep": {"v": agent_stub}}), 1000, None).redactions == [agent_stub["redacted"]]


def test_an_unsplittable_value_becomes_one_stub(tmp_path: pathlib.Path) -> None:
    result = Budget().fit(Result(data=list(range(100000))), 30, tmp_path)
    assert list(iter_redactions(result.data))


def test_errors_are_never_cut() -> None:
    error = {"code": "INTERNAL", "message": "m" * 10000, "hint": ""}
    result = Budget().fit(Result(ok=False, error=error), 10, None)
    assert result.error == error and not result.limits_hit


# --- limits -----------------------------------------------------------------------------------------------------

DESIGN_KEYS = {
    "trace.callgraph_depth",
    "trace.max_methods",
    "trace.max_records",
    "hook.max_hits",
    "query.max_candidates",
    "survey.scope",
    "il_index.records",
    "content.scan.types",
    "capture.max_width",
    "capture.max_per_minute",
    "response.max_tokens",
    "view.depth",
    "view.max_items",
    "research.max_sources",
    "research.max_tokens",
    "research.max_age_days",
    "task.wait_poll_s",
    "runtime.connect_timeout_s",
    "digest.max_tokens",
    "task.max_duration",
}


@pytest.fixture(scope="module")
def registry() -> LimitRegistry:
    return LimitRegistry.load()


def test_every_designed_limit_is_shipped(registry: LimitRegistry) -> None:
    assert set(registry.keys()) == DESIGN_KEYS
    defaults = {r.key: r.value for r in registry.resolve_all()}
    assert defaults["response.max_tokens"] == 6000
    assert defaults["task.wait_poll_s"] == 50
    assert defaults["il_index.records"] == ["calls", "fieldAccess", "strings"]
    assert all(r.source == "default" for r in registry.resolve_all())
    for item in registry.describe():
        assert item["description"] and item["cost_model"] and item["affects"]


@pytest.mark.parametrize(
    ("scopes", "value", "source"),
    [
        ({}, 6000, "default"),
        ({"settings": {"response.max_tokens": 8000}}, 8000, "settings"),
        ({"settings": {"response.max_tokens": 8000}, "target": {"response.max_tokens": 7000}}, 7000, "target"),
        ({"target": {"response.max_tokens": 7000}, "project": {"response.max_tokens": 9000}}, 9000, "project"),
        ({"project": {"response.max_tokens": 9000}, "one_shot": {"response.max_tokens": 12000}}, 12000, "one_shot"),
        ({"settings": {"response.max_tokens": 8000}, "project": {"response.max_tokens": "lots"}}, 8000, "settings"),
    ],
)
def test_precedence(registry: LimitRegistry, scopes: dict[str, Any], value: int, source: str) -> None:
    resolved = registry.resolve("response.max_tokens", scopes)  # type: ignore[arg-type]
    assert (resolved.value, resolved.source) == (value, source)


def test_max_is_a_hard_ceiling_and_min_a_floor(registry: LimitRegistry) -> None:
    high = registry.resolve("trace.max_methods", {"one_shot": {"trace.max_methods": 10**9}})
    assert high.value == 5000 and high.clamped and high.source == "one_shot"
    low = registry.resolve("task.wait_poll_s", {"project": {"task.wait_poll_s": 0}})
    assert low.value == 1 and low.clamped


def test_locks_and_invalid_values_are_reported(registry: LimitRegistry) -> None:
    locked = registry.resolve("view.depth", {"target": {"view.depth": {"value": 3, "locked": True}}, "project": {"view.depth": 4}})
    assert (locked.value, locked.source, locked.locked, locked.locked_at) == (4, "project", True, "target")
    bad = registry.resolve("survey.scope", {"project": {"survey.scope": "everything"}})
    assert bad.value == "game" and bad.ignored and "project" in bad.ignored[0]
    assert registry.resolve("il_index.records", {"settings": {"il_index.records": ["strings", "calls", "calls"]}}).value == ["calls", "strings"]
    assert registry.resolve("content.scan.types", {"settings": {"content.scan.types": ["Texture2D"]}}).value == ["Texture2D"]
    assert locked.to_json() == {"key": "view.depth", "value": 4, "source": "project", "locked": True, "locked_at": "target"}
    with pytest.raises(KeyError):
        registry.resolve("no.such.limit")


def test_broken_definitions_are_rejected(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "limits.json"
    spec = {"type": "int", "default": 50, "min": 1, "max": 10, "unit": "x", "cost_model": "c", "affects": ["cpu"], "description": "d"}
    path.write_text(json.dumps({"limits": {"a.b": spec}}), encoding="utf-8")
    with pytest.raises(ValueError, match="outside"):
        LimitRegistry.load(path)
    path.write_text(json.dumps({"limits": {"a.b": {**spec, "default": 5, "affects": ["mood"]}}}), encoding="utf-8")
    with pytest.raises(ValueError, match="affects"):
        LimitRegistry.load(path)
