"""AgentClient against a scripted in-memory peer: handshake errors, timeouts, cancel, events, jobs, reconnect."""

from __future__ import annotations

import asyncio
import copy
from typing import Any

import pytest

from fakes.fixtures import load_agent_fixtures
from fakes.memory import ScriptedPeer, memory_pair
from unity_ludometry_mcp import errors
from unity_ludometry_mcp.errors import UlmError
from unity_ludometry_mcp.providers.agent_client import CLIENT_NAME, AgentClient, AgentEndpoint

FIXTURES = {f.id: f for f in load_agent_fixtures()}
INFO = FIXTURES["agent.info/ok"].response["result"]
CAPS = FIXTURES["agent.capabilities/ok"].response["result"]
TOKEN = "ab" * 32


class Harness:
    """Hands out a fresh memory connection (with its peer) each time the client connects."""

    def __init__(self) -> None:
        self.peers: asyncio.Queue[ScriptedPeer] = asyncio.Queue()
        self.opens = 0

    async def endpoint(self) -> AgentEndpoint:
        async def open_() -> Any:
            self.opens += 1
            client_side, agent_side = memory_pair()
            self.peers.put_nowait(ScriptedPeer(agent_side))
            return client_side
        return AgentEndpoint(TOKEN, open_)

    async def next_peer(self) -> ScriptedPeer:
        return await asyncio.wait_for(self.peers.get(), 5)


async def handshake(peer: ScriptedPeer, info: dict[str, Any] | None = None) -> None:
    hello = await peer.expect("hello", info or INFO)
    assert hello.params["token"] == TOKEN
    assert hello.params["client"]["name"] == CLIENT_NAME
    assert hello.params["protocol"] == {"major": 0, "minor": 1}
    await peer.expect("agent.capabilities", CAPS)


async def connected(harness: Harness, **kwargs: Any) -> tuple[AgentClient, ScriptedPeer]:
    client = AgentClient(harness.endpoint, backoff_initial_s=0.01, busy_retry_delay_s=0.01, **kwargs)
    task = asyncio.create_task(client.connect())
    peer = await harness.next_peer()
    await handshake(peer)
    await task
    return client, peer


async def test_handshake_reads_info_and_capabilities() -> None:
    harness = Harness()
    client, _ = await connected(harness)
    assert client.connected
    assert client.info is not None and client.info.agent_version == INFO["agentVersion"]
    assert client.capabilities is not None and client.capabilities.api_version == CAPS["apiVersion"]
    await client.close()


@pytest.mark.parametrize("code", ["BAD_TOKEN", "PROTOCOL_MISMATCH", "HANDSHAKE_REQUIRED"])
async def test_handshake_errors_are_provider_unavailable_and_dont_reconnect(code: str) -> None:
    harness = Harness()
    client = AgentClient(harness.endpoint, backoff_initial_s=0.01)
    task = asyncio.create_task(client.connect())
    peer = await harness.next_peer()
    await peer.expect("hello", error={"code": code, "message": "refused"})
    peer.close()
    with pytest.raises(UlmError) as e:
        await task
    assert e.value.code == errors.PROVIDER_UNAVAILABLE
    assert e.value.details["agentCode"] == code
    await asyncio.sleep(0.05)
    assert harness.opens == 1, "a failed first connect must not start a reconnect loop"
    await client.close()


async def test_an_incompatible_agent_version_is_refused() -> None:
    harness = Harness()
    client = AgentClient(harness.endpoint)
    task = asyncio.create_task(client.connect())
    peer = await harness.next_peer()
    info = copy.deepcopy(INFO)
    info["protocol"] = {"major": 0, "minor": 2}
    await peer.expect("hello", info)
    with pytest.raises(UlmError) as e:
        await task
    assert e.value.code == errors.PROVIDER_UNAVAILABLE
    assert "0.2" in e.value.message
    await client.close()


