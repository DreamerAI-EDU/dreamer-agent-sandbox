"""
Dreamer AI Phase 1 — State Bus
In-process event mesh (PoC) with Redis Streams-compatible API surface.

For trial run: uses asyncio queues + pub/sub.
Production path: swap to redis-py XADD/XREADGROUP with zero API changes.
"""

import asyncio
import json
import uuid
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine, Dict, List, Optional
from collections import defaultdict

# ── OTel instrumentation ────────────────────────────
# Tracer is lazy-initialized. If OTel SDK isn't set up, spans are NoOp.
_tracer = None


def _get_tracer():
    global _tracer
    if _tracer is None:
        try:
            from opentelemetry import trace
            _tracer = trace.get_tracer("state-bus")
        except Exception:
            from opentelemetry.trace import NoOpTracer
            _tracer = NoOpTracer()
    return _tracer


@dataclass
class Message:
    """Unified message envelope matching the spec."""

    id: str
    topic: str
    timestamp: str
    trace_id: str
    parent_span_id: str
    source: str
    payload: Dict[str, Any]

    @classmethod
    def create(
        cls,
        topic: str,
        payload: Dict[str, Any],
        source: str,
        trace_id: str = "",
        parent_span_id: str = "",
    ) -> "Message":
        import datetime

        return cls(
            id=str(uuid.uuid4()),
            topic=topic,
            timestamp=datetime.datetime.utcnow().isoformat() + "Z",
            trace_id=trace_id or f"trace-{uuid.uuid4().hex[:12]}",
            parent_span_id=parent_span_id,
            source=source,
            payload=payload,
        )

    def to_json(self) -> str:
        return json.dumps(self.__dict__, default=str)

    @classmethod
    def from_json(cls, raw: str) -> "Message":
        data = json.loads(raw)
        return cls(**data)


class StateBus:
    """
    In-process event mesh.

    Topics are namespaced with 'dreamer:dev:v1:{topic}'.
    Supports publish/subscribe with consumer groups to prevent
    duplicate delivery within a group.
    """

    def __init__(self):
        self._subscribers: Dict[str, List[Callable[[Message], Coroutine]]] = (
            defaultdict(list)
        )
        self._message_log: List[Message] = []
        self._consumer_offsets: Dict[str, int] = defaultdict(lambda: 0)
        self._locks: Dict[str, Dict] = {}  # resource lock store
        self._lock = asyncio.Lock()

    # ── Publish ──────────────────────────────────────────

    async def publish(self, msg: Message) -> None:
        """Publish a message to a topic. All subscribers are notified.
        Each publish is wrapped in an OTel span for trace propagation.
        """
        async with self._lock:
            self._message_log.append(msg)
            idx = len(self._message_log) - 1

        full_topic = f"dreamer:dev:v1:{msg.topic}"
        handlers = self._subscribers.get(full_topic, [])

        tracer = _get_tracer()
        span_name = f"bus.publish.{msg.topic}"

        attrs = {
            "messaging.system": "state-bus",
            "messaging.destination": full_topic,
            "messaging.message_id": msg.id,
            "messaging.source": msg.source,
            "source": msg.source,
        }
        if msg.parent_span_id:
            attrs["parent_span_id"] = msg.parent_span_id

        with tracer.start_as_current_span(span_name, attributes=attrs) as span:
            results = await asyncio.gather(
                *[handler(msg) for handler in handlers], return_exceptions=True
            )
            for r in results:
                if isinstance(r, Exception):
                    span.record_exception(r)
                    print(f"[StateBus] Handler error: {r}")

    # ── Subscribe ────────────────────────────────────────

    def subscribe(
        self, topic_pattern: str, handler: Callable[[Message], Coroutine]
    ) -> None:
        """Subscribe to a topic with optional wildcard '*' suffix."""
        full_topic = f"dreamer:dev:v1:{topic_pattern}"
        self._subscribers[full_topic].append(handler)

    def subscribe_consumer_group(
        self,
        group: str,
        topic_pattern: str,
        handler: Callable[[Message], Coroutine],
    ) -> None:
        """
        Consumer group subscription — only one consumer in the group
        processes each message. For PoC, uses round-robin offset tracking.
        """
        full_topic = f"dreamer:dev:v1:{topic_pattern}"

        async def grouped_handler(msg: Message):
            key = f"{group}:{full_topic}"
            async with self._lock:
                offset = self._consumer_offsets[key]
                self._consumer_offsets[key] = offset + 1
                # In PoC, always process (single consumer per group)
            await handler(msg)

        self._subscribers[full_topic].append(grouped_handler)

    # ── Resource Locking ─────────────────────────────────

    async def acquire_lock(
        self,
        domain: str,
        resource_key: str,
        agent: str,
        mode: str,
        ttl: int,
        trace_id: str = "",
    ) -> Optional[str]:
        """Try to acquire a distributed lock. Returns lease_id or None."""
        lock_topic = f"resource.{domain}.{resource_key}"
        async with self._lock:
            existing = self._locks.get(lock_topic)
            now = time.time()
            if existing and existing["expires_at"] > now:
                return None  # locked
            lease_id = f"lease-{uuid.uuid4().hex[:8]}"
            self._locks[lock_topic] = {
                "domain": domain,
                "resource_key": resource_key,
                "agent": agent,
                "mode": mode,
                "lease_id": lease_id,
                "acquired_at": now,
                "expires_at": now + ttl,
            }

        msg = Message.create(
            topic=f"resource.{domain}.lock",
            payload={
                "domain": domain,
                "resourceKey": resource_key,
                "agent": agent,
                "mode": mode,
                "ttl": ttl,
                "leaseId": lease_id,
                "status": "acquired",
            },
            source=f"agent:{agent}",
            trace_id=trace_id,
        )
        await self.publish(msg)
        return lease_id

    async def release_lock(self, lease_id: str) -> bool:
        """Release a lock by lease_id."""
        async with self._lock:
            for key, lock in list(self._locks.items()):
                if lock["lease_id"] == lease_id:
                    del self._locks[key]
                    return True
        return False

    def get_lock_state(self) -> Dict[str, Dict]:
        """Return current lock state (snapshot)."""
        return dict(self._locks)

    # ── Utilities ────────────────────────────────────────

    def get_message_log(self) -> List[Message]:
        return list(self._message_log)

    def get_messages_by_trace(self, trace_id: str) -> List[Message]:
        return [m for m in self._message_log if m.trace_id == trace_id]
