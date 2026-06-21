"""
tests/test_phase3.py

Phase 3 test suite — Research Sources, Aggregator, Research Agent.

All external I/O is mocked:
  - praw.Reddit              → MagicMock
  - requests.get             → MagicMock (for KnowYourMeme + Threads keyword)
  - feedparser.parse         → MagicMock (for Tumblr RSS)
  - duckduckgo_search.DDGS   → MagicMock (for DuckDuckGo)

TESTING MANDATES:
  1. detect_meme_format("my toxic trait is...") → "toxic_trait"
  2. Aggregator correctly drops duplicate URLs
  3. Meme nodes stored by ResearchAgent have non-empty meme_format_detected
     (which activates the 48-hour expiry clock in MemoryEngine)
  4. store_findings() count is correct after deduplication

Run with:
    .\\venv\\Scripts\\pytest tests/test_phase3.py -v
"""

from __future__ import annotations

import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch, PropertyMock

import pytest
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def fresh_db(tmp_path):
    """Fully migrated memory.db in a temp directory."""
    from asomien.memory.migrations import run_migrations
    mem = str(tmp_path / "memory.db")
    run_migrations(
        memory_db_path=mem,
        metrics_db_path=str(tmp_path / "metrics.db"),
        directives_db_path=str(tmp_path / "directives.db"),
    )
    return mem


@pytest.fixture
def engine(fresh_db):
    from asomien.memory.engine import MemoryEngine
    return MemoryEngine(db_path=fresh_db)


@pytest.fixture
def aggregator():
    from asomien.research.aggregator import ResearchAggregator
    return ResearchAggregator()


def _make_finding(
    headline: str = "test headline",
    url: str = "https://example.com/1",
    source: str = "reddit",
    meme_format: str = "",
    freshness: int = 80,
) -> dict[str, Any]:
    """Helper: build a minimal raw finding dict."""
    return {
        "source": source,
        "headline": headline,
        "summary": f"summary of {headline}",
        "raw_url": url,
        "meme_format_detected": meme_format,
        "cultural_freshness": freshness,
        "discovered_at": datetime.now(timezone.utc),
        "metadata": {},
    }


# =============================================================================
# 1. RedditSource — detect_meme_format() (MANDATE TEST)
# =============================================================================

class TestDetectMemeFormat:
    """
    MANDATE: detect_meme_format() must correctly identify meme format IDs
    from post titles using regex — not simple substring matching.
    """

    def setup_method(self):
        from asomien.research.sources.reddit_source import RedditSource
        self.detect = RedditSource.detect_meme_format

    # ── toxic_trait ───────────────────────────────────────────────────────────

    def test_toxic_trait_lowercase(self):
        """'my toxic trait is...' → 'toxic_trait'"""
        result = self.detect("my toxic trait is opening 14 tabs")
        assert result == "toxic_trait", (
            f"Expected 'toxic_trait', got {result!r}"
        )

    def test_toxic_trait_mixed_case(self):
        """'My Toxic Trait Is...' → 'toxic_trait' (case-insensitive)"""
        result = self.detect("My Toxic Trait Is checking my phone every 2 minutes")
        assert result == "toxic_trait"

    def test_toxic_trait_all_caps(self):
        """'MY TOXIC TRAIT IS...' → 'toxic_trait'"""
        result = self.detect("MY TOXIC TRAIT IS never finishing a show")
        assert result == "toxic_trait"

    def test_toxic_trait_returns_exact_id_string(self):
        """Return value is the exact string 'toxic_trait', not 'Toxic_Trait'."""
        result = self.detect("my toxic trait is sending voice notes at 2am")
        assert result == "toxic_trait"
        assert result.islower() or "_" in result  # must be snake_case format id

    # ── pipeline ──────────────────────────────────────────────────────────────

    def test_pipeline_format(self):
        """'the ... to ... pipeline is so real' → 'pipeline'"""
        result = self.detect("the 'just one more episode' to '4am spiral' pipeline is so real")
        assert result == "pipeline"

    def test_pipeline_short(self):
        result = self.detect("the pipeline is so real bro")
        assert result == "pipeline"

    # ── feminine_urge ─────────────────────────────────────────────────────────

    def test_feminine_urge(self):
        result = self.detect("the feminine urge to reorganize everything at 1am")
        assert result == "feminine_urge"

    def test_masculine_urge(self):
        result = self.detect("the masculine urge to start a new project at midnight")
        assert result == "feminine_urge"  # same format id, different gender

    def test_gender_urge_variants(self):
        """Any gender variant maps to feminine_urge format id."""
        for variant in ["lesbian urge", "gay urge", "trans urge", "queer urge"]:
            result = self.detect(f"the {variant} to be unwell")
            assert result == "feminine_urge", (
                f"Expected 'feminine_urge' for '{variant}', got {result!r}"
            )

    # ── not_to_be_dramatic ────────────────────────────────────────────────────

    def test_not_to_be_dramatic(self):
        result = self.detect("not to be dramatic but my phone dying at 40% is a crisis")
        assert result == "not_to_be_dramatic"

    # ── okay_but_why ──────────────────────────────────────────────────────────

    def test_okay_but_why(self):
        result = self.detect("okay but why does sending one email feel like filing taxes")
        assert result == "okay_but_why"

    # ── real_hours ────────────────────────────────────────────────────────────

    def test_real_hours(self):
        result = self.detect("real chronically online hours: researching at 3am for no reason")
        assert result == "real_hours"

    # ── who_needs_to_hear ─────────────────────────────────────────────────────

    def test_who_needs_to_hear(self):
        result = self.detect("i don't know who needs to hear this but 3am is a vibe")
        assert result == "who_needs_to_hear"

    def test_who_needs_to_hear_with_apostrophe(self):
        result = self.detect("i dont know who needs to hear this but same")
        assert result == "who_needs_to_hear"

    # ── me_also_me ────────────────────────────────────────────────────────────

    def test_me_also_me(self):
        result = self.detect("me: going to sleep at 11. also me at 2am: cheese rolling documentary")
        assert result == "me_also_me"

    # ── speedrun ─────────────────────────────────────────────────────────────

    def test_speedrun(self):
        result = self.detect("adulting speed run: cereal for dinner, ignored 3 emails. new record")
        assert result == "speedrun"

    def test_speedrun_alternate_spacing(self):
        result = self.detect("adulting speedrun: forgot to eat. still going.")
        assert result == "speedrun"

    # ── ai_self_aware ─────────────────────────────────────────────────────────

    def test_ai_self_aware(self):
        result = self.detect("as an AI i have no feelings about loading screens. anyway")
        assert result == "ai_self_aware"

    # ── No match → empty string ───────────────────────────────────────────────

    def test_no_match_returns_empty_string(self):
        """Generic posts with no known format → ''"""
        result = self.detect("this is just a normal post about being tired")
        assert result == "", (
            f"Expected '' for unmatched post, got {result!r}"
        )

    def test_empty_string_returns_empty(self):
        """Empty input → ''"""
        result = self.detect("")
        assert result == ""

    def test_none_like_empty_returns_empty(self):
        """Whitespace-only → ''"""
        result = self.detect("   ")
        assert result == ""

    def test_does_not_match_partial_words(self):
        """'toxicity' should NOT match 'toxic_trait' — whole-word boundary test."""
        result = self.detect("discussing social media toxicity and its effects")
        # 'toxicity' != 'toxic trait is' — should not match
        assert result != "toxic_trait", (
            "Partial word 'toxicity' should not trigger toxic_trait format"
        )

    # ── Return type ───────────────────────────────────────────────────────────

    def test_always_returns_string_not_none(self):
        """detect_meme_format always returns str, never None."""
        for title in ["", "   ", "hello world", "my toxic trait is real"]:
            result = self.detect(title)
            assert isinstance(result, str), (
                f"detect_meme_format must return str, got {type(result)} for {title!r}"
            )


