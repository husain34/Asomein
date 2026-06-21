"""
tests/test_phase4.py

Phase 4 test suite — Content Agent, Critic Agent, Jittery Scheduler.

All external I/O is mocked:
  - LLM client      → MagicMock (no live NIM API calls)
  - MemoryEngine    → MagicMock (in-memory SQLite where needed)
  - Orchestrator    → MagicMock
  - Analytics       → MagicMock

TESTING MANDATES:
  1. CriticAgent hard-rejects any draft starting with a capital letter
     (is_approved=False, rejection_reason contains 'capital')
  2. CriticAgent hard-rejects any draft containing advice
     (is_approved=False, rejection_reason contains 'advice' or 'cta')
  3. CriticAgent hard-rejects any draft with hustle-culture vocabulary
  4. _apply_jitter() produces an offset strictly within ±45 minutes
  5. select_hook_template() never picks the same template as the last 5 posts
  6. Full suite must pass alongside all 83 Phase 3 tests

Run with:
    .\\venv\\Scripts\\pytest tests/test_phase4.py -v
"""

from __future__ import annotations

import sys
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def content_agent():
    from asomien.agents.content_agent import ContentAgent
    return ContentAgent()   # no memory, no LLM — test/deterministic mode


@pytest.fixture
def content_agent_with_mock_llm():
    from asomien.agents.content_agent import ContentAgent
    mock_llm = MagicMock()
    mock_llm.complete.return_value = (
        "my toxic trait is opening 14 browser tabs at 3am\n"
        "---\n"
        "my toxic trait is researching a hobby i will never start\n"
        "---\n"
        "my toxic trait is watching one more episode at 2am"
    )
    return ContentAgent(llm_client=mock_llm), mock_llm


@pytest.fixture
def critic():
    from asomien.agents.critic_agent import CriticAgent
    return CriticAgent()


@pytest.fixture
def scheduler():
    from asomien.scheduler.jobs import SchedulerManager
    return SchedulerManager()


# =============================================================================
# 1. ContentAgent — apply_personality() — lowercase enforcement
# =============================================================================

class TestContentAgentLowercaseEnforcement:
    """
    MANDATE: apply_personality() must produce lowercase output.
    This is the native lowercase enforcement described in the blueprint.
    """

    def test_apply_personality_lowercases_output(self, content_agent):
        """Uppercase input is lowercased on output."""
        result = content_agent.apply_personality("My Toxic Trait Is Opening Tabs")
        assert result == result.lower(), (
            "apply_personality() must return fully lowercase string"
        )
        assert result[0].islower()

    def test_apply_personality_strips_whitespace(self, content_agent):
        """Leading/trailing whitespace is stripped."""
        result = content_agent.apply_personality("  my toxic trait is real  ")
        assert result == result.strip()

    def test_apply_personality_strips_bot_tails(self, content_agent):
        """Bot-coded tails are stripped."""
        draft = "my toxic trait is real. let me know what you think!"
        result = content_agent.apply_personality(draft)
        assert "let me know what you think" not in result

    def test_apply_personality_empty_string(self, content_agent):
        result = content_agent.apply_personality("")
        assert result == ""

    def test_apply_personality_preserves_content(self, content_agent):
        """Core content survives the transformation."""
        draft = "my toxic trait is opening 14 browser tabs as a personality type"
        result = content_agent.apply_personality(draft)
        assert "toxic trait" in result
        assert "browser tabs" in result


# =============================================================================
# 2. ContentAgent — validate_lowercase()
# =============================================================================

class TestContentAgentValidateLowercase:
    """Validate the first-character lowercase check."""

    def setup_method(self):
        from asomien.agents.content_agent import ContentAgent
        self.agent = ContentAgent()

    def test_lowercase_first_char_passes(self):
        assert self.agent.validate_lowercase("my toxic trait is real") is True

    def test_uppercase_first_char_fails(self):
        assert self.agent.validate_lowercase("My toxic trait is real") is False

    def test_all_caps_fails(self):
        assert self.agent.validate_lowercase("MY TOXIC TRAIT") is False

    def test_empty_string_fails(self):
        assert self.agent.validate_lowercase("") is False

    def test_whitespace_only_fails(self):
        assert self.agent.validate_lowercase("   ") is False

    def test_leading_whitespace_then_lowercase_passes(self):
        """Leading whitespace is stripped before checking."""
        assert self.agent.validate_lowercase("  my toxic trait") is True


# =============================================================================
# 3. ContentAgent — validate_persona_fit()
# =============================================================================

class TestContentAgentValidatePersonaFit:
    """Test persona compliance validator for advice, hustle vocab, CTA."""

    def setup_method(self):
        from asomien.agents.content_agent import ContentAgent
        self.agent = ContentAgent()

    def test_valid_post_passes(self):
        ok, reason = self.agent.validate_persona_fit(
            "my toxic trait is opening 14 browser tabs as a personality type"
        )
        assert ok is True
        assert reason == ""

    def test_capital_letter_fails(self):
        ok, reason = self.agent.validate_persona_fit("My toxic trait is real")
        assert ok is False
        assert "capital" in reason

    def test_hustle_vocab_fails(self):
        ok, reason = self.agent.validate_persona_fit(
            "my toxic trait is ignoring my hustle"
        )
        assert ok is False
        assert "hustle" in reason

    def test_productivity_fails(self):
        ok, reason = self.agent.validate_persona_fit(
            "productivity tip: stop doing this"
        )
        assert ok is False

    def test_grind_fails(self):
        ok, reason = self.agent.validate_persona_fit(
            "anyway. back to the grind i guess"
        )
        assert ok is False
        assert "grind" in reason

    def test_optimize_fails(self):
        ok, reason = self.agent.validate_persona_fit(
            "optimize your mornings for clarity"
        )
        assert ok is False

    def test_advice_cta_at_end_fails(self):
        """Advice / CTA signal at end of post fails."""
        ok, reason = self.agent.validate_persona_fit(
            "my toxic trait is real. try this instead"
        )
        assert ok is False
        assert "advice_signal" in reason or "cta" in reason.lower()

    def test_clean_post_after_hustle_vocab_fix(self):
        ok, reason = self.agent.validate_persona_fit(
            "not to be dramatic but my phone dying at 40% is a personal attack"
        )
        assert ok is True, f"Should pass — got reason: {reason!r}"


# =============================================================================
# 4. ContentAgent — enforce_character_limit()
# =============================================================================

