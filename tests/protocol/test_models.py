"""Every golden fixture round-trips through the generated models (the Python counterpart of the C# conformance tests)."""

from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from fakes.fixtures import PROTOCOL, load_agent_fixtures, load_file_fixtures, ndjson_footer_problems
from unity_ludometry_mcp.protocol import envelope
from unity_ludometry_mcp.protocol.base import ProtocolModel
from unity_ludometry_mcp.protocol.generated import EVENTS, FILES, METHODS, EventKinds, Methods, models

AGENT = {f.id: f for f in load_agent_fixtures()}
FILE_CASES = {f.id: f for f in load_file_fixtures()}
SCHEMA = PROTOCOL / "schema"


def round_trip(model: type[ProtocolModel], value: dict[str, Any] | None, what: str) -> list[str]:
    expected = {} if value is None else value
    try:
        written = model.model_validate(expected).to_json()
    except ValidationError as e:
        return [f"{what} failed to validate as {model.__name__}: {e}"]
    return [] if written == expected else [f"{what} doesn't round-trip through {model.__name__}: expected {expected}, wrote {written}"]


def envelope_round_trip(value: dict[str, Any], what: str) -> tuple[envelope.Envelope | None, list[str]]:
    parsed = envelope.parse(value)
    written = parsed.to_json()
    return parsed, [] if written == value else [f"{what} envelope doesn't round-trip: expected {value}, wrote {written}"]


@pytest.mark.parametrize("fixture_id", sorted(AGENT))
def test_fixture_round_trips(fixture_id: str) -> None:
    f = AGENT[fixture_id]
    problems: list[str] = []
    if f.is_event:
        ev, p = envelope_round_trip(f.event, "event")
        problems += p
        assert isinstance(ev, envelope.Event)
        assert ev.method == f.group
        problems += round_trip(EVENTS[ev.method].params, ev.params, "params")
    else:
        req, p1 = envelope_round_trip(f.request, "request")
        resp, p2 = envelope_round_trip(f.response, "response")
        problems += p1 + p2
        assert isinstance(req, envelope.Request) and isinstance(resp, envelope.Response)
        assert req.id == resp.id
        assert req.context == resp.context
        if not f.is_generic:
            assert req.method == f.group
            descriptor = METHODS[req.method]
            if f.request_valid:
                problems += round_trip(descriptor.params, req.params, "params")
            else:
                with pytest.raises(ValidationError):
                    descriptor.params.model_validate(req.params or {})
                assert resp.error is not None and resp.error["code"] == "INVALID_PARAMS"
            if not resp.is_error:
                problems += round_trip(descriptor.result, resp.result, "result")
            if f.job_result is not None:
                assert descriptor.job_result is not None
                problems += round_trip(descriptor.job_result, f.job_result, "jobResult")
            elif descriptor.job and not resp.is_error and f.request_valid:
                problems.append("a job method's success fixture needs a jobResult")
    assert not problems, "\n".join(problems)


@pytest.mark.parametrize("fixture_id", sorted(FILE_CASES))
def test_file_fixture_round_trips(fixture_id: str) -> None:
    f = FILE_CASES[fixture_id]
    registry = {(d.schema, d.rec): d.model for d in FILES}
    problems: list[str] = []
    if not f.is_ndjson:
        problems += round_trip(registry[(f.schema, "")], json.loads(f.data), f.id)
    else:
        lines = f.lines()
        for i, line in enumerate(lines):
            record = json.loads(line)
            schema = "ndjson" if record["rec"] in ("header", "footer") else f.schema
            problems += round_trip(registry[(schema, record["rec"])], record, f"line {i + 1}")
        assert json.loads(lines[0])["rec"] == "header" and json.loads(lines[-1])["rec"] == "footer"
        problems += ndjson_footer_problems(f)
    assert not problems, "\n".join(problems)


