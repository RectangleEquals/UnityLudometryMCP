"""The task manager: operations that may take longer than a few seconds run as tasks.

A tool that starts a task returns its `task_id` at once. The task reports progress, and `task_wait` long-polls for its
result. Task state is kept in a `TaskStore`: in memory for now; the target and project databases take over later. On
shutdown, running tasks are cancelled and stored as `interrupted`, and a new manager over the same store sees them so.
"""

import asyncio
import contextlib
import itertools
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol

from .envelope import Result, as_result
from .errors import CANCELLED, NOT_FOUND, UlmError, internal_error

log = logging.getLogger(__name__)


class TaskState(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


FINISHED = frozenset({TaskState.SUCCEEDED, TaskState.FAILED, TaskState.CANCELLED, TaskState.INTERRUPTED})


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass(frozen=True)
class TaskInfo:
    """A task's state as stored and reported."""

    task_id: str
    kind: str
    state: TaskState
    started_at: str
    target: str | None = None
    project: str | None = None
    progress: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    finished_at: str | None = None

    def to_json(self, include_result: bool = True) -> dict[str, Any]:
        out: dict[str, Any] = {"task_id": self.task_id, "kind": self.kind, "state": self.state.value, "started_at": self.started_at}
        for name in ("target", "project", "finished_at"):
            if getattr(self, name) is not None:
                out[name] = getattr(self, name)
        if self.progress:
            out["progress"] = self.progress
        if self.error is not None:
            out["error"] = self.error
        if include_result and self.result is not None:
            out["result"] = self.result
        return out


class TaskStore(Protocol):
    def save(self, task: TaskInfo) -> None: ...
    def load_all(self) -> list[TaskInfo]: ...


class InMemoryTaskStore:
    """Keeps tasks for the life of the store object."""

    def __init__(self) -> None:
        self._tasks: dict[str, TaskInfo] = {}

    def save(self, task: TaskInfo) -> None:
        self._tasks[task.task_id] = task

    def load_all(self) -> list[TaskInfo]:
        return list(self._tasks.values())


ProgressFn = Callable[[float, float | None, str | None], Awaitable[None]]
TaskBody = Callable[[ProgressFn], Awaitable[Any]]


class TaskManager:
    """Runs task bodies in the background and tracks them."""

    def __init__(self, store: TaskStore | None = None):
        self._store: TaskStore = store or InMemoryTaskStore()
        self._tasks: dict[str, TaskInfo] = {}
        self._running: dict[str, asyncio.Task[None]] = {}
        self._changed: dict[str, asyncio.Event] = {}
        for task in self._store.load_all():
            if task.state == TaskState.RUNNING:  # left over from a previous run
                task = replace(task, state=TaskState.INTERRUPTED, finished_at=task.finished_at or _now())
                self._store.save(task)
            self._tasks[task.task_id] = task
        start = max((int(t.task_id.removeprefix("t-")) for t in self._tasks.values() if t.task_id.removeprefix("t-").isdigit()), default=0)
        self._ids = itertools.count(start + 1)

    def _update(self, task: TaskInfo) -> TaskInfo:
        self._tasks[task.task_id] = task
        self._store.save(task)
        event = self._changed.pop(task.task_id, None)
        if event is not None:
            event.set()
        return task

    def start(self, kind: str, body: TaskBody, target: str | None = None, project: str | None = None) -> TaskInfo:
        """Starts `body(progress)` in the background. Its return value (data or a Result) becomes the task's result."""
        task_id = f"t-{next(self._ids)}"
        task = self._update(TaskInfo(task_id, kind, TaskState.RUNNING, _now(), target, project))

        async def progress(done: float, total: float | None = None, message: str | None = None) -> None:
            current = self._tasks[task_id]
            if current.state == TaskState.RUNNING:
                p: dict[str, Any] = {"done": done}
                if total is not None:
                    p["total"] = total
                if message:
                    p["message"] = message
                self._update(replace(current, progress=p))

        async def run() -> None:
            try:
                result: Result = as_result(await body(progress))
                final = replace(self._tasks[task_id], finished_at=_now())
                if result.ok:
                    self._update(replace(final, state=TaskState.SUCCEEDED, result=result.to_json()))
                else:
                    self._update(replace(final, state=TaskState.FAILED, error=result.error, result=result.to_json()))
            except asyncio.CancelledError:
                current = self._tasks[task_id]
                if current.state == TaskState.RUNNING:
                    error = UlmError(CANCELLED, "The task was cancelled.").to_json()
                    self._update(replace(current, state=TaskState.CANCELLED, error=error, finished_at=_now()))
                raise
            except UlmError as e:
                self._update(replace(self._tasks[task_id], state=TaskState.FAILED, error=e.to_json(), finished_at=_now()))
            except Exception as e:
                log.exception("Task %s (%s) failed", task_id, kind)
                self._update(replace(self._tasks[task_id], state=TaskState.FAILED, error=internal_error(e).to_json(), finished_at=_now()))
            finally:
                self._running.pop(task_id, None)

        self._running[task_id] = asyncio.get_running_loop().create_task(run(), name=f"ulm-task-{task_id}")
        return task

    def get(self, task_id: str) -> TaskInfo:
        try:
            return self._tasks[task_id]
        except KeyError:
            raise UlmError(NOT_FOUND, f"No task {task_id!r}.", "task_list shows the known tasks.") from None

    def list(self, state: TaskState | None = None) -> list[TaskInfo]:
        tasks = sorted(self._tasks.values(), key=lambda t: (t.started_at, int(t.task_id.removeprefix("t-") or 0)))
        return [t for t in tasks if state is None or t.state == state]

    async def wait(self, task_id: str, timeout_s: float, on_change: Callable[[TaskInfo], Awaitable[None]] | None = None) -> TaskInfo:
        """Waits up to `timeout_s` for the task to finish, calling `on_change` whenever its state or progress changes."""
        task = self.get(task_id)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_s
        while task.state not in FINISHED:
            remaining = deadline - loop.time()
            if remaining <= 0:
                break
            event = self._changed.setdefault(task_id, asyncio.Event())
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(event.wait(), remaining)
            task = self.get(task_id)
            if on_change is not None:
                await on_change(task)
        return task

    async def cancel(self, task_id: str) -> TaskInfo:
        """Cancels a running task (a finished task is returned unchanged)."""
        task = self.get(task_id)
        running = self._running.get(task_id)
        if running is not None and task.state == TaskState.RUNNING:
            running.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await running
        return self.get(task_id)

    async def shutdown(self) -> None:
        """Cancels every running task and stores it as `interrupted`."""
        for task_id, running in list(self._running.items()):
            self._update(replace(self._tasks[task_id], state=TaskState.INTERRUPTED, finished_at=_now()))
            running.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await running
