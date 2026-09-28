"""MCP tools, one module per tool group. Each module that has tools defines `register(app)`.

Tools are functions `fn(call: ToolCall, **params)` declared with `@ulm_tool(...)`: async for I/O-bound work that awaits
(providers, tasks), plain functions for quick local work (the profile store's small files). The decorator handles
everything tools share: MCP annotations, the `user_confirmed` consent parameter, the target/project parameters and their
resolution, running long operations as tasks, notices, the token budget, and turning errors into `ok:false` results.
"""

import contextvars
import inspect
import logging
import warnings
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal
from weakref import WeakKeyDictionary

from fastmcp import Context, FastMCP
from fastmcp.server.middleware import Middleware, MiddlewareContext
from fastmcp.tools import Tool
from mcp.shared.exceptions import MCPDeprecationWarning
from mcp.types import ToolAnnotations
from pydantic import Field

from ..envelope import Result, as_result
from ..errors import CAPABILITY_UNAVAILABLE, CONSENT_REQUIRED, PROJECT_NOT_OPEN, TARGET_NOT_OPEN, UlmError, internal_error
from ..logging_setup import ClientLog, client_logs
from ..session import GROUPS, Ref, Session

log = logging.getLogger(__name__)

CONFIRM_DESCRIPTION = "Set only if the user explicitly approved this specific action in this conversation."
CONSENT_RULE = (
    "This changes something. Before calling it, tell the user in plain words what will happen and set user_confirmed only "
    "after they explicitly say yes; never decide for them."
)
TARGET_DESCRIPTION = "Target key. Defaults to the active target."
PROJECT_DESCRIPTION = "Project name. Defaults to the active project."

# none: no target needed · target: a target · project: a target and project · target_or_project: a target, and the
# project too when one is open or named.
Scope = Literal["none", "target", "project", "target_or_project"]
ProgressFn = Callable[[float, float | None, str | None], Awaitable[None]]

current_context: contextvars.ContextVar[Context | None] = contextvars.ContextVar("ulm_current_context", default=None)

_sessions: "WeakKeyDictionary[FastMCP[Any], Session]" = WeakKeyDictionary()


def session_of(app: FastMCP[Any]) -> Session:
    """The session state attached to a server (created on first use)."""
    session = _sessions.get(app)
    if session is None:
        session = _sessions[app] = Session()
    return session


def attach_session(app: FastMCP[Any], session: Session) -> Session:
    _sessions[app] = session
    return session


@dataclass
class AskOutcome:
    """The result of asking the user: an answer, a refusal, or (without elicitation) an advisory for the LLM to relay."""

    answered: bool
    value: Any = None
    declined: bool = False
    advisory: dict[str, Any] | None = None


async def ask_user(
    ctx: Context,
    session: Session,
    question: str,
    *,
    kind: Literal["setup_question", "consent_request", "capability_advisory", "limit_advisory"],
    options: Sequence[str] | None = None,
    question_id: str | None = None,
) -> AskOutcome:
    """Asks the user directly through MCP elicitation when the client supports it; otherwise returns an advisory that
    the tool puts in its result, so the LLM asks the user in chat. The LLM never answers on the user's behalf."""
    advisory: dict[str, Any] = {"kind": kind, "question": question}
    if options:
        advisory["options"] = list(options)
    if question_id:
        advisory["id"] = question_id
    if session.client.elicitation:
        try:
            response = await ctx.elicit(question, list(options) if options else str)
        except Exception:
            log.warning("Elicitation failed; asking through the LLM instead.", exc_info=True)
        else:
            if response.action == "accept":
                return AskOutcome(answered=True, value=response.data)
            return AskOutcome(answered=False, declined=True)
    return AskOutcome(answered=False, advisory=advisory)


@dataclass
class ToolCall:
    """What a tool function gets besides its parameters."""

    ctx: Context
    session: Session
    tool: str
    args: dict[str, Any]
    target: Ref | None = None
    project: Ref | None = None
    confirmed_by: Literal["user_confirmed", "elicitation", "grant"] | None = None
    one_shot_limits: dict[str, Any] = field(default_factory=dict)
    _progress: ProgressFn | None = None

    async def progress(self, done: float, total: float | None = None, message: str | None = None) -> None:
        """Reports progress (to the task, or to the client for a direct call when it asked for progress)."""
        if self._progress is not None:
            await self._progress(done, total, message)
        elif self.session.client.progress:
            await self.ctx.report_progress(done, total, message)

    def limit(self, key: str) -> Any:
        """The effective value of a limit for this call."""
        return self.session.limit(key, self.target, self.project, self.one_shot_limits).value

    async def ask(self, question: str, *, kind: Literal["setup_question", "consent_request"], options: Sequence[str] | None = None) -> AskOutcome:
        return await ask_user(self.ctx, self.session, question, kind=kind, options=options)


ToolFn = Callable[..., Any]