def test_registries_cover_the_schemas_and_fixtures() -> None:
    schema_methods = {p.name.removesuffix(".schema.json") for p in (SCHEMA / "methods").glob("*.schema.json")}
    schema_events = {p.name.removesuffix(".schema.json") for p in (SCHEMA / "events").glob("*.schema.json")}
    schema_files = {p.name.removesuffix(".schema.json") for p in (SCHEMA / "files").glob("*.schema.json")} - {"ndjson"}
    assert set(METHODS) == schema_methods
    assert set(EVENTS) == schema_events
    assert {d.schema for d in FILES} - {"ndjson"} == schema_files
    assert {v for k, v in vars(Methods).items() if k.isupper()} == schema_methods
    assert {v for k, v in vars(EventKinds).items() if k.isupper()} == schema_events
    assert {f.group for f in AGENT.values() if not f.is_event and not f.is_generic and f.id.endswith("/ok")} == schema_methods
    assert {f.group for f in AGENT.values() if f.is_event} == schema_events


def test_registry_metadata_matches_every_method_schema() -> None:
    for name, descriptor in METHODS.items():
        meta = json.loads((SCHEMA / "methods" / f"{name}.schema.json").read_text(encoding="utf-8"))["x-method"]
        assert descriptor.thread.value == meta["thread"], name
        assert descriptor.min_mode == meta["minMode"], name
        assert descriptor.job == meta["job"], name
        assert descriptor.mutating == meta["mutating"], name
        assert descriptor.requires == tuple(meta.get("requires", ())), name
        assert (descriptor.job_result is not None) == meta["job"], name


def _version_pairs(value: Any, path: str = "") -> list[tuple[str, int, int]]:
    found = []
    if isinstance(value, dict):
        if {"major", "minor"} <= set(value):
            found.append((path, value["major"], value["minor"]))
        for key, child in value.items():
            found += _version_pairs(child, f"{path}.{key}")
    elif isinstance(value, list):
        for i, child in enumerate(value):
            found += _version_pairs(child, f"{path}[{i}]")
    return found


def test_fixtures_name_the_current_protocol_version() -> None:
    """Example data must be semantically right, not just valid: every protocol version in a fixture is the current one,
    except in the fixture that demonstrates a mismatch."""
    from unity_ludometry_mcp.protocol.version import PROTOCOL_MAJOR, PROTOCOL_MINOR

    wrong = []
    for f in AGENT.values():
        if f.id == "hello/protocol-mismatch":
            continue
        for part in (f.request, f.response, f.job_result, f.event):
            wrong += [(f.id, *pair) for pair in _version_pairs(part) if pair[1:] != (PROTOCOL_MAJOR, PROTOCOL_MINOR)]
    for f in FILE_CASES.values():
        records = [json.loads(line) for line in f.lines()] if f.is_ndjson else [json.loads(f.data)]
        for record in records:
            wrong += [(f.id, *pair) for pair in _version_pairs(record) if pair[1:] != (PROTOCOL_MAJOR, PROTOCOL_MINOR)]
    assert not wrong, wrong


def test_models_are_strict_and_keep_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        models.PingResult.model_validate({"uptimeMs": "65000", "frame": None})
    with pytest.raises(ValidationError):
        models.PingResult.model_validate({"uptimeMs": True, "frame": None})
    with pytest.raises(ValidationError):
        models.PingResult.model_validate({"uptimeMs": 1})  # a required nullable field must be present
    value = {"uptimeMs": 5.0, "frame": None, "future": {"x": 1}}
    assert models.PingResult.model_validate(value).to_json() == {"uptimeMs": 5, "frame": None, "future": {"x": 1}}
    with pytest.raises(ValidationError):
        models.PingResult.model_validate({"uptimeMs": 2**63, "frame": None})


def test_no_generated_field_shadows_a_pydantic_attribute() -> None:
    reserved = set(dir(BaseModel))
    for name in models.__all__:
        cls = getattr(models, name)
        assert not set(cls.model_fields) & reserved, name


def test_generated_code_is_current() -> None:
    import csharp
    import python
    from schema_ir import build

    model = build()
    rendered = python.render(model)
    for file_name, content in rendered.items():
        assert (python.OUT_DIR / file_name).read_text(encoding="utf-8") == content, f"{file_name} is stale: run python protocol/codegen/python.py"
    for file_name, content in csharp.render(model).items():
        assert (csharp.OUT_DIR / file_name).read_text(encoding="utf-8") == content, f"{file_name} is stale: run python protocol/codegen/csharp.py"