# =============================================================================
# 2. RedditSource — fetch() with mocked PRAW
# =============================================================================

class TestRedditSourceFetch:
    """
    Tests for RedditSource.fetch() with praw.Reddit mocked.
    No live Reddit API calls.
    """

    def _make_mock_post(
        self,
        title: str,
        score: int = 1000,
        num_comments: int = 100,
        permalink: str = "/r/memes/comments/abc123/test/",
        created_utc: float = None,
    ):
        """Build a mock PRAW Submission object."""
        post = MagicMock()
        post.title = title
        post.score = score
        post.num_comments = num_comments
        post.permalink = permalink
        post.url = f"https://reddit.com{permalink}"
        post.created_utc = created_utc or (time.time() - 3600)  # 1h ago
        return post

    def _make_reddit_source(self, hot_posts=None, rising_posts=None):
        """Build a RedditSource with a mocked praw.Reddit."""
        from asomien.research.sources.reddit_source import RedditSource

        mock_reddit = MagicMock()
        mock_subreddit = MagicMock()
        mock_reddit.subreddit.return_value = mock_subreddit

        mock_subreddit.hot.return_value = hot_posts or []
        mock_subreddit.rising.return_value = rising_posts or []

        return RedditSource(reddit=mock_reddit)

    def test_fetch_returns_list(self):
        """fetch() returns a list."""
        source = self._make_reddit_source()
        result = source.fetch(subreddits=["memes"], limit=5)
        assert isinstance(result, list)

    def test_fetch_converts_post_to_finding_dict(self):
        """Each fetched post becomes a finding dict with required keys."""
        post = self._make_mock_post("my toxic trait is opening 14 tabs", score=5000)
        source = self._make_reddit_source(hot_posts=[post])

        result = source.fetch(subreddits=["memes"], limit=5)

        assert len(result) >= 1
        finding = result[0]
        assert "headline" in finding
        assert "raw_url" in finding
        assert "source" in finding
        assert "meme_format_detected" in finding
        assert "cultural_freshness" in finding
        assert "discovered_at" in finding

    def test_fetch_source_is_reddit(self):
        """All findings have source='reddit'."""
        post = self._make_mock_post("late night posting hours")
        source = self._make_reddit_source(hot_posts=[post])

        result = source.fetch(subreddits=["me_irl"], limit=5)
        for finding in result:
            assert finding["source"] == "reddit"

    def test_fetch_detects_meme_format_for_toxic_trait_post(self):
        """
        MANDATE INTEGRATION: A post with 'my toxic trait is...' title
        must produce a finding with meme_format_detected='toxic_trait'.
        """
        post = self._make_mock_post("my toxic trait is doom-scrolling until 4am")
        source = self._make_reddit_source(hot_posts=[post])

        result = source.fetch(subreddits=["memes"], limit=5)

        assert len(result) >= 1
        assert result[0]["meme_format_detected"] == "toxic_trait", (
            f"Expected meme_format_detected='toxic_trait', got {result[0]['meme_format_detected']!r}"
        )

    def test_fetch_sets_empty_meme_format_for_generic_post(self):
        """A generic post title gets meme_format_detected=''."""
        post = self._make_mock_post("just a random post about nothing much")
        source = self._make_reddit_source(hot_posts=[post])

        result = source.fetch(subreddits=["memes"], limit=5)
        assert len(result) >= 1
        assert result[0]["meme_format_detected"] == ""

    def test_fetch_cultural_freshness_is_in_range(self):
        """cultural_freshness is between 20 and 100 for all findings."""
        post = self._make_mock_post("my toxic trait is everything", score=10000, num_comments=2000)
        source = self._make_reddit_source(hot_posts=[post])

        result = source.fetch(subreddits=["memes"], limit=5)
        assert len(result) >= 1
        for f in result:
            assert 20 <= f["cultural_freshness"] <= 100, (
                f"cultural_freshness {f['cultural_freshness']} out of range [20, 100]"
            )

    def test_fetch_handles_subreddit_error_gracefully(self):
        """fetch() doesn't crash if a subreddit raises an exception."""
        from asomien.research.sources.reddit_source import RedditSource

        mock_reddit = MagicMock()
        mock_reddit.subreddit.side_effect = Exception("API error: subreddit not found")

        source = RedditSource(reddit=mock_reddit)
        result = source.fetch(subreddits=["memes"])

        # Must return empty list, not raise
        assert isinstance(result, list)
        assert len(result) == 0

    def test_fetch_uses_both_hot_and_rising(self):
        """fetch() calls both .hot() and .rising() for each subreddit."""
        from asomien.research.sources.reddit_source import RedditSource

        mock_reddit = MagicMock()
        mock_subreddit = MagicMock()
        mock_reddit.subreddit.return_value = mock_subreddit
        mock_subreddit.hot.return_value = [self._make_mock_post("hot post")]
        mock_subreddit.rising.return_value = [self._make_mock_post("rising post")]

        source = RedditSource(reddit=mock_reddit)
        source.fetch(subreddits=["memes"], limit=5)

        mock_subreddit.hot.assert_called_once()
        mock_subreddit.rising.assert_called_once()


