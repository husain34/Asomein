"""
tests/test_phase1.py

Phase 1 test suite. Tests MUST pass with zero errors before Phase 2 begins.

Covers:
  - Configuration system (settings.py)
  - Database schema creation + WAL mode (migrations.py)
  - Memory node models (nodes.py)
  - NIM Rate Limiter (rate_limiter.py)
  - Event Bus (event_bus.py)

All tests use in-memory SQLite databases (":memory:") or temp files
to avoid contaminating production data.

Run with:
    .\\venv\\Scripts\\pytest tests/test_phase1.py -v
"""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ── Ensure tests can import from project root ─────────────────────────────────
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))


# =============================================================================
# 1. Configuration System Tests
# =============================================================================

class TestSettings:
    """Tests for asomien/config/settings.py"""

    def test_settings_import(self):
        """Settings module is importable and SAFETY_CONFIG is a non-empty dict."""
        from asomien.config.settings import Settings, SAFETY_CONFIG
        assert callable(Settings), "Settings must be a callable class"
        assert isinstance(SAFETY_CONFIG, dict), "SAFETY_CONFIG must be a dict"
        assert len(SAFETY_CONFIG) > 0, "SAFETY_CONFIG must not be empty"

    def test_safety_config_keys_present(self):
        """All mandatory SAFETY_CONFIG keys from blueprint Section 10 are present."""
        from asomien.config.settings import SAFETY_CONFIG

        required_keys = [
            "warmup_phase_days",
            "warmup_max_posts_per_day",
            "warmup_max_replies_per_day",
            "warmup_human_approval_required",
            "max_posts_per_day",
            "max_ai_replies_per_day",
            "max_deletions_per_day",
            "min_time_between_posts_minutes",
            "jitter_range_minutes",
            "jitter_enabled",
            "reply_read_delay_min_seconds",
            "reply_read_delay_max_seconds",
            "reply_type_delay_min_seconds",
            "reply_type_delay_max_seconds",
            "publish_windows",
            "max_llm_calls_per_hour",
            "max_characters_per_post",
            "research_expiry_hours_meme",
            "research_expiry_hours_standard",
            "topic_blocklist",
            "max_promotional_tone_score",
            "advice_detection_enabled",
            "hustle_vocabulary_blocklist",
            "monetization_module_enabled",
        ]
        for key in required_keys:
            assert key in SAFETY_CONFIG, f"Missing SAFETY_CONFIG key: '{key}'"

    def test_safety_config_warmup_values(self):
        """Warmup phase values match blueprint specification exactly."""
        from asomien.config.settings import SAFETY_CONFIG

        assert SAFETY_CONFIG["warmup_phase_days"] == 14
        assert SAFETY_CONFIG["warmup_max_posts_per_day"] == 1
        assert SAFETY_CONFIG["warmup_max_replies_per_day"] == 5
        assert SAFETY_CONFIG["warmup_human_approval_required"] is True

    def test_safety_config_sludge_delays(self):
        """
        Human simulation delays match blueprint Section 9 exactly.
        These are SACRED VALUES — do not change.
        """
        from asomien.config.settings import SAFETY_CONFIG

        # _human_read_delay: 45–180s
        assert SAFETY_CONFIG["reply_read_delay_min_seconds"] == 45
        assert SAFETY_CONFIG["reply_read_delay_max_seconds"] == 180

        # _human_type_delay: 10–40s
        assert SAFETY_CONFIG["reply_type_delay_min_seconds"] == 10
        assert SAFETY_CONFIG["reply_type_delay_max_seconds"] == 40

    def test_safety_config_jitter_range(self):
        """T_jitter range matches blueprint specification: ±45 minutes."""
        from asomien.config.settings import SAFETY_CONFIG

        assert SAFETY_CONFIG["jitter_range_minutes"] == 45
        assert SAFETY_CONFIG["jitter_enabled"] is True

    def test_safety_config_character_limit(self):
        """Post character limit is 500 as specified in blueprint."""
        from asomien.config.settings import SAFETY_CONFIG

        assert SAFETY_CONFIG["max_characters_per_post"] == 500

    def test_safety_config_meme_expiry(self):
        """Meme research expires in 48h, standard in 72h."""
        from asomien.config.settings import SAFETY_CONFIG

        assert SAFETY_CONFIG["research_expiry_hours_meme"] == 48
        assert SAFETY_CONFIG["research_expiry_hours_standard"] == 72

    def test_safety_config_hustle_blocklist(self):
        """Hustle vocabulary blocklist contains required forbidden words."""
        from asomien.config.settings import SAFETY_CONFIG

        blocklist = SAFETY_CONFIG["hustle_vocabulary_blocklist"]
        required = ["hustle", "grind", "optimize", "productivity", "discipline", "mindset"]
        for word in required:
            assert word in blocklist, f"'{word}' missing from hustle_vocabulary_blocklist"

    def test_settings_defaults(self):
        """Settings instantiates with safe defaults when no .env is present."""
        with patch.dict(os.environ, {}, clear=True):
            # Override to avoid picking up any actual .env
            from asomien.config.settings import Settings
            s = Settings(
                _env_file=None,  # don't read .env
                nvidia_nim_api_key="",
                threads_access_token="",
                threads_user_id="",
            )
            assert s.nim_model == "nvidia/nemotron-3-ultra-550b-a55b"
            assert s.nim_rate_limit_per_minute == 40
            assert s.nim_rate_limit_soft_cap == 35
            assert s.memory_db_path == "data/memory.db"
            assert s.metrics_db_path == "data/metrics.db"
            assert s.directives_db_path == "data/directives.db"

    def test_is_warmup_phase_new_account(self):
        """is_warmup_phase returns True when account was created today."""
        from asomien.config.settings import Settings
        s = Settings(
            _env_file=None,
            account_created_at=datetime.now().date().isoformat(),
        )
        assert s.is_warmup_phase is True

    def test_is_warmup_phase_old_account(self):
        """is_warmup_phase returns False when account is older than 14 days."""
        from asomien.config.settings import Settings
        old_date = (datetime.now() - timedelta(days=20)).date().isoformat()
        s = Settings(
            _env_file=None,
            account_created_at=old_date,
        )
        assert s.is_warmup_phase is False

    def test_warmup_day_number_day_zero(self):
        """warmup_day_number is 0 on creation day."""
        from asomien.config.settings import Settings
        s = Settings(
            _env_file=None,
            account_created_at=datetime.now().date().isoformat(),
        )
        assert s.warmup_day_number == 0

    def test_personality_seed_json_exists(self):
        """personality_seed.json exists and is valid JSON."""
        seed_path = Path("asomien/config/personality_seed.json")
        assert seed_path.exists(), "personality_seed.json not found"

        with open(seed_path) as f:
            data = json.load(f)

        assert "persona_name" in data
        assert data["persona_name"] == "asomien"
        assert "core_traits" in data
        assert "adaptive_traits" in data
        assert "writing_rules" in data

    def test_personality_seed_lowercase_rule(self):
        """personality_seed enforces lowercase_always writing rule."""
        with open("asomien/config/personality_seed.json") as f:
            data = json.load(f)
        assert data["writing_rules"]["case"] == "lowercase_always"

    def test_personality_seed_has_forbidden_phrases(self):
        """personality_seed contains the required forbidden phrases."""
        with open("asomien/config/personality_seed.json") as f:
            data = json.load(f)
        forbidden = data["writing_rules"]["forbidden_phrases"]
        assert "hustle" in forbidden
        assert "productivity" in forbidden
        assert "optimize" in forbidden


