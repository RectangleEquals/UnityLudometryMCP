"""The task manager, the event store, and how both reach tool results."""

import asyncio
import dataclasses
from typing import Any

import pytest
from fastmcp import Client, FastMCP

from unity_ludometry_mcp.envelope import Result
from unity_ludometry_mcp.errors import NOT_FOUND, UlmError
from unity_ludometry_mcp.events import EventStore
from unity_ludometry_mcp.session import Session
from unity_ludometry_mcp.tasks import InMemoryTaskStore, TaskManager, TaskState
from unity_ludometry_mcp.tools import GroupVisibility, ToolCall, attach_session, register_tools, ulm_tool
from unity_ludometry_mcp.tools import runtime as runtime_tools
from unity_ludometry_mcp.tools import tasks as task_tools

# --- the task manager -------------------------------------------------------------------------------------------


async def test_a_task_reports_progress_and_its_result() -> None:
    manager = TaskManager()
    gate = asyncio.Event()

    async def body(progress: Any) -> Result:
        await progress(1, 3, "first")
        await gate.wait()
        await progress(3, 3, None)
        return Result(data={"answer": 42}).add_evidence("live://x", "runtime:live")

    task = manager.start("survey", body, target="game-1")
    assert task.state == TaskState.RUNNING and task.task_id == "t-1"
    seen: list[dict[str, Any]] = []

    async def on_change(t: Any) -> None:
        seen.append(dict(t.progress))

    early = await manager.wait(task.task_id, 0.2, on_change)
    assert early.state == TaskState.RUNNING
    assert early.progress == {"done": 1, "total": 3, "message": "first"}
    gate.set()
    done = await manager.wait(task.task_id, 5)
    assert done.state == TaskState.SUCCEEDED
    assert done.result == {"ok": True, "data": {"answer": 42}, "evidence": [{"locator": "live://x", "source": "runtime:live"}]}
    assert done.finished_at is not None
    assert seen and seen[0]["done"] == 1


async def test_failures_and_cancellation() -> None:
    manager = TaskManager()

    async def fails_ulm(progress: Any) -> None:
        raise UlmError(NOT_FOUND, "gone")

    async def crashes(progress: Any) -> None:
        raise RuntimeError("boom")

    async def forever(progress: Any) -> None:
        await asyncio.sleep(3600)

    a, b, c = manager.start("a", fails_ulm), manager.start("b", crashes), manager.start("c", forever)
    assert (await manager.wait(a.task_id, 5)).error == {"code": "NOT_FOUND", "message": "gone", "hint": ""}
    crashed = await manager.wait(b.task_id, 5)
    assert crashed.state == TaskState.FAILED and crashed.error is not None and crashed.error["code"] == "INTERNAL"
    cancelled = await manager.cancel(c.task_id)
    assert cancelled.state == TaskState.CANCELLED and cancelled.error is not None and cancelled.error["code"] == "CANCELLED"
    assert (await manager.cancel(c.task_id)).state == TaskState.CANCELLED
    assert [t.task_id for t in manager.list(TaskState.FAILED)] == ["t-1", "t-2"]
    with pytest.raises(UlmError, match="No task"):
        manager.get("t-99")


async def test_state_survives_a_restart_as_interrupted() -> None:
    store = InMemoryTaskStore()
    first = TaskManager(store)

    async def forever(progress: Any) -> None:
        await asyncio.sleep(3600)

    async def quick(progress: Any) -> str:
        return "ok"

    running = first.start("long", forever)
    finished = first.start("short", quick)
    await first.wait(finished.task_id, 5)
    await first.shutdown()
    assert first.get(running.task_id).state == TaskState.INTERRUPTED

    # A crash leaves a task stored as running; the next manager marks it interrupted.
    store.save(dataclasses.replace(first.get(running.task_id), task_id="t-7", state=TaskState.RUNNING))
    second = TaskManager(store)
    assert {t.task_id: t.state for t in second.list()} == {"t-1": TaskState.INTERRUPTED, "t-2": TaskState.SUCCEEDED, "t-7": TaskState.INTERRUPTED}
    assert second.start("next", quick).task_id == "t-8"


# --- the event store --------------------------------------------------------------------------------------------