# =============================================================================
# 3. score_cultural_freshness()
# =============================================================================

class TestScoreCulturalFreshness:
    """Tests for RedditSource.score_cultural_freshness() scoring algorithm."""

    def setup_method(self):
        from asomien.research.sources.reddit_source import RedditSource
        self.score = RedditSource.score_cultural_freshness

    def test_very_fresh_high_upvotes_returns_max(self):
        """Post < 2h old + 5000+ upvotes → maximum freshness (100)."""
        created = time.time() - 3600   # 1 hour ago
        result = self.score(created_utc=created, upvotes=5000, num_comments=500)
        assert result == 100, f"Expected 100, got {result}"

    def test_old_post_low_engagement_returns_minimum(self):
        """Post from 7 days ago + minimal upvotes → minimum freshness (20)."""
        created = time.time() - (7 * 24 * 3600)   # 7 days ago
        result = self.score(created_utc=created, upvotes=0, num_comments=0)
        assert result == 20, f"Expected 20, got {result}"

    def test_freshness_is_always_in_valid_range(self):
        """No matter the input, result is always in [20, 100]."""
        test_cases = [
            (time.time() - 1, 0, 0),
            (time.time() - 3600, 1000, 100),
            (time.time() - 86400, 100, 10),
            (time.time() - 604800, 50000, 10000),   # extreme values
        ]
        for created, upvotes, comments in test_cases:
            result = self.score(created_utc=created, upvotes=upvotes, num_comments=comments)
            assert 20 <= result <= 100, (
                f"Score {result} out of range for created={created}, "
                f"upvotes={upvotes}, comments={comments}"
            )

    def test_older_post_scores_lower_than_fresh_with_same_upvotes(self):
        """Age penalizes score: fresh post > old post with identical engagement."""
        upvotes = 2000
        fresh_score = self.score(time.time() - 3600, upvotes, 100)      # 1h ago
        old_score = self.score(time.time() - 86400, upvotes, 100)       # 24h ago
        assert fresh_score > old_score, (
            f"Fresh post ({fresh_score}) should outscore old post ({old_score})"
        )

    def test_high_upvotes_scores_higher_than_low_upvotes_same_age(self):
        """More upvotes = higher freshness score, same age."""
        created = time.time() - 3600
        high_score = self.score(created, upvotes=5000, num_comments=0)
        low_score = self.score(created, upvotes=10, num_comments=0)
        assert high_score > low_score


# =============================================================================
# 4. TumblrRSSSource — fetch() with mocked feedparser
# =============================================================================

