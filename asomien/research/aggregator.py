"""
asomien/research/aggregator.py

Research Aggregator — compile, deduplicate, and rank findings.

Responsibilities:
  1. Accept raw finding dicts from multiple sources
  2. Deduplicate by exact URL and by normalized headline similarity
  3. Rank by cultural_freshness (for meme research) or headline quality (standard)
  4. Convert ranked findings to ResearchNode objects ready for MemoryEngine.store()

Deduplication strategy:
  - Primary: exact raw_url match (case-insensitive strip)
  - Secondary: normalized headline Jaccard similarity ≥ SIMILARITY_THRESHOLD
    (avoids "My Toxic Trait is X" and "my toxic trait is X" being stored twice)

No semantic embedding here (deferred to Phase 8 / V2).
All deduplication is character-level.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional

from asomien.memory.nodes import ResearchNode

logger = logging.getLogger(__name__)

# ── Deduplication constants ───────────────────────────────────────────────────
# Jaccard similarity above this threshold → treat as duplicate
SIMILARITY_THRESHOLD: float = 0.70

# ── Ranking weights ───────────────────────────────────────────────────────────
# cultural_freshness is 0–100, weighted by whether it's a meme node
_MEME_FRESHNESS_WEIGHT: float = 1.0
_STANDARD_FRESHNESS_WEIGHT: float = 0.8
_SOURCE_PRIORITY: dict[str, int] = {
    # Higher = ranked earlier in results
    "reddit": 5,
    "knowyourmeme": 4,
    "threads_keyword": 3,
    "tumblr_rss": 2,
    "duckduckgo": 1,
}


def _normalize_text(text: str) -> set[str]:
    """
    Normalize a text string into a set of lowercase word tokens for Jaccard comparison.
    Strips punctuation and splits on whitespace.
    """
    cleaned = re.sub(r"[^\w\s]", "", text.lower())
    return set(cleaned.split())


def _jaccard_similarity(a: str, b: str) -> float:
    """
    Compute word-level Jaccard similarity between two strings.

    J(A, B) = |A ∩ B| / |A ∪ B|

    Returns 0.0 if both strings are empty.
    """
    tokens_a = _normalize_text(a)
    tokens_b = _normalize_text(b)

    if not tokens_a and not tokens_b:
        return 0.0

    intersection = tokens_a & tokens_b
    union = tokens_a | tokens_b

    return len(intersection) / len(union)


def _rank_score(finding: dict[str, Any]) -> float:
    """
    Compute a ranking score for a finding dict.

    Higher score = appears earlier in ranked output.

    Formula:
        (cultural_freshness * weight) + source_priority
    """
    freshness = finding.get("cultural_freshness", 50) or 50
    is_meme = bool(finding.get("meme_format_detected", ""))
    weight = _MEME_FRESHNESS_WEIGHT if is_meme else _STANDARD_FRESHNESS_WEIGHT
    source = finding.get("source", "")
    priority = _SOURCE_PRIORITY.get(source, 0)

    return (freshness * weight) + (priority * 10)


class ResearchAggregator:
    """
    Compiles raw finding dicts from all sources into deduplicated, ranked
    ResearchNode objects.

    Usage:
        agg = ResearchAggregator()
        nodes = agg.aggregate(findings_from_all_sources)
        # nodes is a list[ResearchNode] ready for MemoryEngine.store()
    """

    def __init__(
        self,
        similarity_threshold: float = SIMILARITY_THRESHOLD,
    ) -> None:
        self._threshold = similarity_threshold

    def aggregate(
        self,
        findings: list[dict[str, Any]],
        topic_id: Optional[str] = None,
    ) -> list[ResearchNode]:
        """
        Deduplicate and rank findings, then convert to ResearchNode objects.

        Parameters
        ----------
        findings : raw finding dicts from any number of sources
        topic_id : optional — assigned to all generated ResearchNodes

        Returns
        -------
        Ranked list of ResearchNode objects (meme nodes first, then standard).
        """
        if not findings:
            return []

        # Step 1: deduplicate
        deduped = self._deduplicate(findings)
        logger.info(
            "[ResearchAggregator] %d findings → %d after dedup",
            len(findings), len(deduped),
        )

        # Step 2: rank
        ranked = sorted(deduped, key=_rank_score, reverse=True)

        # Step 3: convert to ResearchNode
        nodes: list[ResearchNode] = []
        for finding in ranked:
            node = self._finding_to_node(finding, topic_id)
            if node:
                nodes.append(node)

        logger.info("[ResearchAggregator] produced %d ResearchNodes", len(nodes))
        return nodes

    def _deduplicate(
        self,
        findings: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """
        Remove duplicate findings.

        A finding is a duplicate if:
          (a) Its raw_url (lowercased, stripped) matches an already-seen URL, OR
          (b) Its headline has Jaccard similarity ≥ threshold with an already-seen headline

        The first-seen finding (highest source priority) is kept.
        """
        seen_urls: set[str] = set()
        seen_headlines: list[str] = []
        deduped: list[dict[str, Any]] = []

        # Sort by source priority first so we keep the best-source version
        prioritized = sorted(findings, key=_rank_score, reverse=True)

        for finding in prioritized:
            url = (finding.get("raw_url") or "").lower().strip()
            headline = (finding.get("headline") or "").strip()

            # (a) URL deduplication
            if url and url in seen_urls:
                logger.debug(
                    "[ResearchAggregator] URL duplicate dropped: %s", url[:80]
                )
                continue

            # (b) Headline similarity deduplication
            is_similar = False
            for seen_hl in seen_headlines:
                sim = _jaccard_similarity(headline, seen_hl)
                if sim >= self._threshold:
                    logger.debug(
                        "[ResearchAggregator] Headline similar (%.2f) dropped: %r vs %r",
                        sim, headline[:60], seen_hl[:60],
                    )
                    is_similar = True
                    break

            if is_similar:
                continue

            # Not a duplicate — keep it
            if url:
                seen_urls.add(url)
            if headline:
                seen_headlines.append(headline)
            deduped.append(finding)

        return deduped

    @staticmethod
    def _finding_to_node(
        finding: dict[str, Any],
        topic_id: Optional[str],
    ) -> Optional[ResearchNode]:
        """
        Convert a raw finding dict to a ResearchNode.

        The ResearchNode's expiry is NOT set here — that's the MemoryEngine's
        responsibility (48h for meme nodes, 72h for standard).
        """
        try:
            return ResearchNode(
                topic_id=topic_id,
                source=finding.get("source", "duckduckgo"),
                headline=finding.get("headline", "")[:500],
                summary=finding.get("summary", "")[:1000],
                raw_url=finding.get("raw_url", "")[:2000],
                meme_format_detected=finding.get("meme_format_detected", ""),
                cultural_freshness=int(finding.get("cultural_freshness", 50) or 50),
                discovered_at=finding.get("discovered_at") or datetime.now(timezone.utc),
            )
        except Exception as exc:
            logger.warning(
                "[ResearchAggregator] _finding_to_node error: %s (finding=%r)",
                exc, str(finding)[:120],
            )
            return None
