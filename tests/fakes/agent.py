"""A fake in-game agent that speaks the real protocol, answering from the golden fixtures.

It implements the agent's transport (named pipe or TCP), discovery file, handshake rules, mode checks, events and jobs,
validates every incoming request against the schemas, and supports failure injection (errors, delays, disconnects,
sequence gaps). Later milestones drive the whole tool layer against it.
"""

from __future__ import annotations

import asyncio
import contextlib
import copy
import functools
import hashlib
import itertools
import json
import os
import pathlib
import secrets
import sys
import uuid
from dataclasses import dataclass, field
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from fakes.fixtures import FILE_FIXTURES, PROTOCOL, FixtureCase, load_agent_fixtures
from unity_ludometry_mcp.protocol import envelope, json_codec
from unity_ludometry_mcp.protocol.base import AgentMode, mode_rank
from unity_ludometry_mcp.protocol.errors import ProtocolException
from unity_ludometry_mcp.protocol.framing import encode_frame, read_frame
from unity_ludometry_mcp.protocol.generated import EVENTS, METHODS, Methods
from unity_ludometry_mcp.protocol.version import PROTOCOL_MAJOR, PROTOCOL_MINOR

SCHEMA_BASE = "https://github.com/RectangleEquals/UnityLudometryMCP/protocol/schema/"
JOB_KINDS = {
    "il.index.start": "il.index",
    "survey.start": "survey",
    "obj.query.start": "query",
    "resources.loadAll": "resources.loadAll",
    "content.export.start": "content.export",
    "content.scan.start": "content.scan",
    "trace.start": "trace",
    "profile.start": "profile",
    "test.run": "test.run",
    "metrics.sample.start": "metrics.sample",
    "probe.runBatch": "probe.batch",
}
JOB_FILES = {
    "survey.start": "survey",
    "il.index.start": "il_index",
    "content.scan.start": "content_scan",
    "trace.start": "trace",
    "metrics.sample.start": "metrics",
}


def _schema_registry() -> Registry:
    resources = []
    for path in (PROTOCOL / "schema").rglob("*.schema.json"):
        doc = json.loads(path.read_text(encoding="utf-8"))
        resources.append((doc["$id"], Resource.from_contents(doc)))
    return Registry().with_resources(resources)


_REGISTRY = _schema_registry()


@functools.cache
def params_validator(method: str) -> Draft202012Validator:
    return Draft202012Validator({"$ref": f"{SCHEMA_BASE}methods/{method}.schema.json#/$defs/params"}, registry=_REGISTRY)


@functools.cache
def _fixture_answers() -> dict[str, list[FixtureCase]]:
    """Success fixtures by method (loaded once per process)."""
    answers: dict[str, list[FixtureCase]] = {}
    for f in load_agent_fixtures():
        if not f.is_event and not f.is_generic and f.request_valid and f.response and "result" in f.response:
            answers.setdefault(f.group, []).append(f)
    return answers


@dataclass
class _Connection:
    writer: asyncio.StreamWriter
    authenticated: bool = False
    kinds: set[str] = field(default_factory=set)
    seq: int = 0
    write_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    in_flight: dict[str, asyncio.Task[None]] = field(default_factory=dict)

    async def send(self, message: envelope.Envelope) -> None:
        async with self.write_lock:
            self.writer.write(encode_frame(envelope.serialize(message)))
            await self.writer.drain()


@dataclass
class _Job:
    id: str
    kind: str
    method: str
    result: dict[str, Any] | None
    state: str = "queued"
    started_at: str | None = None
    finished_at: str | None = None
    error: dict[str, Any] | None = None
    done: asyncio.Event = field(default_factory=asyncio.Event)

    def info(self) -> dict[str, Any]:
        d: dict[str, Any] = {"jobId": self.id, "kind": self.kind, "state": self.state, "startedAt": self.started_at, "finishedAt": self.finished_at}
        if self.state == "succeeded":
            d["result"] = self.result
        if self.error:
            d["error"] = self.error
        return d