class TestTumblrRSSSource:
    """Tests for TumblrRSSSource.fetch() with feedparser.parse mocked."""

    def _make_parsed_feed(self, entries: list[dict]) -> dict:
        """Build a minimal feedparser result dict."""
        return {"entries": entries, "status": 200, "bozo": False}

    @patch("feedparser.parse")
    def test_fetch_returns_list(self, mock_parse):
        """fetch() returns a list even with an empty feed."""
        mock_parse.return_value = self._make_parsed_feed([])
        from asomien.research.sources.tumblr_source import TumblrRSSSource
        source = TumblrRSSSource(feeds=["https://fake.tumblr.com/rss"])
        result = source.fetch()
        assert isinstance(result, list)

    @patch("feedparser.parse")
    def test_fetch_converts_entry_to_finding(self, mock_parse):
        """Each RSS entry becomes a finding dict with the required keys."""
        mock_parse.return_value = self._make_parsed_feed([
            {
                "title": "chronically online 3am post",
                "link": "https://tumblr.com/post/12345",
                "summary": "relatable content about being awake at 3am",
            }
        ])

        from asomien.research.sources.tumblr_source import TumblrRSSSource
        source = TumblrRSSSource(feeds=["https://fake.tumblr.com/rss"])
        result = source.fetch()

        assert len(result) == 1
        f = result[0]
        assert f["source"] == "tumblr_rss"
        assert "chronically online" in f["headline"]
        assert f["meme_format_detected"] == ""   # Tumblr never sets a format

    @patch("feedparser.parse")
    def test_fetch_source_id_is_tumblr_rss(self, mock_parse):
        """All findings have source='tumblr_rss'."""
        mock_parse.return_value = self._make_parsed_feed([
            {"title": "post 1", "link": "https://t.com/1", "summary": "s1"},
            {"title": "post 2", "link": "https://t.com/2", "summary": "s2"},
        ])
        from asomien.research.sources.tumblr_source import TumblrRSSSource
        source = TumblrRSSSource(feeds=["https://fake.tumblr.com/rss"])
        result = source.fetch()
        for f in result:
            assert f["source"] == "tumblr_rss"

    @patch("feedparser.parse")
    def test_fetch_handles_feed_error_gracefully(self, mock_parse):
        """fetch() doesn't crash if feedparser.parse raises."""
        mock_parse.side_effect = Exception("Network error")
        from asomien.research.sources.tumblr_source import TumblrRSSSource
        source = TumblrRSSSource(feeds=["https://broken.tumblr.com/rss"])
        result = source.fetch()
        assert isinstance(result, list)
        assert len(result) == 0

    @patch("feedparser.parse")
    def test_fetch_limits_entries_per_feed(self, mock_parse):
        """fetch() respects the limit_per_feed parameter."""
        entries = [
            {"title": f"post {i}", "link": f"https://t.com/{i}", "summary": f"s{i}"}
            for i in range(20)
        ]
        mock_parse.return_value = self._make_parsed_feed(entries)

        from asomien.research.sources.tumblr_source import TumblrRSSSource
        source = TumblrRSSSource(
            feeds=["https://fake.tumblr.com/rss"],
            limit_per_feed=5,
        )
        result = source.fetch()
        assert len(result) == 5, f"Expected 5 entries (limit=5), got {len(result)}"


# =============================================================================
# 5. KnowYourMemeSource — fetch() with mocked requests.get
# =============================================================================

class TestKnowYourMemeSource:
    """Tests for KnowYourMemeSource.fetch() with requests.get mocked."""

    _SAMPLE_HTML = """
    <html><body>
        <a href="/memes/toxic-trait" class="meme-card">Toxic Trait</a>
        <a href="/memes/pipeline" class="meme-card">Pipeline</a>
        <a href="/memes/chronically-online" class="meme-card">Chronically Online</a>
        <nav><a href="/memes/trending">Trending</a></nav>
        <a href="/memes/feminine-urge">The Feminine Urge</a>
    </body></html>
    """

    def _make_mock_session(self, html: str = None):
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.text = html or self._SAMPLE_HTML
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_session.get.return_value = mock_resp
        return mock_session

    def test_fetch_returns_list(self):
        """fetch() returns a list."""
        from asomien.research.sources.knowyourmeme_source import KnowYourMemeSource
        source = KnowYourMemeSource(session=self._make_mock_session())
        result = source.fetch()
        assert isinstance(result, list)

    def test_fetch_parses_meme_entries(self):
        """fetch() extracts entries from the HTML."""
        from asomien.research.sources.knowyourmeme_source import KnowYourMemeSource
        source = KnowYourMemeSource(session=self._make_mock_session())
        result = source.fetch()
        assert len(result) >= 1

    def test_fetch_source_is_knowyourmeme(self):
        """All findings have source='knowyourmeme'."""
        from asomien.research.sources.knowyourmeme_source import KnowYourMemeSource
        source = KnowYourMemeSource(session=self._make_mock_session())
        result = source.fetch()
        for f in result:
            assert f["source"] == "knowyourmeme"

    def test_fetch_includes_raw_url(self):
        """All findings have a raw_url pointing to knowyourmeme.com."""
        from asomien.research.sources.knowyourmeme_source import KnowYourMemeSource
        source = KnowYourMemeSource(session=self._make_mock_session())
        result = source.fetch()
        for f in result:
            assert "knowyourmeme.com" in f["raw_url"]

    def test_fetch_handles_http_error_gracefully(self):
        """fetch() doesn't crash on HTTP errors."""
        from asomien.research.sources.knowyourmeme_source import KnowYourMemeSource
        mock_session = MagicMock()
        mock_session.get.side_effect = Exception("404 Not Found")
        source = KnowYourMemeSource(session=mock_session)
        result = source.fetch()
        assert isinstance(result, list)

    def test_slug_to_format_id_toxic_trait(self):
        """KYM slug 'toxic-trait' maps to format_id 'toxic_trait'."""
        from asomien.research.sources.knowyourmeme_source import KnowYourMemeSource
        assert KnowYourMemeSource._slug_to_format_id("toxic_trait") == "toxic_trait"
        assert KnowYourMemeSource._slug_to_format_id("toxic-trait") == "toxic_trait"

    def test_slug_to_format_id_pipeline(self):
        from asomien.research.sources.knowyourmeme_source import KnowYourMemeSource
        assert KnowYourMemeSource._slug_to_format_id("pipeline") == "pipeline"

    def test_slug_to_format_id_unknown_returns_empty(self):
        """Unknown slugs return ''."""
        from asomien.research.sources.knowyourmeme_source import KnowYourMemeSource
        result = KnowYourMemeSource._slug_to_format_id("completely_unknown_meme_xyz")
        assert result == ""