# =============================================================================
# 2. Database Schema & WAL Mode Tests
# =============================================================================

class TestMigrations:
    """Tests for asomien/memory/migrations.py"""

    def test_migrations_import(self):
        """Migrations module exports callable functions."""
        from asomien.memory.migrations import run_migrations, verify_wal_mode, get_table_names
        assert callable(run_migrations), "run_migrations must be callable"
        assert callable(verify_wal_mode), "verify_wal_mode must be callable"
        assert callable(get_table_names), "get_table_names must be callable"

    def test_run_migrations_creates_databases(self, tmp_path):
        """run_migrations() creates all 3 database files."""
        from asomien.memory.migrations import run_migrations

        mem = str(tmp_path / "memory.db")
        met = str(tmp_path / "metrics.db")
        dire = str(tmp_path / "directives.db")

        run_migrations(mem, met, dire)

        assert Path(mem).exists()
        assert Path(met).exists()
        assert Path(dire).exists()

    def test_memory_db_wal_mode(self, tmp_path):
        """memory.db is opened in WAL mode after migration."""
        from asomien.memory.migrations import run_migrations, verify_wal_mode

        mem = str(tmp_path / "memory.db")
        run_migrations(mem, str(tmp_path / "m.db"), str(tmp_path / "d.db"))
        assert verify_wal_mode(mem), "memory.db is NOT in WAL mode"

    def test_metrics_db_wal_mode(self, tmp_path):
        """metrics.db is opened in WAL mode after migration."""
        from asomien.memory.migrations import run_migrations, verify_wal_mode

        met = str(tmp_path / "metrics.db")
        run_migrations(str(tmp_path / "m.db"), met, str(tmp_path / "d.db"))
        assert verify_wal_mode(met), "metrics.db is NOT in WAL mode"

    def test_directives_db_wal_mode(self, tmp_path):
        """directives.db is opened in WAL mode after migration."""
        from asomien.memory.migrations import run_migrations, verify_wal_mode

        dire = str(tmp_path / "directives.db")
        run_migrations(str(tmp_path / "m.db"), str(tmp_path / "met.db"), dire)
        assert verify_wal_mode(dire), "directives.db is NOT in WAL mode"

    def test_memory_db_tables(self, tmp_path):
        """memory.db contains all required tables from blueprint Section 4."""
        from asomien.memory.migrations import run_migrations, get_table_names

        mem = str(tmp_path / "memory.db")
        run_migrations(mem, str(tmp_path / "m.db"), str(tmp_path / "d.db"))

        tables = get_table_names(mem)
        required = ["topics", "research_nodes", "posts", "reflections",
                    "rules", "personality_traits", "events"]
        for t in required:
            assert t in tables, f"Table '{t}' missing from memory.db"

    def test_metrics_db_tables(self, tmp_path):
        """metrics.db contains all required tables from blueprint Section 4."""
        from asomien.memory.migrations import run_migrations, get_table_names

        met = str(tmp_path / "metrics.db")
        run_migrations(str(tmp_path / "m.db"), met, str(tmp_path / "d.db"))

        tables = get_table_names(met)
        required = ["post_metrics", "audience_snapshots", "audience_demographics", "daily_stats"]
        for t in required:
            assert t in tables, f"Table '{t}' missing from metrics.db"

    def test_directives_db_tables(self, tmp_path):
        """directives.db contains all required tables from blueprint Section 4."""
        from asomien.memory.migrations import run_migrations, get_table_names

        dire = str(tmp_path / "directives.db")
        run_migrations(str(tmp_path / "m.db"), str(tmp_path / "met.db"), dire)

        tables = get_table_names(dire)
        required = ["directives", "campaigns", "monetization_signals", "reports", "warmup_log"]
        for t in required:
            assert t in tables, f"Table '{t}' missing from directives.db"

    def test_migrations_idempotent(self, tmp_path):
        """Running migrations twice does not raise an error (IF NOT EXISTS)."""
        from asomien.memory.migrations import run_migrations

        args = (
            str(tmp_path / "memory.db"),
            str(tmp_path / "metrics.db"),
            str(tmp_path / "directives.db"),
        )
        run_migrations(*args)
        # Should not raise
        run_migrations(*args)

    def test_posts_table_schema(self, tmp_path):
        """posts table in memory.db has all required columns from blueprint."""
        from asomien.memory.migrations import run_migrations

        mem = str(tmp_path / "memory.db")
        run_migrations(mem, str(tmp_path / "m.db"), str(tmp_path / "d.db"))

        conn = sqlite3.connect(mem)
        cursor = conn.execute("PRAGMA table_info(posts);")
        columns = {row[1] for row in cursor.fetchall()}
        conn.close()

        required_cols = [
            "id", "topic_id", "platform", "content", "post_type", "status",
            "scheduled_publish_time", "actual_publish_time", "jitter_offset_minutes",
            "posted_at", "threads_post_id", "threads_container_id", "permalink",
            "hook_template_used", "is_reply", "reply_to_threads_id",
            "is_sponsored", "sponsor_campaign_id", "pre_score", "summary",
            "created_at",
        ]
        for col in required_cols:
            assert col in columns, f"Column '{col}' missing from posts table"

    def test_research_nodes_expiry_column(self, tmp_path):
        """research_nodes has expiry column for 48h meme decay."""
        from asomien.memory.migrations import run_migrations

        mem = str(tmp_path / "memory.db")
        run_migrations(mem, str(tmp_path / "m.db"), str(tmp_path / "d.db"))

        conn = sqlite3.connect(mem)
        cursor = conn.execute("PRAGMA table_info(research_nodes);")
        columns = {row[1] for row in cursor.fetchall()}
        conn.close()

        assert "expiry" in columns
        assert "cultural_freshness" in columns
        assert "meme_format_detected" in columns