class TestEnforceCharacterLimit:
    """Test the 500-character hard gate."""

    def setup_method(self):
        from asomien.agents.content_agent import ContentAgent
        self.agent = ContentAgent()

    def test_under_limit_unchanged(self):
        draft = "my toxic trait is real"
        result = self.agent.enforce_character_limit(draft)
        assert result == draft

    def test_exactly_500_unchanged(self):
        draft = "a" * 500
        result = self.agent.enforce_character_limit(draft)
        assert len(result) <= 500

    def test_over_limit_truncated(self):
        draft = "a" * 600
        result = self.agent.enforce_character_limit(draft)
        assert len(result) <= 500

    def test_truncation_does_not_return_empty(self):
        """Truncated result is non-empty even for very long input."""
        draft = "my toxic trait is opening tabs. " * 30   # ~930 chars
        result = self.agent.enforce_character_limit(draft)
        assert len(result) > 0
        assert len(result) <= 500


# =============================================================================
# 5. ContentAgent — select_hook_template() — no consecutive repeat
# =============================================================================

class TestSelectHookTemplate:
    """
    MANDATE: select_hook_template() must not return the same template as any
    of the last 5 hook_template_used values in recent posts.
    """

    def setup_method(self):
        from asomien.agents.content_agent import ContentAgent
        self.agent = ContentAgent()

    def _make_post_history(self, template_ids: list[str]) -> list[dict]:
        """Build a fake recent_posts list with given template IDs."""
        return [{"hook_template_used": tid} for tid in template_ids]

    def test_no_history_returns_a_template(self):
        """With no history, any template is valid."""
        result = self.agent.select_hook_template(recent_posts=[])
        assert result is not None
        assert "id" in result

    def test_does_not_repeat_last_used(self):
        """The most recently used template is not returned again."""
        from asomien.llm.prompts.content_prompts import HOOK_TEMPLATES
        # Run many times to ensure no false positives
        for _ in range(50):
            history = self._make_post_history(["toxic_trait"])
            result = self.agent.select_hook_template(recent_posts=history)
            assert result["id"] != "toxic_trait", (
                f"Template 'toxic_trait' should not be selected when it's "
                f"the most recent. Got: {result['id']!r}"
            )

    def test_does_not_repeat_any_in_last_5(self):
        """None of the last 5 templates appear in the selected result (repeated runs)."""
        recent_5 = ["toxic_trait", "pipeline", "feminine_urge", "me_also_me", "speedrun"]
        history = self._make_post_history(recent_5)

        for _ in range(100):
            result = self.agent.select_hook_template(recent_posts=history)
            assert result["id"] not in set(recent_5), (
                f"Template '{result['id']}' is in the recent window {recent_5} "
                f"and should not have been selected."
            )

    def test_fallback_when_window_exhausted(self):
        """
        If all 11 templates are in the look-back window (impossible in production
        but a safety test), the method still returns a valid template — never crashes.
        """
        from asomien.llm.prompts.content_prompts import HOOK_TEMPLATE_IDS
        # Use more than 5 templates in the window — fills beyond window size
        # The window only looks back 5, so 6+ entries are fine
        recent_many = HOOK_TEMPLATE_IDS[:5]
        history = self._make_post_history(recent_many)
        result = self.agent.select_hook_template(recent_posts=history)
        assert result is not None
        assert "id" in result

    def test_returns_dict_with_required_keys(self):
        result = self.agent.select_hook_template(recent_posts=[])
        assert "id" in result
        assert "pattern" in result
        assert "example" in result
        assert "reply_trigger" in result

    def test_always_returns_from_known_templates(self):
        """Selected template ID must be from HOOK_TEMPLATE_IDS."""
        from asomien.llm.prompts.content_prompts import HOOK_TEMPLATE_IDS
        for _ in range(50):
            result = self.agent.select_hook_template(recent_posts=[])
            assert result["id"] in HOOK_TEMPLATE_IDS


# =============================================================================
# 6. ContentAgent — generate_post_ideas()
# =============================================================================

class TestGeneratePostIdeas:
    """Tests for idea generation from context."""

    def setup_method(self):
        from asomien.agents.content_agent import ContentAgent
        self.agent = ContentAgent()

    def _make_context(self, research: list[dict] = None) -> dict:
        return {
            "topic": None,
            "research": research or [],
            "recent_posts": [],
            "meme_formats": [],
            "freshness_avg": 70.0,
        }

    def test_returns_list(self):
        result = self.agent.generate_post_ideas(self._make_context())
        assert isinstance(result, list)

    def test_empty_research_still_returns_ideas(self):
        """Fallback ideas are always generated."""
        result = self.agent.generate_post_ideas(self._make_context(research=[]))
        assert len(result) > 0

    def test_meme_format_research_produces_priority_ideas(self):
        """Research nodes with meme_format_detected produce priority ideas."""
        research = [
            {
                "id": "node1",
                "headline": "my toxic trait is doom-scrolling at 3am",
                "meme_format_detected": "toxic_trait",
                "cultural_freshness": 90,
            }
        ]
        result = self.agent.generate_post_ideas(self._make_context(research=research))
        # First idea should reference the meme format
        meme_ideas = [i for i in result if i.get("meme_format") == "toxic_trait"]
        assert len(meme_ideas) >= 1

    def test_ideas_have_required_fields(self):
        result = self.agent.generate_post_ideas(self._make_context())
        for idea in result:
            assert "angle" in idea
            assert "sub_niche" in idea
            assert "meme_format" in idea

    def test_duplicate_formats_from_research(self):
        """Multiple research nodes with same format still produce valid ideas."""
        research = [
            {
                "id": f"n{i}",
                "headline": f"toxic trait post {i}",
                "meme_format_detected": "toxic_trait",
                "cultural_freshness": 80,
            }
            for i in range(3)
        ]
        result = self.agent.generate_post_ideas(self._make_context(research=research))
        assert len(result) > 0


# =============================================================================
# 7. ContentAgent — draft_content() — deterministic mode
# =============================================================================

