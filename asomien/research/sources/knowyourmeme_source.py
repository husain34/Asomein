"""
asomien/research/sources/knowyourmeme_source.py

Know Your Meme scraper — early-warning meme radar.

Scrapes the "Trending" and "New Entries" sections of knowyourmeme.com
to identify memes in their earliest stages before they peak.

Implementation strategy:
  - GET https://knowyourmeme.com/memes/trending (HTML)
  - Parse meme entry cards: title + URL + view count
  - Map each entry to a raw finding dict with source='knowyourmeme'

In tests, requests.get is mocked — no live HTTP calls.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional

import requests

logger = logging.getLogger(__name__)

# ── Target URLs ───────────────────────────────────────────────────────────────
KYM_TRENDING_URL: str = "https://knowyourmeme.com/memes/popular"
KYM_NEW_URL: str = "https://knowyourmeme.com/memes/new"

_DEFAULT_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; asomien-research/1.0; +https://github.com/asomien)"
    ),
    "Accept": "text/html,application/xhtml+xml",
}
_REQUEST_TIMEOUT_SECONDS: int = 10
_MAX_ENTRIES: int = 20
_DEFAULT_FRESHNESS: int = 75    # KYM trending content is fresh by definition


class KnowYourMemeSource:
    """
    Scrapes KnowYourMeme trending/new entries for early meme radar signals.

    Returns findings with source='knowyourmeme'. The meme format name is
    derived from the entry title and matched against the persona's format list
    by the aggregator (or left blank for the ResearchAgent to fill in).

    Usage:
        source = KnowYourMemeSource()
        findings = source.fetch()
    """

    def __init__(
        self,
        session: Optional[requests.Session] = None,
        timeout: int = _REQUEST_TIMEOUT_SECONDS,
    ) -> None:
        self._session = session or requests.Session()
        self._session.headers.update(_DEFAULT_HEADERS)
        self._timeout = timeout

    def fetch(self) -> list[dict[str, Any]]:
        """
        Fetch trending + new entries from KnowYourMeme.

        Returns list of finding dicts. Never raises — errors are logged.
        """
        findings: list[dict[str, Any]] = []

        for url, section in [(KYM_TRENDING_URL, "trending"), (KYM_NEW_URL, "new")]:
            try:
                resp = self._session.get(url, timeout=self._timeout)
                resp.raise_for_status()
                entries = self._parse_page(resp.text, section)
                findings.extend(entries)
            except Exception as exc:
                logger.warning("[KnowYourMemeSource] fetch error %s: %s", url, exc)

        logger.info("[KnowYourMemeSource] fetched %d entries", len(findings))
        return findings

    def _parse_page(
        self,
        html: str,
        section: str,
    ) -> list[dict[str, Any]]:
        """
        Parse meme entry cards from HTML.

        Looks for anchor tags pointing to /memes/<slug> with a title.
        This is deliberately simple — KYM's HTML structure is stable.
        """
        findings = []

        # Match: <a href="/memes/some-meme-name" ...>Some Meme Name</a>
        # KYM uses this pattern consistently in entry cards.
        # KYM redesigned their cards: the title is now in data-title="..."
        # and the anchor contains many nested tags.
        pattern = re.compile(
            r'<a[^>]+class="item"[^>]*>',
            re.IGNORECASE,
        )

        seen_slugs: set[str] = set()
        for match in pattern.finditer(html):
            if len(findings) >= _MAX_ENTRIES:
                break
            
            a_tag = match.group(0)
            
            href_m = re.search(r'href="(/memes/([^/"]+))"', a_tag)
            title_m = re.search(r'data-title="([^"]+)"', a_tag)
            
            if not href_m or not title_m:
                continue
                
            path, slug = href_m.group(1), href_m.group(2)
            title = title_m.group(1).strip()
            slug = slug.strip()

            # Skip navigation links, generic terms, and duplicates
            if not title or not slug or slug in seen_slugs:
                continue
            if slug in {"trending", "new", "all", "popular", "memes"}:
                continue

            seen_slugs.add(slug)
            raw_url = f"https://knowyourmeme.com{path}"

            findings.append({
                "source": "knowyourmeme",
                "headline": title,
                "summary": (
                    f"Know Your Meme {section} entry: '{title}' "
                    f"(slug: {slug})"
                ),
                "raw_url": raw_url,
                # The format id is the KYM slug — aggregator can refine this
                "meme_format_detected": self._slug_to_format_id(slug),
                "cultural_freshness": _DEFAULT_FRESHNESS,
                "discovered_at": datetime.now(timezone.utc),
                "metadata": {"section": section, "slug": slug},
            })

        return findings

    @staticmethod
    def _slug_to_format_id(slug: str) -> str:
        """
        Map a KYM URL slug to one of the persona's recognised format IDs.

        Known mappings (blueprint hook template ids):
            toxic-trait* → toxic_trait
            pipeline      → pipeline
            feminine-urge → feminine_urge
            ...

        Returns '' if no known format matches (will be treated as standard research).
        """
        slug_lower = slug.lower().replace("-", "_")

        _SLUG_MAP: dict[str, str] = {
            "toxic_trait": "toxic_trait",
            "not_to_be_dramatic": "not_to_be_dramatic",
            "the_pipeline": "pipeline",
            "pipeline": "pipeline",
            "feminine_urge": "feminine_urge",
            "masculine_urge": "feminine_urge",   # same format, different gender
            "okay_but_why": "okay_but_why",
            "chronically_online": "",             # topic, not a format
            "me_also_me": "me_also_me",
            "speed_run": "speedrun",
            "real_hours": "real_hours",
        }

        # Exact lookup first
        if slug_lower in _SLUG_MAP:
            return _SLUG_MAP[slug_lower]

        # Partial prefix match
        for key, format_id in _SLUG_MAP.items():
            if slug_lower.startswith(key) or key.startswith(slug_lower[:8]):
                return format_id

        return ""