# =============================================================================
# 3. Memory Node Model Tests
# =============================================================================

class TestMemoryNodes:
    """Tests for asomien/memory/nodes.py"""

    def test_nodes_import(self):
        """All memory node classes are importable and callable."""
        from asomien.memory.nodes import (
            TopicNode, ResearchNode, PostNode, MetricsSnapshot,
            ReflectionNode, RuleNode, CritiqueScore, AudienceSnapshot,
            DirectiveNode,
        )
        for cls in [TopicNode, ResearchNode, PostNode, MetricsSnapshot,
                    ReflectionNode, RuleNode, CritiqueScore, AudienceSnapshot,
                    DirectiveNode]:
            assert callable(cls), f"{cls.__name__} must be a callable class"

    def test_topic_node_creation(self):
        """TopicNode creates with defaults and auto-generates UUID."""
        from asomien.memory.nodes import TopicNode
        node = TopicNode(name="phone brain")
        assert node.id
        assert len(node.id) == 36  # UUID4 format
        assert node.name == "phone brain"
        assert 0.0 <= node.relevance_score <= 1.0
        assert 0.0 <= node.niche_alignment <= 1.0

    def test_topic_node_score_clamp(self):
        """TopicNode clamps relevance/niche scores to [0.0, 1.0]."""
        from asomien.memory.nodes import TopicNode
        node = TopicNode(name="test", relevance_score=2.5, niche_alignment=-0.3)
        assert node.relevance_score == 1.0
        assert node.niche_alignment == 0.0

    def test_research_node_creation(self):
        """ResearchNode creates with valid source."""
        from asomien.memory.nodes import ResearchNode
        node = ResearchNode(source="reddit", headline="my toxic trait", summary="test")
        assert node.source == "reddit"
        assert 0 <= node.cultural_freshness <= 100

    def test_research_node_cultural_freshness_clamp(self):
        """ResearchNode clamps cultural_freshness to [0, 100]."""
        from asomien.memory.nodes import ResearchNode
        node = ResearchNode(source="reddit", cultural_freshness=999)
        assert node.cultural_freshness == 100
        node2 = ResearchNode(source="reddit", cultural_freshness=-5)
        assert node2.cultural_freshness == 0

    def test_post_node_creation(self):
        """PostNode creates with valid content."""
        from asomien.memory.nodes import PostNode
        post = PostNode(content="my toxic trait is opening 14 tabs")
        assert post.content == "my toxic trait is opening 14 tabs"
        assert post.status == "draft"
        assert post.platform == "threads"
        assert post.post_type == "text"

    def test_post_node_lowercase_compliance(self):
        """PostNode.is_lowercase_compliant detects uppercase first characters."""
        from asomien.memory.nodes import PostNode

        # Compliant: starts with lowercase
        p1 = PostNode(content="my toxic trait is chaos")
        assert p1.is_lowercase_compliant is True

        # Non-compliant: starts with uppercase
        p2 = PostNode(content="My toxic trait is chaos")
        assert p2.is_lowercase_compliant is False

    def test_post_node_char_limit(self):
        """PostNode detects when content exceeds 500 characters."""
        from asomien.memory.nodes import PostNode

        short = PostNode(content="a" * 499)
        assert short.is_over_limit is False

        exact = PostNode(content="a" * 500)
        assert exact.is_over_limit is False

        over = PostNode(content="a" * 501)
        assert over.is_over_limit is True

    def test_post_node_invalid_status(self):
        """PostNode raises ValueError for invalid status."""
        from asomien.memory.nodes import PostNode
        with pytest.raises(ValueError, match="Invalid post status"):
            PostNode(content="test", status="sent")

    def test_post_node_invalid_type(self):
        """PostNode raises ValueError for invalid post_type."""
        from asomien.memory.nodes import PostNode
        with pytest.raises(ValueError, match="Invalid post type"):
            PostNode(content="test", post_type="video")

    def test_metrics_snapshot_weighted_engagement(self):
        """MetricsSnapshot computes weighted engagement using blueprint signal weights."""
        from asomien.memory.nodes import MetricsSnapshot
        snap = MetricsSnapshot(
            post_id="test-id",
            likes=100,
            replies=10,
            reposts=5,
            quotes=3,
        )
        # Expected: (10 × 27) + (3 × 8) + (5 × 5) + (100 × 1)
        #         = 270 + 24 + 25 + 100 = 419
        assert snap.weighted_engagement == 419

    def test_critique_score_hard_reject(self):
        """CritiqueScore.hard_reject() creates a definitively rejected score."""
        from asomien.memory.nodes import CritiqueScore
        score = CritiqueScore.hard_reject("starts with capital letter")
        assert score.is_approved is False
        assert score.passed_hard_gates is False
        assert "capital letter" in score.rejection_reason
        assert score.composite == 0.0

    def test_rule_node_confidence_clamp(self):
        """RuleNode clamps confidence to [0.0, 1.0]."""
        from asomien.memory.nodes import RuleNode
        rule = RuleNode(rule_text="test rule", confidence=1.5)
        assert rule.confidence == 1.0

    def test_reflection_node_confidence_clamp(self):
        """ReflectionNode clamps confidence to [0.0, 1.0]."""
        from asomien.memory.nodes import ReflectionNode
        node = ReflectionNode(post_id="abc", confidence=-0.5)
        assert node.confidence == 0.0

    def test_critique_score_to_dict(self):
        """CritiqueScore.to_dict() returns a plain dict for JSON serialization."""
        from asomien.memory.nodes import CritiqueScore
        score = CritiqueScore(
            composite=0.72,
            hook_strength=0.8,
            reply_bait_score=0.7,
            persona_authenticity=0.65,
            is_approved=True,
        )
        d = score.to_dict()
        assert isinstance(d, dict)
        assert d["composite"] == 0.72
        assert d["is_approved"] is True

    def test_audience_snapshot_defaults(self):
        """AudienceSnapshot creates with zero defaults."""
        from asomien.memory.nodes import AudienceSnapshot
        snap = AudienceSnapshot()
        assert snap.followers_count == 0
        assert snap.profile_views == 0

    def test_directive_node_creation(self):
        """DirectiveNode creates with required fields."""
        from asomien.memory.nodes import DirectiveNode
        d = DirectiveNode(directive_type="topic_focus", content="focus on 3am energy today")
        assert d.status == "active"
        assert d.priority == 5


