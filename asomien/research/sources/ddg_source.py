"""
asomien/research/sources/ddg_source.py

DuckDuckGo web search source for cultural moment context.

Used when the Research Agent needs more context about a detected meme or
cultural moment — e.g. "what is the 'toxic trait' meme about?"

Provides broader context and article summaries to enrich ResearchNode
summaries. Treated as standard research (72h expiry, no meme_format).

In tests, the DDGS().text() call is mocked — no live HTTP calls.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

_DEFAULT_FRESHNESS: int = 55    # Web search results are less fresh than social
_DEFAULT_MAX_RESULTS: int = 5


class DuckDuckGoSource:
    """
    Searches DuckDuckGo for context about a given topic or meme.

    Source id: 'duckduckgo'
    No meme_format_detected — pure context enrichment.

    Usage:
        source = DuckDuckGoSource()
        findings = source.search("my toxic trait meme origin", max_results=5)
    """

    def __init__(self, max_results: int = _DEFAULT_MAX_RESULTS) -> None:
        self._max_results = max_results

    def search(
        self,
        query: str,
        max_results: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        """
        Run a DuckDuckGo text search and return finding dicts.

        Parameters
        ----------
        query       : search query string
        max_results : override default max results

        Returns
        -------
        List of finding dicts with source='duckduckgo'.
        Never raises — errors are logged and an empty list is returned.
        """
        limit = max_results or self._max_results
        findings: list[dict[str, Any]] = []

        try:
            from duckduckgo_search import DDGS

            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=limit))

            for result in results:
                finding = self._result_to_finding(result, query)
                if finding:
                    findings.append(finding)

        except Exception as exc:
            logger.warning("[DuckDuckGoSource] search error for %r: %s", query, exc)

        logger.info(
            "[DuckDuckGoSource] query=%r → %d findings", query, len(findings)
        )
        return findings

    def _result_to_finding(
        self,
        result: dict[str, Any],
        query: str,
    ) -> Optional[dict[str, Any]]:
        """Convert a DDGS result dict to a raw finding dict."""
        try:
            title: str = result.get("title", "") or ""
            body: str = result.get("body", "") or ""
            href: str = result.get("href", "") or ""

            if not title and not body:
                return None

            return {
                "source": "duckduckgo",
                "headline": title or body[:80],
                "summary": body[:300],
                "raw_url": href,
                "meme_format_detected": "",
                "cultural_freshness": _DEFAULT_FRESHNESS,
                "discovered_at": datetime.now(timezone.utc),
                "metadata": {"query": query},
            }
        except Exception as exc:
            logger.debug("[DuckDuckGoSource] _result_to_finding error: %s", exc)
            return None
