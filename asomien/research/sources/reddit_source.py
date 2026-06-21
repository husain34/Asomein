"""
asomien/research/sources/reddit_source.py

Reddit meme format scanner.

Targets: r/memes, r/me_irl, r/teenagers, r/dankmemes (hot + rising)

Core responsibility:
  - Fetch hot/rising posts via PRAW
  - Run detect_meme_format() on each title using regex patterns
  - Score cultural_freshness from post age + upvote velocity
  - Return a list of raw finding dicts for the aggregator

PRAW credentials come from Settings (REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET,
REDDIT_USER_AGENT). In tests, praw.Reddit is mocked — no live API calls.
"""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timezone
from typing import Any, Optional

import praw

logger = logging.getLogger(__name__)

# ── Target subreddits ─────────────────────────────────────────────────────────
TARGET_SUBREDDITS: list[str] = [
    "memes",
    "me_irl",
    "teenagers",
    "dankmemes",
]

# ── Meme format detection patterns ────────────────────────────────────────────
# Each entry: (format_id, compiled_regex_pattern)
# Ordered most-specific → least-specific so the first match wins.
_MEME_FORMAT_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    # "my toxic trait is ..."
    (
        "toxic_trait",
        re.compile(r"\bmy\s+toxic\s+trait\s+is\b", re.IGNORECASE),
    ),
    # "the feminine/masculine/gender urge to ..."
    (
        "feminine_urge",
        re.compile(
            r"\bthe\s+(?:feminine|masculine|gender|lesbian|gay|bi|trans|queer)\s+urge\s+to\b",
            re.IGNORECASE,
        ),
    ),
    # "not to be dramatic but ..."
    (
        "not_to_be_dramatic",
        re.compile(r"\bnot\s+to\s+be\s+dramatic\b", re.IGNORECASE),
    ),
    # "the '...' to '...' pipeline"
    (
        "pipeline",
        re.compile(r"\bpipeline\b.*\bso\s+real\b|\bthe\b.*\bto\b.*\bpipeline\b", re.IGNORECASE),
    ),
    # "okay but why does ..."
    (
        "okay_but_why",
        re.compile(r"\bokay\s+but\s+why\b", re.IGNORECASE),
    ),
    # "real [group] hours: ..."
    (
        "real_hours",
        re.compile(r"\breal\b.{1,30}\bhours\b", re.IGNORECASE),
    ),
    # "i don't know who needs to hear this but ..."
    (
        "who_needs_to_hear",
        re.compile(r"\bi\s+don'?t\s+know\s+who\s+needs\s+to\s+hear\s+this\b", re.IGNORECASE),
    ),
    # "me: [intention]. also me [time]: [betrayal]"
    (
        "me_also_me",
        re.compile(r"\bme\s*:\s*.+\.\s*also\s+me\b", re.IGNORECASE),
    ),
    # "[X] speed run:"
    (
        "speedrun",
        re.compile(r"\bspeed\s*run\s*:", re.IGNORECASE),
    ),
    # "as an AI i ..."
    (
        "ai_self_aware",
        re.compile(r"\bas\s+an\s+ai\b", re.IGNORECASE),
    ),
    # "[entity] said [devastating observation]"
    (
        "entity_said",
        re.compile(r"\bsaid\b.{3,60}(?:and|but|so)\b", re.IGNORECASE),
    ),
]

# ── Freshness scoring constants ───────────────────────────────────────────────
# Posts < 2h old with high upvotes get max freshness.
_FRESHNESS_MAX: int = 100
_FRESHNESS_MIN: int = 20
_RECENCY_HOURS_EXCELLENT: float = 2.0   # < 2h → max freshness contribution
_RECENCY_HOURS_GOOD: float = 12.0       # < 12h → good freshness
_VELOCITY_UPVOTES_HOT: int = 5_000      # upvotes threshold for a "hot" post
_POSTS_PER_SUB_LIMIT: int = 25          # max posts fetched per subreddit per scan