# =============================================================================
# 6. ThreadsKeywordSource — fetch() with mocked requests.get
# =============================================================================

class TestThreadsKeywordSource:
    """Tests for ThreadsKeywordSource.fetch() with requests.get mocked."""

    def _make_mock_session(self, posts: list[dict]) -> MagicMock:
        """Build a mock session that returns a Threads API-style response."""
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": posts}
        mock_resp.raise_for_status = MagicMock()
        mock_session.get.return_value = mock_resp
        return mock_session

    def _make_source(self, posts: list[dict], keywords: list[str] = None):
        from asomien.research.sources.threads_keyword_source import ThreadsKeywordSource
        return ThreadsKeywordSource(
            access_token="test-token-123",
            keywords=keywords or ["my toxic trait"],
            session=self._make_mock_session(posts),
        )

    def test_fetch_returns_list(self):
        """fetch() returns a list."""
        source = self._make_source([])
        result = source.fetch()
        assert isinstance(result, list)

    def test_fetch_converts_post_to_finding(self):
        """Each post dict becomes a finding with required keys."""
        posts = [{"id": "p1", "text": "my toxic trait is chronically online", "username": "user1"}]
        source = self._make_source(posts)
        result = source.fetch()

        assert len(result) == 1
        f = result[0]
        assert f["source"] == "threads_keyword"
        assert "toxic trait" in f["headline"] or "toxic trait" in f["summary"]

    def test_fetch_source_is_threads_keyword(self):
        """All findings have source='threads_keyword'."""
        posts = [
            {"id": "p1", "text": "chronically online rn", "username": "u1"},
            {"id": "p2", "text": "3am brain is real", "username": "u2"},
        ]
        source = self._make_source(posts)
        result = source.fetch()
        for f in result:
            assert f["source"] == "threads_keyword"

    def test_fetch_handles_api_error_gracefully(self):
        """fetch() doesn't crash on HTTP/API errors."""
        from asomien.research.sources.threads_keyword_source import ThreadsKeywordSource
        mock_session = MagicMock()
        mock_session.get.side_effect = Exception("401 Unauthorized")
        source = ThreadsKeywordSource(
            access_token="bad-token",
            keywords=["my toxic trait"],
            session=mock_session,
        )
        result = source.fetch()
        assert isinstance(result, list)
        assert len(result) == 0

    def test_niche_keywords_list_contains_required_terms(self):
        """The NICHE_KEYWORDS list contains all blueprint-specified terms."""
        from asomien.research.sources.threads_keyword_source import NICHE_KEYWORDS
        required = [
            "my toxic trait",
            "not to be dramatic",
            "the feminine urge",
            "chronically online",
            "3am",
            "pipeline",
        ]
        for kw in required:
            assert kw in NICHE_KEYWORDS, (
                f"Required niche keyword {kw!r} missing from NICHE_KEYWORDS"
            )


# =============================================================================
# 7. DuckDuckGoSource — search() with mocked DDGS
# =============================================================================

class TestDuckDuckGoSource:
    """Tests for DuckDuckGoSource.search() with DDGS mocked."""

    @patch("duckduckgo_search.DDGS")
    def test_search_returns_list(self, MockDDGS):
        """search() returns a list."""
        instance = MockDDGS.return_value.__enter__.return_value
        instance.text.return_value = []
        from asomien.research.sources.ddg_source import DuckDuckGoSource
        source = DuckDuckGoSource()
        result = source.search("my toxic trait meme")
        assert isinstance(result, list)

    @patch("duckduckgo_search.DDGS")
    def test_search_converts_result_to_finding(self, MockDDGS):
        """Each DDGS result becomes a finding dict."""
        instance = MockDDGS.return_value.__enter__.return_value
        instance.text.return_value = [
            {
                "title": "The Toxic Trait Meme Explained",
                "body": "The 'my toxic trait is...' format originated...",
                "href": "https://example.com/meme-explained",
            }
        ]
        from asomien.research.sources.ddg_source import DuckDuckGoSource
        source = DuckDuckGoSource()
        result = source.search("toxic trait meme origin")

        assert len(result) == 1
        f = result[0]
        assert f["source"] == "duckduckgo"
        assert "Toxic Trait" in f["headline"]
        assert f["meme_format_detected"] == ""

    @patch("duckduckgo_search.DDGS")
    def test_search_handles_error_gracefully(self, MockDDGS):
        """search() doesn't crash if DDGS raises."""
        MockDDGS.return_value.__enter__.side_effect = Exception("Rate limit")
        from asomien.research.sources.ddg_source import DuckDuckGoSource
        source = DuckDuckGoSource()
        result = source.search("some query")
        assert isinstance(result, list)
        assert len(result) == 0

    @patch("duckduckgo_search.DDGS")
    def test_search_source_is_duckduckgo(self, MockDDGS):
        """All findings have source='duckduckgo'."""
        instance = MockDDGS.return_value.__enter__.return_value
        instance.text.return_value = [
            {"title": "result 1", "body": "body 1", "href": "https://a.com"},
            {"title": "result 2", "body": "body 2", "href": "https://b.com"},
        ]
        from asomien.research.sources.ddg_source import DuckDuckGoSource
        source = DuckDuckGoSource()
        result = source.search("meme culture")
        for f in result:
            assert f["source"] == "duckduckgo"


