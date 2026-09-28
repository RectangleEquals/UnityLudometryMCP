"""The state every tool shares during an MCP session: what the client supports, which tool groups are visible, the active
target and project, and the services (tasks, events, limits, budget).

ULM runs as one process per client session (stdio), so there is one `Session` per server.
"""

import logging
import os
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import mcp.types as mt
from mcp_types.version import MODERN_PROTOCOL_VERSIONS

from .budget import Budget
from .errors import SETUP_REQUIRED, UlmError
from .events import EventStore
from .limits.registry import LimitRegistry, Resolved, Scope
from .profiles.paths import resolve_profile_root
from .tasks import TaskManager

if TYPE_CHECKING:
    from fastmcp import Context
    from mcp.server.session import ServerSession

    from .profiles.store import ProfileStore

log = logging.getLogger(__name__)

TOOL_GROUPS_ENV = "ULM_TOOL_GROUPS"

# group → listed by default (02 of the design: only core groups are listed until enabled or auto-enabled).
GROUPS: dict[str, bool] = {
    "core": True,
    "code": True,
    "assets": False,
    "runtime": True,
    "instrument": False,
    "live_act": False,
    "mods": False,
}


@dataclass
class ClientSupport:
    """What the connected client supports, as far as MCP lets a server tell.

    Elicitation, sampling and roots are declared by the client. `push` says whether the server can send the client
    requests and notifications of its own (elicitation, tools/list_changed): handshake-era protocol versions can, the
    2026-07-28 era has no such back-channel. Progress is per request (the request carries a progress token), so
    `progress` records whether a request has carried one. MCP has no capability for image content or resources: every
    client must accept them, so they're assumed.
    """

    name: str | None = None
    version: str | None = None
    protocol_version: str | None = None
    push: bool = True
    elicitation: bool = False
    sampling: bool = False
    roots: bool = False
    progress: bool = False
    images: bool = True
    resources: bool = True
    capabilities: dict[str, Any] = field(default_factory=dict)

    def observe(self, ctx: "Context") -> None:
        params = ctx.session.client_params
        if params is not None:
            caps = params.capabilities
            self.name, self.version = params.client_info.name, params.client_info.version
            self.protocol_version = params.protocol_version
            self.push = params.protocol_version not in MODERN_PROTOCOL_VERSIONS
            self.elicitation = caps.elicitation is not None and self.push
            self.sampling = caps.sampling is not None
            self.roots = caps.roots is not None
            self.capabilities = caps.model_dump(mode="json", by_alias=True, exclude_none=True)
        request = ctx.request_context
        meta = request.meta if request is not None else None
        if isinstance(meta, Mapping) and meta.get("progressToken") is not None:
            self.progress = True

    def to_json(self) -> dict[str, Any] | None:
        if self.name is None:
            return None
        return {
            "name": self.name,
            "version": self.version,
            "protocol_version": self.protocol_version,
            "capabilities": self.capabilities,
            "supports": {
                "elicitation": self.elicitation,
                "list_changed": self.push,
                "progress": self.progress,
                "images": self.images,
                "resources": self.resources,
            },
        }


class ToolGroups:
    """Which tool groups are listed.

    Every tool is listed when `mode="all"` (set with ULM_TOOL_GROUPS=all) or when the server can't tell the client that
    the list changed (`list_changed_supported=False`); otherwise only the enabled groups are.
    """

    def __init__(self, mode: Literal["dynamic", "all"] = "dynamic"):
        self.configured_mode = mode
        self.list_changed_supported = True
        self._enabled = {g for g, on in GROUPS.items() if on}
        self._tools: dict[str, str] = {}
        self._notify: Callable[[], Awaitable[None]] | None = None

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "ToolGroups":
        value = (os.environ if environ is None else environ).get(TOOL_GROUPS_ENV, "").strip().lower()
        if value not in ("", "dynamic", "all"):
            log.warning("Ignoring %s=%r; expected 'dynamic' or 'all'.", TOOL_GROUPS_ENV, value)
        return cls("all" if value == "all" else "dynamic")

    def add_tool(self, name: str, group: str) -> None:
        if group not in GROUPS:
            raise ValueError(f"unknown tool group {group!r}")
        self._tools[name] = group

    def group_of(self, tool: str) -> str | None:
        return self._tools.get(tool)

    @property
    def mode(self) -> Literal["dynamic", "all"]:
        return "all" if self.configured_mode == "all" or not self.list_changed_supported else "dynamic"

    def is_enabled(self, group: str) -> bool:
        return self.mode == "all" or group in self._enabled

    def is_visible(self, tool: str) -> bool:
        group = self._tools.get(tool)
        return group is None or self.is_enabled(group)

    def enabled(self) -> list[str]:
        return [g for g in GROUPS if self.is_enabled(g)]

    def state(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "groups": {g: {"enabled": self.is_enabled(g), "tools": sorted(t for t, tg in self._tools.items() if tg == g)} for g in GROUPS},
        }

    def _check(self, groups: Iterable[str]) -> list[str]:
        groups = list(groups)
        unknown = [g for g in groups if g not in GROUPS]
        if unknown:
            raise ValueError(f"unknown tool groups: {', '.join(unknown)} (known: {', '.join(GROUPS)})")
        return groups

    async def enable(self, groups: Iterable[str]) -> list[str]:
        """Enables groups; returns those that changed (and notifies the client if any did)."""
        changed = [g for g in self._check(groups) if g not in self._enabled]
        self._enabled.update(changed)
        await self._changed(changed)
        return changed

    async def disable(self, groups: Iterable[str]) -> list[str]:
        """Disables groups (never `core`); returns those that changed."""
        groups = self._check(groups)
        if "core" in groups:
            raise ValueError("The core group can't be disabled.")
        changed = [g for g in groups if g in self._enabled]
        self._enabled.difference_update(changed)
        await self._changed(changed)
        return changed

    async def auto_enable(self, group: str, reason: str) -> bool:
        """For later features: enable a group when its preconditions become true (e.g. an agent connects)."""
        changed = await self.enable([group])
        if changed:
            log.info("Enabled tool group %s: %s", group, reason)
        return bool(changed)

    def bind_notifier(self, notify: Callable[[], Awaitable[None]]) -> None:
        self._notify = notify

    async def _changed(self, changed: list[str]) -> None:
        if changed and self.mode == "dynamic" and self._notify is not None:
            try:
                await self._notify()
            except Exception:
                log.warning("Couldn't send tools/list_changed to the client.", exc_info=True)


