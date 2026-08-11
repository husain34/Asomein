"""
asomien/agents/analytics_agent.py

Analytics agent for collecting post metrics and audience snapshots.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import date, datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from asomien.agents.base_agent import BaseAgent
from asomien.memory.migrations import run_migrations
from asomien.memory.nodes import MetricsSnapshot
from asomien.platforms.base_platform import BasePlatformAdapter

logger = logging.getLogger(__name__)


class AnalyticsAgent(BaseAgent):
    """Collect metrics from the Threads adapter and write append-only snapshots."""

    def __init__(
        self,
        adapter: Optional[BasePlatformAdapter] = None,
        metrics_db_path: str = "data/metrics.db",
    ) -> None:
        super().__init__(name="AnalyticsAgent")
        self.adapter = adapter
        self.metrics_db_path = metrics_db_path
        # FIX BUG-02: Run migrations once at init, not on every _connect() call.
        run_migrations(
            memory_db_path="data/memory.db",
            metrics_db_path=self.metrics_db_path,
            directives_db_path="data/directives.db",
        )

    def run(self) -> None:
        self.start()
        self.log_action(
            action="analytics_cycle",
            reason="scheduled analytics collection",
        )

        try:
            from types import SimpleNamespace

            # 1. Query the last 100 published posts (root posts + quotes + replies) from memory.db.
            # 100 covers ~50 days of posting at max 2 root posts/day, plus all quotes and replies.
            with sqlite3.connect("data/memory.db") as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute(
                    """
                    SELECT id, threads_post_id
                    FROM posts
                    WHERE status = 'published'
                      AND threads_post_id != ''
                      AND threads_post_id IS NOT NULL
                    ORDER BY COALESCE(actual_publish_time, created_at) DESC
                    LIMIT 100
                    """
                )
                rows = cursor.fetchall()

            # 2. Collect metrics and store snapshots
            for row in rows:
                post = SimpleNamespace(id=row["id"], threads_post_id=row["threads_post_id"])
                try:
                    # FIX BUG-01: collect_post_metrics() now correctly stores exactly once.
                    # Removed redundant self._store_snapshot(snapshot) from here.
                    snapshot = self.collect_post_metrics(post)
                    logger.debug("[AnalyticsAgent] Stored metrics snapshot for post %s", post.id)
                except Exception as e:
                    logger.error("[AnalyticsAgent] Failed to collect metrics for post %s: %s", post.id, e)

        except Exception as e:
            logger.error("[AnalyticsAgent] Error in analytics cycle: %s", e)

        self.stop()

    def _connect(self) -> sqlite3.Connection:
        # FIX BUG-02: Migrations removed from here — now called once in __init__.
        conn = sqlite3.connect(self.metrics_db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        return conn

    def _store_snapshot(self, snapshot: MetricsSnapshot) -> None:
        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO post_metrics (id, post_id, threads_post_id, snapshot_time, views, likes, replies, reposts, quotes, shares, creator_engagement_score) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    snapshot.id,
                    snapshot.post_id,
                    snapshot.threads_post_id,
                    snapshot.snapshot_time.isoformat(),
                    snapshot.views,
                    snapshot.likes,
                    snapshot.replies,
                    snapshot.reposts,
                    snapshot.quotes,
                    snapshot.shares,
                    snapshot.creator_engagement_score,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def compute_creator_engagement_score(self, metrics: dict[str, Any]) -> float:
        views = max(int(metrics.get("views", 0) or 0), 1)
        likes = int(metrics.get("likes", 0) or 0)
        replies = int(metrics.get("replies", 0) or 0)
        reposts = int(metrics.get("reposts", 0) or 0)
        quotes = int(metrics.get("quotes", 0) or 0)
        return (likes * 1 + replies * 27 + reposts * 5 + quotes * 8) / views

    def collect_post_metrics(self, post: Any) -> MetricsSnapshot:
        if self.adapter is None:
            raise RuntimeError("AnalyticsAgent requires an adapter")

        post_id = getattr(post, "id", str(post))
        threads_post_id = getattr(post, "threads_post_id", "")
        if not threads_post_id:
            threads_post_id = str(post_id)

        payload = self.adapter.get_post_metrics(threads_post_id)
        metric_fields = {
            "views": 0,
            "likes": 0,
            "replies": 0,
            "reposts": 0,
            "quotes": 0,
            "shares": 0,
        }

        def _safe_int(value: Any) -> int:
            try:
                return int(value)
            except (TypeError, ValueError):
                return 0

        # Support both the legacy flat payload shape and the Meta nested insights shape.
        for key in metric_fields:
            if key in payload:
                metric_fields[key] = _safe_int(payload.get(key))

        data = payload.get("data")
        if isinstance(data, list):
            for item in data:
                if not isinstance(item, dict):
                    continue
                name = item.get("name")
                if name not in metric_fields:
                    continue
                values = item.get("values")
                if isinstance(values, list) and values:
                    first_value = values[0]
                    if isinstance(first_value, dict):
                        metric_fields[name] = _safe_int(first_value.get("value"))
        elif isinstance(data, dict):
            for key in metric_fields:
                if key in data:
                    metric_fields[key] = _safe_int(data.get(key))

        snapshot = MetricsSnapshot(
            post_id=post_id,
            threads_post_id=threads_post_id,
            views=metric_fields["views"],
            likes=metric_fields["likes"],
            replies=metric_fields["replies"],
            reposts=metric_fields["reposts"],
            quotes=metric_fields["quotes"],
            shares=metric_fields["shares"],
        )
        snapshot.creator_engagement_score = self.compute_creator_engagement_score(
            {
                "views": snapshot.views,
                "likes": snapshot.likes,
                "replies": snapshot.replies,
                "reposts": snapshot.reposts,
                "quotes": snapshot.quotes,
            }
        )
        # FIX BUG-01: Restored _store_snapshot() call here so external callers
        # (and tests) get the data stored. The double-store was fixed by removing
        # the extra _store_snapshot() call from the run() loop.
        self._store_snapshot(snapshot)
        return snapshot

    def collect_audience_snapshot(self) -> dict[str, Any]:
        if self.adapter is None:
            raise RuntimeError("AnalyticsAgent requires an adapter")

        payload = self.adapter.get_audience_insights()

        followers_count = int(payload.get("followers_count", 0))
        # FIX BUG-04: Use proper try/finally with explicit None init to prevent leaks.
        conn = None
        try:
            conn = self._connect()
            snapshot_id = str(uuid4())
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                "INSERT INTO audience_snapshots (id, snapshot_time, followers_count) VALUES (?, ?, ?)",
                (snapshot_id, now, followers_count)
            )
            conn.commit()
            logger.debug("[AnalyticsAgent] Stored audience snapshot with %s followers", followers_count)
        except Exception as e:
            logger.error("[AnalyticsAgent] Failed to store audience snapshot: %s", e)
        finally:
            if conn is not None:
                conn.close()

        return payload

    def aggregate_daily_stats(self, date_str: Optional[str] = None) -> dict[str, Any]:
        day = date_str or date.today().isoformat()
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT COUNT(*) AS count, SUM(views) AS views, SUM(likes) AS likes, SUM(replies) AS replies, SUM(reposts) AS reposts, SUM(quotes) AS quotes, SUM(shares) AS shares, AVG(creator_engagement_score) AS avg_score FROM post_metrics WHERE date(snapshot_time) = ?",
                (day,),
            ).fetchone()
            result = {
                "date": day,
                "posts_published": int(row["count"] or 0),
                "total_views": int(row["views"] or 0),
                "total_likes": int(row["likes"] or 0),
                "total_replies_received": int(row["replies"] or 0),
                "total_reposts": int(row["reposts"] or 0),
                "total_quotes": int(row["quotes"] or 0),
                "total_shares": int(row["shares"] or 0),
                "avg_creator_engagement_score": float(row["avg_score"] or 0.0),
            }

            # Persist daily stats so dashboard and weekly analysis can read them
            try:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO daily_stats
                        (id, date, posts_published, total_views, total_likes,
                         total_replies_received, total_reposts, total_quotes,
                         total_shares, avg_creator_engagement_score)
                    VALUES (lower(hex(randomblob(8))), ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        result["date"],
                        result["posts_published"],
                        result["total_views"],
                        result["total_likes"],
                        result["total_replies_received"],
                        result["total_reposts"],
                        result["total_quotes"],
                        result["total_shares"],
                        result["avg_creator_engagement_score"],
                    ),
                )
                conn.commit()
            except Exception as e:
                logger.error("[AnalyticsAgent] Failed to persist daily stats: %s", e)

            return result
        finally:
            conn.close()

    def get_latest_metrics(self) -> Optional[dict[str, Any]]:
        """Return the most recent day's aggregated stats."""
        try:
            return self.aggregate_daily_stats()
        except Exception as e:
            logger.error("[AnalyticsAgent] get_latest_metrics failed: %s", e)
            return None

    def get_posts_published_today(self) -> int:
        """Return count of posts published today (used by scheduler guards)."""
        try:
            today = date.today().isoformat()
            with sqlite3.connect("data/memory.db") as conn:
                row = conn.execute(
                    "SELECT COUNT(*) FROM posts WHERE status='published' AND is_reply=0 AND date(created_at)=?",
                    (today,)
                ).fetchone()
                return int(row[0] or 0)
        except Exception as e:
            logger.error("[AnalyticsAgent] get_posts_published_today failed: %s", e)
            return 0

    def get_hours_since_last_post(self) -> float:
        """Return hours since the last published post (used by scheduler guards)."""
        try:
            with sqlite3.connect("data/memory.db") as conn:
                row = conn.execute(
                    "SELECT MAX(COALESCE(actual_publish_time, created_at)) FROM posts WHERE status='published' AND is_reply=0"
                ).fetchone()
                if row and row[0]:
                    from datetime import datetime, timezone
                    last_dt = datetime.fromisoformat(row[0].replace("Z", "+00:00"))
                    if last_dt.tzinfo is None:
                        last_dt = last_dt.replace(tzinfo=timezone.utc)
                    delta = datetime.now(timezone.utc) - last_dt
                    return delta.total_seconds() / 3600.0
        except Exception as e:
            logger.error("[AnalyticsAgent] get_hours_since_last_post failed: %s", e)
        return 999.0


    def log_warmup_day(self, day_number: Optional[int] = None) -> None:
        # FIX BUG-03: The old fallback used strftime("%d") which gives the calendar
        # day of the month (1-31), not the sequential warmup day counter.
        # Now we query the DB for the next sequential day number.
        if day_number is None:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT MAX(day_number) as max_day FROM warmup_log"
                ).fetchone()
                max_day = row["max_day"] if row and row["max_day"] is not None else 0
                day_number = max_day + 1
            except Exception as e:
                logger.error("[AnalyticsAgent] Failed to determine warmup day number: %s", e)
                day_number = 1
            finally:
                conn.close()

        conn = self._connect()
        try:
            conn.execute(
                "INSERT OR IGNORE INTO warmup_log (id, day_number, posts_published, replies_published, phase_status, logged_at) VALUES (?, ?, 0, 0, ?, ?)",
                (
                    str(uuid4()),
                    day_number,
                    "active",
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            conn.commit()
        finally:
            conn.close()