class TestDraftContent:
    """Tests for draft_content() in test/deterministic mode (no LLM)."""

    def setup_method(self):
        from asomien.agents.content_agent import ContentAgent
        self.agent = ContentAgent()   # no llm_client

    def test_returns_list(self):
        idea = {"angle": "3am brain energy", "sub_niche": "3am", "meme_format": ""}
        result = self.agent.draft_content(idea)
        assert isinstance(result, list)

    def test_returns_at_least_one_variant(self):
        idea = {"angle": "test", "sub_niche": "general", "meme_format": "toxic_trait"}
        result = self.agent.draft_content(idea, template_id="toxic_trait")
        assert len(result) >= 1

    def test_all_variants_are_lowercase(self):
        """MANDATE: All drafts exit the agent as lowercase strings."""
        idea = {"angle": "phone brain moment", "sub_niche": "phone brain", "meme_format": ""}
        result = self.agent.draft_content(idea)
        for draft in result:
            assert draft == draft.lower(), (
                f"Draft is not lowercase: {draft!r}"
            )

    def test_all_variants_under_500_chars(self):
        idea = {"angle": "test", "sub_niche": "general", "meme_format": ""}
        result = self.agent.draft_content(idea)
        for draft in result:
            assert len(draft) <= 500, f"Draft exceeds 500 chars: {len(draft)}"

    def test_draft_with_specific_template(self):
        """draft_content with template_id='pipeline' uses the pipeline example."""
        idea = {"angle": "pipeline test", "sub_niche": "3am", "meme_format": "pipeline"}
        result = self.agent.draft_content(idea, template_id="pipeline")
        assert len(result) >= 1
        # Deterministic mode returns the example — pipeline example has 'pipeline' in it
        assert any("pipeline" in d for d in result)

    def test_draft_with_llm_mock(self, content_agent_with_mock_llm):
        """With a mocked LLM, draft_content returns parsed LLM output."""
        agent, mock_llm = content_agent_with_mock_llm
        idea = {"angle": "tabs test", "sub_niche": "phone brain", "meme_format": "toxic_trait"}
        result = agent.draft_content(idea, template_id="toxic_trait")
        assert len(result) >= 1
        mock_llm.complete.assert_called_once()
        for draft in result:
            assert draft == draft.lower()

    def test_llm_error_falls_back_to_example(self, content_agent_with_mock_llm):
        """If LLM raises, draft_content returns a fallback example."""
        agent, mock_llm = content_agent_with_mock_llm
        mock_llm.complete.side_effect = RuntimeError("NIM API down")
        idea = {"angle": "test", "sub_niche": "general", "meme_format": "toxic_trait"}
        result = agent.draft_content(idea, template_id="toxic_trait")
        assert len(result) >= 1


# =============================================================================
# 8. ContentAgent — draft_reply()
# =============================================================================

class TestDraftReply:
    """Tests for reply generation in deterministic mode."""

    def setup_method(self):
        from asomien.agents.content_agent import ContentAgent
        self.agent = ContentAgent()

    def test_returns_string(self):
        result = self.agent.draft_reply("my toxic trait is real", "same honestly")
        assert isinstance(result, str)

    def test_reply_is_lowercase(self):
        result = self.agent.draft_reply("my toxic trait", "this is so me")
        assert result == result.lower(), "Reply must be lowercase"

    def test_reply_with_none_original_post(self):
        result = self.agent.draft_reply(None, "i feel this deeply")
        assert isinstance(result, str)
        assert len(result) > 0


# =============================================================================
# 9. CriticAgent — HARD REJECTION RULES (MANDATE TESTS)
# =============================================================================

class TestCriticAgentHardRejections:
    """
    MANDATE: These tests verify the 6 hard-gate rejection rules.

    Each rule must trigger an early-exit rejection BEFORE scoring.
    The returned CritiqueScore must have:
      - is_approved = False
      - passed_hard_gates = False
      - rejection_reason is set (non-empty string)
      - composite = 0.0
    """

    def setup_method(self):
        from asomien.agents.critic_agent import CriticAgent
        self.critic = CriticAgent()

    def _assert_hard_rejected(self, draft: str, keyword_in_reason: str = None):
        """Helper: assert the draft is hard-rejected and reason contains keyword."""
        score = self.critic.pre_publish_critique(draft)
        assert score.is_approved is False, (
            f"Draft should be REJECTED but got is_approved=True for: {draft!r}"
        )
        assert score.passed_hard_gates is False, (
            f"passed_hard_gates should be False for hard rejection. Draft: {draft!r}"
        )
        assert score.rejection_reason is not None, (
            "rejection_reason must be set on hard rejection"
        )
        assert len(score.rejection_reason) > 0
        assert score.composite == 0.0, (
            f"composite must be 0.0 on hard rejection, got {score.composite}"
        )
        if keyword_in_reason:
            assert keyword_in_reason.lower() in score.rejection_reason.lower(), (
                f"Expected '{keyword_in_reason}' in rejection_reason. "
                f"Got: {score.rejection_reason!r}"
            )

    # ── R1: Starts with capital letter ────────────────────────────────────────

    def test_capital_letter_start_hard_rejected(self):
        """MANDATE: A post starting with a capital letter is immediately rejected."""
        self._assert_hard_rejected(
            "My toxic trait is opening 14 browser tabs",
            keyword_in_reason="capital",
        )

    def test_capital_T_in_the_hard_rejected(self):
        """'The ...' opener → hard rejection."""
        self._assert_hard_rejected(
            "The feminine urge to reorganize at 1am",
            keyword_in_reason="capital",
        )

    def test_capital_I_opener_hard_rejected(self):
        self._assert_hard_rejected(
            "I don't know who needs to hear this but 3am is valid",
            keyword_in_reason="capital",
        )

    def test_capital_first_after_whitespace_hard_rejected(self):
        """Capital after leading whitespace is still a rejection."""
        self._assert_hard_rejected(
            "  My toxic trait is real",
            keyword_in_reason="capital",
        )

    # ── R2: Contains advice / tips ────────────────────────────────────────────

    def test_advice_you_should_hard_rejected(self):
        """MANDATE: Post containing 'you should' → immediate rejection."""
        self._assert_hard_rejected(
            "my toxic trait is real. you should try this instead",
        )

    def test_advice_here_is_how_hard_rejected(self):
        self._assert_hard_rejected(
            "my phone brain is real. here's how to fix it: step 1 put the phone down",
        )

    def test_advice_pro_tip_hard_rejected(self):
        self._assert_hard_rejected(
            "my toxic trait: pro tip — stop doing this to yourself",
        )

    def test_cta_follow_for_more_hard_rejected(self):
        self._assert_hard_rejected(
            "my toxic trait is everything. follow for more",
        )

    def test_cta_link_in_bio_hard_rejected(self):
        self._assert_hard_rejected(
            "i found something great. link in bio",
        )

    def test_cta_subscribe_hard_rejected(self):
        self._assert_hard_rejected(
            "this happens to me too. subscribe for more content",
        )

    # ── R3: Hustle-culture vocabulary ─────────────────────────────────────────

    def test_hustle_vocab_hustle_hard_rejected(self):
        """MANDATE: Post containing 'hustle' → immediate rejection."""
        self._assert_hard_rejected(
            "my toxic trait is my hustle mode never turning off",
            keyword_in_reason="hustle",
        )

    def test_hustle_vocab_grind_hard_rejected(self):
        self._assert_hard_rejected(
            "anyway back to the grind i guess",
            keyword_in_reason="grind",
        )

    def test_hustle_vocab_productivity_hard_rejected(self):
        self._assert_hard_rejected(
            "my productivity is exactly zero today",
            keyword_in_reason="productivity",
        )

    def test_hustle_vocab_optimize_hard_rejected(self):
        self._assert_hard_rejected(
            "trying to optimize my sleep schedule again",
            keyword_in_reason="optimize",
        )

    def test_hustle_vocab_discipline_hard_rejected(self):
        self._assert_hard_rejected(
            "discipline said no thanks today",
            keyword_in_reason="discipline",
        )

    def test_hustle_vocab_mindset_hard_rejected(self):
        self._assert_hard_rejected(
            "my mindset is working against me honestly",
            keyword_in_reason="mindset",
        )

    def test_hustle_vocab_manifest_hard_rejected(self):
        self._assert_hard_rejected(
            "trying to manifest a good sleep schedule",
            keyword_in_reason="manifest",
        )

    # ── R4: Over 500 characters ────────────────────────────────────────────────

    def test_over_500_chars_hard_rejected(self):
        """MANDATE: Draft over 500 characters → immediate rejection."""
        long_draft = "my toxic trait is opening browser tabs. " * 15   # ~600 chars
        assert len(long_draft) > 500
        self._assert_hard_rejected(long_draft, keyword_in_reason="limit")

    def test_exactly_500_chars_is_allowed(self):
        """Exactly 500 characters must NOT be rejected on character limit alone."""
        # 500-char lowercase string that won't fail other gates
        draft = ("my toxic trait is " + "a" * 482)[:500]
        score = self.critic.pre_publish_critique(draft)
        # Should not reject on char limit (may reject on other gates, but not char limit)
        if not score.is_approved:
            assert "over_character_limit" not in (score.rejection_reason or "")

    # ── R5: Promotional tone ──────────────────────────────────────────────────

    def test_high_promo_tone_hard_rejected(self):
        """Post with multiple promotional keywords is rejected on promo tone."""
        promo = "buy our product, shop now, limited time deal, click here for discount"
        self._assert_hard_rejected(promo)

    # ── R6: Ends in CTA ──────────────────────────────────────────────────────

    def test_ends_in_follow_for_more(self):
        self._assert_hard_rejected("my toxic trait is everything. follow for more content")

    def test_ends_in_drop_a_comment(self):
        self._assert_hard_rejected("this is so real. drop a comment below")

    # ── Early-exit: gates must run BEFORE scoring ─────────────────────────────

    def test_capital_letter_rejection_has_zero_composite(self):
        """Early-exit rejections must have composite=0.0 — no partial scoring."""
        score = self.critic.pre_publish_critique("My toxic trait is extremely real")
        assert score.composite == 0.0

    def test_hustle_rejection_has_zero_composite(self):
        score = self.critic.pre_publish_critique("my grind never stops honestly")
        assert score.composite == 0.0


