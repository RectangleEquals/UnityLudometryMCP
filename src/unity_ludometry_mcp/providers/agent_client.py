"""Client for the in-game agent: handshake, requests, events, jobs and reconnects over the shared protocol."""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from .. import __version__
from ..errors import CANCELLED, PROVIDER_UNAVAILABLE, TIMEOUT, UlmError, map_agent_error
from ..protocol import envelope
from ..protocol.base import ProtocolModel
from ..protocol.errors import ProtocolException
from ..protocol.framing import DEFAULT_MAX_FRAME_BYTES, read_frame, write_frame
from ..protocol.generated import METHODS, Methods
from ..protocol.generated.models import AgentCapabilities, AgentInfo, DiscoveryFile, JobInfo, JobRef
from ..protocol.transport import open_pipe, open_tcp
from ..protocol.version import PROTOCOL_MAJOR, PROTOCOL_MINOR, PROTOCOL_TEXT, is_compatible

log = logging.getLogger(__name__)

CLIENT_NAME = "unity-ludometry-mcp"
Streams = tuple[asyncio.StreamReader, asyncio.StreamWriter]


@dataclass(frozen=True)
class AgentEndpoint:
    """Where and how to reach an agent: its session token and a way to open a connection."""

    token: str
    open: Callable[[], Awaitable[Streams]]

    @classmethod
    def from_discovery(cls, info: DiscoveryFile) -> AgentEndpoint:
        if info.transport == "pipe" and info.pipe:
            pipe = info.pipe
            return cls(info.token, lambda: open_pipe(pipe))
        if info.transport == "tcp" and info.port:
            port = info.port
            return cls(info.token, lambda: open_tcp(port))
        raise UlmError(PROVIDER_UNAVAILABLE, "The agent's discovery file names no usable transport.")


EndpointSource = AgentEndpoint | Callable[[], Awaitable[AgentEndpoint]]


