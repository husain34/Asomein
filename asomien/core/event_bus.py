"""
asomien/core/event_bus.py

In-process event bus backed by the SQLite events table in memory.db.

All inter-agent communication goes through this bus. Events are persisted
to the database so they survive restarts and provide an audit trail.

Event types (from blueprint Section 2):
    RESEARCH_COMPLETE       — Research Agent → Content Agent
    POST_CREATED            — Content Agent  → Publisher
    POST_PUBLISHED          — Publisher      → Analytics Agent
    METRICS_UPDATED         — Analytics      → Critic Agent
    REFLECTION_COMPLETE     — Critic Agent   → Memory Engine
    REPLY_RECEIVED          — Engagement     → Content Agent
    DIRECTIVE_ISSUED        — Human Control  → Orchestrator
    SLEEP_TRIGGERED         — Orchestrator   → Critic Agent
    WARMUP_PHASE_ACTIVE     — Orchestrator   → All Agents
    WARMUP_PHASE_COMPLETE   — Orchestrator   → All Agents

Blueprint reference: Section 5 (EventBus class), Section 12 Step 5.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

# ── Canonical event types ─────────────────────────────────────────────────────

class EventType:
    RESEARCH_COMPLETE       = "RESEARCH_COMPLETE"
    POST_CREATED            = "POST_CREATED"
    POST_PUBLISHED          = "POST_PUBLISHED"
    METRICS_UPDATED         = "METRICS_UPDATED"
    REFLECTION_COMPLETE     = "REFLECTION_COMPLETE"
    REPLY_RECEIVED          = "REPLY_RECEIVED"
    DIRECTIVE_ISSUED        = "DIRECTIVE_ISSUED"
    SLEEP_TRIGGERED         = "SLEEP_TRIGGERED"
    WARMUP_PHASE_ACTIVE     = "WARMUP_PHASE_ACTIVE"
    WARMUP_PHASE_COMPLETE   = "WARMUP_PHASE_COMPLETE"

    ALL = {
        RESEARCH_COMPLETE, POST_CREATED, POST_PUBLISHED, METRICS_UPDATED,
        REFLECTION_COMPLETE, REPLY_RECEIVED, DIRECTIVE_ISSUED, SLEEP_TRIGGERED,
        WARMUP_PHASE_ACTIVE, WARMUP_PHASE_COMPLETE,
    }


# ── EventBus ──────────────────────────────────────────────────────────────────

class EventBus:
    """
    Lightweight event bus backed by the SQLite events table.

    Events flow between agents asynchronously via publish/subscribe.
    Subscribers are in-memory callbacks; published events are also persisted
    to SQLite for audit and replay after restarts.

    Usage:
        bus = EventBus(db_path="data/memory.db")

        # Subscribe to an event type
        bus.subscribe(EventType.POST_PUBLISHED, analytics_agent.on_post_published)

        # Publish an event
        bus.publish(
            event_type=EventType.POST_PUBLISHED,
            payload={"post_id": "abc-123"},
            producer="publisher",
        )

        # Consume and dispatch all pending events from DB
        bus.consume_pending()
    """

    def __init__(self, db_path: str = "data/memory.db") -> None:
        self.db_path = db_path
        # In-memory subscriber registry: event_type → list of callbacks
        self._subscribers: dict[str, list[Callable[[dict[str, Any]], None]]] = {}
        logger.info(f"[EventBus] initialized. db={db_path}")

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    # ── Subscription ─────────────────────────────────────────────────────────

    def subscribe(
        self,
        event_type: str,
        callback: Callable[[dict[str, Any]], None],
    ) -> None:
        """
        Register a callback for a specific event type.
        Callbacks are invoked synchronously in consume_pending().

        Args:
            event_type: One of the EventType constants (or any custom string).
            callback:   Function that accepts the event payload dict.
        """
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(callback)
        logger.debug(f"[EventBus] subscribed to '{event_type}': {callback.__qualname__}")

    def unsubscribe(
        self,
        event_type: str,
        callback: Callable[[dict[str, Any]], None],
    ) -> bool:
        """
        Remove a specific callback from an event type.
        Returns True if found and removed, False if not found.
        """
        subscribers = self._subscribers.get(event_type, [])
        if callback in subscribers:
            subscribers.remove(callback)
            logger.debug(f"[EventBus] unsubscribed from '{event_type}': {callback.__qualname__}")
            return True
        return False

    # ── Publishing ────────────────────────────────────────────────────────────

    def publish(
        self,
        event_type: str,
        payload: Optional[dict[str, Any]] = None,
        producer: str = "system",
        consumer: Optional[str] = None,
    ) -> str:
        """
        Publish an event. The event is:
          1. Persisted to the SQLite events table (status='pending').
          2. Immediately dispatched to all in-memory subscribers.

        Args:
            event_type: One of the EventType constants.
            payload:    JSON-serializable dict of event data.
            producer:   Identifier of the agent/module publishing (for audit).
            consumer:   Expected consumer (optional; for routing intent audit).

        Returns:
            The event ID (UUID string).
        """
        event_id = str(uuid.uuid4())
        payload_json = json.dumps(payload or {})

        # Persist to DB
        conn = self._get_conn()
        try:
            conn.execute(
                """
                INSERT INTO events (id, event_type, payload, produced_by, consumed_by, status, created_at)
                VALUES (?, ?, ?, ?, ?, 'pending', ?)
                """,
                (event_id, event_type, payload_json, producer, consumer, self._now_iso()),
            )
            conn.commit()
        finally:
            conn.close()

        logger.info(f"[EventBus] published: {event_type} (id={event_id}, producer={producer})")

        # Immediately dispatch to in-memory subscribers
        self._dispatch(event_id, event_type, payload or {})

        return event_id

    def _dispatch(
        self,
        event_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        """Invoke all registered callbacks for event_type."""
        callbacks = self._subscribers.get(event_type, [])
        if not callbacks:
            logger.debug(f"[EventBus] no subscribers for '{event_type}'.")
            return

        for callback in callbacks:
            try:
                callback(payload)
                logger.debug(
                    f"[EventBus] dispatched '{event_type}' to {callback.__qualname__}"
                )
            except Exception as exc:
                logger.error(
                    f"[EventBus] error in subscriber {callback.__qualname__} "
                    f"for event '{event_type}' (id={event_id}): {exc}",
                    exc_info=True,
                )
                # Do not re-raise — event bus errors must not crash the publisher

        # Mark event as consumed in DB
        self._mark_consumed(event_id, consumer=", ".join(
            cb.__qualname__ for cb in callbacks
        ))

    def _mark_consumed(self, event_id: str, consumer: str) -> None:
        """Mark an event as consumed in the SQLite events table."""
        conn = self._get_conn()
        try:
            conn.execute(
                """
                UPDATE events
                SET status='consumed', consumed_at=?, consumed_by=?
                WHERE id=?
                """,
                (self._now_iso(), consumer, event_id),
            )
            conn.commit()
        finally:
            conn.close()

    # ── Consume pending ───────────────────────────────────────────────────────

    def consume_pending(self, limit: int = 100) -> int:
        """
        Fetch and dispatch all events with status='pending' from the database.
        Used to replay events after a restart.

        Args:
            limit: Maximum events to process in one call (default: 100).

        Returns:
            Number of events dispatched.
        """
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                """
                SELECT id, event_type, payload
                FROM events
                WHERE status = 'pending'
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (limit,),
            )
            rows = cursor.fetchall()
        finally:
            conn.close()

        count = 0
        for row in rows:
            try:
                payload = json.loads(row["payload"] or "{}")
                self._dispatch(row["id"], row["event_type"], payload)
                count += 1
            except Exception as exc:
                logger.error(
                    f"[EventBus] failed to dispatch pending event "
                    f"id={row['id']}: {exc}",
                    exc_info=True,
                )

        if count:
            logger.info(f"[EventBus] consumed {count} pending events from DB.")

        return count

    # ── Introspection ─────────────────────────────────────────────────────────

    def get_pending_count(self) -> int:
        """Return the number of pending events in the database."""
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                "SELECT COUNT(*) FROM events WHERE status = 'pending';"
            )
            return cursor.fetchone()[0]
        finally:
            conn.close()

    def get_recent_events(
        self,
        limit: int = 50,
        event_type: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """
        Retrieve recent events from the database for monitoring.

        Args:
            limit:      Maximum events to return.
            event_type: Filter by event type (optional).

        Returns:
            List of event dicts with keys: id, event_type, payload, produced_by,
            status, created_at, consumed_at.
        """
        conn = self._get_conn()
        try:
            if event_type:
                cursor = conn.execute(
                    """
                    SELECT id, event_type, payload, produced_by, consumed_by,
                           status, created_at, consumed_at
                    FROM events
                    WHERE event_type = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (event_type, limit),
                )
            else:
                cursor = conn.execute(
                    """
                    SELECT id, event_type, payload, produced_by, consumed_by,
                           status, created_at, consumed_at
                    FROM events
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (limit,),
                )
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()