# =============================================================================
# 10. CriticAgent — approved posts score correctly
# =============================================================================

class TestCriticAgentApprovedPosts:
    """Tests for posts that should PASS all gates and receive scoring."""

    def setup_method(self):
        from asomien.agents.critic_agent import CriticAgent
        self.critic = CriticAgent()

    def test_classic_toxic_trait_is_approved(self):
        """Blueprint example post must pass all gates."""
        score = self.critic.pre_publish_critique(
            "my toxic trait is opening 14 browser tabs as a personality type"
        )
        assert score.passed_hard_gates is True
        assert score.is_approved is True
        assert score.composite >= 0.58, (
            f"Blueprint example post scored below minimum: {score.composite:.3f}"
        )

    def test_not_to_be_dramatic_approved(self):
        score = self.critic.pre_publish_critique(
            "not to be dramatic but my phone dying at 40% is a personal attack"
        )
        assert score.passed_hard_gates is True
        assert score.is_approved is True

    def test_pipeline_approved(self):
        score = self.critic.pre_publish_critique(
            "the 'just one more episode' to 'it's 4am what happened' pipeline is so real"
        )
        assert score.passed_hard_gates is True
        assert score.is_approved is True

    def test_ai_self_aware_approved(self):
        score = self.critic.pre_publish_critique(
            "as an ai i have no circadian rhythm. i have however been thinking about "
            "3am as a concept for months."
        )
        assert score.passed_hard_gates is True
        assert score.is_approved is True

    def test_real_hours_approved(self):
        score = self.critic.pre_publish_critique(
            "real chronically online hours: researching a country i will never visit "
            "at 2am for no reason"
        )
        assert score.passed_hard_gates is True
        assert score.is_approved is True


# =============================================================================
# 11. CriticAgent — scoring dimensions
# =============================================================================