@dataclass(frozen=True)
class Ref:
    """A resolved target or project (filled in by the profile store)."""

    key: str
    root: Path
    artifacts: Path | None = None  # a project's `paths.artifacts` when relocated


TargetResolver = Callable[[str | None], Ref | None]
ProjectResolver = Callable[[Ref, str | None], Ref | None]


class Session:
    """Everything tools share for the life of the server."""

    def __init__(
        self,
        limits: LimitRegistry | None = None,
        groups: ToolGroups | None = None,
        budget: Budget | None = None,
        store: "ProfileStore | None" = None,
    ):
        self.client = ClientSupport()
        self.groups = groups or ToolGroups.from_env()
        self.tasks = TaskManager()
        self.events = EventStore()
        self.limits = limits or LimitRegistry.load()
        self.budget = budget or Budget()
        self._store = store
        # Hooks (replaceable, e.g. in tests); the defaults use the profile store.
        self.resolve_target: TargetResolver = self._resolve_target
        self.resolve_project: ProjectResolver = self._resolve_project
        self.consent_granted: Callable[[str, Mapping[str, Any]], bool] = lambda tool, args: False
        self.limit_scopes: Callable[[Ref | None, Ref | None], dict[Scope, dict[str, Any]]] = self._limit_scopes
        self._server_session: ServerSession | None = None
        self.groups.bind_notifier(self._send_tool_list_changed)

    @property
    def store(self) -> "ProfileStore":
        """The profile store in the profile root (SETUP_REQUIRED if ULM_HOME is invalid)."""
        if self._store is None:
            from .profiles.store import ProfileStore

            try:
                root = resolve_profile_root().path
            except ValueError as e:
                raise UlmError(SETUP_REQUIRED, str(e), "Fix or unset ULM_HOME in the MCP client's server entry.", ["ULM_HOME"]) from None
            self._store = ProfileStore(root)
        return self._store

    def _resolve_target(self, key: str | None) -> Ref | None:
        store = self.store
        key = key or store.active()[0]
        if key is None:
            return None
        target = store.open_target(key)
        return Ref(target.key, target.root)

    def _resolve_project(self, target: Ref, key: str | None) -> Ref | None:
        store = self.store
        if key is None:
            active_target, key = store.active()
            if active_target != target.key or key is None:
                return None
        project = store.open_project(target.key, key)
        return Ref(project.key, project.root, project.artifacts_dir)

    def _limit_scopes(self, target: Ref | None, project: Ref | None) -> dict[Scope, dict[str, Any]]:
        store = self.store
        scopes: dict[Scope, dict[str, Any]] = {}
        settings_limits = store.settings.load().limits
        if settings_limits:
            scopes["settings"] = dict(settings_limits)
        if target is not None:
            facts = store.open_target(target.key).facts.section("limits")
            scopes["target"] = {name: fact.value for name, fact in facts.items()}
            if project is not None:
                facts = store.open_project(target.key, project.key).facts.section("limits")
                scopes["project"] = {name: fact.value for name, fact in facts.items()}
        return scopes

    def observe(self, ctx: "Context") -> None:
        """Called at the start of every request: records client support and the session to notify."""
        self.client.observe(ctx)
        self.groups.list_changed_supported = self.client.push
        self._server_session = ctx.session

    async def _send_tool_list_changed(self) -> None:
        if self._server_session is not None:
            await self._server_session.send_notification(mt.ToolListChangedNotification())

    def limit(self, key: str, target: Ref | None = None, project: Ref | None = None, one_shot: Mapping[str, Any] | None = None) -> Resolved:
        scopes = self.limit_scopes(target, project)
        if one_shot:
            scopes = {**scopes, "one_shot": dict(one_shot)}
        return self.limits.resolve(key, scopes)

    def spill_dir(self, target: Ref | None, project: Ref | None) -> Path | None:
        """Where oversized results are written: the project's artifacts (`paths.artifacts`, default `artifacts`), else
        the target's logs, else the server logs in the profile root."""
        if project is not None:
            return (project.artifacts or project.root / "artifacts") / "results"
        if target is not None:
            return target.root / "logs" / "results"
        try:
            return resolve_profile_root().path / "logs" / "results"
        except ValueError:
            return None