class AgentClient:
    """One logical session with an agent. Survives disconnects by reconnecting (the agent keeps session state).

    Requests in flight when the connection drops fail with PROVIDER_UNAVAILABLE and are never retried automatically:
    they may or may not have run. `BUSY` (refused before running) is retried once.
    """

    def __init__(self, endpoint: EndpointSource, *, client_version: str = __version__, default_timeout_s: float = 30.0,
                 reconnect: bool = True, backoff_initial_s: float = 0.2, backoff_max_s: float = 10.0,
                 busy_retry_delay_s: float = 0.5, max_frame_bytes: int = DEFAULT_MAX_FRAME_BYTES) -> None:
        self._endpoint = endpoint
        self._client_version = client_version
        self.default_timeout_s = default_timeout_s
        self._reconnect_enabled = reconnect
        self._backoff_initial_s = backoff_initial_s
        self._backoff_max_s = backoff_max_s
        self._busy_retry_delay_s = busy_retry_delay_s
        self._max_frame_bytes = max_frame_bytes

        self.info: AgentInfo | None = None
        self.capabilities: AgentCapabilities | None = None
        self.gaps: asyncio.Queue[tuple[int, int]] = asyncio.Queue()
        """Event sequence gaps `(expected seq, received seq)`: batches were dropped; resync with the pull methods."""

        self._ids = itertools.count(1)
        self._pending: dict[str, asyncio.Future[envelope.Response]] = {}
        self._queues: dict[str, asyncio.Queue[envelope.Event]] = {}
        self._subscriptions: dict[str, dict[str, Any]] = {}
        self._streams: Streams | None = None
        self._write_lock = asyncio.Lock()
        self._reader_task: asyncio.Task[None] | None = None
        self._reconnect_task: asyncio.Task[None] | None = None
        self._connected = asyncio.Event()
        self._closed = False
        self._in_connect = False
        self._established = False
        self._last_seq: int | None = None

    # ------------------------------------------------------------------ lifecycle

    @property
    def connected(self) -> bool:
        return self._connected.is_set()

    async def connect(self) -> AgentInfo:
        """Connects and authenticates. Raises UlmError(PROVIDER_UNAVAILABLE) if the agent refuses or is incompatible."""
        self._in_connect = True
        try:
            return await self._connect()
        finally:
            self._in_connect = False

    async def _connect(self) -> AgentInfo:
        endpoint = self._endpoint if isinstance(self._endpoint, AgentEndpoint) else await self._endpoint()
        try:
            streams = await endpoint.open()
        except OSError as e:
            raise UlmError(PROVIDER_UNAVAILABLE, f"Couldn't connect to the agent: {e}", "Is the game running with the agent installed?") from e
        self._streams = streams
        self._last_seq = None
        self._reader_task = asyncio.create_task(self._read_loop(streams), name="agent-client-reader")
        try:
            hello = {"token": endpoint.token, "client": {"name": CLIENT_NAME, "version": self._client_version},
                     "protocol": {"major": PROTOCOL_MAJOR, "minor": PROTOCOL_MINOR}}
            info = AgentInfo.model_validate(await self._send(Methods.HELLO, hello, self.default_timeout_s, None))
            if not is_compatible(info.protocol.major, info.protocol.minor):
                agent_version = f"{info.protocol.major}.{info.protocol.minor}"
                raise UlmError(PROVIDER_UNAVAILABLE, f"The agent speaks protocol {agent_version}; this orchestrator needs {PROTOCOL_TEXT}.",
                               "Install matching releases of the orchestrator and the agent.")
            self.info = info
            self._established = True
            self._connected.set()
            self.capabilities = AgentCapabilities.model_validate(await self._send(Methods.AGENT_CAPABILITIES, {}, self.default_timeout_s, None))
            for kinds in self._subscriptions.values():
                await self._send(Methods.EVENTS_SUBSCRIBE, kinds, self.default_timeout_s, None)
        except BaseException:
            self._connected.clear()
            await self._drop_connection()
            raise
        return info

    async def close(self) -> None:
        """Closes the session for good (no reconnect)."""
        self._closed = True
        if self._reconnect_task:
            self._reconnect_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reconnect_task
        await self._drop_connection()
        self._fail_pending(UlmError(PROVIDER_UNAVAILABLE, "The agent client was closed."))

    async def wait_connected(self, timeout_s: float) -> None:
        await asyncio.wait_for(self._connected.wait(), timeout_s)

    # ------------------------------------------------------------------ requests

    async def request(self, method: str, params: dict[str, Any] | ProtocolModel | None = None, *, timeout_s: float | None = None,
                      context: dict[str, Any] | None = None) -> Any:
        """Sends a request and returns the raw result. Agent errors raise the mapped UlmError."""
        if isinstance(params, ProtocolModel):
            params = params.to_json()
        if not self.connected:
            raise UlmError(PROVIDER_UNAVAILABLE, "The agent isn't connected.", "Wait for the game and the agent, then retry.")
        timeout = self.default_timeout_s if timeout_s is None else timeout_s
        try:
            return await self._send(method, params, timeout, context)
        except UlmError as e:
            if e.details.get("agentCode") == "BUSY":
                await asyncio.sleep(self._busy_retry_delay_s)
                return await self._send(method, params, timeout, context)
            if e.details.get("agentCode") == "METHOD_NOT_FOUND":
                with contextlib.suppress(UlmError):
                    self.capabilities = AgentCapabilities.model_validate(await self._send(Methods.AGENT_CAPABILITIES, {}, timeout, None))
            raise

    async def call(self, method: str, params: dict[str, Any] | ProtocolModel | None = None, **kwargs: Any) -> ProtocolModel:
        """Like `request`, but validates the result into the method's generated result model."""
        result = await self.request(method, params, **kwargs)
        return METHODS[method].result.model_validate(result)

    async def cancel(self, request_id: str) -> bool:
        """Cancels an in-flight request. Returns False if it had already finished."""
        result = await self._send(Methods.CANCEL, {"id": request_id}, self.default_timeout_s, None)
        return bool(result.get("cancelled"))

    async def _send(self, method: str, params: dict[str, Any] | None, timeout_s: float, context: dict[str, Any] | None) -> Any:
        streams = self._streams
        if streams is None:
            raise UlmError(PROVIDER_UNAVAILABLE, "The agent isn't connected.")
        request_id = f"r-{next(self._ids)}"
        request = envelope.Request(request_id, method, params, int(timeout_s * 1000) if timeout_s > 0 else None, context)
        future: asyncio.Future[envelope.Response] = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        try:
            async with self._write_lock:
                await write_frame(streams[1], envelope.serialize(request), self._max_frame_bytes)
            try:
                # The agent enforces the timeout too; the extra second lets its TIMEOUT response arrive first.
                response = await asyncio.wait_for(asyncio.shield(future), timeout_s + 1.0)
            except TimeoutError:
                with contextlib.suppress(Exception):
                    await self._send(Methods.CANCEL, {"id": request_id}, 5.0, None)
                raise UlmError(TIMEOUT, f"{method} didn't finish within {timeout_s:g} s.", "The game may be loading or hung.",
                               details={"method": method, "requestId": request_id}) from None
        except (ConnectionError, OSError) as e:
            raise UlmError(PROVIDER_UNAVAILABLE, f"The connection to the agent failed: {e}", "It may or may not have run; check before repeating.",
                           details={"method": method}) from e
        finally:
            self._pending.pop(request_id, None)
        if response.error is not None:
            raise map_agent_error(response.error, method)
        return response.result

    # ------------------------------------------------------------------ events

    async def subscribe(self, kinds: list[str], *, filter: dict[str, Any] | None = None, throttle_ms: int | None = None,
                        max_batch: int | None = None) -> dict[str, Any]:
        """Subscribes to event kinds (remembered, and renewed after reconnects). Events arrive in `events(kind)`."""
        params: dict[str, Any] = {"kinds": kinds}
        if filter is not None:
            params["filter"] = filter
        if throttle_ms is not None:
            params["throttleMs"] = throttle_ms
        if max_batch is not None:
            params["maxBatch"] = max_batch
        result = await self.request(Methods.EVENTS_SUBSCRIBE, params)
        key = ",".join(sorted(kinds))
        self._subscriptions[key] = params
        for kind in kinds:
            self.events(kind)
        return result

    async def unsubscribe(self, kinds: list[str] | None = None) -> dict[str, Any]:
        result = await self.request(Methods.EVENTS_UNSUBSCRIBE, {} if kinds is None else {"kinds": kinds})
        if kinds is None:
            self._subscriptions.clear()
        else:
            for key in [k for k, v in self._subscriptions.items() if set(v["kinds"]) <= set(kinds)]:
                del self._subscriptions[key]
        return result

    def events(self, kind: str) -> asyncio.Queue[envelope.Event]:
        """The queue receiving events of one kind."""
        return self._queues.setdefault(kind, asyncio.Queue())

    # ------------------------------------------------------------------ jobs

    async def start_job(self, method: str, params: dict[str, Any] | ProtocolModel | None = None, **kwargs: Any) -> JobRef:
        if not METHODS[method].job:
            raise ValueError(f"{method} isn't a job method")
        return JobRef.model_validate(await self.request(method, params, **kwargs))

    async def wait_job(self, job_id: str, *, timeout_s: float, poll_s: float = 10.0,
                       on_progress: Callable[[dict[str, Any]], None] | None = None) -> JobInfo:
        """Waits for a job with `job.wait` long-polls; reports `job.progress` events (if subscribed) to `on_progress`.
        Returns the finished job; a failed or cancelled job raises the mapped error."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_s
        progress_queue = self._queues.get("job.progress")
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise UlmError(TIMEOUT, f"Job {job_id} didn't finish within {timeout_s:g} s.", details={"jobId": job_id})
            info = JobInfo.model_validate(await self.request(Methods.JOB_WAIT, {"jobId": job_id, "timeoutMs": max(1, int(min(poll_s, remaining) * 1000))},
                                                             timeout_s=min(poll_s, remaining) + 5.0))
            if on_progress and progress_queue:
                while not progress_queue.empty():
                    ev = progress_queue.get_nowait()
                    if ev.params.get("jobId") == job_id:
                        on_progress(ev.params)
            if info.state == "succeeded":
                return info
            if info.state == "failed":
                error = info.error.to_json() if info.error else {"code": "INTERNAL", "message": "The job failed."}
                raise map_agent_error(error, f"job {job_id}")
            if info.state == "cancelled":
                raise UlmError(CANCELLED, f"Job {job_id} was cancelled.", details={"jobId": job_id})

    # ------------------------------------------------------------------ connection handling

    async def _read_loop(self, streams: Streams) -> None:
        reader = streams[0]
        reason: BaseException | None = None
        try:
            while True:
                payload = await read_frame(reader, self._max_frame_bytes)
                if payload is None:
                    break
                message = envelope.parse(payload)
                if isinstance(message, envelope.Response):
                    future = self._pending.get(message.id)
                    if future is not None and not future.done():
                        future.set_result(message)
                elif isinstance(message, envelope.Event):
                    self._on_event(message)
        except asyncio.CancelledError:
            raise
        except (ProtocolException, ConnectionError, OSError) as e:
            reason = e
            log.warning("agent connection failed: %s", e)
        if self._streams is streams:
            await self._on_disconnect(reason)

    def _on_event(self, event: envelope.Event) -> None:
        if self._last_seq is not None and event.seq != self._last_seq + 1:
            self.gaps.put_nowait((self._last_seq + 1, event.seq))
        self._last_seq = event.seq
        self.events(event.method).put_nowait(event)

    async def _on_disconnect(self, reason: BaseException | None) -> None:
        self._connected.clear()
        streams, self._streams = self._streams, None
        if streams is not None:
            with contextlib.suppress(Exception):
                streams[1].close()
        self._fail_pending(UlmError(PROVIDER_UNAVAILABLE, "The connection to the agent was lost.",
                                    "The request may or may not have run; check before repeating.",
                                    details={"reason": str(reason) if reason else "closed"}))
        # Only an established session is renewed; a failing connect() reports its own error instead.
        if (self._reconnect_enabled and self._established and not self._closed and not self._in_connect
                and (self._reconnect_task is None or self._reconnect_task.done())):
            self._reconnect_task = asyncio.create_task(self._reconnect_loop(), name="agent-client-reconnect")

    async def _reconnect_loop(self) -> None:
        delay = self._backoff_initial_s
        while not self._closed:
            await asyncio.sleep(delay)
            try:
                await self.connect()
                return
            except UlmError as e:
                log.info("agent reconnect failed: %s", e.message)
            delay = min(delay * 2, self._backoff_max_s)

    def _fail_pending(self, error: UlmError) -> None:
        for future in self._pending.values():
            if not future.done():
                future.set_exception(error)
        self._pending.clear()

    async def _drop_connection(self) -> None:
        streams, self._streams = self._streams, None
        task, self._reader_task = self._reader_task, None
        if streams is not None:
            with contextlib.suppress(Exception):
                streams[1].close()
        if task is not None and task is not asyncio.current_task():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task


__all__ = ["CLIENT_NAME", "AgentClient", "AgentEndpoint"]