# =============================================================================
# 4. Rate Limiter Tests
# =============================================================================

class TestNIMRateLimiter:
    """Tests for asomien/core/rate_limiter.py"""

    def test_import(self):
        """NIMRateLimiter class is importable and callable."""
        from asomien.core.rate_limiter import NIMRateLimiter
        assert callable(NIMRateLimiter), "NIMRateLimiter must be a callable class"

    def test_acquire_immediately_available(self):
        """acquire() returns True immediately when tokens are available."""
        from asomien.core.rate_limiter import NIMRateLimiter
        limiter = NIMRateLimiter(max_calls_per_minute=10)
        result = limiter.acquire()
        assert result is True

    def test_get_remaining_decrements(self):
        """get_remaining() decrements after each acquire()."""
        from asomien.core.rate_limiter import NIMRateLimiter
        limiter = NIMRateLimiter(max_calls_per_minute=5)
        assert limiter.get_remaining() == 5
        limiter.acquire()
        assert limiter.get_remaining() == 4
        limiter.acquire()
        assert limiter.get_remaining() == 3

    def test_estimate_wait_returns_zero_when_available(self):
        """estimate_wait() returns 0.0 when tokens are immediately available."""
        from asomien.core.rate_limiter import NIMRateLimiter
        limiter = NIMRateLimiter(max_calls_per_minute=10)
        assert limiter.estimate_wait() == 0.0

    def test_estimate_wait_positive_when_exhausted(self):
        """estimate_wait() returns a positive float when the window is full."""
        from asomien.core.rate_limiter import NIMRateLimiter
        limiter = NIMRateLimiter(max_calls_per_minute=3)
        for _ in range(3):
            limiter.acquire()
        wait = limiter.estimate_wait()
        assert wait > 0.0, "Should have a positive wait time after exhausting tokens"

    def test_timeout_raises_runtime_error(self):
        """acquire() raises RuntimeError if it cannot get a token within timeout."""
        from asomien.core.rate_limiter import NIMRateLimiter
        limiter = NIMRateLimiter(max_calls_per_minute=2, window_seconds=5.0)
        # Exhaust all tokens
        for _ in range(2):
            limiter.acquire()
        # Should timeout immediately (timeout=0.1s is less than window)
        with pytest.raises(RuntimeError, match="Timeout"):
            limiter.acquire(timeout=0.1)

    def test_usage_in_window_property(self):
        """usage_in_window tracks current call count correctly."""
        from asomien.core.rate_limiter import NIMRateLimiter
        limiter = NIMRateLimiter(max_calls_per_minute=10)
        assert limiter.usage_in_window == 0
        limiter.acquire()
        limiter.acquire()
        assert limiter.usage_in_window == 2

    def test_reset_clears_timestamps(self):
        """reset() clears all timestamps and restores full token count."""
        from asomien.core.rate_limiter import NIMRateLimiter
        limiter = NIMRateLimiter(max_calls_per_minute=3)
        for _ in range(3):
            limiter.acquire()
        assert limiter.get_remaining() == 0
        limiter.reset()
        assert limiter.get_remaining() == 3

    def test_rate_limiter_enforces_hard_limit(self):
        """
        Under high demand, all N acquired tokens are within the allowed window.
        This tests that the limiter correctly tracks the rolling window.
        """
        from asomien.core.rate_limiter import NIMRateLimiter
        limiter = NIMRateLimiter(max_calls_per_minute=5, window_seconds=60.0)
        # Acquire 5 tokens — should all succeed
        for _ in range(5):
            result = limiter.acquire()
            assert result is True
        # 6th should fail with short timeout
        with pytest.raises(RuntimeError):
            limiter.acquire(timeout=0.05)

    def test_default_soft_cap_is_35(self):
        """NIMRateLimiter default max_calls matches the SAFETY_CONFIG soft cap."""
        from asomien.core.rate_limiter import NIMRateLimiter
        # Default is 35, not 40 (we use the soft cap, not the hard limit)
        limiter = NIMRateLimiter()
        assert limiter.max_calls == 35


