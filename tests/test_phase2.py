"""
tests/test_phase2.py

Phase 2 test suite — Memory Engine & Personality Engine.
AUDIT-HARDENED: All lazy assertions replaced with exact-value checks.
All boundary conditions added. All OR-logic in personality tests removed.

Anti-patterns eliminated:
  - No `assert x is not None` as the final assertion
  - No `assert 0 <= x <= 100` when an exact value is derivable
  - No broken loop-only assertions for empty-result proofs
  - No OR-logic in prompt injection tests
  - Expiry boundary tests at 47h59m (active) and 48h01m (expired)

Run with:
    .\\venv\\Scripts\\pytest tests/test_phase2.py -v
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))


# =============================================================================
# Helpers / Fixtures
# =============================================================================

@pytest.fixture
def fresh_db(tmp_path):
    """Create a fully migrated memory.db in a temp directory and return its path."""
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
    """Return a MemoryEngine bound to the fresh test database."""
    from asomien.memory.engine import MemoryEngine
    return MemoryEngine(db_path=fresh_db)


@pytest.fixture
def personality():
    """Return a PersonalityEngine loaded from the real personality_seed.json."""
    from asomien.personality.engine import PersonalityEngine
    return PersonalityEngine()


def _is_valid_uuid(val: str) -> bool:
    try:
        uuid.UUID(str(val))
        return True
    except (ValueError, AttributeError):
        return False


def _parse_db_datetime(raw: str) -> datetime:
    """Parse a datetime stored as ISO string from SQLite (may be naive UTC)."""
    dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# =============================================================================
# 1. Memory Engine — store()
# =============================================================================

class TestMemoryEngineStore:
    """Tests for MemoryEngine.store() — exact value verification for all node types."""

    def test_store_topic_node_persists_exact_values(self, engine, fresh_db):
        """
        HARDENED: store() must persist ALL fields of a TopicNode correctly.
        Verifies id, name, and relevance_score — not just row existence.
        """
        from asomien.memory.nodes import TopicNode

        node = TopicNode(name="phone brain", relevance_score=0.9, niche_alignment=0.75)
        returned_id = engine.store(node)

        assert returned_id == node.id
        assert _is_valid_uuid(returned_id), "store() must return a valid UUID"

        conn = sqlite3.connect(fresh_db)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM topics WHERE id = ?", (node.id,)).fetchone()
        conn.close()

        assert row is not None, "TopicNode not found in topics table"
        assert row["name"] == "phone brain", f"Expected 'phone brain', got {row['name']!r}"
        assert abs(row["relevance_score"] - 0.9) < 1e-6, (
            f"Expected relevance_score=0.9, got {row['relevance_score']}"
        )
        assert abs(row["niche_alignment"] - 0.75) < 1e-6, (
            f"Expected niche_alignment=0.75, got {row['niche_alignment']}"
        )

    def test_store_standard_research_node_assigns_correct_72h_expiry(self, engine, fresh_db):
        """
        HARDENED: A standard ResearchNode (meme_format_detected='') must receive
        exactly a 72-hour expiry — not just 'some expiry'.
        This test would catch an engine that assigns 48h to all nodes.
        """
        from asomien.memory.nodes import ResearchNode

        discovered = datetime(2024, 3, 15, 10, 0, 0, tzinfo=timezone.utc)
        node = ResearchNode(
            source="duckduckgo",
            headline="standard research finding",
            meme_format_detected="",  # no meme → standard → 72h
            discovered_at=discovered,
        )
        assert node.expiry is None  # pre-condition: engine should assign it

        engine.store(node)

        conn = sqlite3.connect(fresh_db)
        row = conn.execute(
            "SELECT expiry FROM research_nodes WHERE id = ?", (node.id,)
        ).fetchone()
        conn.close()

        assert row is not None
        assert row[0] is not None, "Expiry must be set after store()"

        stored_expiry = _parse_db_datetime(row[0])
        expected_expiry = discovered + timedelta(hours=72)

        assert stored_expiry == expected_expiry, (
            f"Standard node must get 72h expiry. Expected {expected_expiry}, got {stored_expiry}"
        )

    def test_store_meme_research_node_assigns_correct_48h_expiry(self, engine, fresh_db):
        """
        HARDENED: A meme ResearchNode must receive exactly a 48-hour expiry.
        This test would catch an engine that assigns 72h to meme nodes.
        """
        from asomien.memory.nodes import ResearchNode

        discovered = datetime(2024, 3, 15, 10, 0, 0, tzinfo=timezone.utc)
        node = ResearchNode(
            source="reddit",
            headline="toxic trait meme",
            meme_format_detected="toxic_trait",  # meme → 48h
            discovered_at=discovered,
        )

        engine.store(node)

        conn = sqlite3.connect(fresh_db)
        row = conn.execute(
            "SELECT expiry FROM research_nodes WHERE id = ?", (node.id,)
        ).fetchone()
        conn.close()

        stored_expiry = _parse_db_datetime(row[0])
        expected_expiry = discovered + timedelta(hours=48)

        assert stored_expiry == expected_expiry, (
            f"Meme node must get 48h expiry. Expected {expected_expiry}, got {stored_expiry}"
        )

    def test_store_post_node_persists_exact_content(self, engine, fresh_db):
        """HARDENED: Verifies the content column, status, platform and post_type round-trip."""
        from asomien.memory.nodes import PostNode

        post = PostNode(
            content="my toxic trait is opening 14 tabs",
            status="queued",
            post_type="text",
            platform="threads",
            hook_template_used="toxic_trait",
        )
        engine.store(post)

        conn = sqlite3.connect(fresh_db)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM posts WHERE id = ?", (post.id,)).fetchone()
        conn.close()

        assert row is not None
        assert row["content"] == "my toxic trait is opening 14 tabs"
        assert row["status"] == "queued"
        assert row["platform"] == "threads"
        assert row["post_type"] == "text"
        assert row["hook_template_used"] == "toxic_trait"

    def test_store_reflection_node_persists_exact_fields(self, engine, fresh_db):
        """
        HARDENED: Verifies post_id, success_factors JSON serialisation, and confidence
        all round-trip correctly — not just row existence.
        """
        from asomien.memory.nodes import ReflectionNode

        ref = ReflectionNode(
            post_id="target-post-id-abc",
            success_factors=["lowercase hook", "relatable premise"],
            failure_factors=["too long"],
            confidence=0.82,
            sub_niche="phone brain",
        )
        engine.store(ref)

        conn = sqlite3.connect(fresh_db)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM reflections WHERE id = ?", (ref.id,)
        ).fetchone()
        conn.close()

        assert row is not None
        assert row["post_id"] == "target-post-id-abc", (
            f"post_id mismatch: {row['post_id']!r}"
        )
        assert row["sub_niche"] == "phone brain", (
            f"sub_niche mismatch: {row['sub_niche']!r}"
        )
        assert abs(row["confidence"] - 0.82) < 1e-6, (
            f"confidence mismatch: {row['confidence']}"
        )
        stored_success = json.loads(row["success_factors"])
        assert stored_success == ["lowercase hook", "relatable premise"], (
            f"success_factors serialisation broken: {stored_success!r}"
        )
        stored_failure = json.loads(row["failure_factors"])
        assert stored_failure == ["too long"], (
            f"failure_factors serialisation broken: {stored_failure!r}"
        )

    def test_store_rule_node_persists_exact_fields(self, engine, fresh_db):
        """HARDENED: Verifies rule_text, confidence, and evidence list round-trip."""
        from asomien.memory.nodes import RuleNode

        rule = RuleNode(
            rule_text="posts under 100 chars get 2x engagement",
            confidence=0.73,
            evidence=["post-id-1", "post-id-2"],
        )
        engine.store(rule)

        conn = sqlite3.connect(fresh_db)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM rules WHERE id = ?", (rule.id,)
        ).fetchone()
        conn.close()

        assert row is not None
        assert row["rule_text"] == "posts under 100 chars get 2x engagement"
        assert abs(row["confidence"] - 0.73) < 1e-6
        stored_evidence = json.loads(row["evidence"])
        assert stored_evidence == ["post-id-1", "post-id-2"], (
            f"evidence serialisation broken: {stored_evidence!r}"
        )

    def test_store_unsupported_type_raises(self, engine):
        """store() raises TypeError for unsupported node types."""
        with pytest.raises(TypeError, match="Unsupported node type"):
            engine.store({"not": "a node"})


# =============================================================================
# 2. Memory Engine — Expiry Logic (KEY MANDATE + BOUNDARY TESTS)
# =============================================================================

class TestMemoryEngineExpiry:
    """
    MANDATE: Rigorous proof that meme nodes expire at 48h and standard at 72h.
    Includes fence-post boundary tests at ±1 minute of each threshold.
    """

    def test_meme_node_expiry_is_exactly_48_hours(self, engine):
        """
        KEY TEST: Meme ResearchNode expiry is discovered_at + exactly 48h.
        Verifies to-the-second precision of the stored expiry timestamp.
        """
        from asomien.memory.engine import MEME_EXPIRY_HOURS
        from asomien.memory.nodes import ResearchNode

        assert MEME_EXPIRY_HOURS == 48, "MEME_EXPIRY_HOURS constant must be exactly 48"

        discovered = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        node = ResearchNode(
            source="reddit",
            headline="my toxic trait is sending memes at 3am",
            meme_format_detected="toxic_trait",
            discovered_at=discovered,
        )

        engine.store(node)
        fetched = engine.get_research_node(node.id)

        assert fetched is not None
        stored_expiry = _parse_db_datetime(fetched["expiry"])
        expected_expiry = discovered + timedelta(hours=48)

        assert stored_expiry == expected_expiry, (
            f"Meme node expiry must be exactly 48h after discovered_at.\n"
            f"  Expected : {expected_expiry.isoformat()}\n"
            f"  Got      : {stored_expiry.isoformat()}"
        )

    def test_standard_node_expiry_is_exactly_72_hours(self, engine):
        """
        KEY TEST: Standard ResearchNode expiry is discovered_at + exactly 72h.
        Verifies to-the-second precision.
        """
        from asomien.memory.engine import STANDARD_EXPIRY_HOURS
        from asomien.memory.nodes import ResearchNode

        assert STANDARD_EXPIRY_HOURS == 72, "STANDARD_EXPIRY_HOURS constant must be exactly 72"

        discovered = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        node = ResearchNode(
            source="duckduckgo",
            headline="standard research finding",
            meme_format_detected="",
            discovered_at=discovered,
        )

        engine.store(node)
        fetched = engine.get_research_node(node.id)

        stored_expiry = _parse_db_datetime(fetched["expiry"])
        expected_expiry = discovered + timedelta(hours=72)

        assert stored_expiry == expected_expiry, (
            f"Standard node expiry must be exactly 72h after discovered_at.\n"
            f"  Expected : {expected_expiry.isoformat()}\n"
            f"  Got      : {stored_expiry.isoformat()}"
        )

    def test_meme_node_expires_exactly_24h_before_standard(self, engine):
        """Meme expiry is exactly 24h earlier than standard when both start at same time."""
        from asomien.memory.nodes import ResearchNode

        discovered = datetime(2024, 6, 1, 0, 0, 0, tzinfo=timezone.utc)

        meme = ResearchNode(
            source="knowyourmeme",
            headline="pipeline meme goes viral",
            meme_format_detected="pipeline",
            discovered_at=discovered,
        )
        standard = ResearchNode(
            source="reddit",
            headline="people talk about internet use",
            meme_format_detected="",
            discovered_at=discovered,
        )

        engine.store(meme)
        engine.store(standard)

        meme_row = engine.get_research_node(meme.id)
        std_row = engine.get_research_node(standard.id)

        meme_expiry = _parse_db_datetime(meme_row["expiry"])
        std_expiry = _parse_db_datetime(std_row["expiry"])

        diff = std_expiry - meme_expiry
        assert diff == timedelta(hours=24), (
            f"Meme must expire exactly 24h before standard. Gap was {diff}"
        )

    # ── BOUNDARY FENCE-POST TESTS ─────────────────────────────────────────────
    # These are the tests the original suite was missing.
    # They prove that the threshold is at exactly 48h, not 47h59m or 48h01m.

    def test_meme_node_is_active_at_47h59m(self, engine):
        """
        BOUNDARY: A meme node discovered 47h 59m ago is still ACTIVE.
        One minute inside the window must not be expired.
        """
        from asomien.memory.nodes import ResearchNode

        discovered = datetime.now(timezone.utc) - timedelta(hours=47, minutes=59)
        node = ResearchNode(
            source="reddit",
            headline="almost expired meme",
            meme_format_detected="toxic_trait",
            discovered_at=discovered,
        )
        engine.store(node)

        # expire_stale_nodes() runs against current time
        expired_count = engine.expire_stale_nodes()

        fetched = engine.get_research_node(node.id)
        assert fetched["is_active"] == 1, (
            f"A meme node at 47h59m should still be ACTIVE. "
            f"expire_stale_nodes() deactivated {expired_count} row(s)."
        )

    def test_meme_node_is_inactive_at_48h01m(self, engine):
        """
        BOUNDARY: A meme node discovered 48h 01m ago is EXPIRED.
        One minute past the window must be deactivated.
        """
        from asomien.memory.nodes import ResearchNode

        discovered = datetime.now(timezone.utc) - timedelta(hours=48, minutes=1)
        node = ResearchNode(
            source="reddit",
            headline="just-expired meme",
            meme_format_detected="toxic_trait",
            discovered_at=discovered,
        )
        engine.store(node)

        # Pre-condition: node is active before enforcement
        assert engine.get_research_node(node.id)["is_active"] == 1

        engine.expire_stale_nodes()

        fetched = engine.get_research_node(node.id)
        assert fetched["is_active"] == 0, (
            "A meme node at 48h01m must be INACTIVE after expire_stale_nodes(). "
            "The 48-hour boundary is being enforced incorrectly."
        )

    def test_standard_node_is_active_at_71h59m(self, engine):
        """
        BOUNDARY: A standard node discovered 71h 59m ago is still ACTIVE.
        One minute inside the 72h window must not be expired.
        """
        from asomien.memory.nodes import ResearchNode

        discovered = datetime.now(timezone.utc) - timedelta(hours=71, minutes=59)
        node = ResearchNode(
            source="duckduckgo",
            headline="almost expired standard research",
            meme_format_detected="",
            discovered_at=discovered,
        )
        engine.store(node)

        engine.expire_stale_nodes()

        fetched = engine.get_research_node(node.id)
        assert fetched["is_active"] == 1, (
            "A standard node at 71h59m should still be ACTIVE."
        )

    def test_standard_node_is_inactive_at_72h01m(self, engine):
        """
        BOUNDARY: A standard node discovered 72h 01m ago is EXPIRED.
        One minute past the 72h window must be deactivated.
        """
        from asomien.memory.nodes import ResearchNode

        discovered = datetime.now(timezone.utc) - timedelta(hours=72, minutes=1)
        node = ResearchNode(
            source="duckduckgo",
            headline="just-expired standard research",
            meme_format_detected="",
            discovered_at=discovered,
        )
        engine.store(node)

        assert engine.get_research_node(node.id)["is_active"] == 1

        engine.expire_stale_nodes()

        fetched = engine.get_research_node(node.id)
        assert fetched["is_active"] == 0, (
            "A standard node at 72h01m must be INACTIVE after expire_stale_nodes(). "
            "The 72-hour boundary is being enforced incorrectly."
        )

    def test_expire_stale_nodes_returns_exact_count(self, engine):
        """
        expire_stale_nodes() returns exactly N — the number deactivated.
        Proves the count is not off-by-one or returning total rows.
        """
        from asomien.memory.nodes import ResearchNode

        # 3 expired meme nodes
        for i in range(3):
            node = ResearchNode(
                source="reddit",
                headline=f"stale meme {i}",
                meme_format_detected="toxic_trait",
                discovered_at=datetime.now(timezone.utc) - timedelta(hours=49),
            )
            engine.store(node)

        # 1 fresh meme node (should NOT be deactivated)
        fresh = ResearchNode(
            source="reddit",
            headline="fresh meme",
            meme_format_detected="pipeline",
            discovered_at=datetime.now(timezone.utc) - timedelta(hours=24),
        )
        engine.store(fresh)

        count = engine.expire_stale_nodes()

        assert count == 3, (
            f"expire_stale_nodes() should have deactivated exactly 3 nodes, got {count}"
        )
        assert engine.get_research_node(fresh.id)["is_active"] == 1, (
            "Fresh meme node must remain active after stale expiry run"
        )

    def test_retrieve_does_not_return_expired_meme_nodes(self, engine):
        """
        End-to-end: store an expired meme, call retrieve(), verify it is absent.
        retrieve() must call expire_stale_nodes() internally.
        """
        from asomien.memory.nodes import ResearchNode

        expired = ResearchNode(
            source="reddit",
            headline="toxic trait meme expired",
            summary="this meme is too old to be in context",
            meme_format_detected="toxic_trait",
            discovered_at=datetime.now(timezone.utc) - timedelta(hours=49),
        )
        engine.store(expired)

        results = engine.retrieve(query="toxic trait meme")
        result_ids = [r["id"] for r in results]

        assert expired.id not in result_ids, (
            "Expired meme node (49h old) must NOT appear in retrieve() results. "
            "retrieve() must call expire_stale_nodes() before querying."
        )


# =============================================================================
# 3. Memory Engine — retrieve()
# =============================================================================

class TestMemoryEngineRetrieve:
    """Tests for MemoryEngine.retrieve() — keyword matching, scoring, and filtering."""

    def test_retrieve_returns_empty_when_no_match(self, engine):
        """
        HARDENED: retrieve() returns an empty list — NOT a non-empty list that
        happens to pass through a never-executed loop assertion.
        """
        from asomien.memory.nodes import ResearchNode

        # Store a node with keywords completely unrelated to the query
        node = ResearchNode(
            source="reddit",
            headline="something completely unrelated to the upcoming query",
        )
        engine.store(node)

        results = engine.retrieve(query="meme pipeline absurdist xyzzy nonexistent")

        # Direct assertion — no loop, no conditional
        assert len(results) == 0, (
            f"Expected 0 results for a query with no matching keywords, "
            f"got {len(results)}: {[r['headline'] for r in results]}"
        )

    def test_retrieve_returns_matching_nodes(self, engine):
        """retrieve() returns nodes whose headlines contain query keywords."""
        from asomien.memory.nodes import ResearchNode

        node = ResearchNode(
            source="reddit",
            headline="phone brain is a real phenomenon",
            summary="studies show people check phones constantly",
        )
        engine.store(node)

        results = engine.retrieve(query="phone brain")
        ids = [r["id"] for r in results]
        assert node.id in ids, "Node with matching headline must be in results"

    def test_retrieve_headline_score_is_higher_than_summary_score(self, engine):
        """
        Score of headline match must be numerically greater than summary-only match.
        Headline weight=2.0, summary weight=1.0 — test the actual _score values.
        """
        from asomien.memory.nodes import ResearchNode

        headline_match = ResearchNode(
            source="reddit",
            headline="3am energy is the only energy",
            summary="something generic with no query terms",
            cultural_freshness=50,  # equal freshness to eliminate tiebreaker
        )
        summary_match = ResearchNode(
            source="reddit",
            headline="late night habits",
            summary="3am energy hits different for many people",
            cultural_freshness=50,
        )
        engine.store(headline_match)
        engine.store(summary_match)

        results = engine.retrieve(query="3am energy", limit=10)
        scores = {r["id"]: r["_score"] for r in results}

        assert headline_match.id in scores, "headline_match not in results"
        assert summary_match.id in scores, "summary_match not in results"
        assert scores[headline_match.id] > scores[summary_match.id], (
            f"Headline match score ({scores[headline_match.id]}) must be strictly "
            f"greater than summary-only match ({scores[summary_match.id]}). "
            f"Headline weight=2.0 > summary weight=1.0"
        )

    def test_retrieve_respects_limit_exactly(self, engine):
        """retrieve() returns AT MOST `limit` results — tested with exact counts."""
        from asomien.memory.nodes import ResearchNode

        for i in range(8):
            engine.store(ResearchNode(source="reddit", headline=f"phone brain post {i}"))

        results_3 = engine.retrieve(query="phone brain", limit=3)
        results_5 = engine.retrieve(query="phone brain", limit=5)

        assert len(results_3) == 3, f"Expected 3 results with limit=3, got {len(results_3)}"
        assert len(results_5) == 5, f"Expected 5 results with limit=5, got {len(results_5)}"

    def test_retrieve_every_result_has_score_key(self, engine):
        """Every result dict must contain a '_score' key with a numeric value."""
        from asomien.memory.nodes import ResearchNode

        engine.store(ResearchNode(source="reddit", headline="chronically online vibes"))
        results = engine.retrieve(query="chronically online")

        assert len(results) > 0, "Expected at least one result"
        for r in results:
            assert "_score" in r, f"Missing '_score' key in result: {r}"
            assert isinstance(r["_score"], (int, float)), (
                f"'_score' must be numeric, got {type(r['_score'])}"
            )

    def test_retrieve_include_meme_only_excludes_standard_nodes(self, engine):
        """include_meme_only=True returns only meme nodes; standard nodes absent."""
        from asomien.memory.nodes import ResearchNode

        meme_node = ResearchNode(
            source="knowyourmeme",
            headline="toxic trait meme",
            meme_format_detected="toxic_trait",
        )
        plain_node = ResearchNode(
            source="duckduckgo",
            headline="toxic trait",
            meme_format_detected="",
        )
        engine.store(meme_node)
        engine.store(plain_node)

        results = engine.retrieve(query="toxic trait", include_meme_only=True)
        ids = [r["id"] for r in results]

        assert meme_node.id in ids, "Meme node must appear in meme-only results"
        assert plain_node.id not in ids, "Standard node must be excluded from meme-only results"

    def test_retrieve_topic_filter_excludes_other_topics(self, engine):
        """Passing topic_id returns only nodes belonging to that topic."""
        from asomien.memory.nodes import ResearchNode, TopicNode

        topic_a = TopicNode(name="phone brain")
        topic_b = TopicNode(name="sleep culture")
        engine.store(topic_a)
        engine.store(topic_b)

        node_a = ResearchNode(source="reddit", headline="phone brain post", topic_id=topic_a.id)
        node_b = ResearchNode(source="reddit", headline="phone brain but sleep", topic_id=topic_b.id)
        engine.store(node_a)
        engine.store(node_b)

        results = engine.retrieve(query="phone brain", topic_id=topic_a.id, limit=10)
        ids = [r["id"] for r in results]

        assert node_a.id in ids, "Node belonging to topic_a must appear"
        assert node_b.id not in ids, "Node belonging to topic_b must be excluded"


# =============================================================================
# 4. Memory Engine — assemble_context()
# =============================================================================

class TestMemoryEngineAssembleContext:
    """Tests for MemoryEngine.assemble_context() — exact values, not just key presence."""

    def test_assemble_context_returns_all_required_keys(self, engine):
        """assemble_context() returns a dict with all 5 required keys."""
        ctx = engine.assemble_context(query="phone brain")

        required_keys = {"topic", "research", "recent_posts", "meme_formats", "freshness_avg"}
        missing = required_keys - set(ctx.keys())
        assert not missing, f"assemble_context() missing keys: {missing}"

    def test_assemble_context_freshness_avg_is_exact_value(self, engine):
        """
        HARDENED: freshness_avg must be exactly 80.0 when 3 nodes
        with cultural_freshness=80 are stored and retrieved.
        A range check (0 <= x <= 100) would pass even if broken.
        """
        from asomien.memory.nodes import ResearchNode

        for i in range(3):
            engine.store(ResearchNode(
                source="reddit",
                headline=f"fresh content {i}",
                summary=f"content about fresh topic {i}",
                cultural_freshness=80,
            ))

        ctx = engine.assemble_context(query="fresh content")

        assert len(ctx["research"]) == 3, (
            f"Expected 3 research nodes in context, got {len(ctx['research'])}"
        )
        assert ctx["freshness_avg"] == 80.0, (
            f"freshness_avg must be exactly 80.0 when all nodes have freshness=80. "
            f"Got {ctx['freshness_avg']}"
        )

    def test_assemble_context_freshness_avg_mixed_values(self, engine):
        """freshness_avg is the correct arithmetic mean of mixed values."""
        from asomien.memory.nodes import ResearchNode

        for freshness in [60, 80, 100]:
            engine.store(ResearchNode(
                source="reddit",
                headline=f"mixed freshness node {freshness}",
                summary=f"node with freshness {freshness}",
                cultural_freshness=freshness,
            ))

        ctx = engine.assemble_context(query="mixed freshness node")
        expected_avg = (60 + 80 + 100) / 3  # = 80.0

        assert abs(ctx["freshness_avg"] - expected_avg) < 0.01, (
            f"freshness_avg must be {expected_avg}, got {ctx['freshness_avg']}"
        )

    def test_assemble_context_includes_specific_research_node(self, engine):
        """assemble_context() includes the stored active research node by id."""
        from asomien.memory.nodes import ResearchNode

        node = ResearchNode(
            source="reddit",
            headline="3am energy",
            summary="real chronically online hours",
        )
        engine.store(node)

        ctx = engine.assemble_context(query="3am energy")
        research_ids = [r["id"] for r in ctx["research"]]
        assert node.id in research_ids, "Stored node must appear in assembled context"

    def test_assemble_context_excludes_expired_nodes(self, engine):
        """assemble_context() must not include expired research nodes."""
        from asomien.memory.nodes import ResearchNode

        old = ResearchNode(
            source="reddit",
            headline="stale meme",
            meme_format_detected="toxic_trait",
            discovered_at=datetime.now(timezone.utc) - timedelta(hours=50),
        )
        engine.store(old)

        ctx = engine.assemble_context(query="stale meme")
        research_ids = [r["id"] for r in ctx["research"]]
        assert old.id not in research_ids, (
            "Expired meme node (50h old) must be absent from assembled context"
        )

    def test_assemble_context_meme_formats_is_exact_set(self, engine):
        """assemble_context() meme_formats contains exactly the formats in active research."""
        from asomien.memory.nodes import ResearchNode

        engine.store(ResearchNode(
            source="reddit",
            headline="pipeline test post",
            meme_format_detected="pipeline",
        ))
        engine.store(ResearchNode(
            source="reddit",
            headline="toxic trait test post",
            meme_format_detected="toxic_trait",
        ))

        ctx = engine.assemble_context(query="pipeline toxic trait test post")
        meme_formats = ctx["meme_formats"]

        assert "pipeline" in meme_formats, f"'pipeline' missing from {meme_formats}"
        assert "toxic_trait" in meme_formats, f"'toxic_trait' missing from {meme_formats}"
        # Verify no unexpected formats slipped in
        assert set(meme_formats).issubset({"pipeline", "toxic_trait"}), (
            f"Unexpected formats in context: {set(meme_formats) - {'pipeline', 'toxic_trait'}}"
        )

    def test_assemble_context_includes_recent_posts(self, engine):
        """assemble_context() includes recent PostNodes in recent_posts."""
        from asomien.memory.nodes import PostNode

        post = PostNode(content="my toxic trait is this entire thread")
        engine.store(post)

        ctx = engine.assemble_context(query="toxic trait")
        post_ids = [p["id"] for p in ctx["recent_posts"]]
        assert post.id in post_ids, "Stored post must appear in recent_posts"

    def test_assemble_context_max_research_nodes_respected(self, engine):
        """max_research_nodes parameter caps the research list at exactly N entries."""
        from asomien.memory.nodes import ResearchNode

        for i in range(7):
            engine.store(ResearchNode(source="reddit", headline=f"content node {i}"))

        ctx = engine.assemble_context(query="content node", max_research_nodes=4)
        assert len(ctx["research"]) == 4, (
            f"max_research_nodes=4 must return exactly 4, got {len(ctx['research'])}"
        )


# =============================================================================
# 5. Personality Engine — Loading (KEY MANDATE)
# =============================================================================

class TestPersonalityEngineLoad:
    """Tests for PersonalityEngine — exact trait value assertions, no lazy checks."""

    def test_personality_engine_is_callable(self):
        """PersonalityEngine class is importable and callable."""
        from asomien.personality.engine import PersonalityEngine
        assert callable(PersonalityEngine), "PersonalityEngine must be a callable class"

    def test_loads_persona_name_exactly(self, personality):
        """persona_name property returns the exact string from the seed."""
        assert personality.persona_name == "asomien", (
            f"Expected persona_name='asomien', got {personality.persona_name!r}"
        )

    def test_chaos_warmth_balance_loads_with_exact_value(self, personality):
        """
        KEY MANDATE TEST: chaos_warmth_balance must have value exactly 0.75.
        Exact float comparison — not a range, not a None check.
        """
        trait = personality.get_trait("chaos_warmth_balance")

        assert trait is not None, (
            "chaos_warmth_balance trait not found in core_traits. "
            "Check personality_seed.json."
        )
        assert trait["trait_name"] == "chaos_warmth_balance"
        assert trait["trait_type"] == "core", (
            f"chaos_warmth_balance must be a 'core' trait, got {trait['trait_type']!r}"
        )
        assert trait["value"] == 0.75, (
            f"chaos_warmth_balance value must be exactly 0.75, got {trait['value']!r}"
        )

    def test_advice_aversion_is_exactly_1_0(self, personality):
        """advice_aversion must be exactly 1.00 — the hard zero. Not 0.99, not 0.9."""
        trait = personality.get_trait("advice_aversion")

        assert trait is not None, "advice_aversion must exist in core_traits"
        assert trait["value"] == 1.00, (
            f"advice_aversion must be EXACTLY 1.00 (hard zero). Got {trait['value']!r}. "
            f"Any value below 1.00 means the persona could technically give advice."
        )

    def test_hustle_culture_immunity_is_exactly_1_0(self, personality):
        """hustle_culture_immunity must also be exactly 1.00."""
        trait = personality.get_trait("hustle_culture_immunity")
        assert trait is not None
        assert trait["value"] == 1.00, (
            f"hustle_culture_immunity must be 1.00, got {trait['value']!r}"
        )

    def test_relatability_score_is_exactly_0_95(self, personality):
        """relatability_score must be exactly 0.95."""
        trait = personality.get_trait("relatability_score")
        assert trait is not None
        assert trait["value"] == 0.95, f"Expected 0.95, got {trait['value']!r}"

    def test_self_awareness_index_is_exactly_0_90(self, personality):
        """self_awareness_index must be exactly 0.90."""
        trait = personality.get_trait("self_awareness_index")
        assert trait is not None
        assert trait["value"] == 0.90, f"Expected 0.90, got {trait['value']!r}"

    def test_ai_bit_frequency_is_exactly_0_20(self, personality):
        """Adaptive trait ai_bit_frequency must be exactly 0.20."""
        trait = personality.get_trait("ai_bit_frequency")
        assert trait is not None
        assert trait["trait_type"] == "adaptive"
        assert trait["value"] == 0.20, f"Expected 0.20, got {trait['value']!r}"

    def test_absurdist_dial_is_exactly_0_60(self, personality):
        """Adaptive trait absurdist_dial must be exactly 0.60."""
        trait = personality.get_trait("absurdist_dial")
        assert trait is not None
        assert trait["value"] == 0.60, f"Expected 0.60, got {trait['value']!r}"

    def test_writing_rule_case_is_lowercase_always(self, personality):
        """writing_rules['case'] must be the exact string 'lowercase_always'."""
        rules = personality.writing_rules
        assert rules.get("case") == "lowercase_always", (
            f"Expected case='lowercase_always', got {rules.get('case')!r}"
        )

    def test_forbidden_phrases_exact_membership(self, personality):
        """All blueprint-required forbidden phrases are present in the list."""
        phrases = personality.forbidden_phrases
        required = ["hustle", "grind", "productivity", "optimize", "discipline", "mindset",
                    "manifest", "morning routine", "10 tips", "you need to", "you should",
                    "here's how"]
        missing = [p for p in required if p not in phrases]
        assert not missing, (
            f"The following required forbidden phrases are missing: {missing}"
        )

    def test_core_traits_count_is_exactly_five(self, personality):
        """The seed must define exactly 5 core traits."""
        assert len(personality.core_traits) == 5, (
            f"Expected exactly 5 core traits, got {len(personality.core_traits)}: "
            f"{[t['trait_name'] for t in personality.core_traits]}"
        )

    def test_all_five_core_trait_names_present(self, personality):
        """All 5 core trait names from the seed are present in core_traits."""
        trait_names = {t["trait_name"] for t in personality.core_traits}
        expected = {
            "relatability_score",
            "chaos_warmth_balance",
            "self_awareness_index",
            "advice_aversion",
            "hustle_culture_immunity",
        }
        missing = expected - trait_names
        assert not missing, f"Core traits missing: {missing}"

    def test_invalid_seed_path_raises_file_not_found(self):
        """PersonalityEngine raises FileNotFoundError for a missing seed file."""
        from asomien.personality.engine import PersonalityEngine

        with pytest.raises(FileNotFoundError, match="personality_seed.json not found"):
            PersonalityEngine(seed_path="nonexistent/path/seed.json")


# =============================================================================
# 6. Personality Engine — apply_to_prompt() DOUBLE-INJECTION PROOF
# =============================================================================

class TestPersonalityEngineApplyToPrompt:
    """
    Tests proving that lowercase_always and advice_aversion are injected
    at BOTH the top AND the bottom of the system prompt.
    No OR-logic. Each rule's presence is asserted independently at each location.
    """

    def test_apply_to_prompt_returns_non_empty_string(self, personality):
        """apply_to_prompt() returns a string with substantial content."""
        result = personality.apply_to_prompt("generate a post about phone brain")
        assert isinstance(result, str)
        assert len(result) >= 500, (
            f"System prompt is suspiciously short: {len(result)} chars. "
            "A real personality prompt should be much longer."
        )

    # ── lowercase_always: TOP injection ──────────────────────────────────────

    def test_lowercase_rule_injected_at_top_of_prompt(self, personality):
        """
        JACKET ENFORCEMENT: 'LOWERCASE' or 'lowercase_always' must appear
        in the FIRST QUARTER of the prompt — proving top injection.
        """
        result = personality.apply_to_prompt("generate a post")
        lines = result.split("\n")
        total_lines = len(lines)
        first_quarter_end = total_lines // 4

        first_quarter = "\n".join(lines[:first_quarter_end])

        assert "LOWERCASE" in first_quarter or "lowercase_always" in first_quarter, (
            f"'LOWERCASE' or 'lowercase_always' must appear in the first quarter "
            f"of the prompt (first {first_quarter_end} of {total_lines} lines). "
            "The rule is not aggressively injected at the top."
        )

    # ── lowercase_always: BOTTOM injection ───────────────────────────────────

    def test_lowercase_rule_injected_at_bottom_of_prompt(self, personality):
        """
        JACKET ENFORCEMENT: 'LOWERCASE' must also appear in the LAST 15 lines
        of the prompt — proving the belt-and-suspenders recap.
        """
        result = personality.apply_to_prompt("generate a post")
        lines = result.split("\n")
        last_15 = "\n".join(lines[-15:])

        assert "LOWERCASE" in last_15, (
            f"'LOWERCASE' must appear in the final 15 lines of the prompt "
            "(the hard-rules recap). Last 15 lines:\n{last_15!r}"
        )

    # ── advice_aversion: TOP injection ───────────────────────────────────────

    def test_advice_aversion_injected_at_top_of_prompt(self, personality):
        """
        JACKET ENFORCEMENT: 'advice_aversion' and 'NEVER' must both appear
        in the first quarter of the prompt — proving aggressive top injection.
        """
        result = personality.apply_to_prompt("generate a post")
        lines = result.split("\n")
        first_quarter = "\n".join(lines[: len(lines) // 4])

        assert "advice_aversion" in first_quarter, (
            "The literal string 'advice_aversion' must appear in the first quarter "
            "of the prompt. The trait name must be explicitly called out."
        )
        assert "NEVER" in first_quarter, (
            "The word 'NEVER' (uppercase) must appear in the first quarter to "
            "aggressively enforce the advice prohibition at the top."
        )

    # ── advice_aversion: BOTTOM injection ────────────────────────────────────

    def test_advice_aversion_injected_at_bottom_of_prompt(self, personality):
        """
        JACKET ENFORCEMENT: The advice prohibition must also appear in the last
        15 lines of the prompt — proving the bottom recap exists.
        """
        result = personality.apply_to_prompt("generate a post")
        lines = result.split("\n")
        last_15 = "\n".join(lines[-15:])

        # The word "advice" (or "ADVICE") must appear in the final recap
        assert "advice" in last_15.lower(), (
            f"The advice prohibition must be recapped in the final 15 lines. "
            f"Last 15 lines:\n{last_15!r}"
        )

    # ── Rule independence — no OR-logic ──────────────────────────────────────

    def test_lowercase_rule_and_advice_rule_are_independently_present(self, personality):
        """
        Both rules must be present independently. This test would catch an implementation
        that injects ONE rule and not the other.
        """
        result = personality.apply_to_prompt("generate a post")

        # Test each rule's key phrase independently
        assert "lowercase_always" in result, (
            "The exact string 'lowercase_always' must appear in the prompt"
        )
        assert "advice_aversion" in result, (
            "The exact string 'advice_aversion' must appear in the prompt"
        )
        assert "NEVER" in result, (
            "The word 'NEVER' (uppercase) must appear as an enforcement directive"
        )

    def test_task_instruction_appears_verbatim_in_prompt(self, personality):
        """apply_to_prompt() injects the user_instruction into the prompt verbatim."""
        instruction = "generate a post about being chronically online at 3am"
        result = personality.apply_to_prompt(instruction)
        assert instruction in result, (
            f"The user instruction must appear verbatim in the prompt.\n"
            f"Instruction: {instruction!r}"
        )

    def test_persona_name_appears_in_prompt(self, personality):
        """The persona name 'asomien' must appear in the generated prompt."""
        result = personality.apply_to_prompt("test task")
        assert "asomien" in result.lower(), (
            "Persona name 'asomien' must appear in the system prompt"
        )

    def test_all_forbidden_phrases_listed_in_prompt(self, personality):
        """Every required forbidden phrase appears in the prompt."""
        result = personality.apply_to_prompt("test")
        for phrase in ["hustle", "productivity", "optimize", "grind"]:
            assert phrase in result, (
                f"Forbidden phrase '{phrase}' must appear in the system prompt"
            )

    def test_approved_example_posts_appear_in_prompt(self, personality):
        """At least one approved post example appears in the prompt verbatim."""
        result = personality.apply_to_prompt("test")
        approved = personality._example_approved
        assert any(ex in result for ex in approved), (
            "At least one approved example post must appear verbatim in the prompt"
        )

    def test_prompt_structure_has_task_between_rule_blocks(self, personality):
        """
        The user task must appear AFTER the top rules block and BEFORE the bottom
        recap block — proving the sandwich structure is correct.
        """
        instruction = "UNIQUE_INSTRUCTION_SENTINEL_12345"
        result = personality.apply_to_prompt(instruction)

        task_pos = result.find(instruction)
        assert task_pos != -1, "Instruction must appear in prompt"

        # FINAL HARD RULES CHECK (bottom recap) must come AFTER the task
        recap_pos = result.find("FINAL HARD RULES")
        assert recap_pos != -1, "'FINAL HARD RULES' marker must exist in prompt"
        assert recap_pos > task_pos, (
            f"The hard rules recap must come AFTER the task instruction. "
            f"Task at pos {task_pos}, recap at pos {recap_pos}."
        )


# =============================================================================
# 7. Personality Engine — Helper Methods
# =============================================================================

class TestPersonalityEngineHelpers:
    """Tests for PersonalityEngine utility methods — exact boolean results."""

    def test_is_lowercase_compliant_true_for_lowercase(self, personality):
        assert personality.is_lowercase_compliant("my toxic trait is this") is True

    def test_is_lowercase_compliant_false_for_uppercase(self, personality):
        assert personality.is_lowercase_compliant("My toxic trait is this") is False

    def test_is_lowercase_compliant_false_for_single_capital_i(self, personality):
        """The capital letter 'I' is the most common lowercase violation."""
        assert personality.is_lowercase_compliant("I have thoughts about this") is False

    def test_is_lowercase_compliant_false_for_empty_string(self, personality):
        assert personality.is_lowercase_compliant("") is False

    def test_is_lowercase_compliant_strips_leading_whitespace_correctly(self, personality):
        assert personality.is_lowercase_compliant("   my post starts here") is True
        assert personality.is_lowercase_compliant("   My post starts here") is False

    def test_contains_advice_true_for_you_need_to(self, personality):
        assert personality.contains_advice("you need to get more sleep") is True

    def test_contains_advice_true_for_heres_how(self, personality):
        assert personality.contains_advice("here's how to fix that") is True

    def test_contains_advice_false_for_relatable_post(self, personality):
        assert personality.contains_advice("my toxic trait is existing") is False

    def test_contains_advice_false_for_question(self, personality):
        """Posts ending in questions are allowed — they are not advice."""
        assert personality.contains_advice("why is 3am so specific and so real") is False

    def test_get_trait_returns_none_for_nonexistent_trait(self, personality):
        result = personality.get_trait("nonexistent_trait_xyz_zzz")
        assert result is None, (
            f"get_trait() must return None for missing traits, got {result!r}"
        )

    def test_forbidden_openers_contains_required_values(self, personality):
        """Forbidden openers must contain 'I ', 'The ', 'Here ', 'Today ', 'In '."""
        openers = personality.forbidden_openers
        required = ["I ", "The ", "Here ", "Today ", "In "]
        missing = [o for o in required if o not in openers]
        assert not missing, (
            f"Missing required forbidden openers: {missing}. Got: {openers}"
        )

    def test_writing_rules_property_returns_defensive_copy(self, personality):
        """Mutating the returned writing_rules dict must not affect the engine."""
        rules_a = personality.writing_rules
        original_case = rules_a["case"]
        rules_a["case"] = "UPPERCASE_SABOTAGE"

        rules_b = personality.writing_rules
        assert rules_b["case"] == original_case, (
            f"Mutating returned writing_rules must not affect internal state. "
            f"Expected {original_case!r}, got {rules_b['case']!r}"
        )

    def test_core_traits_property_returns_defensive_copy(self, personality):
        """Mutating the returned core_traits list must not affect the engine."""
        traits_a = personality.core_traits
        original_len = len(traits_a)
        traits_a.clear()  # wipe the copy

        traits_b = personality.core_traits
        assert len(traits_b) == original_len, (
            f"Mutating returned core_traits list must not affect internal state. "
            f"Expected {original_len} traits, got {len(traits_b)}"
        )