@dataclass(frozen=True)
class ToolSpec:
    fn: ToolFn
    name: str
    group: str
    title: str
    description: str
    read_only: bool
    destructive: bool
    idempotent: bool
    needs_confirmation: bool
    long_running: bool
    scope: Scope
    consent_question: str | None

    def annotations(self) -> ToolAnnotations:
        return ToolAnnotations(
            title=self.title,
            read_only_hint=self.read_only,
            destructive_hint=self.destructive,
            idempotent_hint=self.idempotent,
            open_world_hint=False,
        )

    def question(self, args: Mapping[str, Any]) -> str:
        if self.consent_question:
            return self.consent_question.format_map(_Missing(args))
        shown = ", ".join(f"{k}={v!r}" for k, v in args.items())
        return f"Allow {self.title.lower()}{f' ({shown})' if shown else ''}?"


class _Missing(dict[str, Any]):
    def __missing__(self, key: str) -> str:
        return "?"


def ulm_tool(
    *,
    group: str,
    title: str,
    read_only: bool = False,
    destructive: bool = False,
    idempotent: bool = False,
    needs_confirmation: bool = False,
    long_running: bool = False,
    scope: Scope = "none",
    consent_question: str | None = None,
    name: str | None = None,
) -> Callable[[ToolFn], ToolSpec]:
    """Declares a tool. The function's docstring is its description; its parameters after `call` are the tool's."""
    if group not in GROUPS:
        raise ValueError(f"unknown tool group {group!r}")
    if read_only and destructive:
        raise ValueError("a tool can't be both read-only and destructive")
    if needs_confirmation and read_only:
        raise ValueError("a read-only tool never needs the user's confirmation")

    def decorate(fn: ToolFn) -> ToolSpec:
        params = list(inspect.signature(fn).parameters)
        if not params or params[0] != "call":
            raise TypeError(f"{fn.__name__}: the first parameter must be `call: ToolCall`")
        description = inspect.cleandoc(fn.__doc__ or "")
        if not description:
            raise ValueError(f"{fn.__name__}: a tool needs a docstring (its description)")
        if needs_confirmation:
            description = f"{description}\n\n{CONSENT_RULE}"
        if long_running:
            description = f"{description}\n\nRuns as a background task: returns a task_id; task_wait returns the result."
        return ToolSpec(
            fn, name or fn.__name__, group, title, description, read_only, destructive, idempotent, needs_confirmation, long_running, scope, consent_question
        )

    return decorate


def _signature(spec: ToolSpec) -> inspect.Signature:
    original = list(inspect.signature(spec.fn).parameters.values())[1:]
    extra: list[inspect.Parameter] = []
    keyword = inspect.Parameter.KEYWORD_ONLY
    if spec.scope != "none":
        extra.append(inspect.Parameter("target", keyword, default=None, annotation=Annotated[str | None, Field(description=TARGET_DESCRIPTION)]))
    if spec.scope in ("project", "target_or_project"):
        extra.append(inspect.Parameter("project", keyword, default=None, annotation=Annotated[str | None, Field(description=PROJECT_DESCRIPTION)]))
    if spec.needs_confirmation:
        extra.append(inspect.Parameter("user_confirmed", keyword, default=False, annotation=Annotated[bool, Field(description=CONFIRM_DESCRIPTION)]))
    extra.append(inspect.Parameter("ctx", keyword, annotation=Context))
    params = [p.replace(kind=keyword) for p in original] + extra
    return inspect.Signature(params, return_annotation=dict[str, Any])


def _resolve_scope(spec: ToolSpec, session: Session, kwargs: dict[str, Any]) -> tuple[Ref | None, Ref | None]:
    if spec.scope == "none":
        return None, None
    target_key = kwargs.pop("target", None)
    project_key = kwargs.pop("project", None) if spec.scope in ("project", "target_or_project") else None
    target = session.resolve_target(target_key)
    if target is None:
        raise UlmError(
            TARGET_NOT_OPEN,
            f"No target {target_key!r} is open." if target_key else "No target is open.",
            "Open a target first (target_open), or pass `target`.",
            ["target"],
        )
    project = None
    if spec.scope in ("project", "target_or_project"):
        project = session.resolve_project(target, project_key)
        if project is None and (spec.scope == "project" or project_key):
            raise UlmError(PROJECT_NOT_OPEN, "No project is open.", "Open or create a project first, or pass `project`.", ["project"])
    return target, project


async def _consent(spec: ToolSpec, call: ToolCall, user_confirmed: bool) -> Result | None:
    """None when the call may proceed; otherwise the CONSENT_REQUIRED result."""
    if user_confirmed:
        call.confirmed_by = "user_confirmed"
    elif call.session.consent_granted(spec.name, call.args):
        call.confirmed_by = "grant"
    else:
        question = spec.question(call.args)
        outcome = await ask_user(call.ctx, call.session, question, kind="consent_request", options=["yes", "no"])
        if outcome.answered and outcome.value == "yes":
            call.confirmed_by = "elicitation"
        elif outcome.answered or outcome.declined:
            return UlmError(
                CONSENT_REQUIRED, "The user declined.", "Don't retry unless the user asks for it.", details={"question": question, "declined": True}
            ).to_result()
        else:
            result = UlmError(
                CONSENT_REQUIRED,
                "This needs the user's explicit approval.",
                "Ask the user the question, then call again with user_confirmed=true only if they say yes.",
                ["user_confirmed"],
                {"question": question},
            ).to_result()
            result.advisories.append({**(outcome.advisory or {}), "tool": spec.name})
            return result
    log.info("Consent for %s given via %s: %s", spec.name, call.confirmed_by, call.args)
    return None


