"""Long-running tasks: status, waiting and cancelling."""

from typing import Annotated, Any

from fastmcp import FastMCP
from pydantic import Field

from ..envelope import Result
from ..tasks import FINISHED, TaskInfo, TaskState
from . import ToolCall, register_tools, ulm_tool

TaskId = Annotated[str, Field(min_length=1, description="The task_id a tool returned.")]


def _task_result(task: TaskInfo) -> Result:
    """The task's state, with the finished task's own result merged in (its data, evidence, redactions, advisories)."""
    result = Result(data={"task": task.to_json(include_result=False)}, task_id=task.task_id)
    inner = task.result or {}
    if task.state in FINISHED and inner:
        if inner.get("ok"):
            result.data["result"] = inner.get("data")
        for part in ("evidence", "redactions", "advisories"):
            getattr(result, part).extend(inner.get(part, []))
        if "depth" in inner:
            result.depth = inner["depth"]
    return result


@ulm_tool(group="core", title="Get a task", read_only=True, idempotent=True)
async def task_get(call: ToolCall, task_id: TaskId) -> Result:
    """A task's state and progress, and its result once it has finished."""
    return _task_result(call.session.tasks.get(task_id))


@ulm_tool(group="core", title="Wait for a task", read_only=True, idempotent=True)
async def task_wait(
    call: ToolCall,
    task_id: TaskId,
    timeout_s: Annotated[float | None, Field(gt=0, description="Longest wait in seconds (capped by the task.wait_poll_s limit).")] = None,
) -> Result:
    """Wait for a task to finish and return its result. Returns early with the current state and progress when the wait
    time is up: call it again to keep waiting."""
    cap = float(call.limit("task.wait_poll_s"))
    wait_s = min(timeout_s, cap) if timeout_s is not None else cap

    async def forward(task: TaskInfo) -> None:
        if task.progress:
            await call.progress(task.progress.get("done", 0), task.progress.get("total"), task.progress.get("message"))

    task = await call.session.tasks.wait(task_id, wait_s, forward)
    result = _task_result(task)
    if task.state == TaskState.RUNNING:
        result.data["hint"] = "Still running: call task_wait again."
    return result


@ulm_tool(group="core", title="Cancel a task", destructive=True, idempotent=True)
async def task_cancel(call: ToolCall, task_id: TaskId) -> Result:
    """Cancel a running task. Work it already finished stays; a finished task is returned unchanged."""
    return _task_result(await call.session.tasks.cancel(task_id))


@ulm_tool(group="core", title="List tasks", read_only=True, idempotent=True)
async def task_list(call: ToolCall, state: Annotated[TaskState | None, Field(description="Only tasks in this state.")] = None) -> dict[str, Any]:
    """The tasks of this session (and interrupted ones from earlier sessions), oldest first, without their results."""
    return {"tasks": [t.to_json(include_result=False) for t in call.session.tasks.list(state)]}


def register(app: FastMCP[Any]) -> None:
    register_tools(app, [task_get, task_wait, task_cancel, task_list])