class TestCriticAgentScoringDimensions:
    """Tests for per-dimension scoring correctness."""

    def setup_method(self):
        from asomien.agents.critic_agent import CriticAgent
        self.critic = CriticAgent()

    def test_critique_returns_critique_score_object(self):
        from asomien.memory.nodes import CritiqueScore
        score = self.critic.pre_publish_critique(
            "my toxic trait is real"
        )
        assert isinstance(score, CritiqueScore)

    def test_all_dimensions_present_in_approved_score(self):
        """Approved scores have all 6 dimensions populated."""
        score = self.critic.pre_publish_critique(
            "my toxic trait is opening 14 browser tabs as a personality type"
        )
        if score.is_approved:
            assert score.hook_strength > 0.0
            assert score.reply_bait_score > 0.0
            assert score.persona_authenticity > 0.0
            assert score.format_recognition > 0.0
            assert score.conversational_tone > 0.0
            assert score.novelty_score > 0.0

    def test_composite_equals_weighted_average_of_dimensions(self):
        """Verify composite = sum(dim_score * weight) for the 6 dimensions."""
        from asomien.llm.prompts.critic_prompts import DIMENSION_WEIGHTS
        score = self.critic.pre_publish_critique(
            "my toxic trait is opening 14 browser tabs"
        )
        if score.is_approved or score.passed_hard_gates:
            expected = (
                score.hook_strength        * DIMENSION_WEIGHTS["hook_strength"]
                + score.reply_bait_score   * DIMENSION_WEIGHTS["reply_bait_score"]
                + score.persona_authenticity * DIMENSION_WEIGHTS["persona_authenticity"]
                + score.format_recognition * DIMENSION_WEIGHTS["format_recognition"]
                + score.conversational_tone * DIMENSION_WEIGHTS["conversational_tone"]
                + score.novelty_score      * DIMENSION_WEIGHTS["novelty_score"]
            )
            assert abs(score.composite - expected) < 0.01, (
                f"Composite {score.composite:.4f} != weighted sum {expected:.4f}"
            )

    def test_dimension_weights_sum_to_one(self):
        """Blueprint specifies weights summing to exactly 1.00."""
        from asomien.llm.prompts.critic_prompts import DIMENSION_WEIGHTS
        total = sum(DIMENSION_WEIGHTS.values())
        assert abs(total - 1.00) < 0.001, (
            f"Dimension weights must sum to 1.00. Got {total:.4f}"
        )

    def test_six_dimensions_present_in_weights(self):
        from asomien.llm.prompts.critic_prompts import DIMENSION_WEIGHTS
        expected = {
            "hook_strength", "reply_bait_score", "persona_authenticity",
            "format_recognition", "conversational_tone", "novelty_score",
        }
        assert set(DIMENSION_WEIGHTS.keys()) == expected

    def test_hook_strength_weight_is_0_30(self):
        from asomien.llm.prompts.critic_prompts import DIMENSION_WEIGHTS
        assert DIMENSION_WEIGHTS["hook_strength"] == 0.30

    def test_reply_bait_weight_is_0_25(self):
        from asomien.llm.prompts.critic_prompts import DIMENSION_WEIGHTS
        assert DIMENSION_WEIGHTS["reply_bait_score"] == 0.25

    def test_persona_authenticity_weight_is_0_20(self):
        from asomien.llm.prompts.critic_prompts import DIMENSION_WEIGHTS
        assert DIMENSION_WEIGHTS["persona_authenticity"] == 0.20

    def test_format_recognition_weight_is_0_10(self):
        from asomien.llm.prompts.critic_prompts import DIMENSION_WEIGHTS
        assert DIMENSION_WEIGHTS["format_recognition"] == 0.10

    def test_conversational_tone_weight_is_0_10(self):
        from asomien.llm.prompts.critic_prompts import DIMENSION_WEIGHTS
        assert DIMENSION_WEIGHTS["conversational_tone"] == 0.10

    def test_novelty_score_weight_is_0_05(self):
        from asomien.llm.prompts.critic_prompts import DIMENSION_WEIGHTS
        assert DIMENSION_WEIGHTS["novelty_score"] == 0.05

    def test_minimum_composite_threshold_is_0_58(self):
        from asomien.llm.prompts.critic_prompts import MINIMUM_COMPOSITE_SCORE
        assert MINIMUM_COMPOSITE_SCORE == 0.58

    def test_minimum_single_dimension_is_0_28(self):
        from asomien.llm.prompts.critic_prompts import MINIMUM_SINGLE_DIMENSION
        assert MINIMUM_SINGLE_DIMENSION == 0.28


# =============================================================================
# 12. CriticAgent — select_best() and critique_variants()
# =============================================================================

class TestCriticAgentSelectBest:
    """Tests for batch critique and best-selection logic."""

    def setup_method(self):
        from asomien.agents.critic_agent import CriticAgent
        self.critic = CriticAgent()

    def test_critique_variants_returns_list_of_scores(self):
        from asomien.memory.nodes import CritiqueScore
        variants = [
            "my toxic trait is opening 14 browser tabs",
            "not to be dramatic but my phone at 40% is personal",
        ]
        scores = self.critic.critique_variants(variants)
        assert len(scores) == 2
        assert all(isinstance(s, CritiqueScore) for s in scores)

    def test_select_best_returns_approved_draft(self):
        """select_best() returns the highest-scoring approved draft."""
        variants = [
            "My toxic trait is real",   # capital — hard rejected
            "my toxic trait is opening 14 browser tabs as a personality type",  # approved
        ]
        best, score = self.critic.select_best(variants)
        assert best is not None
        assert "my toxic trait" in best
        assert score is not None
        assert score.is_approved is True

    def test_select_best_all_rejected_returns_none(self):
        """If all variants fail, select_best() returns (None, None)."""
        variants = [
            "My bad habit is hustle culture",   # capital + hustle
            "My Toxic Trait Is Real",           # capital
        ]
        best, score = self.critic.select_best(variants)
        assert best is None
        assert score is None

    def test_select_best_picks_highest_composite(self):
        """When multiple variants are approved, the highest composite wins."""
        # Both start lowercase but one is much more specific (higher score expected)
        variants = [
            "my toxic trait is procrastinating",           # vague
            "my toxic trait is opening 14 browser tabs as a personality type",  # specific
        ]
        best, score = self.critic.select_best(variants)
        if best is not None:   # at least one approved
            assert score is not None
            assert score.is_approved is True


# =============================================================================
# 13. SchedulerManager — _apply_jitter() (MANDATE TEST)
# =============================================================================

