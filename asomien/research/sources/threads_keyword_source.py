"""
asomien/research/sources/threads_keyword_source.py

Threads /keyword_search endpoint adapter.

Uses the Threads Graph API keyword_search endpoint to find posts containing
the persona's niche keywords. This surfaces what real people are posting
about these topics right now — invaluable for freshness calibration.

Endpoint:
    GET https://graph.threads.net/v1.0/keyword_search
    ?q={keyword}&access_token={token}&fields=id,text,timestamp

In tests, requests.get is mocked — no live API calls.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

import requests

logger = logging.getLogger(__name__)

# ── Niche keyword list (blueprint Section 11) ─────────────────────────────────
# These are the search terms that surface chronically-online content on Threads.
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

_THREADS_KEYWORD_SEARCH_URL: str = "https://graph.threads.net/v1.0/keyword_search"
_DEFAULT_FRESHNESS: int = 85    # Threads posts are current by definition
_RESULTS_PER_KEYWORD: int = 10
_REQUEST_TIMEOUT_SECONDS: int = 10

# Fields requested from the API
_API_FIELDS: str = "id,text,timestamp,username"


class ThreadsKeywordSource:
    """
    Searches Threads for the persona's niche keywords via the Graph API.

    Source id: 'threads_keyword'
    All findings treated as meme-adjacent content (freshness > 80).

    Usage:
        source = ThreadsKeywordSource(
            access_token="...",
            keywords=NICHE_KEYWORDS,
        )
        findings = source.fetch()
    """

    def __init__(
        self,
        access_token: str,
        keywords: Optional[list[str]] = None,
        session: Optional[requests.Session] = None,
        timeout: int = _REQUEST_TIMEOUT_SECONDS,
    ) -> None:
        self._token = access_token
        self._keywords = keywords or NICHE_KEYWORDS
        self._session = session or requests.Session()
        self._timeout = timeout

    def fetch(
        self,
        keywords: Optional[list[str]] = None,
    ) -> list[dict[str, Any]]:
        """
        Search Threads for all configured niche keywords.

        Parameters
        ----------
        keywords : override the keyword list for this fetch

        Returns
        -------
        List of finding dicts with source='threads_keyword'.
        """
        search_terms = keywords or self._keywords
        findings: list[dict[str, Any]] = []

        for keyword in search_terms:
            try:
                results = self._search_keyword(keyword)
                findings.extend(results)
            except requests.exceptions.HTTPError as exc:
                if exc.response is not None and exc.response.status_code == 500:
                    logger.debug("[ThreadsKeywordSource] Meta API 500 for keyword %r (Expected restriction)", keyword)
                else:
                    logger.warning("[ThreadsKeywordSource] HTTP error %r: %s", keyword, exc)
            except Exception as exc:
                logger.warning(
                    "[ThreadsKeywordSource] keyword error %r: %s", keyword, exc
                )

        logger.info(
            "[ThreadsKeywordSource] fetched %d findings for %d keywords",
            len(findings), len(search_terms),
        )
        return findings

    def _search_keyword(self, keyword: str) -> list[dict[str, Any]]:
        """
        Hit the Threads keyword_search endpoint for a single keyword.
        Returns list of finding dicts.
        """
        params: dict[str, Any] = {
            "q": keyword,
            "access_token": self._token,
            "fields": _API_FIELDS,
        }

        resp = self._session.get(
            _THREADS_KEYWORD_SEARCH_URL,
            params=params,
            timeout=self._timeout,
        )
        resp.raise_for_status()
        data = resp.json()

        findings = []
        posts = data.get("data", [])

        for post in posts[:_RESULTS_PER_KEYWORD]:
            finding = self._post_to_finding(post, keyword)
            if finding:
                findings.append(finding)

        return findings

    def _post_to_finding(
        self,
        post: dict[str, Any],
        keyword: str,
    ) -> Optional[dict[str, Any]]:
        """Map a Threads API post dict to a raw finding dict."""
        try:
            post_id: str = post.get("id", "") or ""
            text: str = post.get("text", "") or ""
            timestamp: str = post.get("timestamp", "") or ""
            username: str = post.get("username", "") or ""

            if not text:
                return None

            # Build a canonical URL from the post id and username
            raw_url = (
                f"https://www.threads.net/@{username}/post/{post_id}"
                if username and post_id
                else ""
            )

            headline = text[:120]
            summary = (
                f"Threads post by @{username} matching keyword {keyword!r}: "
                f"{text[:200]}"
            )

            return {
                "source": "threads_keyword",
                "headline": headline,
                "summary": summary,
                "raw_url": raw_url,
                "meme_format_detected": "",        # No format detection here
                "cultural_freshness": _DEFAULT_FRESHNESS,
                "discovered_at": datetime.now(timezone.utc),
                "metadata": {
                    "keyword": keyword,
                    "post_id": post_id,
                    "username": username,
                    "timestamp": timestamp,
                },
            }
        except Exception as exc:
            logger.debug("[ThreadsKeywordSource] _post_to_finding error: %s", exc)
            return None