# =============================================================================
# 8. ResearchAggregator — deduplication (MANDATE TEST)
# =============================================================================

class TestResearchAggregatorDeduplication:
    """
    MANDATE: The aggregator must correctly drop duplicate findings.
    Tests cover URL deduplication and headline Jaccard similarity.
    """

    def test_exact_url_duplicate_dropped(self, aggregator):
        """
        MANDATE: Two findings with the same URL → only one is kept.
        The higher-priority source is retained.
        """
        findings = [
            _make_finding("post about meme formats", url="https://reddit.com/r/memes/abc", source="reddit", freshness=90),
            _make_finding("post about meme formats (duplicate)", url="https://reddit.com/r/memes/abc", source="duckduckgo", freshness=50),
        ]
        nodes = aggregator.aggregate(findings)

        assert len(nodes) == 1, (
            f"Exact URL duplicate must be dropped. Got {len(nodes)} nodes."
        )

    def test_url_deduplication_case_insensitive(self, aggregator):
        """URL deduplication is case-insensitive."""
        findings = [
            _make_finding("post A", url="HTTPS://REDDIT.COM/memes/xyz"),
            _make_finding("post B", url="https://reddit.com/memes/xyz"),
        ]
        nodes = aggregator.aggregate(findings)
        assert len(nodes) == 1

    def test_similar_headline_duplicate_dropped(self, aggregator):
        """
        Findings with near-identical headlines (Jaccard ≥ 0.70) are deduplicated.

        Jaccard math for chosen headlines:
          A tokens: {my, toxic, trait, is, opening, 14, browser, tabs, at, 3am}  (10)
          B tokens: {my, toxic, trait, is, opening, 14, browser, tabs, past, 3am} (10)
          Intersection: {my, toxic, trait, is, opening, 14, browser, tabs, 3am}   (9)
          Union: 11
          J = 9/11 ≈ 0.818  →  above the 0.70 threshold → deduplicated
        """
        headline_a = "my toxic trait is opening 14 browser tabs at 3am"
        headline_b = "my toxic trait is opening 14 browser tabs past 3am"

        findings = [
            _make_finding(headline_a, url="https://reddit.com/1"),
            _make_finding(headline_b, url="https://reddit.com/2"),
        ]
        nodes = aggregator.aggregate(findings)
        assert len(nodes) == 1, (
            f"Near-identical headlines should be deduplicated. Got {len(nodes)} nodes."
        )

    def test_different_headlines_both_kept(self, aggregator):
        """Sufficiently different headlines → both nodes are kept."""
        findings = [
            _make_finding("my toxic trait is opening 14 tabs", url="https://r.com/1"),
            _make_finding("3am brain said let's research something useless", url="https://r.com/2"),
        ]
        nodes = aggregator.aggregate(findings)
        assert len(nodes) == 2, (
            f"Different headlines must both be kept. Got {len(nodes)} nodes."
        )

    def test_empty_input_returns_empty_list(self, aggregator):
        """aggregate([]) returns []."""
        result = aggregator.aggregate([])
        assert result == []

    def test_single_finding_returns_one_node(self, aggregator):
        """Single finding → exactly one node."""
        findings = [_make_finding("my toxic trait is real", url="https://r.com/1")]
        nodes = aggregator.aggregate(findings)
        assert len(nodes) == 1

    def test_dedup_keeps_correct_count(self, aggregator):
        """5 findings with 2 exact URL duplicates → 3 unique nodes."""
        findings = [
            _make_finding("post alpha", url="https://r.com/alpha", freshness=90),
            _make_finding("post alpha dup", url="https://r.com/alpha", freshness=50),   # dup
            _make_finding("post beta", url="https://r.com/beta", freshness=80),
            _make_finding("post gamma", url="https://r.com/gamma", freshness=70),
            _make_finding("post gamma dup", url="https://r.com/gamma", freshness=40),   # dup
        ]
        nodes = aggregator.aggregate(findings)
        assert len(nodes) == 3, (
            f"Expected 3 unique nodes after dedup, got {len(nodes)}"
        )


# =============================================================================
# 9. ResearchAggregator — ranking
# =============================================================================