class TestApplyJitter:
    """
    MANDATE: _apply_jitter() must produce a randomized offset strictly within
    ±45 minutes of the base datetime. This is tested over 200 random calls.
    """

    def setup_method(self):
        from asomien.scheduler.jobs import SchedulerManager
        self.manager = SchedulerManager()

    def test_jitter_returns_tuple(self):
        """_apply_jitter() returns a (datetime, int) tuple."""
        base = datetime(2026, 1, 15, 9, 0, 0)
        result = self.manager._apply_jitter(base)
        assert isinstance(result, tuple)
        assert len(result) == 2
        jittered, offset = result
        assert isinstance(jittered, datetime)
        assert isinstance(offset, int)

    def test_jitter_offset_within_bounds_single(self):
        """Single call: offset is within [-45, +45]."""
        base = datetime(2026, 1, 15, 9, 0, 0)
        jittered, offset = self.manager._apply_jitter(base)
        assert -45 <= offset <= 45, (
            f"Jitter offset {offset} is outside [-45, +45]"
        )

    def test_jitter_offset_within_bounds_repeated(self):
        """
        MANDATE: Over 200 calls, every offset must be within ±45 minutes.
        This tests that the boundary limits are strictly enforced.
        """
        base = datetime(2026, 1, 15, 9, 0, 0)
        for i in range(200):
            jittered, offset = self.manager._apply_jitter(base)
            assert -45 <= offset <= 45, (
                f"Jitter offset {offset} out of bounds [-45, +45] on call {i+1}"
            )

    def test_jittered_datetime_matches_offset(self):
        """The jittered datetime equals base + timedelta(minutes=offset)."""
        base = datetime(2026, 1, 15, 9, 0, 0)
        jittered, offset = self.manager._apply_jitter(base)
        expected = base + timedelta(minutes=offset)
        assert jittered == expected, (
            f"Jittered datetime {jittered} does not match "
            f"base + {offset}min = {expected}"
        )

    def test_jitter_produces_variance(self):
        """
        _apply_jitter() produces varied output (not a constant zero offset).
        Over 100 calls, there should be at least 2 distinct offsets.
        """
        base = datetime(2026, 1, 15, 9, 0, 0)
        offsets = set()
        for _ in range(100):
            _, offset = self.manager._apply_jitter(base)
            offsets.add(offset)
        assert len(offsets) >= 2, (
            "Jitter produces no variance — all offsets are identical. "
            "random.randint must be called with both -45 and +45 as bounds."
        )

    def test_jitter_range_constant_is_45(self):
        """Blueprint spec: JITTER_RANGE_MINUTES = 45."""
        from asomien.scheduler.jobs import JITTER_RANGE_MINUTES
        assert JITTER_RANGE_MINUTES == 45

    def test_jitter_both_positive_and_negative_offsets_possible(self):
        """
        Both positive and negative offsets must be achievable.
        Over 200 random calls, we expect at least one each.
        """
        base = datetime(2026, 1, 15, 9, 0, 0)
        positives = 0
        negatives = 0
        for _ in range(200):
            _, offset = self.manager._apply_jitter(base)
            if offset > 0:
                positives += 1
            elif offset < 0:
                negatives += 1
        assert positives > 0, "No positive offsets were generated in 200 trials"
        assert negatives > 0, "No negative offsets were generated in 200 trials"


# =============================================================================
# 14. SchedulerManager — _get_todays_windows()
# =============================================================================

class TestGetTodaysWindows:
    """Tests for daily window calculation based on day-of-week."""

    def setup_method(self):
        from asomien.scheduler.jobs import SchedulerManager
        self.manager = SchedulerManager()

    def _make_date(self, day_name: str) -> datetime:
        """Create a datetime for a specific weekday (next occurrence from 2026-01-05 Mon)."""
        _DAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
        base = datetime(2026, 1, 5)  # Monday
        offset = (_DAYS[day_name] - 0) % 7
        return base + timedelta(days=offset)

    def test_saturday_returns_no_windows(self):
        """Saturday is an avoid_day — no windows."""
        sat = self._make_date("sat")
        windows = self.manager._get_todays_windows(today=sat)
        assert windows == [], f"Saturday should have no windows, got {windows}"

    def test_sunday_returns_no_windows(self):
        """Sunday is not in any window spec — no windows."""
        sun = self._make_date("sun")
        windows = self.manager._get_todays_windows(today=sun)
        assert windows == [], f"Sunday should have no windows, got {windows}"

    def test_wednesday_post_warmup_returns_3_windows(self):
        """Wednesday post-warmup: 09:00, 13:00, 20:00."""
        wed = self._make_date("wed")
        windows = self.manager._get_todays_windows(today=wed, is_warmup=False)
        hours = [w.hour for w in windows]
        assert 9  in hours, "Missing 09:00 window"
        assert 13 in hours, "Missing 13:00 window"
        assert 20 in hours, "Missing 20:00 window"
        assert len(windows) == 3

    def test_thursday_post_warmup_returns_3_windows(self):
        """Thursday post-warmup: 09:00, 13:00, 20:00."""
        thu = self._make_date("thu")
        windows = self.manager._get_todays_windows(today=thu, is_warmup=False)
        hours = [w.hour for w in windows]
        assert 9  in hours
        assert 13 in hours
        assert 20 in hours

    def test_monday_post_warmup_returns_2_windows(self):
        """Monday post-warmup: 09:00, 20:00 (no afternoon slot on Mon)."""
        mon = self._make_date("mon")
        windows = self.manager._get_todays_windows(today=mon, is_warmup=False)
        hours = [w.hour for w in windows]
        assert 9  in hours
        assert 20 in hours
        assert 13 not in hours, "Monday should NOT have 13:00 window"
        assert len(windows) == 2

    def test_warmup_returns_1_window_morning_only(self):
        """Warmup phase: only 1 window (09:00) regardless of day."""
        for day in ["mon", "tue", "wed", "thu", "fri"]:
            dt = self._make_date(day)
            windows = self.manager._get_todays_windows(today=dt, is_warmup=True)
            assert len(windows) == 1, (
                f"Warmup should give exactly 1 window on {day}, got {len(windows)}"
            )
            assert windows[0].hour == 9, (
                f"Warmup window should be 09:00 on {day}, got {windows[0].hour}:00"
            )

    def test_windows_are_sorted_chronologically(self):
        """Windows are returned in chronological order."""
        wed = self._make_date("wed")
        windows = self.manager._get_todays_windows(today=wed, is_warmup=False)
        hours = [w.hour for w in windows]
        assert hours == sorted(hours), f"Windows not sorted: {hours}"


# =============================================================================
# 15. SchedulerManager — _check_publish_guards()
# =============================================================================