def _make_handler(spec: ToolSpec) -> Callable[..., Awaitable[dict[str, Any]]]:
    async def handler(**kwargs: Any) -> dict[str, Any]:
        ctx: Context = kwargs.pop("ctx")
        session = session_of(ctx.fastmcp)
        session.observe(ctx)
        token = current_context.set(ctx)
        logs: list[ClientLog] = []
        logs_token = client_logs.set(logs)
        target = project = None
        try:
            user_confirmed = bool(kwargs.pop("user_confirmed", False))
            if not session.groups.is_visible(spec.name):
                raise UlmError(
                    CAPABILITY_UNAVAILABLE,
                    f"The {spec.group} tool group is disabled.",
                    f"Enable it with tools_enable(groups=['{spec.group}']).",
                    [f"tools_enable:{spec.group}"],
                )
            target, project = _resolve_scope(spec, session, kwargs)
            call = ToolCall(ctx, session, spec.name, dict(kwargs), target, project)
            refused = await _consent(spec, call, user_confirmed) if spec.needs_confirmation else None
            if refused is not None:
                result = refused
            elif spec.long_running:
                result = _start_task(spec, call)
            else:
                result = as_result(await _run(spec.fn, call, kwargs))
        except UlmError as e:
            result = e.to_result()
        except Exception as e:
            log.exception("Tool %s failed", spec.name)
            result = internal_error(e).to_result()
        finally:
            current_context.reset(token)
            client_logs.reset(logs_token)
        await _mirror_logs(ctx, session, logs)
        return finish(session, result, target, project)

    handler.__name__ = spec.name
    handler.__doc__ = spec.description
    signature = _signature(spec)
    handler.__signature__ = signature  # type: ignore[attr-defined]
    handler.__annotations__ = {p.name: p.annotation for p in signature.parameters.values()} | {"return": dict[str, Any]}
    return handler


async def _mirror_logs(ctx: Context, session: Session, logs: list[ClientLog]) -> None:
    """Sends the call's warnings and errors to the client as MCP log messages. Only handshake-era connections carry
    them: the 2026-07-28 protocol dropped server logging, so there they stay in the server log."""
    if not logs or not session.client.push:
        return
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", MCPDeprecationWarning)
        for level, message, logger_name in logs:
            try:
                await ctx.log(message, level=level, logger_name=logger_name)
            except Exception:  # the client is gone or doesn't take log messages
                break


async def _run(fn: ToolFn, call: ToolCall, kwargs: Mapping[str, Any]) -> Any:
    value = fn(call, **kwargs)
    return await value if inspect.isawaitable(value) else value


def _start_task(spec: ToolSpec, call: ToolCall) -> Result:
    async def body(progress: ProgressFn) -> Any:
        call._progress = progress
        return await _run(spec.fn, call, call.args)

    task = call.session.tasks.start(spec.name, body, call.target.key if call.target else None, call.project.key if call.project else None)
    return Result(data={"task_id": task.task_id, "state": task.state.value, "hint": "Call task_wait with this task_id for the result."}, task_id=task.task_id)


def finish(session: Session, result: Result, target: Ref | None = None, project: Ref | None = None) -> dict[str, Any]:
    """Attaches pending notices, applies the token budget, and serializes the envelope.

    This never fails the call: if the scopes can't be read (a damaged profile, an invalid ULM_HOME), the shipped
    limit and no spill folder are used, and the problem is logged.
    """
    result.notices.extend(session.events.drain_notices())
    result.target = target.key if target else None
    result.project = project.key if project else None
    try:
        max_tokens = session.limit("response.max_tokens", target, project).value
        spill_dir = session.spill_dir(target, project)
    except Exception:
        log.warning("Couldn't read the limit scopes; using the shipped response limit.", exc_info=True)
        max_tokens, spill_dir = session.limits.resolve("response.max_tokens").value, None
    session.budget.fit(result, max_tokens, spill_dir)
    return result.to_json()


def register_tools(app: FastMCP[Any], specs: Sequence[ToolSpec]) -> None:
    """Registers tools with the server and records their groups."""
    session = session_of(app)
    for spec in specs:
        session.groups.add_tool(spec.name, spec.group)
        tool = Tool.from_function(
            _make_handler(spec),
            name=spec.name,
            title=spec.title,
            description=spec.description,
            annotations=spec.annotations(),
            tags={f"group:{spec.group}"},
        )
        app.add_tool(tool)


class GroupVisibility(Middleware):
    """Lists only the tools of enabled groups (every tool when groups are in `all` mode)."""

    async def on_list_tools(self, context: MiddlewareContext[Any], call_next: Any) -> Any:
        tools = await call_next(context)
        ctx = context.fastmcp_context
        if ctx is None:
            return tools
        session = session_of(ctx.fastmcp)
        session.observe(ctx)
        return [t for t in tools if session.groups.is_visible(t.name)]
