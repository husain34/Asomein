"""
asomien/agents/research_agent.py

Research Agent — orchestrates all research sources, aggregates findings,
and stores them in the MemoryEngine with correct expiry flags.

Blueprint spec (Section 5 / Step 10):
  - scan_trending_meme_formats() → Reddit r/memes, r/me_irl, r/teenagers, r/dankmemes
  - scan_pop_culture_moments()  → Tumblr RSS + Know Your Meme
  - keyword_search_bluesky()    → Bluesky searchPosts on NICHE_KEYWORDS
  - search_web()                → DuckDuckGo context enrichment
  - store_findings()            → ResearchAggregator → MemoryEngine.store()

CRITICAL GUARANTEE: When a finding has meme_format_detected set (non-empty),
the ResearchNode is stored with that field populated, which triggers
MemoryEngine._compute_expiry() to assign the 48-hour expiry (vs 72h standard).
This is the mechanism that activates "digital amnesia" for stale memes.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from asomien.agents.base_agent import BaseAgent
from asomien.memory.engine import MemoryEngine
from asomien.memory.nodes import ResearchNode
from asomien.research.aggregator import ResearchAggregator
from asomien.research.sources.bluesky_keyword_source import (
    NICHE_KEYWORDS,
    BlueskyKeywordSource,
)
from asomien.research.sources.ddg_source import DuckDuckGoSource
from asomien.research.sources.knowyourmeme_source import KnowYourMemeSource
from asomien.research.sources.reddit_source import RedditSource
from asomien.research.sources.tumblr_source import TumblrRSSSource
from asomien.llm.client import NIMClient

logger = logging.getLogger(__name__)


class ResearchAgent(BaseAgent):
    """
    Orchestrates all research sources and stores findings in the MemoryEngine.

    Dependencies injected at construction time — all sources can be
    replaced with mocks in tests.

    Usage (production):
        agent = ResearchAgent(
            memory=MemoryEngine(),
            reddit_source=RedditSource(reddit=praw.Reddit(...)),
            tumblr_source=TumblrRSSSource(),
            kym_source=KnowYourMemeSource(),
            bluesky_source=BlueskyKeywordSource(handle="...", app_password="..."),
            ddg_source=DuckDuckGoSource(),
        )
        agent.run()  # runs a single full research cycle

    Usage (tests — all sources mocked):
        agent = ResearchAgent(
            memory=MemoryEngine(db_path=":memory:"),
            reddit_source=mock_reddit,
            tumblr_source=mock_tumblr,
            ...
        )
    """

    def __init__(
        self,
        memory: MemoryEngine,
        reddit_source: Optional[RedditSource] = None,
        tumblr_source: Optional[TumblrRSSSource] = None,
        kym_source: Optional[KnowYourMemeSource] = None,
        bluesky_source: Optional[BlueskyKeywordSource] = None,
        ddg_source: Optional[DuckDuckGoSource] = None,
        aggregator: Optional[ResearchAggregator] = None,
        topic_id: Optional[str] = None,
        llm_client: Optional[NIMClient] = None,
    ) -> None:
        super().__init__(name="ResearchAgent")
        self.memory = memory
        self.reddit_source = reddit_source
        self.tumblr_source = tumblr_source
        self.kym_source = kym_source
        self.bluesky_source = bluesky_source
        self.ddg_source = ddg_source
        self.aggregator = aggregator or ResearchAggregator()
        self.topic_id = topic_id
        # FIX BUG-20: Accept llm_client as an optional constructor parameter,
        # consistent with all other agents. If not provided, instantiate from
        # settings (which reads NVIDIA_NIM_API_KEY from the environment).
        # Previously NIMClient() was always created here without passing api_key,
        # which was inconsistent with main.py always passing api_key= explicitly.
        if llm_client is not None:
            self.llm_client = llm_client
        else:
            try:
                from asomien.config.settings import settings
                self.llm_client = NIMClient(api_key=settings.nvidia_nim_api_key)
            except Exception:
                self.llm_client = NIMClient()  # fallback: reads env var internally

    # FIX BUG-19: BaseAgent.run() is annotated -> None. Overriding with -> int
    # violates the Liskov Substitution Principle and breaks mypy/type checkers.
    # We store the count as self.last_stored_count so callers can read it after run().
    def run(self) -> None:
        """
        Execute one full research cycle.

        Calls all available sources, aggregates findings, stores them.
        The count of stored nodes is available at self.last_stored_count after the call.

        Safe to call even if some sources are None (they are skipped).
        """
        self.start()
        self.log_action(
            action="research_cycle_start",
            reason="scheduled research loop",
        )

        all_findings: list[dict[str, Any]] = []

        # ── Meme radar: Reddit hot/rising ───────────────────────────────────
        meme_findings = self.scan_trending_meme_formats()
        all_findings.extend(meme_findings)

        # ── Pop culture radar: Tumblr + KYM ────────────────────────────
        pop_findings = self.scan_pop_culture_moments()
        all_findings.extend(pop_findings)

        # ── Bluesky keyword search ───────────────────────────────────
        bluesky_findings = self.keyword_search_bluesky()
        all_findings.extend(bluesky_findings)

        # ── Gen Z Slang Dictionary Fetch ────────────────────────────
        slang_findings = self.fetch_latest_slang()
        all_findings.extend(slang_findings)

        # ── Aggregate + store ───────────────────────────────────────
        stored_count = self.store_findings(all_findings)
        self.last_stored_count = stored_count

        self.log_action(
            action="research_cycle_complete",
            reason="cycle finished",
            outcome=f"{stored_count} nodes stored from {len(all_findings)} raw findings",
        )
        self.stop()

    def stop(self) -> None:
        """Mark the agent as stopped. Calls super().stop() for base class compliance."""
        # FIX BUG-24: Always call super().stop() to ensure _running flag is cleared
        # via the base class and any future base class cleanup is honoured.
        super().stop()

    # ── Source methods ────────────────────────────────────────────────────────

    def scan_trending_meme_formats(self) -> list[dict[str, Any]]:
        """
        Fetch hot/rising posts from target subreddits.
        Populates meme_format_detected on findings that match known formats.

        Returns raw finding dicts (not yet aggregated or stored).
        """
        if self.reddit_source is None:
            logger.debug("[ResearchAgent] reddit_source not configured — skipping")
            return []

        try:
            findings = self.reddit_source.fetch()
            meme_count = sum(1 for f in findings if f.get("meme_format_detected"))
            self.log_action(
                action="scan_trending_meme_formats",
                reason="reddit hot/rising scan",
                outcome=f"{len(findings)} findings ({meme_count} meme-format matches)",
            )
            return findings
        except Exception as exc:
            logger.warning("[ResearchAgent] reddit scan error: %s", exc)
            return []

    def scan_pop_culture_moments(self) -> list[dict[str, Any]]:
        """
        Fetch from Tumblr RSS and Know Your Meme.
        Returns combined raw finding dicts.
        """
        findings: list[dict[str, Any]] = []

        # Tumblr RSS
        if self.tumblr_source is not None:
            try:
                tumblr_findings = self.tumblr_source.fetch()
                findings.extend(tumblr_findings)
                self.log_action(
                    action="scan_tumblr_rss",
                    reason="tumblr pop culture scan",
                    outcome=f"{len(tumblr_findings)} findings",
                )
            except Exception as exc:
                logger.warning("[ResearchAgent] tumblr scan error: %s", exc)

        # Know Your Meme
        if self.kym_source is not None:
            try:
                kym_findings = self.kym_source.fetch()
                findings.extend(kym_findings)
                self.log_action(
                    action="scan_knowyourmeme",
                    reason="kym trending/new scan",
                    outcome=f"{len(kym_findings)} findings",
                )
            except Exception as exc:
                logger.warning("[ResearchAgent] kym scan error: %s", exc)

        return findings

    def keyword_search_bluesky(
        self,
        keywords: Optional[list[str]] = None,
    ) -> list[dict[str, Any]]:
        """
        Search Bluesky for the niche keyword list.

        Parameters
        ----------
        keywords : override keyword list (default: NICHE_KEYWORDS)

        Returns raw finding dicts.
        """
        if self.bluesky_source is None:
            logger.debug("[ResearchAgent] bluesky_source not configured — skipping")
            return []

        try:
            kws = keywords or NICHE_KEYWORDS
            findings = self.bluesky_source.fetch(keywords=kws)
            self.log_action(
                action="keyword_search_bluesky",
                reason=f"keyword search: {kws[:3]}...",
                outcome=f"{len(findings)} findings",
            )
            return findings
        except Exception as exc:
            logger.warning("[ResearchAgent] bluesky keyword search error: %s", exc)
            return []

    def fetch_latest_slang(self) -> list[dict[str, Any]]:
        """
        Fetch the latest trending Gen Z slang from the web using a dynamically generated query.
        """
        if not self.ddg_source:
            logger.debug("[ResearchAgent] No DuckDuckGoSource available for slang fetch.")
            return []
            
        prompt = "Generate exactly one short, highly specific Google search query to find articles about the most recent Gen Z slang or TikTok internet vocabulary in 2026. Do not use quotes or explanations, just the query itself."
        try:
            response = self.llm_client.complete(
                system_prompt="You are a search query generator. Return ONLY the search query string.",
                user_prompt=prompt,
                temperature=0.9,
                max_tokens=20
            )
            search_query = response.strip().strip("'").strip('"')
            if not search_query:
                search_query = "trending TikTok Gen Z slang dictionary 2026 meaning"
        except Exception:
            search_query = "trending TikTok Gen Z slang dictionary 2026 meaning"
            
        logger.info(f"[ResearchAgent] Dynamically generated slang search query: '{search_query}'")
        return self.ddg_source.search(search_query, max_results=3)

    def search_web(self, query: str, max_results: int = 5) -> list[dict[str, Any]]:
        """
        DuckDuckGo context enrichment for a specific query.

        Parameters
        ----------
        query       : search query (e.g. 'toxic trait meme origin')
        max_results : max results to return

        Returns raw finding dicts.
        """
        if self.ddg_source is None:
            logger.debug("[ResearchAgent] ddg_source not configured — skipping")
            return []

        try:
            findings = self.ddg_source.search(query, max_results=max_results)
            self.log_action(
                action="search_web",
                reason=f"ddg context enrichment for {query!r}",
                outcome=f"{len(findings)} findings",
            )
            return findings
        except Exception as exc:
            logger.warning("[ResearchAgent] ddg search error: %s", exc)
            return []

    # ── Scoring helpers ───────────────────────────────────────────────────────

    @staticmethod
    def detect_meme_format(content: str) -> str:
        """
        Proxy to RedditSource.detect_meme_format() for use by other callers.

        Identified as a public method on ResearchAgent in the blueprint class spec.
        """
        return RedditSource.detect_meme_format(content)

    @staticmethod
    def score_cultural_freshness(
        created_utc: float,
        upvotes: int = 0,
        num_comments: int = 0,
    ) -> int:
        """
        Proxy to RedditSource.score_cultural_freshness() for use by other callers.
        """
        return RedditSource.score_cultural_freshness(
            created_utc=created_utc,
            upvotes=upvotes,
            num_comments=num_comments,
        )

    # ── Storage ───────────────────────────────────────────────────────────────

    def store_findings(
        self,
        findings: list[dict[str, Any]],
    ) -> int:
        """
        Aggregate + deduplicate findings, then store as ResearchNodes.

        CRITICAL: When meme_format_detected is set on a finding, the
        ResearchNode is stored with that field non-empty. MemoryEngine then
        assigns the 48-hour expiry (vs 72h standard) — activating digital amnesia.

        Returns count of nodes successfully stored.
        """
        if not findings:
            return 0

        nodes: list[ResearchNode] = self.aggregator.aggregate(
            findings,
            topic_id=self.topic_id,
        )

        stored = 0
        for node in nodes:
            try:
                self.memory.store(node)
                stored += 1
                logger.debug(
                    "[ResearchAgent] stored %s node id=%s meme=%r freshness=%d",
                    "meme" if node.meme_format_detected else "standard",
                    node.id,
                    node.meme_format_detected,
                    node.cultural_freshness,
                )
            except Exception as exc:
                logger.warning(
                    "[ResearchAgent] store error for node %s: %s", node.id, exc
                )

        self.log_action(
            action="store_findings",
            reason="post-aggregation storage",
            outcome=f"{stored}/{len(nodes)} nodes stored",
        )
        return stored