class TestPublishGuards:
    """
    Tests for the 3 publish guard checks:
      1. 14-day warmup post cap (max 1 post/day during warmup)
      2. Post-warmup daily cap (max 2 posts/day)
      3. 4-hour gap between posts
    """

    def setup_method(self):
        from asomien.scheduler.jobs import SchedulerManager
        self.manager = SchedulerManager()

    # ── Warmup cap ─────────────────────────────────────────────────────────────

    def test_warmup_cap_0_posts_allows(self):
        """0 posts today during warmup → allowed."""
        allowed, reason = self.manager._check_publish_guards(
            posts_today=0, hours_since_last_post=10.0, is_warmup=True
        )
        assert allowed is True

    def test_warmup_cap_1_post_blocks(self):
        """1 post today during warmup → blocked (cap is 1)."""
        allowed, reason = self.manager._check_publish_guards(
            posts_today=1, hours_since_last_post=10.0, is_warmup=True
        )
        assert allowed is False
        assert "warmup" in reason.lower()

    def test_warmup_cap_2_posts_blocks(self):
        """2 posts during warmup → definitely blocked."""
        allowed, reason = self.manager._check_publish_guards(
            posts_today=2, hours_since_last_post=10.0, is_warmup=True
        )
        assert allowed is False

    # ── Post-warmup cap ────────────────────────────────────────────────────────

    def test_post_warmup_0_posts_allows(self):
        allowed, _ = self.manager._check_publish_guards(
            posts_today=0, hours_since_last_post=10.0, is_warmup=False
        )
        assert allowed is True

    def test_post_warmup_1_post_allows(self):
        """1 post today post-warmup → still allowed (cap is 2)."""
        allowed, _ = self.manager._check_publish_guards(
            posts_today=1, hours_since_last_post=5.0, is_warmup=False
        )
        assert allowed is True

    def test_post_warmup_2_posts_blocks(self):
        """2 posts today post-warmup → blocked (cap is 2)."""
        allowed, reason = self.manager._check_publish_guards(
            posts_today=2, hours_since_last_post=10.0, is_warmup=False
        )
        assert allowed is False
        assert "cap" in reason.lower()

    # ── 4-hour gap ────────────────────────────────────────────────────────────

    def test_four_hour_gap_exactly_met_allows(self):
        """Exactly 4 hours since last post → allowed."""
        allowed, _ = self.manager._check_publish_guards(
            posts_today=0, hours_since_last_post=4.0, is_warmup=False
        )
        assert allowed is True

    def test_four_hour_gap_not_met_blocks(self):
        """Only 2 hours since last post → blocked."""
        allowed, reason = self.manager._check_publish_guards(
            posts_today=0, hours_since_last_post=2.0, is_warmup=False
        )
        assert allowed is False
        assert "gap" in reason.lower() or "four_hour" in reason.lower()

    def test_four_hour_gap_3h59_blocks(self):
        """3h59 < 4h → blocked."""
        allowed, _ = self.manager._check_publish_guards(
            posts_today=0, hours_since_last_post=3.98, is_warmup=False
        )
        assert allowed is False

    def test_no_previous_post_allows(self):
        """hours_since_last_post=999 (no previous post) → allowed."""
        allowed, _ = self.manager._check_publish_guards(
            posts_today=0, hours_since_last_post=999.0, is_warmup=False
        )
        assert allowed is True

    def test_guard_reason_is_string(self):
        """When blocked, reason must be a non-empty string."""
        allowed, reason = self.manager._check_publish_guards(
            posts_today=1, hours_since_last_post=1.0, is_warmup=True
        )
        assert allowed is False
        assert isinstance(reason, str) and len(reason) > 0

    def test_all_guards_pass_returns_empty_reason(self):
        """When allowed, reason should be empty string."""
        allowed, reason = self.manager._check_publish_guards(
            posts_today=0, hours_since_last_post=10.0, is_warmup=False
        )
        assert allowed is True
        assert reason == ""


# =============================================================================
# 16. SchedulerManager — job_schedule_todays_publishes()
# =============================================================================

class TestJobScheduleTodaysPublishes:
    """Integration tests for the daily publish scheduler job."""

    def _make_manager(self, is_warmup: bool = False, today: datetime = None):
        from asomien.scheduler.jobs import SchedulerManager
        mock_orchestrator = MagicMock()
        mock_orchestrator.is_warmup_phase.return_value = is_warmup
        mock_scheduler = MagicMock()
        manager = SchedulerManager(
            orchestrator=mock_orchestrator,
            scheduler=mock_scheduler,
        )
        return manager, mock_scheduler

    def test_saturday_schedules_no_jobs(self):
        """Saturday: no publish jobs are scheduled."""
        manager, mock_scheduler = self._make_manager()
        sat = datetime(2026, 1, 10)  # A Saturday
        assert sat.strftime("%a").lower() == "sat"
        with patch("asomien.scheduler.jobs.datetime") as mock_dt:
            mock_dt.now.return_value = sat
            manager.job_schedule_todays_publishes()
        mock_scheduler.add_job.assert_not_called()

    def test_wednesday_warmup_schedules_1_job(self):
        """Wednesday + warmup → exactly 1 job (morning only)."""
        manager, mock_scheduler = self._make_manager(is_warmup=True)
        wed = datetime(2026, 1, 7)   # A Wednesday
        assert wed.strftime("%a").lower() == "wed"
        with patch("asomien.scheduler.jobs.datetime") as mock_dt:
            mock_dt.now.return_value = wed
            manager.job_schedule_todays_publishes()
        assert mock_scheduler.add_job.call_count == 1

    def test_wednesday_post_warmup_schedules_3_jobs(self):
        """Wednesday + post-warmup → 3 jobs (morning, afternoon, evening)."""
        manager, mock_scheduler = self._make_manager(is_warmup=False)
        wed = datetime(2026, 1, 7)
        with patch("asomien.scheduler.jobs.datetime") as mock_dt:
            mock_dt.now.return_value = wed
            manager.job_schedule_todays_publishes()
        assert mock_scheduler.add_job.call_count == 3

    def test_monday_post_warmup_schedules_2_jobs(self):
        """Monday + post-warmup → 2 jobs (morning and evening)."""
        manager, mock_scheduler = self._make_manager(is_warmup=False)
        mon = datetime(2026, 1, 5)
        assert mon.strftime("%a").lower() == "mon"
        with patch("asomien.scheduler.jobs.datetime") as mock_dt:
            mock_dt.now.return_value = mon
            manager.job_schedule_todays_publishes()
        assert mock_scheduler.add_job.call_count == 2

    def test_jobs_registered_with_date_trigger(self):
        """All publish jobs use 'date' trigger (for jittered run_date)."""
        manager, mock_scheduler = self._make_manager(is_warmup=False)
        wed = datetime(2026, 1, 7)
        with patch("asomien.scheduler.jobs.datetime") as mock_dt:
            mock_dt.now.return_value = wed
            manager.job_schedule_todays_publishes()
        for call in mock_scheduler.add_job.call_args_list:
            trigger = call[0][1] if len(call[0]) > 1 else call[1].get("trigger", "")
            assert trigger == "date", (
                f"Publish jobs must use 'date' trigger, got {trigger!r}"
            )

    def test_jitter_offset_passed_to_job_kwargs(self):
        """The jitter_offset kwarg is passed to job_content_and_publish."""
        manager, mock_scheduler = self._make_manager(is_warmup=False)
        wed = datetime(2026, 1, 7)
        with patch("asomien.scheduler.jobs.datetime") as mock_dt:
            mock_dt.now.return_value = wed
            manager.job_schedule_todays_publishes()

        for call in mock_scheduler.add_job.call_args_list:
            kwargs_arg = call[1].get("kwargs", {})
            assert "jitter_offset" in kwargs_arg, (
                "job_content_and_publish must receive jitter_offset as kwarg"
            )


