"""
asomien/research/sources/tumblr_source.py

Tumblr RSS aggregator for pop culture and fandom energy.

Fetches RSS feeds from configured Tumblr tag feeds and maps entries to
raw finding dicts for the aggregator. No meme format detection here —
Tumblr content is treated as standard research (72h expiry).

In tests, feedparser.parse is mocked — no live HTTP requests.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

import feedparser

logger = logging.getLogger(__name__)

# ── Target Tumblr RSS feeds (tag-based) ──────────────────────────────────────
# Tumblr deprecated public tag RSS feeds. We must use specific blog RSS feeds instead.
TARGET_TUMBLR_FEEDS: list[str] = [
    "https://memedocumentation.tumblr.com/rss",
    "https://internet-culture.tumblr.com/rss",
    "https://shitpostbot5k.tumblr.com/rss",
    "https://knowyourmeme.tumblr.com/rss",
]

_DEFAULT_FRESHNESS: int = 65   # Tumblr content is not as fresh as Reddit hot posts
_POSTS_PER_FEED_LIMIT: int = 10


class TumblrRSSSource:
    """
    Fetches pop culture energy from Tumblr tag RSS feeds.

    Each entry maps to a raw finding dict with source='tumblr_rss'.
    No meme_format_detected set — content treated as standard research.

    Usage:
        source = TumblrRSSSource()
        findings = source.fetch()
    """

    def __init__(
        self,
        feeds: Optional[list[str]] = None,
        limit_per_feed: int = _POSTS_PER_FEED_LIMIT,
    ) -> None:
        self._feeds = feeds or TARGET_TUMBLR_FEEDS
        self._limit = limit_per_feed

    def fetch(self) -> list[dict[str, Any]]:
        """
        Parse all target Tumblr RSS feeds.

        Returns list of finding dicts. Errors on individual feeds are logged
        and skipped — never crash the agent loop.
        """
        findings: list[dict[str, Any]] = []

        for feed_url in self._feeds:
            try:
                parsed = feedparser.parse(feed_url)
                entries = parsed.get("entries", [])

                for entry in entries[: self._limit]:
                    finding = self._entry_to_finding(entry, feed_url)
                    if finding:
                        findings.append(finding)

            except Exception as exc:
                logger.warning("[TumblrRSSSource] feed error %s: %s", feed_url, exc)

        logger.info("[TumblrRSSSource] fetched %d findings", len(findings))
        return findings

    def _entry_to_finding(
        self,
        entry: dict[str, Any],
        feed_url: str,
    ) -> Optional[dict[str, Any]]:
        """Map a feedparser entry dict to a raw finding dict."""
        try:
            title: str = entry.get("title", "") or ""
            link: str = entry.get("link", "") or ""
            summary_raw: str = entry.get("summary", "") or entry.get("content", "") or ""

            # Strip basic HTML from summary if present
            summary = self._strip_html(str(summary_raw))[:300]

            if not title and not summary:
                return None

            headline = title or summary[:80]

            return {
                "source": "tumblr_rss",
                "headline": headline,
                "summary": summary,
                "raw_url": link,
                "meme_format_detected": "",        # No format detection for Tumblr
                "cultural_freshness": _DEFAULT_FRESHNESS,
                "discovered_at": datetime.now(timezone.utc),
                "metadata": {"feed_url": feed_url},
            }
        except Exception as exc:
            logger.debug("[TumblrRSSSource] entry parse error: %s", exc)
            return None

    @staticmethod
    def _strip_html(text: str) -> str:
        """Very lightweight HTML tag remover."""
        import re
        return re.sub(r"<[^>]+>", "", text).strip()