# =============================================================================
# 5. Event Bus Tests
# =============================================================================

class TestEventBus:
    """Tests for asomien/core/event_bus.py"""

    @pytest.fixture
    def bus_with_db(self, tmp_path):
        """Create an EventBus with a fresh temp database."""
        from asomien.memory.migrations import run_migrations
        from asomien.core.event_bus import EventBus

        mem = str(tmp_path / "memory.db")
        run_migrations(mem, str(tmp_path / "metrics.db"), str(tmp_path / "directives.db"))
        return EventBus(db_path=mem)

    def test_import(self):
        """EventBus and EventType are importable and correctly typed."""
        from asomien.core.event_bus import EventBus, EventType
        assert callable(EventBus), "EventBus must be a callable class"
        assert isinstance(EventType.ALL, (set, frozenset, list)), (
            "EventType.ALL must be a collection"
        )

    def test_all_event_types_defined(self):
        """All 10 canonical event types from blueprint Section 2 are present."""
        from asomien.core.event_bus import EventType
        required = {
            "RESEARCH_COMPLETE", "POST_CREATED", "POST_PUBLISHED",
            "METRICS_UPDATED", "REFLECTION_COMPLETE", "REPLY_RECEIVED",
            "DIRECTIVE_ISSUED", "SLEEP_TRIGGERED",
            "WARMUP_PHASE_ACTIVE", "WARMUP_PHASE_COMPLETE",
        }
        for event_type in required:
            assert event_type in EventType.ALL, f"Missing EventType: {event_type}"

    def test_publish_persists_to_db(self, bus_with_db, tmp_path):
        """
        HARDENED: publish() stores the event in SQLite with correct event_type,
        payload, and producer values — not just row existence.
        """
        from asomien.core.event_bus import EventType
        import json as _json

        bus = bus_with_db
        event_id = bus.publish(
            event_type=EventType.POST_PUBLISHED,
            payload={"post_id": "test-123"},
            producer="test_publisher",
        )

        # Verify event_id is a valid UUID
        import uuid as _uuid
        try:
            _uuid.UUID(event_id)
        except (ValueError, AttributeError):
            pytest.fail(f"publish() must return a valid UUID. Got: {event_id!r}")

        conn = sqlite3.connect(str(tmp_path / "memory.db"))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM events WHERE id = ?", (event_id,)
        ).fetchone()
        conn.close()

        assert row is not None, "Event not found in database"
        assert row["event_type"] == EventType.POST_PUBLISHED, (
            f"event_type mismatch: expected {EventType.POST_PUBLISHED!r}, "
            f"got {row['event_type']!r}"
        )
        assert row["produced_by"] == "test_publisher", (
            f"producer mismatch: got {row['produced_by']!r}"
        )
        stored_payload = _json.loads(row["payload"])
        assert stored_payload["post_id"] == "test-123", (
            f"payload.post_id mismatch: got {stored_payload!r}"
        )

    def test_subscribe_and_dispatch(self, bus_with_db):
        """Subscribing and publishing triggers the callback with the correct payload."""
        from asomien.core.event_bus import EventType

        bus = bus_with_db
        received_payloads = []

        def on_research_complete(payload: dict):
            received_payloads.append(payload)

        bus.subscribe(EventType.RESEARCH_COMPLETE, on_research_complete)
        bus.publish(
            event_type=EventType.RESEARCH_COMPLETE,
            payload={"findings_count": 5},
            producer="research_agent",
        )

        assert len(received_payloads) == 1
        assert received_payloads[0]["findings_count"] == 5

    def test_multiple_subscribers_same_event(self, bus_with_db):
        """Multiple subscribers all receive the same event."""
        from asomien.core.event_bus import EventType

        bus = bus_with_db
        call_counts = [0, 0]

        bus.subscribe(EventType.POST_PUBLISHED, lambda p: call_counts.__setitem__(0, call_counts[0] + 1))
        bus.subscribe(EventType.POST_PUBLISHED, lambda p: call_counts.__setitem__(1, call_counts[1] + 1))

        bus.publish(EventType.POST_PUBLISHED, {"post_id": "abc"})

        assert call_counts[0] == 1
        assert call_counts[1] == 1

    def test_subscriber_error_does_not_crash_bus(self, bus_with_db):
        """A subscriber that raises an exception does not crash the event bus."""
        from asomien.core.event_bus import EventType

        bus = bus_with_db

        def bad_subscriber(payload: dict):
            raise RuntimeError("subscriber exploded")

        bus.subscribe(EventType.DIRECTIVE_ISSUED, bad_subscriber)

        # Should not raise
        event_id = bus.publish(EventType.DIRECTIVE_ISSUED, {"content": "test"})
        assert event_id  # event still got published

    def test_no_subscribers_does_not_crash(self, bus_with_db):
        """
        HARDENED: Publishing with no subscribers completes without error
        and returns a valid UUID string.
        """
        from asomien.core.event_bus import EventType
        import uuid as _uuid

        bus = bus_with_db
        event_id = bus.publish(EventType.SLEEP_TRIGGERED, {"reason": "test"})

        assert event_id, "event_id must be a non-empty string"
        try:
            _uuid.UUID(event_id)
        except (ValueError, AttributeError):
            pytest.fail(
                f"publish() must return a valid UUID even with no subscribers. "
                f"Got: {event_id!r}"
            )

    def test_get_pending_count(self, bus_with_db):
        """
        get_pending_count() returns the correct count.

        Events with subscribers are marked 'consumed' in the DB immediately.
        Events with NO subscribers remain 'pending' in the DB (they may be
        replayed later via consume_pending). This test verifies both behaviors.
        """
        from asomien.core.event_bus import EventType

        bus = bus_with_db

        # --- Event WITH a subscriber: gets consumed immediately ---
        consumed = []
        bus.subscribe(EventType.WARMUP_PHASE_ACTIVE, lambda p: consumed.append(p))
        bus.publish(EventType.WARMUP_PHASE_ACTIVE, {"day": 1})
        # Subscriber received the event; it should be marked consumed
        count_after_consumed = bus.get_pending_count()
        # After dispatching to subscriber, event is marked consumed: pending = 0
        assert count_after_consumed == 0

        # --- Event with NO subscriber: stays pending in DB ---
        bus.publish(EventType.SLEEP_TRIGGERED, {"reason": "no-subscriber-test"})
        count_after_no_sub = bus.get_pending_count()
        # No subscriber → _mark_consumed not called → stays pending
        assert count_after_no_sub == 1

    def test_warmup_event_types_available(self, bus_with_db):
        """
        HARDENED: WARMUP_PHASE_ACTIVE and WARMUP_PHASE_COMPLETE publish successfully,
        returning distinct valid UUIDs.
        """
        from asomien.core.event_bus import EventType
        import uuid as _uuid

        bus = bus_with_db

        id1 = bus.publish(EventType.WARMUP_PHASE_ACTIVE, {"day": 1})
        id2 = bus.publish(EventType.WARMUP_PHASE_COMPLETE, {"day": 14})

        for eid, label in [(id1, "WARMUP_PHASE_ACTIVE"), (id2, "WARMUP_PHASE_COMPLETE")]:
            assert eid, f"{label} publish() must return a non-empty id"
            try:
                _uuid.UUID(eid)
            except (ValueError, AttributeError):
                pytest.fail(f"{label} publish() must return a valid UUID. Got: {eid!r}")

        assert id1 != id2, "Two separate publishes must return distinct UUIDs"

    def test_get_recent_events(self, bus_with_db):
        """get_recent_events() returns published events."""
        from asomien.core.event_bus import EventType

        bus = bus_with_db
        bus.publish(EventType.POST_CREATED, {"post_id": "xyz"}, producer="content_agent")

        events = bus.get_recent_events(limit=10)
        assert len(events) >= 1
        types = [e["event_type"] for e in events]
        assert EventType.POST_CREATED in types

    def test_unsubscribe(self, bus_with_db):
        """unsubscribe() prevents a callback from receiving future events."""
        from asomien.core.event_bus import EventType

        bus = bus_with_db
        received = []

        def callback(payload: dict):
            received.append(payload)

        bus.subscribe(EventType.METRICS_UPDATED, callback)
        bus.publish(EventType.METRICS_UPDATED, {"snap": 1})
        assert len(received) == 1

        bus.unsubscribe(EventType.METRICS_UPDATED, callback)
        bus.publish(EventType.METRICS_UPDATED, {"snap": 2})
        assert len(received) == 1  # Should NOT have received the second event

    def test_consume_pending_replays_db_events(self, tmp_path):
        """
        consume_pending() dispatches events that are in the DB with status='pending'
        but were not dispatched in-memory (simulates restart scenario).
        """
        from asomien.memory.migrations import run_migrations
        from asomien.core.event_bus import EventBus, EventType

        mem = str(tmp_path / "memory.db")
        run_migrations(mem, str(tmp_path / "metrics.db"), str(tmp_path / "directives.db"))

        # Manually insert a pending event into the DB (simulating pre-restart event)
        event_id = str(uuid.uuid4())
        conn = sqlite3.connect(mem)
        conn.execute(
            """
            INSERT INTO events (id, event_type, payload, produced_by, status, created_at)
            VALUES (?, ?, ?, ?, 'pending', datetime('now'))
            """,
            (event_id, EventType.REFLECTION_COMPLETE, '{"post_id": "test"}', "test"),
        )
        conn.commit()
        conn.close()

        # Create a fresh bus (simulates restart)
        bus = EventBus(db_path=mem)
        received = []
        bus.subscribe(EventType.REFLECTION_COMPLETE, lambda p: received.append(p))

        # consume_pending should pick up the orphaned event
        count = bus.consume_pending()
        assert count == 1
        assert len(received) == 1
        assert received[0]["post_id"] == "test"