async def test_requests_are_correlated_and_context_is_passed() -> None:
    harness = Harness()
    client, peer = await connected(harness)
    first = asyncio.create_task(client.request("ping", {"echo": "a"}, context={"task": "t-1"}))
    second = asyncio.create_task(client.request("ping", {"echo": "b"}))
    r1, r2 = await peer.receive(), await peer.receive()
    assert r1.context == {"task": "t-1"} and r2.context is None
    await peer.respond(r2, {"echo": "b", "uptimeMs": 2, "frame": 2})  # out of order
    await peer.respond(r1, {"echo": "a", "uptimeMs": 1, "frame": 1})
    assert (await first)["echo"] == "a"
    assert (await second)["echo"] == "b"
    typed = asyncio.create_task(client.call("ping", {}))
    await peer.expect("ping", {"uptimeMs": 5, "frame": None})
    assert (await typed).uptime_ms == 5
    await client.close()


async def test_a_timeout_cancels_the_request() -> None:
    harness = Harness()
    client, peer = await connected(harness)
    task = asyncio.create_task(client.request("obj.get", {"target": {"h": 1}, "paths": [[{"name": "x"}]]}, timeout_s=0.05))
    slow = await peer.receive()
    assert slow.timeout_ms == 50
    cancel = await peer.receive(timeout_s=5)
    assert cancel.method == "cancel" and cancel.params == {"id": slow.id}
    await peer.respond(cancel, {"cancelled": True})
    with pytest.raises(UlmError) as e:
        await task
    assert e.value.code == errors.TIMEOUT
    await client.close()


async def test_cancel_and_mapped_errors() -> None:
    harness = Harness()
    client, peer = await connected(harness)
    task = asyncio.create_task(client.cancel("r-99"))
    await peer.expect("cancel", {"cancelled": False})
    assert await task is False
    task = asyncio.create_task(client.request("obj.set", {"target": {"h": 1}, "path": [{"name": "x"}], "value": 1}))
    await peer.expect("obj.set", error={"code": "MODE_FORBIDDEN", "message": "no", "data": {"requiredMode": "Full"}})
    with pytest.raises(UlmError) as e:
        await task
    assert e.value.code == errors.MODE_FORBIDDEN and e.value.needs == ["consent:runtime_set_mode"]
    await client.close()


async def test_busy_is_retried_once() -> None:
    harness = Harness()
    client, peer = await connected(harness)
    task = asyncio.create_task(client.request("ping", {}))
    await peer.expect("ping", error={"code": "BUSY", "message": "busy"})
    await peer.expect("ping", {"uptimeMs": 1, "frame": 1})
    assert (await task)["uptimeMs"] == 1
    task = asyncio.create_task(client.request("ping", {}))
    await peer.expect("ping", error={"code": "BUSY", "message": "busy"})
    await peer.expect("ping", error={"code": "BUSY", "message": "busy"})
    with pytest.raises(UlmError) as e:
        await task
    assert e.value.code == errors.PROVIDER_FAILED and e.value.retryable
    await client.close()


async def test_method_not_found_refreshes_capabilities() -> None:
    harness = Harness()
    client, peer = await connected(harness)
    task = asyncio.create_task(client.request("time.info", {}))
    await peer.expect("time.info", error={"code": "METHOD_NOT_FOUND", "message": "unknown"})
    await peer.expect("agent.capabilities", CAPS)
    with pytest.raises(UlmError) as e:
        await task
    assert e.value.code == errors.INTERNAL
    await client.close()


async def test_events_are_queued_by_kind_and_gaps_are_reported() -> None:
    harness = Harness()
    client, peer = await connected(harness)
    task = asyncio.create_task(client.subscribe(["log", "agent.warning"], throttle_ms=50))
    sub = await peer.expect("events.subscribe", {"subscribed": ["log", "agent.warning"], "unknown": []})
    assert sub.params == {"kinds": ["log", "agent.warning"], "throttleMs": 50}
    await task
    await peer.event("log", {"items": [], "dropped": 0}, seq=1)
    await peer.event("agent.warning", {"code": "X", "message": "m"}, seq=2)
    await peer.event("log", {"items": [], "dropped": 0}, seq=5)
    assert (await asyncio.wait_for(client.events("log").get(), 2)).seq == 1
    assert (await asyncio.wait_for(client.events("agent.warning").get(), 2)).seq == 2
    assert (await asyncio.wait_for(client.events("log").get(), 2)).seq == 5
    assert await asyncio.wait_for(client.gaps.get(), 2) == (3, 5)
    await client.close()


