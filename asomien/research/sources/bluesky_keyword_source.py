"""
asomien/research/sources/bluesky_keyword_source.py

Bluesky API keyword_search endpoint adapter.

Uses the Bluesky AT Protocol searchPosts endpoint to find posts containing
the persona's niche keywords. This surfaces what real people are posting
about these topics right now. We filter for high engagement (viral) posts.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from atproto import Client

logger = logging.getLogger(__name__)

# ── Niche keyword list (blueprint Section 11) ─────────────────────────────────
NICHE_KEYWORDS: list[str] = [
    "my toxic trait",
    "not to be dramatic",
    "the feminine urge",
    "chronically online",
    "3am",
    "pipeline",
    "real hours",
    "phone brain",
    "screen time",
    "the audacity",
]

_DEFAULT_FRESHNESS: int = 85
_RESULTS_PER_KEYWORD: int = 15  # Fetch more to filter for virality
_MIN_VIRAL_LIKES: int = 10      # Minimum likes to be considered "viral" enough for research


class BlueskyKeywordSource:
    """
    Searches Bluesky for the persona's niche keywords via the AT Protocol.
    Filters for viral posts to ensure high quality research nodes.

    Source id: 'bluesky_keyword'

    Usage:
        source = BlueskyKeywordSource(
            handle="...",
            app_password="...",
            keywords=NICHE_KEYWORDS,
        )
        findings = source.fetch()
    """

    def __init__(
        self,
        handle: str,
        app_password: str,
        keywords: Optional[list[str]] = None,
    ) -> None:
        self.handle = handle
        self.app_password = app_password
        self._keywords = keywords or NICHE_KEYWORDS
        
        self.client = Client()
        self.client.login(self.handle, self.app_password)

    def fetch(
        self,
        keywords: Optional[list[str]] = None,
    ) -> list[dict[str, Any]]:
        """
        Search Bluesky for all configured niche keywords.
        """
        search_terms = keywords or self._keywords
        findings: list[dict[str, Any]] = []

        for keyword in search_terms:
            try:
                results = self._search_keyword(keyword)
                findings.extend(results)
            except Exception as exc:
                logger.warning(
                    "[BlueskyKeywordSource] keyword error %r: %s", keyword, exc
                )

        logger.info(
            "[BlueskyKeywordSource] fetched %d viral findings for %d keywords",
            len(findings), len(search_terms),
        )
        return findings

    def _search_keyword(self, keyword: str) -> list[dict[str, Any]]:
        """
        Hit the Bluesky searchPosts endpoint for a single keyword.
        Filters by like_count to find viral posts.
        """
        # Sort by top instead of latest to automatically favor viral posts
        results = self.client.app.bsky.feed.search_posts(
            params={'q': keyword, 'limit': _RESULTS_PER_KEYWORD, 'sort': 'top'}
        )

        findings = []
        for post in results.posts:
            if post.like_count and post.like_count >= _MIN_VIRAL_LIKES:
                finding = self._post_to_finding(post, keyword)
                if finding:
                    findings.append(finding)

        return findings

    def _post_to_finding(
        self,
        post: Any,
        keyword: str,
    ) -> Optional[dict[str, Any]]:
        """Map a Bluesky API post to a raw finding dict."""
        try:
            post_uri = post.uri
            text = post.record.text
            timestamp = post.record.created_at
            handle = post.author.handle

            if not text:
                return None

            # Build a canonical URL
            # uri is at://did:plc:.../app.bsky.feed.post/rkey
            rkey = post_uri.split("/")[-1]
            raw_url = f"https://bsky.app/profile/{handle}/post/{rkey}"

            headline = text[:120]
            summary = (
                f"Bluesky viral post by @{handle} matching keyword {keyword!r} ({post.like_count} likes): "
                f"{text[:200]}"
            )

            return {
                "source": "bluesky_keyword",
                "headline": headline,
                "summary": summary,
                "raw_url": raw_url,
                "meme_format_detected": "",
                "cultural_freshness": _DEFAULT_FRESHNESS,
                "discovered_at": datetime.now(timezone.utc),
                "metadata": {
                    "keyword": keyword,
                    "post_uri": post_uri,
                    "username": handle,
                    "timestamp": timestamp,
                    "likes": post.like_count,
                    "reposts": post.repost_count,
                    "replies": post.reply_count
                },
            }
        except Exception as exc:
            logger.debug("[BlueskyKeywordSource] _post_to_finding error: %s", exc)
            return None
