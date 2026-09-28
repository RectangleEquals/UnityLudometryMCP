"""AgentClient ↔ fake agent over a real named pipe (and TCP): discovery, handshake, every fixture method, jobs, reconnect."""

from __future__ import annotations

import asyncio
import hashlib
import json
import pathlib
import sys
from collections.abc import AsyncIterator

import pytest

from fakes.agent import FakeAgent
from fakes.fixtures import load_agent_fixtures
from unity_ludometry_mcp import errors
from unity_ludometry_mcp.errors import UlmError
from unity_ludometry_mcp.protocol.generated import METHODS
from unity_ludometry_mcp.providers import discovery
from unity_ludometry_mcp.providers.agent_client import AgentClient, AgentEndpoint

TRANSPORTS = [pytest.param("pipe", marks=[pytest.mark.windows, pytest.mark.skipif(sys.platform != "win32", reason="named pipes need Windows")]), "tcp"]
FIXTURES = load_agent_fixtures()
# Methods the fake agent answers itself (handshake, session, jobs) rather than from fixtures.
NATIVE = {"hello", "cancel", "job.get", "job.wait", "job.cancel", "job.list"}


def client_for(providers: pathlib.Path) -> AgentClient:
    async def endpoint() -> AgentEndpoint:
        agents = discovery.scan(providers)
        if not agents:
            raise UlmError(errors.GAME_NOT_RUNNING, "No agent found.")
        return AgentEndpoint.from_discovery(agents[0].info)

    return AgentClient(endpoint, backoff_initial_s=0.02, default_timeout_s=10)


@pytest.fixture(params=TRANSPORTS)
async def fake(request: pytest.FixtureRequest, tmp_path: pathlib.Path) -> AsyncIterator[FakeAgent]:
    agent = await FakeAgent(tmp_path / "providers", transport=request.param, mode="Full").start()
    yield agent
    await agent.stop()


@pytest.fixture
async def client(fake: FakeAgent) -> AsyncIterator[AgentClient]:
    c = client_for(fake.providers_dir)
    await c.connect()
    yield c
    await c.close()


async def test_handshake_through_discovery(fake: FakeAgent, client: AgentClient) -> None:
    assert client.info is not None and client.info.mode == "Full" and client.info.transport == fake.transport
    assert client.capabilities is not None and len(client.capabilities.methods) == len(METHODS)
    assert fake.received[0].method == "hello" and fake.received[0].params["token"] == fake.token


@pytest.mark.parametrize(
    "case",
    [
        f
        for f in FIXTURES
        if not f.is_event and not f.is_generic and f.request_valid and f.id.endswith("/ok") and f.group not in NATIVE and not METHODS[f.group].job
    ],
    ids=lambda f: f.group,
)
async def test_every_fixture_method(fake: FakeAgent, client: AgentClient, case: object) -> None:
    """The client sends each fixture request (the fake validates it against the schema) and types the result."""
    request = case.request  # type: ignore[attr-defined]
    result = await client.call(request["method"], request.get("params"))
    if request["method"] not in ("ping", "agent.info", "agent.capabilities", "events.subscribe", "events.unsubscribe"):
        assert result.to_json() == case.response["result"]  # type: ignore[attr-defined]


async def test_a_job_with_events_writes_its_file(fake: FakeAgent, client: AgentClient, tmp_path: pathlib.Path) -> None:
    await client.subscribe(["job.progress", "job.finished"])
    out_file = tmp_path / "survey.ndjson"
    job = await client.start_job("survey.start", {"outFile": str(out_file)})
    progress: list[dict] = []
    info = await client.wait_job(job.job_id, timeout_s=10, poll_s=2, on_progress=progress.append)
    assert info.state == "succeeded"
    data = out_file.read_bytes()
    assert info.result["file"]["sha256"] == hashlib.sha256(data).hexdigest()
    assert info.result["file"]["counts"] == json.loads(data.decode().rstrip("\n").split("\n")[-1])["counts"]
    finished = await asyncio.wait_for(client.events("job.finished").get(), 5)
    assert finished.params["job"]["jobId"] == job.job_id
    assert progress or not client.events("job.progress").empty()


async def test_reconnect_after_the_connection_drops(fake: FakeAgent, client: AgentClient) -> None:
    await client.subscribe(["log"])
    await fake.drop_connections()
    await asyncio.sleep(0.05)
    await client.wait_connected(5)
    assert (await client.request("ping", {"echo": "back"}))["echo"] == "back"
    await asyncio.sleep(0.05)
    await fake.emit("log", {"items": [], "dropped": 0})
    assert (await asyncio.wait_for(client.events("log").get(), 5)).method == "log"


async def test_handshake_refusals(fake: FakeAgent) -> None:
    agents = discovery.scan(fake.providers_dir)
    bad = AgentClient(AgentEndpoint("00" * 32, AgentEndpoint.from_discovery(agents[0].info).open))
    with pytest.raises(UlmError) as e:
        await bad.connect()
    assert e.value.code == errors.PROVIDER_UNAVAILABLE and e.value.details["agentCode"] == "BAD_TOKEN"
    await bad.close()
    fake.protocol = (0, 2)
    other = client_for(fake.providers_dir)
    with pytest.raises(UlmError) as e:
        await other.connect()
    assert e.value.details["agentCode"] == "PROTOCOL_MISMATCH"
    await other.close()


async def test_modes_invalid_params_and_injected_failures(fake: FakeAgent, client: AgentClient) -> None:
    fake.mode = "ReadOnly"
    with pytest.raises(UlmError) as e:
        await client.request("obj.set", {"target": {"h": 1}, "path": [{"name": "x"}], "value": 1})
    assert e.value.code == errors.MODE_FORBIDDEN and e.value.details["requiredMode"] == "Full"
    with pytest.raises(UlmError) as e:
        await client.request("obj.get", {"target": {"h": 1}})
    assert e.value.code == errors.INTERNAL and e.value.details["agentCode"] == "INVALID_PARAMS" and e.value.details["param"] == "params"
    fake.fail["ping"] = {"code": "BUSY", "message": "busy"}
    fake.fail_times["ping"] = 1
    assert (await client.request("ping", {}))["uptimeMs"] == 1000, "BUSY is retried once"
    fake.fail["code.types"] = {"code": "INDEX_STALE", "message": "stale", "data": {"hint": "Rescan."}}
    with pytest.raises(UlmError) as e:
        await client.request("code.types", {})
    assert e.value.code == errors.INDEX_STALE and "Rescan." in e.value.hint
    fake.delay_s["time.info"] = 5
    with pytest.raises(UlmError) as e:
        await client.request("time.info", {}, timeout_s=0.2)
    assert e.value.code == errors.TIMEOUT
    assert fake.received[-1].method == "cancel"