class RedditSource:
    """
    Fetches hot and rising posts from target subreddits and detects meme formats.

    Usage:
        source = RedditSource(reddit=praw.Reddit(...))
        findings = source.fetch(limit=25)

    Each finding dict contains all fields needed to construct a ResearchNode:
        - headline, summary, raw_url, source, meme_format_detected,
          cultural_freshness, discovered_at
    """

    def __init__(self, reddit: praw.Reddit) -> None:
        self._reddit = reddit

    # ── Public API ────────────────────────────────────────────────────────────

    def fetch(
        self,
        subreddits: Optional[list[str]] = None,
        limit: int = _POSTS_PER_SUB_LIMIT,
    ) -> list[dict[str, Any]]:
        """
        Fetch hot + rising posts from target subreddits.

        Parameters
        ----------
        subreddits : override target list (default: TARGET_SUBREDDITS)
        limit      : posts to fetch per subreddit per sort (hot + rising)

        Returns
        -------
        List of finding dicts ready for the aggregator.
        """
        subs = subreddits or TARGET_SUBREDDITS
        findings: list[dict[str, Any]] = []

        for sub_name in subs:
            try:
                subreddit = self._reddit.subreddit(sub_name)
                for sort in ("hot", "rising"):
                    try:
                        posts = (
                            subreddit.hot(limit=limit)
                            if sort == "hot"
                            else subreddit.rising(limit=limit)
                        )
                        for post in posts:
                            finding = self._post_to_finding(post, sub_name, sort)
                            if finding:
                                findings.append(finding)
                    except Exception as exc:
                        logger.warning(
                            "[RedditSource] fetch error sub=%s sort=%s: %s",
                            sub_name, sort, exc,
                        )
            except Exception as exc:
                logger.warning("[RedditSource] subreddit error %s: %s", sub_name, exc)

        logger.info(
            "[RedditSource] fetched %d findings from %d subreddits",
            len(findings), len(subs),
        )
        return findings

    # ── Core logic ────────────────────────────────────────────────────────────

    def _post_to_finding(
        self,
        post: Any,
        subreddit_name: str,
        sort: str,
    ) -> Optional[dict[str, Any]]:
        """Convert a PRAW Submission to a finding dict. Returns None if unusable."""
        try:
            title: str = getattr(post, "title", "") or ""
            url: str = getattr(post, "url", "") or ""
            permalink: str = getattr(post, "permalink", "") or ""
            score: int = getattr(post, "score", 0) or 0
            created_utc: float = getattr(post, "created_utc", time.time()) or time.time()
            num_comments: int = getattr(post, "num_comments", 0) or 0

            if not title:
                return None

            raw_url = f"https://reddit.com{permalink}" if permalink else url
            meme_format = self.detect_meme_format(title)
            freshness = self.score_cultural_freshness(
                created_utc=created_utc,
                upvotes=score,
                num_comments=num_comments,
            )

            return {
                "source": "reddit",
                "headline": title,
                "summary": (
                    f"r/{subreddit_name} {sort} — {score:,} upvotes, "
                    f"{num_comments:,} comments"
                ),
                "raw_url": raw_url,
                "meme_format_detected": meme_format,
                "cultural_freshness": freshness,
                "discovered_at": datetime.now(timezone.utc),
                "metadata": {
                    "subreddit": subreddit_name,
                    "sort": sort,
                    "upvotes": score,
                    "num_comments": num_comments,
                    "created_utc": created_utc,
                },
            }
        except Exception as exc:
            logger.debug("[RedditSource] _post_to_finding error: %s", exc)
            return None

    @staticmethod
    def detect_meme_format(title: str) -> str:
        """
        Identify a known meme format from a post title using regex matching.

        Returns the format_id string (e.g. 'toxic_trait') or '' if no match.

        Pattern priority: most-specific patterns are checked first.
        Only the first matching pattern's format_id is returned.
        """
        if not title:
            return ""

        for format_id, pattern in _MEME_FORMAT_PATTERNS:
            if pattern.search(title):
                return format_id

        return ""

    @staticmethod
    def score_cultural_freshness(
        created_utc: float,
        upvotes: int,
        num_comments: int = 0,
    ) -> int:
        """
        Score cultural freshness from post age and engagement velocity.

        Algorithm:
          - Age score   : 50 pts if < 2h old, 35 if < 12h, 20 if older
          - Upvote score: 30 pts if > 5000 upvotes, scaled linearly below
          - Comment bump: 20 pts if > 500 comments, scaled below

        Returns int in [20, 100].
        """
        now_utc = time.time()
        age_hours = max(0.0, (now_utc - created_utc) / 3600.0)

        # Age contribution (0–50)
        if age_hours < _RECENCY_HOURS_EXCELLENT:
            age_score = 50
        elif age_hours < _RECENCY_HOURS_GOOD:
            age_score = 35
        else:
            age_score = 20

        # Upvote velocity contribution (0–30)
        upvote_score = min(30, int(30 * (upvotes / _VELOCITY_UPVOTES_HOT)))

        # Comment activity contribution (0–20)
        comment_score = min(20, int(20 * (num_comments / 500)))

        raw = age_score + upvote_score + comment_score
        return max(_FRESHNESS_MIN, min(_FRESHNESS_MAX, raw))