async def test_jobs_are_waited_for_with_progress() -> None:
    harness = Harness()
    client, peer = await connected(harness)
    sub = asyncio.create_task(client.subscribe(["job.progress"]))
    await peer.expect("events.subscribe", {"subscribed": ["job.progress"], "unknown": []})
    await sub
    start = asyncio.create_task(client.start_job("survey.start", {"outFile": "X:/Example/survey.ndjson"}))
    await peer.expect("survey.start", {"jobId": "j-1", "kind": "survey"})
    job = await start
    progress: list[dict[str, Any]] = []
    wait = asyncio.create_task(client.wait_job(job.job_id, timeout_s=5, poll_s=1, on_progress=progress.append))
    running = {"jobId": "j-1", "kind": "survey", "state": "running", "startedAt": "2026-09-27T10:00:00.000Z", "finishedAt": None}
    await peer.event("job.progress", {"jobId": "j-1", "kind": "survey", "progress": {"phase": "scan", "done": 1, "total": 2}})
    await peer.expect("job.wait", running)
    done = {**running, "state": "succeeded", "finishedAt": "2026-09-27T10:00:01.000Z",
            "result": {"file": {"path": "p", "bytes": 1, "sha256": "0" * 64}, "durationMs": 1}}
    await peer.expect("job.wait", done)
    info = await wait
    assert info.state == "succeeded" and info.result["durationMs"] == 1
    assert progress and progress[0]["progress"]["done"] == 1

    for state, error, code in (("failed", {"code": "IO_FAILED", "message": "disk"}, errors.PROVIDER_FAILED), ("cancelled", None, errors.CANCELLED)):
        wait = asyncio.create_task(client.wait_job("j-2", timeout_s=5, poll_s=1))
        finished = {**running, "jobId": "j-2", "state": state, "finishedAt": "2026-09-27T10:00:01.000Z"}
        await peer.expect("job.wait", {**finished, **({"error": error} if error else {})})
        with pytest.raises(UlmError) as e:
            await wait
        assert e.value.code == code
    with pytest.raises(ValueError):
        await client.start_job("ping", {})
    await client.close()


async def test_reconnect_renews_the_session_and_pending_requests_fail() -> None:
    harness = Harness()
    client, peer = await connected(harness)
    sub = asyncio.create_task(client.subscribe(["log"]))
    await peer.expect("events.subscribe", {"subscribed": ["log"], "unknown": []})
    await sub
    pending = asyncio.create_task(client.request("ping", {}))
    await peer.receive()
    peer.close()
    with pytest.raises(UlmError) as e:
        await pending
    assert e.value.code == errors.PROVIDER_UNAVAILABLE and "may or may not have run" in e.value.hint
    assert not client.connected
    with pytest.raises(UlmError):
        await client.request("ping", {})

    peer2 = await harness.next_peer()
    await handshake(peer2)
    resubscribe = await peer2.expect("events.subscribe", {"subscribed": ["log"], "unknown": []})
    assert resubscribe.params == {"kinds": ["log"]}
    await client.wait_connected(2)
    task = asyncio.create_task(client.request("ping", {}))
    await peer2.expect("ping", {"uptimeMs": 1, "frame": 1})
    assert (await task)["frame"] == 1
    await client.close()


async def test_reconnect_backs_off_until_the_agent_is_back() -> None:
    harness = Harness()
    client, peer = await connected(harness)
    peer.close()
    refused = await harness.next_peer()
    await refused.expect("hello", error={"code": "BAD_TOKEN", "message": "old token"})
    refused.close()
    peer3 = await harness.next_peer()
    await handshake(peer3)
    await client.wait_connected(2)
    assert harness.opens == 3
    await client.close()
