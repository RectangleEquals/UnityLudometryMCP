"""Loads the protocol's golden fixtures (protocol/fixtures) for tests and the fake agent."""

from __future__ import annotations

import hashlib
import json
import pathlib
from dataclasses import dataclass
from typing import Any

PROTOCOL = pathlib.Path(__file__).resolve().parents[2] / "protocol"
AGENT_FIXTURES = PROTOCOL / "fixtures" / "agent"
FILE_FIXTURES = PROTOCOL / "fixtures" / "files"


@dataclass(frozen=True)
class FixtureCase:
    id: str  # e.g. "hello/ok", "events/log/full"
    group: str  # method name, event kind, or "_generic"
    is_event: bool
    description: str
    request_valid: bool
    request: dict[str, Any] | None
    response: dict[str, Any] | None
    job_result: dict[str, Any] | None
    event: dict[str, Any] | None

    @property
    def is_generic(self) -> bool:
        return self.group == "_generic"


def load_agent_fixtures() -> list[FixtureCase]:
    cases = []
    for path in sorted(AGENT_FIXTURES.rglob("*.json")):
        rel = path.relative_to(AGENT_FIXTURES).with_suffix("").as_posix()
        parts = rel.split("/")
        is_event = parts[0] == "events"
        if len(parts) != (3 if is_event else 2):
            raise ValueError(f"fixture {rel} must be at <method>/<case>.json or events/<kind>/<case>.json")
        d = json.loads(path.read_text(encoding="utf-8"))
        unknown = set(d) - {"description", "requestValid", "request", "response", "jobResult", "event"}
        if unknown:
            raise ValueError(f"fixture {rel} has unknown properties: {sorted(unknown)}")
        cases.append(
            FixtureCase(
                rel,
                parts[1] if is_event else parts[0],
                is_event,
                d["description"],
                d.get("requestValid", True),
                d.get("request"),
                d.get("response"),
                d.get("jobResult"),
                d.get("event"),
            )
        )
    return cases


@dataclass(frozen=True)
class FileFixture:
    id: str  # e.g. "survey/example.ndjson"
    schema: str
    is_ndjson: bool
    data: bytes

    def lines(self) -> list[str]:
        text = self.data.decode("utf-8")
        if not text.endswith("\n"):
            raise ValueError(f"{self.id}: the last line must end with a newline")
        return text[:-1].split("\n")


def load_file_fixtures() -> list[FileFixture]:
    result = []
    for path in sorted(FILE_FIXTURES.rglob("*.*")):
        rel = path.relative_to(FILE_FIXTURES).as_posix()
        result.append(FileFixture(rel, rel.split("/")[0], path.suffix == ".ndjson", path.read_bytes()))
    return result


def ndjson_footer_problems(fixture: FileFixture) -> list[str]:
    """Checks that the footer's sha256 and counts match the preceding lines."""
    lines = fixture.lines()
    footer = json.loads(lines[-1])
    body = "".join(line + "\n" for line in lines[:-1]).encode("utf-8")
    problems = []
    if footer.get("sha256") != hashlib.sha256(body).hexdigest():
        problems.append("footer sha256 doesn't match the preceding lines")
    counts: dict[str, int] = {}
    for line in lines[1:-1]:
        rec = json.loads(line)["rec"]
        counts[rec] = counts.get(rec, 0) + 1
    if footer.get("counts") != counts:
        problems.append(f"footer counts {footer.get('counts')} != {counts}")
    return problems
