"""The event store: events from providers (the agent, the dnSpy bridge) kept in a ring.

Each event goes to the handlers registered for its kind (relays, E-STOP handling, …). An event no handler consumed
becomes a **notice**: notices are attached to the next tool result, each once and in order. Repeats of the same notice
are merged (with a count), and at most `max_notices` notices go out per result; the rest are summarised in one
`notices.more` notice and stay readable through `runtime_events`.
"""

import itertools
import logging
from collections import deque
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Event:
    seq: int
    kind: str
    source: str
    data: dict[str, Any]
    time: str

    def to_json(self) -> dict[str, Any]:
        return {"seq": self.seq, "kind": self.kind, "source": self.source, "time": self.time, "data": self.data}


Handler = Callable[[Event], Awaitable[bool]]


@dataclass
class _Notice:
    kind: str
    key: str
    data: dict[str, Any]
    first_seq: int
    last_seq: int
    count: int = 1
    extra: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"kind": self.kind, "seq": self.last_seq, **self.data}
        if self.count > 1:
            out["count"] = self.count
            out["first_seq"] = self.first_seq
        return out


class EventStore:
    """Keeps recent events, routes them to handlers, and queues the rest as notices."""

    def __init__(self, capacity: int = 1000, max_notices: int = 10):
        self._ring: deque[Event] = deque(maxlen=capacity)
        self._seq = itertools.count(1)
        self._handlers: dict[str, list[Handler]] = {}
        self._pending: dict[tuple[str, str], _Notice] = {}
        self.max_notices = max_notices

    def on(self, kind: str, handler: Handler) -> None:
        """Registers a handler for a kind. It returns True when it consumed the event (then no notice is queued)."""
        self._handlers.setdefault(kind, []).append(handler)

    async def publish(self, kind: str, data: dict[str, Any] | None = None, source: str = "agent", dedup_key: str | None = None) -> Event:
        """Records an event, runs its handlers, and queues a notice unless a handler consumed it.

        Notices with the same kind and `dedup_key` are merged while pending (default key: the event's data).
        """
        event = Event(next(self._seq), kind, source, dict(data or {}), datetime.now(UTC).isoformat(timespec="milliseconds"))
        self._ring.append(event)
        consumed = False
        for handler in self._handlers.get(kind, []):
            try:
                consumed |= await handler(event)
            except Exception:
                log.exception("Event handler for %s failed", kind)
        if not consumed:
            key = dedup_key if dedup_key is not None else repr(sorted(event.data.items()))
            pending = self._pending.get((kind, key))
            if pending is None:
                self._pending[(kind, key)] = _Notice(kind, key, event.data, event.seq, event.seq)
            else:
                pending.count += 1
                pending.last_seq = event.seq
                pending.data = event.data
        return event

    def drain_notices(self) -> list[dict[str, Any]]:
        """The pending notices in order (each is returned once), at most `max_notices` plus a summary of the rest."""
        pending = sorted(self._pending.values(), key=lambda n: n.first_seq)
        self._pending.clear()
        out = [n.to_json() for n in pending[: self.max_notices]]
        rest = pending[self.max_notices :]
        if rest:
            out.append(
                {
                    "kind": "notices.more",
                    "count": sum(n.count for n in rest),
                    "kinds": sorted({n.kind for n in rest}),
                    "since_seq": rest[0].first_seq,
                    "hint": "runtime_events returns them.",
                }
            )
        return out

    def query(self, kinds: Iterable[str] | None = None, since: int = 0, limit: int = 200) -> list[Event]:
        """Events after `since` (a seq), optionally of some kinds, oldest first, at most `limit`."""
        wanted = set(kinds) if kinds else None
        return [e for e in self._ring if e.seq > since and (wanted is None or e.kind in wanted)][:limit]

    @property
    def last_seq(self) -> int:
        return self._ring[-1].seq if self._ring else 0