async def test_notices_appear_once_in_order_merged_and_throttled() -> None:
    store = EventStore(max_notices=3)
    await store.publish("exception", {"type": "NullReferenceException"})
    await store.publish("rule.fired", {"rule": "r1"})
    await store.publish("exception", {"type": "NullReferenceException"})  # merged with the first
    await store.publish("agent.warning", {"code": "SLOW"})
    await store.publish("overlay.picked", {"h": 1})
    await store.publish("overlay.picked", {"h": 2}, dedup_key="pick")
    await store.publish("overlay.picked", {"h": 3}, dedup_key="pick")

    notices = store.drain_notices()
    assert [n["kind"] for n in notices] == ["exception", "rule.fired", "agent.warning", "notices.more"]
    assert notices[0] == {"kind": "exception", "seq": 3, "type": "NullReferenceException", "count": 2, "first_seq": 1}
    assert notices[3]["count"] == 3 and notices[3]["kinds"] == ["overlay.picked"] and notices[3]["since_seq"] == 5
    assert store.drain_notices() == []
    assert [e.seq for e in store.query(since=4)] == [5, 6, 7]
    assert [e.kind for e in store.query(kinds=["rule.fired"])] == ["rule.fired"]
    assert store.last_seq == 7


async def test_handlers_consume_events() -> None:
    store = EventStore()
    handled: list[int] = []

    async def estop(event: Any) -> bool:
        handled.append(event.seq)
        return True

    async def observer(event: Any) -> bool:
        return False

    async def broken(event: Any) -> bool:
        raise RuntimeError("handler bug")

    store.on("overlay.estop", estop)
    store.on("exception", observer)
    store.on("exception", broken)
    await store.publish("overlay.estop", {})
    await store.publish("exception", {"type": "X"})
    assert handled == [1]
    assert [n["kind"] for n in store.drain_notices()] == ["exception"]


# --- through the tools ------------------------------------------------------------------------------------------


@ulm_tool(group="core", title="Slow survey", read_only=True, long_running=True)
async def slow_survey(call: ToolCall, steps: int) -> Result:
    """Pretends to survey."""
    for i in range(steps):
        await call.progress(i + 1, steps, f"step {i + 1}")
        await asyncio.sleep(0.05)
    return Result(data={"steps": steps}, depth="runtime-only")


@ulm_tool(group="core", title="Echo", read_only=True)
async def echo(call: ToolCall) -> str:
    """Echoes."""
    return "echo"


def make_app() -> tuple[FastMCP[Any], Session]:
    app: FastMCP[Any] = FastMCP("test", middleware=[GroupVisibility()])
    session = attach_session(app, Session())
    register_tools(app, [slow_survey, echo])
    task_tools.register(app)
    runtime_tools.register(app)
    return app, session


async def test_task_tools_through_the_client() -> None:
    app, _ = make_app()
    progress: list[tuple[float, float | None, str | None]] = []

    async def on_progress(done: float, total: float | None, message: str | None) -> None:
        progress.append((done, total, message))

    async with Client(app, progress_handler=on_progress) as client:
        started = (await client.call_tool("slow_survey", {"steps": 6})).structured_content
        assert started is not None and started["task_id"] == "t-1" and started["data"]["state"] == "running"
        early = (await client.call_tool("task_wait", {"task_id": "t-1", "timeout_s": 0.08})).structured_content
        done = (await client.call_tool("task_wait", {"task_id": "t-1"})).structured_content
        listed = (await client.call_tool("task_list", {"state": "succeeded"})).structured_content
        missing = (await client.call_tool("task_get", {"task_id": "t-9"})).structured_content
        long = (await client.call_tool("slow_survey", {"steps": 1000})).structured_content
        assert long is not None
        cancelled = (await client.call_tool("task_cancel", {"task_id": long["task_id"]})).structured_content

    assert early is not None and early["data"]["task"]["state"] == "running" and "hint" in early["data"]
    assert done is not None and done["data"]["task"]["state"] == "succeeded"
    assert done["data"]["result"] == {"steps": 6} and done["depth"] == "runtime-only" and done["task_id"] == "t-1"
    assert listed is not None and [t["task_id"] for t in listed["data"]["tasks"]] == ["t-1"]
    assert missing is not None and missing["error"]["code"] == "NOT_FOUND"
    assert cancelled is not None and cancelled["data"]["task"]["state"] == "cancelled"
    assert progress, "task_wait forwards task progress to the client"


async def test_notices_are_attached_to_the_next_result_and_events_are_readable() -> None:
    app, session = make_app()
    async with Client(app) as client:
        await session.events.publish("rule.fired", {"rule": "hp-low"})
        first = (await client.call_tool("echo", {})).structured_content
        second = (await client.call_tool("echo", {})).structured_content
        events = (await client.call_tool("runtime_events", {"since": 0})).structured_content
        newer = (await client.call_tool("runtime_events", {"since": 1})).structured_content
    assert first is not None and first["notices"] == [{"kind": "rule.fired", "seq": 1, "rule": "hp-low"}]
    assert second == {"ok": True, "data": "echo"}
    assert events is not None and events["data"]["last_seq"] == 1 and events["data"]["events"][0]["data"] == {"rule": "hp-low"}
    assert newer is not None and newer["data"] == {"events": [], "last_seq": 1}