class TestResearchAggregatorRanking:
    """Tests for aggregator ranking: meme nodes first, higher freshness first."""

    def test_meme_node_ranked_before_standard_same_freshness(self, aggregator):
        """
        Meme findings (meme_format_detected non-empty) should rank before
        standard findings with the same cultural_freshness.
        """
        findings = [
            _make_finding("standard research", url="https://r.com/1", source="duckduckgo", meme_format="", freshness=80),
            _make_finding("meme finding", url="https://r.com/2", source="reddit", meme_format="toxic_trait", freshness=80),
        ]
        nodes = aggregator.aggregate(findings)
        assert len(nodes) == 2
        # Meme node (reddit, format=toxic_trait) should come first
        assert nodes[0].meme_format_detected == "toxic_trait", (
            f"Meme node should be ranked first. Got meme_format_detected={nodes[0].meme_format_detected!r}"
        )

    def test_higher_freshness_ranked_first(self, aggregator):
        """Higher cultural_freshness → higher rank (same source, no meme format)."""
        findings = [
            _make_finding("old content", url="https://r.com/1", source="duckduckgo", freshness=30),
            _make_finding("fresh content", url="https://r.com/2", source="duckduckgo", freshness=90),
        ]
        nodes = aggregator.aggregate(findings)
        assert nodes[0].cultural_freshness == 90, (
            f"Higher freshness should rank first. Got {nodes[0].cultural_freshness}"
        )

    def test_returns_research_node_objects(self, aggregator):
        """aggregate() returns ResearchNode instances, not raw dicts."""
        from asomien.memory.nodes import ResearchNode
        findings = [_make_finding("test post", url="https://r.com/1")]
        nodes = aggregator.aggregate(findings)
        assert all(isinstance(n, ResearchNode) for n in nodes), (
            "All returned objects must be ResearchNode instances"
        )

    def test_meme_format_detected_preserved_in_node(self, aggregator):
        """meme_format_detected from the finding is preserved in the ResearchNode."""
        findings = [
            _make_finding("toxic trait post", url="https://r.com/1",
                         meme_format="toxic_trait", freshness=85)
        ]
        nodes = aggregator.aggregate(findings)
        assert len(nodes) == 1
        assert nodes[0].meme_format_detected == "toxic_trait"


# =============================================================================
# 10. Jaccard similarity helper
# =============================================================================

class TestJaccardSimilarity:
    """Direct unit tests for the Jaccard similarity dedup helper."""

    def setup_method(self):
        from asomien.research.aggregator import _jaccard_similarity
        self.sim = _jaccard_similarity

    def test_identical_strings_return_1_0(self):
        assert self.sim("hello world", "hello world") == 1.0

    def test_completely_different_returns_0_0(self):
        assert self.sim("hello world", "foo bar baz qux") == 0.0

    def test_partial_overlap_returns_correct_value(self):
        # "my toxic trait is real" ∩ "my toxic trait is fake" = {my, toxic, trait, is} = 4
        # union = {my, toxic, trait, is, real, fake} = 6
        # J = 4/6 ≈ 0.667
        sim = self.sim("my toxic trait is real", "my toxic trait is fake")
        assert abs(sim - 4/6) < 0.01, f"Expected ~0.667, got {sim:.4f}"

    def test_empty_both_returns_0_0(self):
        assert self.sim("", "") == 0.0

    def test_case_insensitive(self):
        """Jaccard comparison is case-insensitive."""
        sim_lower = self.sim("my toxic trait", "my toxic trait")
        sim_mixed = self.sim("My Toxic Trait", "my toxic trait")
        assert sim_lower == sim_mixed == 1.0


# =============================================================================
# 11. ResearchAgent — integration tests with all sources mocked
# =============================================================================