class FakeAgent:
    """Start with `await agent.start()`; connect through the discovery file it writes into `providers_dir`."""

    def __init__(
        self,
        providers_dir: pathlib.Path,
        *,
        transport: str = "pipe",
        mode: AgentMode = "ReadOnly",
        protocol: tuple[int, int] = (PROTOCOL_MAJOR, PROTOCOL_MINOR),
        pid: int | None = None,
        process_path: str | None = None,
        job_duration_s: float = 0.05,
    ) -> None:
        self.providers_dir = pathlib.Path(providers_dir)
        self.transport = transport
        self.mode: AgentMode = mode
        self.protocol = protocol
        self.pid = os.getpid() if pid is None else pid
        self.process_path = process_path or sys.executable
        self.token = secrets.token_hex(32)
        self.job_duration_s = job_duration_s
        self.pipe_name = f"ulm-agent-test-{uuid.uuid4().hex[:12]}"
        self.port: int | None = None

        self.fail: dict[str, dict[str, Any]] = {}
        """Method → error object `{code, message, data?}` to answer with (failure injection)."""
        self.fail_times: dict[str, int] = {}
        """Method → how many times `fail` applies (default: always)."""
        self.delay_s: dict[str, float] = {}
        self.received: list[envelope.Request] = []
        self.handlers: dict[str, Any] = {}
        """Method → `callable(params) -> result` overriding the fixture answer."""

        self._fixtures = _fixture_answers()
        self._connections: list[_Connection] = []
        self._server: Any = None
        self._jobs: dict[str, _Job] = {}
        self._job_ids = itertools.count(1)
        self._started_at = "2026-09-27T10:00:00.000Z"
        self.discovery_path = self.providers_dir / f"agent-{self.pid}.json"

    # ------------------------------------------------------------------ lifecycle

    async def start(self) -> FakeAgent:
        loop = asyncio.get_running_loop()
        if self.transport == "pipe":
            address = "\\\\.\\pipe\\" + self.pipe_name
            self._server = await loop.start_serving_pipe(  # type: ignore[attr-defined]
                lambda: asyncio.StreamReaderProtocol(asyncio.StreamReader(), self._on_connection), address
            )
        else:
            self._server = await asyncio.start_server(self._on_connection, "127.0.0.1", 0)
            self.port = self._server.sockets[0].getsockname()[1]
        self.write_discovery()
        return self

    def write_discovery(self) -> None:
        self.providers_dir.mkdir(parents=True, exist_ok=True)
        info = {
            "provider": "agent",
            "pid": self.pid,
            "processName": pathlib.Path(self.process_path).stem,
            "processPath": self.process_path,
            "transport": self.transport,
            "pipe": self.pipe_name if self.transport == "pipe" else None,
            "port": self.port if self.transport == "tcp" else None,
            "token": self.token,
            "protocol": {"major": self.protocol[0], "minor": self.protocol[1]},
            "agentVersion": "0.1.0",
            "loader": {"name": "BepInEx", "version": "5.4.23.5"},
            "unityVersion": "2021.3.45f1",
            "mode": self.mode,
            "startedAt": self._started_at,
        }
        tmp = self.discovery_path.with_suffix(".tmp")
        tmp.write_bytes(json_codec.dumps(info))
        os.replace(tmp, self.discovery_path)

    async def stop(self) -> None:
        await self.drop_connections()
        if self._server is not None:
            if self.transport == "pipe":
                for server in self._server:
                    server.close()
            else:
                self._server.close()
                await self._server.wait_closed()
            self._server = None
        with contextlib.suppress(FileNotFoundError):
            self.discovery_path.unlink()

    async def drop_connections(self) -> None:
        """Closes every client connection (the session and its jobs survive, like the real agent)."""
        for conn in list(self._connections):
            with contextlib.suppress(Exception):
                conn.writer.close()
        self._connections.clear()
        await asyncio.sleep(0)

    # ------------------------------------------------------------------ events

    async def emit(self, kind: str, params: dict[str, Any], *, skip_seq: int = 0, context: dict[str, Any] | None = None) -> None:
        """Sends an event to every connection subscribed to `kind`. `skip_seq` simulates dropped batches."""
        for conn in list(self._connections):
            if kind in conn.kinds:
                conn.seq += 1 + skip_seq
                with contextlib.suppress(Exception):
                    await conn.send(envelope.Event(kind, conn.seq, params, context))

    # ------------------------------------------------------------------ connection handling

    async def _on_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        conn = _Connection(writer)
        self._connections.append(conn)
        try:
            while True:
                payload = await read_frame(reader)
                if payload is None:
                    break
                try:
                    message = envelope.parse(payload)
                except ProtocolException as e:
                    await conn.send(envelope.Response("?", error=e.to_error()))
                    break
                if not isinstance(message, envelope.Request):
                    continue
                self.received.append(message)
                if not conn.authenticated:
                    if not await self._handshake(conn, message):
                        break
                    continue
                task = asyncio.create_task(self._dispatch(conn, message))
                conn.in_flight[message.id] = task
                task.add_done_callback(lambda _t, rid=message.id: conn.in_flight.pop(rid, None))
        except (ConnectionError, OSError, ProtocolException):
            pass
        finally:
            with contextlib.suppress(ValueError):
                self._connections.remove(conn)
            with contextlib.suppress(Exception):
                writer.close()

    async def _handshake(self, conn: _Connection, request: envelope.Request) -> bool:
        def refuse(code: str, message: str) -> envelope.Response:
            return envelope.Response(request.id, error={"code": code, "message": message}, context=request.context)

        if request.method != Methods.HELLO:
            await conn.send(refuse("HANDSHAKE_REQUIRED", "The first request on a connection must be hello."))
            return False
        params = request.params or {}
        if params.get("token") != self.token:
            await conn.send(refuse("BAD_TOKEN", "The session token is not valid for this agent."))
            return False
        client = params.get("protocol", {})
        if (client.get("major"), client.get("minor")) != self.protocol:
            await conn.send(refuse("PROTOCOL_MISMATCH", f"Client protocol {client.get('major')}.{client.get('minor')} is not compatible."))
            return False
        conn.authenticated = True
        await conn.send(envelope.Response(request.id, self._agent_info(), context=request.context))
        return True

    async def _dispatch(self, conn: _Connection, request: envelope.Request) -> None:
        try:
            result = await self._handle(conn, request)
            response = envelope.Response(request.id, result, context=request.context)
        except ProtocolException as e:
            response = envelope.Response(request.id, error=e.to_error(), context=request.context)
        except asyncio.CancelledError:
            response = envelope.Response(request.id, error={"code": "CANCELLED", "message": "Cancelled."}, context=request.context)
        with contextlib.suppress(Exception):
            await conn.send(response)

    async def _handle(self, conn: _Connection, request: envelope.Request) -> Any:
        method, params = request.method, request.params or {}
        descriptor = METHODS.get(method)
        if descriptor is None:
            raise ProtocolException("METHOD_NOT_FOUND", f"Unknown method '{method}'.", {"hint": "Check agent.capabilities."})
        error = next(iter(sorted(params_validator(method).iter_errors(params), key=lambda e: list(e.path))), None)
        if error is not None:
            path = "params" + "".join(f".{p}" if isinstance(p, str) else f"[{p}]" for p in error.path)
            raise ProtocolException("INVALID_PARAMS", f"{path}: {error.message}", {"param": path})
        if mode_rank(descriptor.min_mode) > mode_rank(self.mode):
            raise ProtocolException(
                "MODE_FORBIDDEN", f"{method} requires mode {descriptor.min_mode}; the agent is in {self.mode}.", {"requiredMode": descriptor.min_mode}
            )
        if method in self.fail and self.fail_times.get(method, 1) > 0:
            if method in self.fail_times:
                self.fail_times[method] -= 1
            injected = self.fail[method]
            raise ProtocolException(injected["code"], injected.get("message", injected["code"]), injected.get("data"))
        if method in self.delay_s:
            await asyncio.sleep(self.delay_s[method])
        if method in self.handlers:
            return self.handlers[method](params)

        if method == Methods.PING:
            return {**({"echo": params["echo"]} if "echo" in params else {}), "uptimeMs": 1000, "frame": 42}
        if method == Methods.AGENT_INFO:
            return self._agent_info()
        if method == Methods.AGENT_CAPABILITIES:
            return self._capabilities()
        if method == Methods.CANCEL:
            task = conn.in_flight.get(params["id"])
            if task is not None and not task.done():
                task.cancel()
                return {"cancelled": True}
            return {"cancelled": False}
        if method == Methods.EVENTS_SUBSCRIBE:
            known = [k for k in params["kinds"] if k in EVENTS]
            conn.kinds.update(known)
            return {"subscribed": known, "unknown": [k for k in params["kinds"] if k not in EVENTS]}
        if method == Methods.EVENTS_UNSUBSCRIBE:
            kinds = params.get("kinds", sorted(conn.kinds))
            removed = [k for k in kinds if k in conn.kinds]
            conn.kinds.difference_update(removed)
            return {"unsubscribed": removed}
        if method in (Methods.JOB_GET, Methods.JOB_WAIT, Methods.JOB_CANCEL):
            job = self._jobs.get(params["jobId"])
            if job is None:
                raise ProtocolException("NOT_FOUND", f"Unknown job {params['jobId']}.")
            if method == Methods.JOB_WAIT:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(job.done.wait(), params.get("timeoutMs", 30000) / 1000)
            if method == Methods.JOB_CANCEL:
                cancelled = job.state in ("queued", "running")
                if cancelled:
                    job.state, job.finished_at = "cancelled", "2026-09-27T10:00:02.000Z"
                    job.done.set()
                return {"cancelled": cancelled, "state": job.state}
            return job.info()
        if method == Methods.JOB_LIST:
            return {"items": [j.info() for j in self._jobs.values() if params.get("state") in (None, j.state)]}
        if descriptor.job:
            return self._start_job(method, params)
        return self._fixture_answer(method, params)

    # ------------------------------------------------------------------ answers

    def _fixture_answer(self, method: str, params: dict[str, Any]) -> Any:
        cases = self._fixtures.get(method)
        if not cases:
            raise ProtocolException("INTERNAL", f"The fake agent has no fixture for {method}.")
        # Prefer the "ok" fixture when several fixtures send these params (e.g. "ok" and "minimal").
        matches = sorted((c for c in cases if (c.request or {}).get("params", {}) == params), key=lambda c: not c.id.endswith("/ok"))
        chosen = matches[0] if matches else next((c for c in cases if c.id.endswith("/ok")), cases[0])
        return copy.deepcopy(chosen.response["result"])

    def _start_job(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        job_id = f"j-{next(self._job_ids)}"
        fixture = next((c for c in self._fixtures.get(method, []) if c.job_result is not None and c.id.endswith("/ok")), None)
        job = _Job(job_id, JOB_KINDS[method], method, copy.deepcopy(fixture.job_result) if fixture else {})
        self._jobs[job_id] = job
        asyncio.get_running_loop().create_task(self._run_job(job, params))
        return {"jobId": job_id, "kind": job.kind}

    async def _run_job(self, job: _Job, params: dict[str, Any]) -> None:
        job.state, job.started_at = "running", "2026-09-27T10:00:01.000Z"
        total = 3
        for done in range(1, total + 1):
            await asyncio.sleep(self.job_duration_s / total)
            if job.state != "running":
                return
            await self.emit("job.progress", {"jobId": job.id, "kind": job.kind, "progress": {"phase": "scan", "done": done, "total": total}})
        out_file = params.get("outFile")
        example = FILE_FIXTURES / JOB_FILES.get(job.method, "") / "example.ndjson"
        if out_file and job.method in JOB_FILES and example.exists():
            data = example.read_bytes()
            await asyncio.to_thread(pathlib.Path(out_file).write_bytes, data)
            footer = json.loads(data.decode("utf-8").rstrip("\n").split("\n")[-1])
            file_info = {"path": out_file, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "counts": footer["counts"]}
            if isinstance(job.result, dict) and "file" in job.result:
                job.result["file"] = file_info
        if job.state == "running":
            job.state, job.finished_at = "succeeded", "2026-09-27T10:00:02.000Z"
            job.done.set()
            await self.emit("job.finished", {"job": job.info()})

    def _agent_info(self) -> dict[str, Any]:
        return {
            "agentVersion": "0.1.0",
            "gitCommit": None,
            "protocol": {"major": self.protocol[0], "minor": self.protocol[1]},
            "pid": self.pid,
            "processName": pathlib.Path(self.process_path).stem,
            "unityVersion": "2021.3.45f1",
            "scriptingBackend": "mono",
            "platform": "WindowsPlayer",
            "loader": {"name": "BepInEx", "version": "5.4.23.5"},
            "mode": self.mode,
            "transport": self.transport,
            "startedAt": self._started_at,
            "uptimeMs": 1000,
            "limits": {},
            "health": {
                "pump": {"alive": True, "lastTickFrame": 42, "queueLength": 0, "stalledMs": 0, "recreatedCount": 0},
                "connections": len(self._connections),
            },
        }

    def _capabilities(self) -> dict[str, Any]:
        return {
            "agentVersion": "0.1.0",
            "apiVersion": "0.1",
            "protocol": {"major": self.protocol[0], "minor": self.protocol[1]},
            "methods": [
                {
                    "name": d.name,
                    "thread": d.thread.value,
                    "minMode": d.min_mode,
                    "mutating": d.mutating,
                    "job": d.job,
                    **({"requires": list(d.requires)} if d.requires else {}),
                }
                for d in METHODS.values()
            ],
            "eventKinds": sorted(EVENTS),
            "modules": [{"name": "ugui", "available": True, "version": None}],
            "limits": {},
        }