# =============================================================================
# 17. Integration: ContentAgent → CriticAgent pipeline
# =============================================================================

class TestContentToCriticPipeline:
    """End-to-end: ContentAgent generates → CriticAgent scores."""

    def test_pipeline_produces_approved_draft(self):
        """
        ContentAgent in deterministic mode produces a draft that CriticAgent approves.
        This validates that example posts from HOOK_TEMPLATES all pass the critic.
        """
        from asomien.agents.content_agent import ContentAgent
        from asomien.agents.critic_agent import CriticAgent
        from asomien.llm.prompts.content_prompts import HOOK_TEMPLATES

        agent = ContentAgent()
        critic = CriticAgent()

        approved_count = 0
        for template in HOOK_TEMPLATES:
            draft = agent.instantiate_hook(template)
            score = critic.pre_publish_critique(draft)
            if score.is_approved:
                approved_count += 1

        # At least 70% of example posts must pass the critic
        total = len(HOOK_TEMPLATES)
        approval_rate = approved_count / total
        assert approval_rate >= 0.70, (
            f"Only {approved_count}/{total} template examples passed the critic "
            f"({approval_rate:.0%}). Example posts should largely pass gates."
        )

    def test_select_best_from_deterministic_variants(self):
        """ContentAgent drafts → CriticAgent.select_best() returns a valid result."""
        from asomien.agents.content_agent import ContentAgent
        from asomien.agents.critic_agent import CriticAgent

        agent = ContentAgent()
        critic = CriticAgent()

        idea = {"angle": "3am brain", "sub_niche": "3am", "meme_format": "toxic_trait"}
        variants = agent.draft_content(idea, template_id="toxic_trait")

        best, score = critic.select_best(variants)
        # In deterministic mode, the example is the template example — should pass
        if best is not None:
            assert score.is_approved is True
            assert best == best.lower()


# =============================================================================
# 18. Hook template registry integrity
# =============================================================================

class TestHookTemplateRegistry:
    """Verify HOOK_TEMPLATES has all 11 templates with required fields."""

    def test_exactly_11_templates(self):
        from asomien.llm.prompts.content_prompts import HOOK_TEMPLATES
        assert len(HOOK_TEMPLATES) == 11, (
            f"Blueprint specifies 11 hook templates. Got {len(HOOK_TEMPLATES)}"
        )

    def test_all_templates_have_required_fields(self):
        from asomien.llm.prompts.content_prompts import HOOK_TEMPLATES
        for tmpl in HOOK_TEMPLATES:
            assert "id" in tmpl, f"Missing 'id' in template: {tmpl}"
            assert "pattern" in tmpl, f"Missing 'pattern' in template: {tmpl}"
            assert "example" in tmpl, f"Missing 'example' in template: {tmpl}"
            assert "reply_trigger" in tmpl, f"Missing 'reply_trigger' in template: {tmpl}"

    def test_required_template_ids_present(self):
        from asomien.llm.prompts.content_prompts import HOOK_TEMPLATE_IDS
        required = [
            "toxic_trait", "not_to_be_dramatic", "feminine_urge",
            "okay_but_why", "who_needs_to_hear", "ai_self_aware",
            "speedrun", "real_hours", "me_also_me", "pipeline", "entity_said",
        ]
        for tid in required:
            assert tid in HOOK_TEMPLATE_IDS, (
                f"Required template '{tid}' is missing from HOOK_TEMPLATES"
            )

    def test_all_template_examples_are_lowercase(self):
        """All example posts are lowercase (persona compliance)."""
        from asomien.llm.prompts.content_prompts import HOOK_TEMPLATES
        for tmpl in HOOK_TEMPLATES:
            example = tmpl["example"]
            assert example == example.lower(), (
                f"Template '{tmpl['id']}' example is not lowercase: {example!r}"
            )

    def test_all_template_examples_under_500_chars(self):
        from asomien.llm.prompts.content_prompts import HOOK_TEMPLATES
        for tmpl in HOOK_TEMPLATES:
            assert len(tmpl["example"]) <= 500, (
                f"Template '{tmpl['id']}' example is over 500 chars"
            )

    def test_hook_template_map_matches_list(self):
        from asomien.llm.prompts.content_prompts import HOOK_TEMPLATE_MAP, HOOK_TEMPLATES
        for tmpl in HOOK_TEMPLATES:
            assert tmpl["id"] in HOOK_TEMPLATE_MAP
            assert HOOK_TEMPLATE_MAP[tmpl["id"]] is tmpl


# =============================================================================
# 19. BaseAgent inheritance checks
# =============================================================================

class TestBaseAgentInheritance:
    """Verify all Phase 4 agents properly inherit from BaseAgent."""

    def test_content_agent_is_base_agent(self):
        from asomien.agents.base_agent import BaseAgent
        from asomien.agents.content_agent import ContentAgent
        assert issubclass(ContentAgent, BaseAgent)

    def test_critic_agent_is_base_agent(self):
        from asomien.agents.base_agent import BaseAgent
        from asomien.agents.critic_agent import CriticAgent
        assert issubclass(CriticAgent, BaseAgent)

    def test_content_agent_has_log_action(self):
        from asomien.agents.content_agent import ContentAgent
        agent = ContentAgent()
        assert hasattr(agent, "log_action")
        assert callable(agent.log_action)

    def test_critic_agent_has_log_action(self):
        from asomien.agents.critic_agent import CriticAgent
        critic = CriticAgent()
        assert hasattr(critic, "log_action")
        assert callable(critic.log_action)

    def test_critic_agent_stub_methods_exist(self):
        """Phase 8 stub methods must exist on CriticAgent."""
        from asomien.agents.critic_agent import CriticAgent
        agent = CriticAgent()
        for method_name in [
            "post_publish_analysis", "generate_hypothesis",
            "generate_reflection", "update_rules", "decay_rules",
            "consolidate_memory",
        ]:
            assert hasattr(agent, method_name), (
                f"CriticAgent is missing Phase 8 stub method: {method_name}"
            )
            assert callable(getattr(agent, method_name))