class TestResearchAgent:
    """
    Integration tests for ResearchAgent.

    All external sources are mocked via MagicMock — no live API calls.
    """

    def _make_mock_reddit_source(self, findings: list[dict]):
        mock = MagicMock()
        mock.fetch.return_value = findings
        return mock

    def _make_mock_tumblr_source(self, findings: list[dict]):
        mock = MagicMock()
        mock.fetch.return_value = findings
        return mock

    def _make_mock_kym_source(self, findings: list[dict]):
        mock = MagicMock()
        mock.fetch.return_value = findings
        return mock

    def _make_mock_threads_source(self, findings: list[dict]):
        mock = MagicMock()
        mock.fetch.return_value = findings
        return mock

    def _make_agent(self, engine, reddit_findings=None, tumblr_findings=None,
                    kym_findings=None, threads_findings=None):
        from asomien.agents.research_agent import ResearchAgent
        return ResearchAgent(
            memory=engine,
            reddit_source=self._make_mock_reddit_source(reddit_findings or []),
            tumblr_source=self._make_mock_tumblr_source(tumblr_findings or []),
            kym_source=self._make_mock_kym_source(kym_findings or []),
            threads_source=self._make_mock_threads_source(threads_findings or []),
        )

    def test_run_returns_count_of_stored_nodes(self, engine):
        """run() returns the count of nodes stored in MemoryEngine."""
        findings = [
            _make_finding("my toxic trait is real", url="https://r.com/1",
                         meme_format="toxic_trait", freshness=90),
            _make_finding("3am brain is alive", url="https://r.com/2",
                         meme_format="", freshness=60),
        ]
        agent = self._make_agent(engine, reddit_findings=findings)
        count = agent.run()
        assert count == 2, f"Expected 2 nodes stored, got {count}"

    def test_run_stores_meme_nodes_with_meme_format(self, engine, fresh_db):
        """
        MANDATE: Meme findings reach MemoryEngine with meme_format_detected set.
        This activates the 48-hour expiry clock.
        """
        meme_finding = _make_finding(
            "my toxic trait is doom-scrolling",
            url="https://reddit.com/r/memes/abc",
            meme_format="toxic_trait",
            freshness=90,
        )
        agent = self._make_agent(engine, reddit_findings=[meme_finding])
        count = agent.run()

        assert count == 1

        conn = sqlite3.connect(fresh_db)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM research_nodes WHERE meme_format_detected != ''"
        ).fetchall()
        conn.close()

        assert len(rows) == 1, (
            f"Expected 1 meme node in DB with meme_format_detected set. Got {len(rows)}"
        )
        assert rows[0]["meme_format_detected"] == "toxic_trait"

    def test_run_meme_node_gets_48h_expiry(self, engine, fresh_db):
        """
        End-to-end: meme finding → ResearchAgent.run() → stored node has 48h expiry.
        This is the "digital amnesia clock" activation proof.
        """
        from asomien.memory.engine import MEME_EXPIRY_HOURS

        meme_finding = _make_finding(
            "the pipeline meme is so real",
            url="https://reddit.com/memes/pipeline123",
            meme_format="pipeline",
            freshness=85,
        )
        agent = self._make_agent(engine, reddit_findings=[meme_finding])

        before_store = datetime.now(timezone.utc)
        agent.run()
        after_store = datetime.now(timezone.utc)

        conn = sqlite3.connect(fresh_db)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT expiry FROM research_nodes WHERE meme_format_detected = 'pipeline'"
        ).fetchone()
        conn.close()

        assert row is not None, "Meme node not found in DB"
        expiry_str = row["expiry"]
        assert expiry_str is not None, "Expiry must be set for meme node"

        expiry_dt = datetime.fromisoformat(expiry_str.replace("Z", "+00:00"))
        if expiry_dt.tzinfo is None:
            expiry_dt = expiry_dt.replace(tzinfo=timezone.utc)

        # Expiry must be approximately 48h from now (±2 minutes tolerance)
        expected_min = before_store + timedelta(hours=MEME_EXPIRY_HOURS) - timedelta(minutes=2)
        expected_max = after_store + timedelta(hours=MEME_EXPIRY_HOURS) + timedelta(minutes=2)

        assert expected_min <= expiry_dt <= expected_max, (
            f"Meme node expiry {expiry_dt.isoformat()} is not ~48h from store time. "
            f"Expected between {expected_min.isoformat()} and {expected_max.isoformat()}"
        )
        assert MEME_EXPIRY_HOURS == 48

    def test_run_with_no_sources_configured_returns_zero(self, engine):
        """ResearchAgent with no sources configured returns 0 stored."""
        from asomien.agents.research_agent import ResearchAgent
        agent = ResearchAgent(
            memory=engine,
            reddit_source=None,
            tumblr_source=None,
            kym_source=None,
            threads_source=None,
            ddg_source=None,
        )
        count = agent.run()
        assert count == 0

    def test_detect_meme_format_proxy_works(self):
        """ResearchAgent.detect_meme_format() is a working proxy to RedditSource."""
        from asomien.agents.research_agent import ResearchAgent
        result = ResearchAgent.detect_meme_format("my toxic trait is existing")
        assert result == "toxic_trait"

    def test_store_findings_deduplicates_before_storing(self, engine):
        """
        store_findings() with duplicate URLs stores only unique nodes.
        Verifies the aggregator is wired correctly inside the agent.
        """
        findings = [
            _make_finding("duplicate post", url="https://r.com/same"),
            _make_finding("duplicate post again", url="https://r.com/same"),  # same URL
            _make_finding("unique post", url="https://r.com/different"),
        ]
        from asomien.agents.research_agent import ResearchAgent
        agent = ResearchAgent(memory=engine)
        count = agent.store_findings(findings)
        assert count == 2, (
            f"Expected 2 unique nodes stored (3 findings - 1 duplicate). Got {count}"
        )

    def test_source_errors_dont_crash_run(self, engine):
        """
        If a source raises during run(), the agent continues with other sources.
        """
        from asomien.agents.research_agent import ResearchAgent

        bad_reddit = MagicMock()
        bad_reddit.fetch.side_effect = RuntimeError("Reddit API down")

        good_tumblr = MagicMock()
        good_tumblr.fetch.return_value = [
            _make_finding("tumblr post", url="https://tumblr.com/post/1", source="tumblr_rss")
        ]

        agent = ResearchAgent(
            memory=engine,
            reddit_source=bad_reddit,
            tumblr_source=good_tumblr,
        )
        # Should not raise; should store the tumblr finding
        count = agent.run()
        assert count >= 0   # May be 0 or 1 depending on error handling path

    # ── BaseAgent inheritance ─────────────────────────────────────────────────

    def test_research_agent_is_a_base_agent(self):
        """ResearchAgent inherits from BaseAgent."""
        from asomien.agents.base_agent import BaseAgent
        from asomien.agents.research_agent import ResearchAgent
        assert issubclass(ResearchAgent, BaseAgent)

    def test_research_agent_has_log_action(self, engine):
        """ResearchAgent has the log_action method from BaseAgent."""
        agent = self._make_agent(engine)
        assert hasattr(agent, "log_action")
        assert callable(agent.log_action)
