"""
asomien/memory/engine.py

TRACE-XP Memory Engine — Phase 2 implementation.

Provides:
  - store()            : persist a node to SQLite (topics, research_nodes, posts,
                          reflections, rules)
  - retrieve()         : keyword + recency-weighted search across research_nodes;
                          automatically expires stale nodes before returning results
  - assemble_context() : build a prompt-ready context dict from recent/relevant
                          research nodes and the last N posts for a given topic

Expiry rules (hardcoded from blueprint Section 10 / SAFETY_CONFIG):
  - meme research nodes   → 48 hours  (meme_format_detected is non-empty)
  - standard research     → 72 hours

No semantic search in this phase (deferred to Phase 8 / V2).
"""

from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Generator, Optional

from asomien.memory.nodes import (
    PostNode,
    ReflectionNode,
    ResearchNode,
    RuleNode,
    TopicNode,
)

logger = logging.getLogger(__name__)

# ── Expiry constants ──────────────────────────────────────────────────────────
MEME_EXPIRY_HOURS: int = 48     # meme research: cultural freshness decays fast
STANDARD_EXPIRY_HOURS: int = 72  # standard research nodes

# ── Retrieval weights ─────────────────────────────────────────────────────────
# Keyword match in headline contributes more than in summary alone.
_HEADLINE_KEYWORD_WEIGHT: float = 2.0
_SUMMARY_KEYWORD_WEIGHT: float = 1.0
# Recency bonus: nodes discovered within the last 6 hours get a bump.
_RECENCY_THRESHOLD_HOURS: int = 6
_RECENCY_BONUS: float = 1.5


class MemoryEngine:
    """
    Thin SQLite wrapper for the TRACE-XP memory system.

    Each MemoryEngine instance is bound to the path of memory.db.
    The database must already be initialised (run_migrations must have been
    called before instantiating this class).

    Thread-safety: each public method opens and closes its own connection,
    which is safe for the single-threaded agent loop. For concurrent access,
    use WAL mode (already enforced by migrations.py).
    """

    def __init__(self, db_path: str = "data/memory.db") -> None:
        self.db_path = db_path
        logger.info("[MemoryEngine] Initialised with db_path=%s", db_path)

    # ── Internal helpers ──────────────────────────────────────────────────────

    @contextmanager
    def _connect(self) -> Generator[sqlite3.Connection, None, None]:
        """Context manager: open a WAL-mode connection and close when done."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row          # enable column-name access
        conn.execute("PRAGMA journal_mode=WAL;")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def _utc_now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _compute_expiry(node: ResearchNode) -> datetime:
        """
        Return the correct expiry datetime for a ResearchNode.

        Rules (blueprint Section 10):
          - meme_format_detected is non-empty → MEME_EXPIRY_HOURS  (48 h)
          - otherwise                         → STANDARD_EXPIRY_HOURS (72 h)
        """
        hours = (
            MEME_EXPIRY_HOURS
            if node.meme_format_detected and node.meme_format_detected.strip()
            else STANDARD_EXPIRY_HOURS
        )
        return node.discovered_at + timedelta(hours=hours)

    # ── store() ───────────────────────────────────────────────────────────────

    def store(self, node: Any) -> str:
        """
        Persist a memory node to SQLite.

        Supported node types:
            TopicNode, ResearchNode, PostNode, ReflectionNode, RuleNode

        For ResearchNode: expiry is computed automatically using the 48h/72h
        rule if the node does not already have an expiry set.

        Returns the node's id.
        """
        if isinstance(node, TopicNode):
            self._store_topic(node)
        elif isinstance(node, ResearchNode):
            # Auto-assign expiry if not already set
            if node.expiry is None:
                node.expiry = self._compute_expiry(node)
            self._store_research_node(node)
        elif isinstance(node, PostNode):
            self._store_post(node)
        elif isinstance(node, ReflectionNode):
            self._store_reflection(node)
        elif isinstance(node, RuleNode):
            self._store_rule(node)
        else:
            raise TypeError(
                f"[MemoryEngine.store] Unsupported node type: {type(node).__name__}"
            )
        logger.debug("[MemoryEngine.store] Stored %s id=%s", type(node).__name__, node.id)
        return node.id

    def _store_topic(self, node: TopicNode) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO topics
                    (id, name, parent_id, relevance_score, niche_alignment,
                     last_researched, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    node.id,
                    node.name,
                    node.parent_id,
                    node.relevance_score,
                    node.niche_alignment,
                    node.last_researched.isoformat() if node.last_researched else None,
                    node.created_at.isoformat(),
                ),
            )

    def _store_research_node(self, node: ResearchNode) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO research_nodes
                    (id, topic_id, source, headline, summary, raw_url,
                     meme_format_detected, cultural_freshness,
                     discovered_at, expiry, is_active)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    node.id,
                    node.topic_id,
                    node.source,
                    node.headline,
                    node.summary,
                    node.raw_url,
                    node.meme_format_detected,
                    node.cultural_freshness,
                    node.discovered_at.isoformat(),
                    node.expiry.isoformat() if node.expiry else None,
                    1 if node.is_active else 0,
                ),
            )

    def _store_post(self, node: PostNode) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO posts
                    (id, topic_id, platform, content, post_type, status,
                     scheduled_publish_time, actual_publish_time,
                     jitter_offset_minutes, posted_at,
                     threads_post_id, threads_container_id, permalink,
                     hook_template_used, is_reply, reply_to_threads_id,
                     is_sponsored, sponsor_campaign_id, pre_score, summary,
                     created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    node.id,
                    node.topic_id,
                    node.platform,
                    node.content,
                    node.post_type,
                    node.status,
                    node.scheduled_publish_time.isoformat() if node.scheduled_publish_time else None,
                    node.actual_publish_time.isoformat() if node.actual_publish_time else None,
                    node.jitter_offset_minutes,
                    node.posted_at.isoformat() if node.posted_at else None,
                    node.threads_post_id,
                    node.threads_container_id,
                    node.permalink,
                    node.hook_template_used,
                    1 if node.is_reply else 0,
                    node.reply_to_threads_id,
                    1 if node.is_sponsored else 0,
                    node.sponsor_campaign_id,
                    json.dumps(node.pre_score) if node.pre_score else None,
                    node.summary,
                    node.created_at.isoformat(),
                ),
            )

    def _store_reflection(self, node: ReflectionNode) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO reflections
                    (id, post_id, hook_template_used, sub_niche, generated_at,
                     success_factors, failure_factors, hypotheses,
                     lessons_learned, confidence)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    node.id,
                    node.post_id,
                    node.hook_template_used,
                    node.sub_niche,
                    node.generated_at.isoformat(),
                    json.dumps(node.success_factors),
                    json.dumps(node.failure_factors),
                    json.dumps(node.hypotheses),
                    json.dumps(node.lessons_learned),
                    node.confidence,
                ),
            )

    def _store_rule(self, node: RuleNode) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO rules
                    (id, rule_text, confidence, evidence, created_at,
                     last_validated, validation_count, decay_rate, is_active)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    node.id,
                    node.rule_text,
                    node.confidence,
                    json.dumps(node.evidence),
                    node.created_at.isoformat(),
                    node.last_validated.isoformat() if node.last_validated else None,
                    node.validation_count,
                    node.decay_rate,
                    1 if node.is_active else 0,
                ),
            )

    # ── Expiry enforcement ────────────────────────────────────────────────────

    def expire_stale_nodes(self) -> int:
        """
        Mark all research_nodes whose expiry has passed as is_active=0.

        Called automatically by retrieve() before fetching results, and can
        also be called manually by a maintenance job.

        Returns the number of rows deactivated.
        """
        now_iso = self._utc_now().isoformat()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE research_nodes
                SET    is_active = 0
                WHERE  is_active = 1
                  AND  expiry IS NOT NULL
                  AND  expiry <= ?
                """,
                (now_iso,),
            )
            count = cursor.rowcount
        if count:
            logger.info("[MemoryEngine.expire_stale_nodes] Expired %d nodes.", count)
        return count

    # ── retrieve() ────────────────────────────────────────────────────────────

    def retrieve(
        self,
        query: str,
        topic_id: Optional[str] = None,
        limit: int = 10,
        include_meme_only: bool = False,
    ) -> list[dict[str, Any]]:
        """
        Keyword + recency-weighted retrieval of active ResearchNodes.

        Algorithm (no semantic search — deferred to Phase 8):
          1. Expire stale nodes first (enforce 48h/72h TTL).
          2. Fetch all active nodes for the topic (or globally if topic_id is None).
          3. Score each node:
             - +HEADLINE_KEYWORD_WEIGHT per keyword found in headline
             - +SUMMARY_KEYWORD_WEIGHT  per keyword found in summary
             - +RECENCY_BONUS if discovered within last RECENCY_THRESHOLD_HOURS
             - +cultural_freshness normalised to 0–1 as a tiebreaker
          4. Sort by score descending, return top `limit` results as dicts.

        Parameters
        ----------
        query           : free-text search string; split on whitespace into keywords
        topic_id        : optional; restrict search to a single topic
        limit           : max results to return
        include_meme_only: if True, only return nodes where meme_format_detected != ''

        Returns
        -------
        List of dicts with all research_node columns plus a synthetic `_score` key.
        """
        # Step 1: expire stale nodes
        self.expire_stale_nodes()

        # Step 2: fetch active candidate nodes
        with self._connect() as conn:
            if topic_id:
                cursor = conn.execute(
                    """
                    SELECT * FROM research_nodes
                    WHERE is_active = 1 AND topic_id = ?
                    ORDER BY discovered_at DESC
                    """,
                    (topic_id,),
                )
            else:
                cursor = conn.execute(
                    """
                    SELECT * FROM research_nodes
                    WHERE is_active = 1
                    ORDER BY discovered_at DESC
                    """
                )
            rows = [dict(r) for r in cursor.fetchall()]

        if not rows:
            return []

        # Step 3: score rows
        keywords = [kw.lower().strip() for kw in query.split() if kw.strip()]
        now = self._utc_now()
        recency_cutoff = now - timedelta(hours=_RECENCY_THRESHOLD_HOURS)

        scored: list[tuple[float, dict[str, Any]]] = []
        for row in rows:
            # Meme-only filter
            if include_meme_only and not row.get("meme_format_detected", ""):
                continue

            score = 0.0
            headline = (row.get("headline") or "").lower()
            summary = (row.get("summary") or "").lower()
            matches_found = 0

            for kw in keywords:
                if kw in headline:
                    score += _HEADLINE_KEYWORD_WEIGHT
                    matches_found += 1
                if kw in summary:
                    score += _SUMMARY_KEYWORD_WEIGHT
                    matches_found += 1
            
            # Apply keyword gate if query is not empty
            if keywords and matches_found == 0:
                continue

            # Recency bonus
            discovered_raw = row.get("discovered_at", "")
            if discovered_raw:
                try:
                    # SQLite stores as ISO string without timezone
                    discovered_dt = datetime.fromisoformat(
                        discovered_raw.replace("Z", "+00:00")
                    )
                    # Make timezone-aware if naive
                    if discovered_dt.tzinfo is None:
                        discovered_dt = discovered_dt.replace(tzinfo=timezone.utc)
                    if discovered_dt >= recency_cutoff:
                        score += _RECENCY_BONUS
                except (ValueError, TypeError):
                    pass

            # Cultural freshness as tiebreaker (0–100 → 0.0–1.0)
            score += (row.get("cultural_freshness", 0) or 0) / 100.0

            scored.append((score, row))

        # Step 4: sort by score descending, inject _score, return top N
        scored.sort(key=lambda t: t[0], reverse=True)
        results = []
        for rank_score, row in scored[:limit]:
            row["_score"] = round(rank_score, 4)
            results.append(row)

        logger.debug(
            "[MemoryEngine.retrieve] query=%r → %d results (limit=%d)",
            query, len(results), limit,
        )
        return results

    def similarity_search(self, query: str, limit: int = 3) -> list[dict[str, Any]]:
        """
        Perform a semantic similarity search across recent posts.
        Fetches the latest 100 posts, vectorizes them on the fly, and returns the top matches.
        """
        try:
            from asomien.memory.embedder import Embedder
            import numpy as np
        except ImportError:
            logger.warning("[MemoryEngine] Embedder or numpy not available. Falling back to keyword search.")
            return self.retrieve(query=query, limit=limit)
            
        embedder = Embedder()
        query_vec = np.array(embedder.get_embedding(query))
        
        with self._connect() as conn:
            cursor = conn.execute(
                "SELECT * FROM posts ORDER BY created_at DESC LIMIT 100"
            )
            rows = [dict(r) for r in cursor.fetchall()]
            
        if not rows:
            return []
            
        texts = [row.get("content", "") for row in rows]
        doc_vecs = np.array(embedder.encode(texts))
        
        if doc_vecs.size == 0 or query_vec.size == 0:
            return rows[:limit]
            
        # Cosine similarity
        query_norm = np.linalg.norm(query_vec)
        doc_norms = np.linalg.norm(doc_vecs, axis=1)
        
        # Avoid division by zero
        query_norm = query_norm if query_norm > 0 else 1e-10
        doc_norms = np.where(doc_norms > 0, doc_norms, 1e-10)
        
        similarities = np.dot(doc_vecs, query_vec) / (doc_norms * query_norm)
        
        for i, row in enumerate(rows):
            row["_similarity_score"] = float(similarities[i])
            
        rows.sort(key=lambda r: r.get("_similarity_score", 0), reverse=True)
        return rows[:limit]

    # ── assemble_context() ────────────────────────────────────────────────────

    def assemble_context(
        self,
        topic_id: Optional[str] = None,
        query: str = "",
        max_research_nodes: int = 5,
        max_recent_posts: int = 100,
    ) -> dict[str, Any]:
        """
        Build a prompt-ready context dictionary for the Content Agent.

        Returns a dict with:
          - "topic"         : TopicNode dict (or None)
          - "research"      : list of scored ResearchNode dicts (active only)
          - "recent_posts"  : list of recent PostNode dicts for the topic
          - "meme_formats"  : list of unique meme_format_detected values from research
          - "freshness_avg" : average cultural_freshness across research nodes

        This structure is designed to be serialised as JSON and injected directly
        into the system prompt by the Content Agent.
        """
        context: dict[str, Any] = {
            "topic": None,
            "research": [],
            "recent_posts": [],
            "meme_formats": [],
            "freshness_avg": 0.0,
        }

        # Resolve topic
        if topic_id:
            with self._connect() as conn:
                cursor = conn.execute(
                    "SELECT * FROM topics WHERE id = ?", (topic_id,)
                )
                row = cursor.fetchone()
                if row:
                    context["topic"] = dict(row)

        # Research nodes — use retrieve() so expiry is enforced + scores are set
        research_results = self.retrieve(
            query=query,
            topic_id=topic_id,
            limit=max_research_nodes,
        )
        context["research"] = research_results

        # Meme formats used
        context["meme_formats"] = list(
            {
                r["meme_format_detected"]
                for r in research_results
                if r.get("meme_format_detected", "")
            }
        )

        # Average cultural freshness
        if research_results:
            total_freshness = sum(
                r.get("cultural_freshness", 0) or 0 for r in research_results
            )
            context["freshness_avg"] = round(total_freshness / len(research_results), 2)

        # Recent posts for topic
        with self._connect() as conn:
            if topic_id:
                cursor = conn.execute(
                    """
                    SELECT * FROM posts
                    WHERE topic_id = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (topic_id, max_recent_posts),
                )
            else:
                cursor = conn.execute(
                    """
                    SELECT * FROM posts
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (max_recent_posts,),
                )
            context["recent_posts"] = [dict(r) for r in cursor.fetchall()]

        logger.debug(
            "[MemoryEngine.assemble_context] topic_id=%s → %d research, %d posts",
            topic_id,
            len(context["research"]),
            len(context["recent_posts"]),
        )
        return context

    # ── Utility accessors ─────────────────────────────────────────────────────

    def get_research_node(self, node_id: str) -> Optional[dict[str, Any]]:
        """Fetch a single research node by id (regardless of active status)."""
        with self._connect() as conn:
            cursor = conn.execute(
                "SELECT * FROM research_nodes WHERE id = ?", (node_id,)
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_active_research_count(self, topic_id: Optional[str] = None) -> int:
        """Return count of is_active=1 research nodes, optionally filtered by topic."""
        with self._connect() as conn:
            if topic_id:
                cursor = conn.execute(
                    "SELECT COUNT(*) FROM research_nodes WHERE is_active=1 AND topic_id=?",
                    (topic_id,),
                )
            else:
                cursor = conn.execute(
                    "SELECT COUNT(*) FROM research_nodes WHERE is_active=1"
                )
            return cursor.fetchone()[0]

    def consolidate(self) -> None:
        """Consolidate memory during sleep mode."""
        logger.info("[MemoryEngine.consolidate] Consolidating memory...")
        count = self.expire_stale_nodes()
        logger.info("[MemoryEngine.consolidate] Consolidation complete. Expired %d nodes.", count)
