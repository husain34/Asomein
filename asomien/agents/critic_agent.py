"""
asomien/agents/critic_agent.py

Pre-Publish Critic Agent — enforces content quality and persona compliance
before any draft is allowed to proceed to publication.

Blueprint specification (Section 5 / Section 7):

SCORING DIMENSIONS (6 dimensions, weights sum to 1.00):
  1. hook_strength        0.30 — scroll-stop power; specificity and curiosity gap
  2. reply_bait_score     0.25 — will this generate "same", "wait why", "okay but"?
  3. persona_authenticity 0.20 — sounds like the account, not a brand
  4. format_recognition   0.10 — known meme format used correctly and freshly
  5. conversational_tone  0.10 — lowercase, fragments, natural, not polished
  6. novelty_score        0.05 — fresh angle or clever instantiation

HARD REJECTION RULES (run FIRST, before any scoring):
  R1. Starts with capital letter → immediate reject
  R2. Contains advice / tips → immediate reject
  R3. Contains hustle-culture vocabulary → immediate reject
  R4. Over 500 characters → immediate reject
  R5. Promotional tone > 0.30 → immediate reject (heuristic scan)
  R6. Ends in a call-to-action → immediate reject

Minimum thresholds (post-scoring):
  - composite score < 0.58 → reject
  - any single dimension  < 0.28 → reject

All hard rejections use CritiqueScore.hard_reject() to produce a structured
result with rejection_reason set.  is_approved=True only when ALL gates and
ALL thresholds pass.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

from asomien.agents.base_agent import BaseAgent
from asomien.llm.prompts.critic_prompts import (
    ADVICE_SIGNAL_PHRASES,
    DIMENSION_WEIGHTS,
    HUSTLE_VOCABULARY,
    MAX_CHARACTERS,
    MINIMUM_COMPOSITE_SCORE,
    MINIMUM_SINGLE_DIMENSION,
)
from asomien.memory.nodes import CritiqueScore

logger = logging.getLogger(__name__)

# ── Promotional-tone keyword heuristic ───────────────────────────────────────
_PROMO_KEYWORDS: list[str] = [
    "buy", "purchase", "shop", "sale", "discount", "deal", "offer",
    "limited time", "click here", "visit our", "check out our",
    "brand", "product", "sponsor", "partner", "ad",
]

# ── Reply-bait signal phrases ─────────────────────────────────────────────────
# Presence of these patterns strongly signals reply-bait potential.
_REPLY_BAIT_PATTERNS: list[re.Pattern] = [
    re.compile(r"\bsame\b", re.IGNORECASE),
    re.compile(r"\bwait\b.{1,20}\bwhy\b", re.IGNORECASE),
    re.compile(r"\bokay but\b", re.IGNORECASE),
    re.compile(r"\bwhy does\b", re.IGNORECASE),
    re.compile(r"\bpipeline\b", re.IGNORECASE),
    re.compile(r"\bso real\b", re.IGNORECASE),
    re.compile(r"\brelatable\b", re.IGNORECASE),
    re.compile(r"\bi don'?t know who needs\b", re.IGNORECASE),
    re.compile(r"\bme:.*also me\b", re.IGNORECASE),
    re.compile(r"\bmy toxic trait\b", re.IGNORECASE),
    re.compile(r"\bnot to be dramatic\b", re.IGNORECASE),
    re.compile(r"\breal .{1,25} hours\b", re.IGNORECASE),
]

# ── Hook-strength signal patterns ─────────────────────────────────────────────
# Specificity markers: numbers, measurements, named objects — the bit is in the detail.
_SPECIFICITY_PATTERN: re.Pattern = re.compile(
    r"\b\d+\b|"            # numbers ("14 tabs", "3am", "40%")
    r"\b[a-z]+'s\b|"      # possessives ("phone's")
    r"\b(?:specifically|exactly|literally|genuinely|honestly)\b",
    re.IGNORECASE,
)

# ── CTA / advice patterns (end-of-post scan) ─────────────────────────────────
_CTA_PATTERNS: list[re.Pattern] = [
    re.compile(
        r"\b(?:follow for|link in bio|check this out|subscribe|save this|"
        r"share this|repost if|drop a comment|comment below|tell me in the "
        r"comments|let me know what you think|click)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:here'?s? how|here are \d|tips? for|tip:|pro tip|you need to|"
        r"you should|try this|do this|start doing|stop doing)\b",
        re.IGNORECASE,
    ),
]


class CriticAgent(BaseAgent):
    """
    Pre-Publish Critic for the Asomien content pipeline.

    Usage:
        critic = CriticAgent()
        score = critic.pre_publish_critique("my toxic trait is everything")
        if score.is_approved:
            publish(draft)

    In tests, no llm_client is required — the critic operates entirely
    on rule-based heuristics. The LLM client is reserved for Phase 8+
    post-hoc analysis and reflection generation.
    """

    def __init__(
        self,
        llm_client=None,    # reserved for reflection/post-hoc analysis (Phase 8)
        memory=None,        # reserved for rule retrieval (Phase 8)
    ) -> None:
        super().__init__(name="CriticAgent")
        self.llm_client = llm_client
        self.memory = memory

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def run(self) -> None:
        """CriticAgent does not have an autonomous loop — it is invoked on demand."""
        self.start()
        logger.info("[CriticAgent] Invoked (no autonomous loop).")
        self.stop()

    def analyze_weekly_performance(self, metrics_db_path: str = "data/metrics.db", memory_db_path: str = "data/memory.db", directives_db_path: str = "data/directives.db") -> None:
        """Phase 8: Post-Hoc Reflection. Analyze top posts and generate new directives."""
        if not self.llm_client:
            logger.warning("[CriticAgent] No LLM client provided. Cannot run reflection.")
            return

        self.log_action("analyze_weekly_performance", "Fetching top posts for reflection.")
        try:
            import sqlite3
            import uuid
            from datetime import datetime, timezone
            
            # 1. Fetch top 5 posts from metrics
            with sqlite3.connect(metrics_db_path) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    "SELECT post_id, creator_engagement_score, likes, replies, reposts FROM post_metrics ORDER BY creator_engagement_score DESC LIMIT 5"
                ).fetchall()
            
            if not rows:
                logger.info("[CriticAgent] No metrics found for reflection.")
                return

            # 2. Fetch content from memory
            top_posts = []
            with sqlite3.connect(memory_db_path) as mem_conn:
                mem_conn.row_factory = sqlite3.Row
                for row in rows:
                    post_row = mem_conn.execute("SELECT content FROM posts WHERE id = ?", (row["post_id"],)).fetchone()
                    if post_row:
                        top_posts.append({
                            "content": post_row["content"],
                            "score": row["creator_engagement_score"],
                            "likes": row["likes"],
                            "replies": row["replies"]
                        })

            if not top_posts:
                return

            # 3. Generate Reflection via LLM
            prompt = (
                "You are the internal Critic for an autonomous Gen-Z persona bot.\\n"
                "Here are the top performing posts of the week based on engagement score:\\n\\n"
            )
            for p in top_posts:
                prompt += f"- POST: \\\"{p['content']}\\\" (Score: {p['score']:.2f}, Likes: {p['likes']}, Replies: {p['replies']})\\n"
            
            prompt += (
                "\\nBased on these successful posts, extract 1 extremely concise, hard rule (directive) "
                "about what topics, vocabulary, or humor styles the bot should focus on next week. "
                "Output ONLY the rule, nothing else. Start with 'Focus on...'"
            )

            reflection = self.llm_client.generate(prompt=prompt, system_prompt="You are a strict analytics engine.", temperature=0.7)
            if not reflection:
                return

            reflection_clean = reflection.strip().strip('"').strip("'")
            self.log_action("generated_directive", f"New directive: {reflection_clean}")

            # 4. Save to directives.db
            with sqlite3.connect(directives_db_path) as dir_conn:
                dir_conn.execute(
                    "INSERT INTO directives (id, directive_type, content, priority, status, start_time) VALUES (?, ?, ?, ?, ?, ?)",
                    (str(uuid.uuid4()), "content_rule", reflection_clean, 8, "active", datetime.now(timezone.utc).isoformat())
                )
                dir_conn.commit()

        except Exception as e:
            logger.error(f"[CriticAgent] Reflection failed: {e}")

    # ── Main API ──────────────────────────────────────────────────────────────

    def pre_publish_critique(self, draft: str) -> CritiqueScore:
        """
        Score a draft for publication readiness.

        PIPELINE (in order):
          1. Run ALL hard-gate checks first.  Any failure → early-exit rejection.
          2. Run 6 heuristic dimension scores.
          3. Compute weighted composite.
          4. Check minimum composite (0.58) and minimum single-dimension (0.28).
          5. Return CritiqueScore with is_approved=True only if all gates pass.

        Parameters
        ----------
        draft : the raw post string to evaluate

        Returns
        -------
        CritiqueScore with all dimensions populated, composite score, and
        is_approved flag.  On hard rejection, composite=0.0 and
        rejection_reason is set.
        """
        self.log_action(
            action="pre_publish_critique",
            reason="evaluating draft before publish",
            outcome=f"draft_len={len(draft)}",
        )

        # ── STEP 1: Hard gates (must run BEFORE scoring) ─────────────────────
        hard_gate_result = self._run_hard_gates(draft)
        if hard_gate_result is not None:
            # Hard gate failed — early exit
            self.log_action(
                action="pre_publish_critique_result",
                reason="hard_gate_failure",
                outcome=f"rejected: {hard_gate_result}",
                level="warning",
            )
            return CritiqueScore.hard_reject(hard_gate_result)

        # ── STEP 2: Dimension scoring ─────────────────────────────────────────
        dim_scores = self._score_dimensions(draft)

        # ── STEP 3: Composite score ───────────────────────────────────────────
        composite = self._compute_composite(dim_scores)

        # ── STEP 4: Minimum thresholds ────────────────────────────────────────
        # Check composite minimum
        if composite < MINIMUM_COMPOSITE_SCORE:
            reason = (
                f"composite_score_below_threshold: "
                f"{composite:.3f} < {MINIMUM_COMPOSITE_SCORE}"
            )
            self.log_action(
                action="pre_publish_critique_result",
                reason="below_composite_threshold",
                outcome=reason,
                level="warning",
            )
            return CritiqueScore(
                composite=composite,
                passed_hard_gates=True,
                rejection_reason=reason,
                is_approved=False,
                **dim_scores,
            )

        # Check minimum per-dimension
        for dim_name, score in dim_scores.items():
            if score < MINIMUM_SINGLE_DIMENSION:
                reason = (
                    f"dimension_below_minimum: {dim_name}={score:.3f} "
                    f"< {MINIMUM_SINGLE_DIMENSION}"
                )
                self.log_action(
                    action="pre_publish_critique_result",
                    reason="below_dimension_threshold",
                    outcome=reason,
                    level="warning",
                )
                return CritiqueScore(
                    composite=composite,
                    passed_hard_gates=True,
                    rejection_reason=reason,
                    is_approved=False,
                    **dim_scores,
                )

        # ── STEP 5: Approved ──────────────────────────────────────────────────
        self.log_action(
            action="pre_publish_critique_result",
            reason="all_gates_passed",
            outcome=f"composite={composite:.3f} — APPROVED",
        )
        return CritiqueScore(
            composite=composite,
            passed_hard_gates=True,
            rejection_reason=None,
            is_approved=True,
            **dim_scores,
        )

    # ── Hard gate checks ──────────────────────────────────────────────────────

    def _run_hard_gates(self, draft: str) -> Optional[str]:
        """
        Run all hard-gate checks.  Returns None if all pass, or a rejection
        reason string as soon as the first failure is encountered.

        Gates run in this order (blueprint Section 10 / pre-publish filter):
          R1. Character limit (>500)
          R2. Starts with capital letter
          R3. Hustle-culture vocabulary
          R4. Advice or tips detected
          R5. Promotional tone heuristic (>0.30)
          R6. Call-to-action detected
        """
        stripped = draft.strip()

        # R1: Character limit
        if len(stripped) > MAX_CHARACTERS:
            return f"over_character_limit: {len(stripped)} > {MAX_CHARACTERS}"

        # R2: Starts with capital letter (MOST CRITICAL persona rule)
        if stripped and stripped[0].isupper():
            return f"starts_with_capital_letter: first_char='{stripped[0]}'"

        draft_lower = stripped.lower()

        # R3: Hustle-culture vocabulary
        for phrase in HUSTLE_VOCABULARY:
            if phrase in draft_lower:
                return f"hustle_vocabulary_detected: '{phrase}'"

        # R4: Advice / tips
        for pattern in _CTA_PATTERNS:
            m = pattern.search(draft_lower)
            if m:
                return f"advice_or_cta_detected: '{m.group(0)}'"

        # R5: Promotional tone heuristic
        promo_score = self._compute_promotional_score(draft_lower)
        if promo_score > 0.30:
            return f"promotional_tone_score: {promo_score:.2f} > 0.30"

        # All gates passed
        return None

    def _compute_promotional_score(self, draft_lower: str) -> float:
        """
        Heuristic promotional tone score in [0.0, 1.0].

        Each promo keyword found adds to the score.  Normalised so that
        4 or more promo keywords = 1.0 (hard reject territory).
        """
        hits = sum(1 for kw in _PROMO_KEYWORDS if kw in draft_lower)
        return min(1.0, hits / 4.0)

    # ── Dimension scoring ─────────────────────────────────────────────────────

    def _score_dimensions(self, draft: str) -> dict[str, float]:
        """
        Run all 6 dimension scorers and return a dict of name → score (0.0–1.0).
        """
        return {
            "hook_strength":        self._score_hook_strength(draft),
            "reply_bait_score":     self._score_reply_bait(draft),
            "persona_authenticity": self._score_persona_authenticity(draft),
            "format_recognition":   self._score_format_recognition(draft),
            "conversational_tone":  self._score_conversational_tone(draft),
            "novelty_score":        self._score_novelty(draft),
        }

    def _score_hook_strength(self, draft: str) -> float:
        """
        Dimension 1 — hook_strength (weight: 0.30).

        Criteria:
          - Has specificity markers (numbers, measurements, named objects)
          - Uses a known meme hook opener pattern
          - Is ≤200 chars (one-line hook energy)
          - Does NOT start generic (e.g. "some thoughts on")

        Score range: [0.30, 1.0] for passing drafts.
        """
        score = 0.30    # base score for anything that passed hard gates

        draft_lower = draft.lower()

        # Specificity bonus
        specificity_hits = len(_SPECIFICITY_PATTERN.findall(draft))
        if specificity_hits >= 2:
            score += 0.30
        elif specificity_hits == 1:
            score += 0.15

        # Known meme opener bonus
        meme_openers = [
            "my toxic trait", "not to be dramatic", "the feminine urge",
            "okay but why", "i don't know who needs", "as an ai",
            "real ", " speed run", "me:", "pipeline is so real",
            "the '", "said ",
        ]
        for opener in meme_openers:
            if opener in draft_lower:
                score += 0.25
                break

        # Brevity bonus — hook energy is stronger in short posts
        if len(draft) <= 150:
            score += 0.15
        elif len(draft) <= 250:
            score += 0.07

        return min(1.0, score)

    def _score_reply_bait(self, draft: str) -> float:
        """
        Dimension 2 — reply_bait_score (weight: 0.25).

        Counts reply-bait signal patterns (same, wait why, pipeline, etc.)
        and scores based on how many triggers are present.
        """
        hits = sum(1 for p in _REPLY_BAIT_PATTERNS if p.search(draft))
        if hits >= 3:
            return 1.0
        if hits == 2:
            return 0.80
        if hits == 1:
            return 0.60
        # No pattern hit, but still passed hard gates — check for question structure
        if "?" in draft or draft.rstrip().endswith("honestly"):
            return 0.45
        return 0.30

    def _score_persona_authenticity(self, draft: str) -> float:
        """
        Dimension 3 — persona_authenticity (weight: 0.20).

        Positive signals: lowercase throughout, fragments, internet idioms,
        AI self-reference.
        Negative signals: formal phrases, corporate tone, complete sentences
        that sound like press releases.
        """
        score = 0.50    # neutral base

        draft_lower = draft.lower()

        # Positive: fully lowercase (already hard-gated but bonus for full compliance)
        if draft == draft_lower:
            score += 0.20

        # Positive: internet idioms
        _IDIOMS = [
            "ngl", "honestly", "genuinely", "literally", "okay but",
            "no but", "wait", "anyway", "lol", "idk", "tbh",
            "chronically", "3am", "brain said", "phone said",
            "as an ai",
        ]
        idiom_hits = sum(1 for idiom in _IDIOMS if idiom in draft_lower)
        score += min(0.25, idiom_hits * 0.08)

        # Negative: formal / corporate phrases
        _FORMAL = [
            "in today's digital landscape", "it is important to",
            "as we navigate", "moving forward", "in conclusion",
            "to summarize", "please note", "i am pleased to",
        ]
        for phrase in _FORMAL:
            if phrase in draft_lower:
                score -= 0.30
                break

        return max(0.0, min(1.0, score))

    def _score_format_recognition(self, draft: str) -> float:
        """
        Dimension 4 — format_recognition (weight: 0.10).

        Checks whether the draft uses a known meme format from HOOK_TEMPLATE_IDS.
        A correctly instantiated template scores high; no template = lower score.
        """
        draft_lower = draft.lower()

        # Map template IDs to their characteristic opener strings
        _FORMAT_OPENERS: dict[str, list[str]] = {
            "toxic_trait":       ["my toxic trait is"],
            "not_to_be_dramatic": ["not to be dramatic"],
            "feminine_urge":     ["the feminine urge", "the masculine urge",
                                   "the lesbian urge", "the gay urge",
                                   "the trans urge", "the queer urge"],
            "okay_but_why":      ["okay but why"],
            "who_needs_to_hear": ["i don't know who needs", "i dont know who needs"],
            "ai_self_aware":     ["as an ai i"],
            "speedrun":          ["speed run:", "speedrun:"],
            "real_hours":        ["real ", " hours:"],
            "me_also_me":        ["me:", "also me"],
            "pipeline":          ["pipeline is so real", "the '", "' to '"],
            "entity_said":       [" said "],
        }

        for tmpl_id, openers in _FORMAT_OPENERS.items():
            if all(op in draft_lower for op in openers) or openers[0] in draft_lower:
                return 1.0

        # Partial match — recognizable internet format but not a core template
        if any(
            pat in draft_lower for pat in [
                "real talk", "lowkey", "no but seriously", "the audacity",
                "okay so", "not gonna lie",
            ]
        ):
            return 0.60

        return 0.35   # No recognizable format — still passing minimum

    def _score_conversational_tone(self, draft: str) -> float:
        """
        Dimension 5 — conversational_tone (weight: 0.10).

        Evaluates: lowercase compliance, fragment use (short sentences),
        natural punctuation (ellipses, minimal commas), absence of polish.
        """
        score = 0.40   # base

        # Full lowercase compliance
        if draft == draft.lower():
            score += 0.30

        # Fragment style: shorter sentences score better
        sentences = [s.strip() for s in re.split(r"[.!?\n]", draft) if s.strip()]
        avg_len = sum(len(s) for s in sentences) / max(len(sentences), 1)
        if avg_len < 50:
            score += 0.20
        elif avg_len < 100:
            score += 0.10

        # Ellipses or em-dash — signals casual rhythm
        if "..." in draft or "—" in draft or "…" in draft:
            score += 0.10

        # Negative: ends with a period and a capital-letter opener nearby
        if draft.rstrip().endswith(".") and any(c.isupper() for c in draft[:20]):
            score -= 0.10

        return max(0.0, min(1.0, score))

    def _score_novelty(self, draft: str) -> float:
        """
        Dimension 6 — novelty_score (weight: 0.05).

        Heuristic: specificity of detail signals a fresh instantiation.
        Very generic examples score low; highly specific ones score high.

        This is the smallest-weight dimension, so it only acts as a tiebreaker.
        """
        specificity_hits = len(_SPECIFICITY_PATTERN.findall(draft))
        word_count = len(draft.split())

        # Unique phrasing density: specificity markers relative to word count
        if word_count > 0:
            density = specificity_hits / word_count
        else:
            density = 0.0

        if density >= 0.15:
            return 1.0
        if density >= 0.08:
            return 0.75
        if specificity_hits >= 1:
            return 0.55
        return 0.35

    # ── Composite computation ─────────────────────────────────────────────────

    @staticmethod
    def _compute_composite(dim_scores: dict[str, float]) -> float:
        """
        Weighted average of the 6 dimension scores.

        Uses DIMENSION_WEIGHTS from critic_prompts.py.
        Returns a float in [0.0, 1.0].
        """
        total = 0.0
        for name, score in dim_scores.items():
            weight = DIMENSION_WEIGHTS.get(name, 0.0)
            total += score * weight
        return round(min(1.0, max(0.0, total)), 4)

    # ── Convenience batch method ──────────────────────────────────────────────

    def critique_variants(
        self,
        variants: list[str],
    ) -> list[CritiqueScore]:
        """
        Critique a list of draft variants and return a CritiqueScore for each.

        Returned list has the same order as the input variants list.
        """
        return [self.pre_publish_critique(v) for v in variants]

    def select_best(
        self,
        variants: list[str],
    ) -> tuple[Optional[str], Optional[CritiqueScore]]:
        """
        Critique all variants and return (best_draft, best_score).

        Selects the variant with the highest composite score among those
        with is_approved=True.  If none are approved, returns (None, None).
        """
        scored = list(zip(variants, self.critique_variants(variants)))
        approved = [(draft, score) for draft, score in scored if score.is_approved]

        if not approved:
            return None, None

        best_draft, best_score = max(approved, key=lambda t: t[1].composite)
        return best_draft, best_score

    # ── Stub methods for Phase 8+ ─────────────────────────────────────────────
    # Defined here so the class matches the blueprint Section 5 spec.

    def post_publish_analysis(self, post: Any, metrics: Any) -> None:
        """Phase 8: run post-hoc analysis after metrics are collected."""
        logger.debug("[CriticAgent] post_publish_analysis deferred to Phase 8.")

    def generate_hypothesis(self, observation: str) -> str:
        """Phase 8: generate a testable hypothesis from an observation."""
        logger.debug("[CriticAgent] generate_hypothesis deferred to Phase 8.")
        return ""

    def generate_reflection(self, post: Any, metrics: Any) -> None:
        """Phase 8: generate a ReflectionNode for a post + metrics."""
        logger.debug("[CriticAgent] generate_reflection deferred to Phase 8.")

    def update_rules(self, reflection: Any) -> None:
        """Phase 8: update RuleNodes based on reflection learnings."""
        logger.info("[CriticAgent] Running update_rules() with reflection data.")
        if not self.memory or not reflection:
            return
            
        try:
            import sqlite3
            from datetime import datetime
            import uuid
            
            adjustments = reflection.get("trait_adjustments", {})
            with sqlite3.connect(self.memory.db_path) as conn:
                for trait_name, shift in adjustments.items():
                    try:
                        shift_val = float(shift)
                        conn.execute(
                            """
                            UPDATE personality_traits
                            SET value = MIN(1.0, MAX(0.0, value + ?)),
                                last_updated = ?
                            WHERE trait_name = ?
                            """,
                            (shift_val, datetime.now().isoformat(), trait_name)
                        )
                    except ValueError:
                        continue
                        
            lessons = reflection.get("new_rules", [])
            for rule in lessons:
                with sqlite3.connect(self.memory.db_path) as conn:
                    conn.execute(
                        """
                        INSERT INTO rules (id, rule_text, confidence, created_at, is_active)
                        VALUES (?, ?, 0.6, ?, 1)
                        """,
                        (str(uuid.uuid4()), rule, datetime.now().isoformat())
                    )
        except Exception as e:
            logger.error("[CriticAgent] Failed to update rules: %s", e)

    def decay_rules(self) -> None:
        """Phase 8: decay confidence on stale RuleNodes."""
        logger.info("[CriticAgent] Running decay_rules().")
        if not self.memory:
            return
            
        try:
            import sqlite3
            from datetime import datetime, timedelta
            now_iso = datetime.now() - timedelta(days=7)
            
            with sqlite3.connect(self.memory.db_path) as conn:
                conn.execute(
                    """
                    UPDATE rules
                    SET confidence = MAX(0.1, confidence - decay_rate)
                    WHERE last_validated IS NOT NULL 
                      AND last_validated < ?
                    """,
                    (now_iso.isoformat(),)
                )
                
                conn.execute(
                    """
                    UPDATE personality_traits
                    SET value = value + (0.5 - value) * 0.1
                    WHERE last_updated < ?
                    """,
                    (now_iso.isoformat(),)
                )
        except Exception as e:
            logger.error("[CriticAgent] Failed to decay rules: %s", e)

    def consolidate_memory(self) -> None:
        """Phase 8: consolidate memory during sleep mode."""
        logger.debug("[CriticAgent] consolidate_memory deferred to Phase 8.")

    def run_daily_reflection(self, recent_posts: list[dict]) -> dict:
        """
        Generate reflection using the REFLECTION_SYSTEM_PROMPT based on recent posts.
        Returns a parsed JSON dictionary containing trait adjustments and new rules.
        """
        if not self.llm_client:
            logger.warning("[CriticAgent] No LLM client available for reflection.")
            return {}
            
        try:
            from asomien.llm.prompts.reflection_prompts import REFLECTION_SYSTEM_PROMPT
            import json
            
            context_str = "\n".join([f"- Post: {p.get('content', '')} | Views: {p.get('views', 0)} | Likes: {p.get('likes', 0)} | Replies: {p.get('replies', 0)}" for p in recent_posts])
            user_prompt = (
                f"Recent posts:\n{context_str}\n\n"
                "Provide ONLY valid JSON. The JSON must have exactly this structure:\n"
                "{\n"
                '  "trait_adjustments": {"trait_name": 0.1},\n'
                '  "new_rules": ["rule 1", "rule 2"]\n'
                "}\n"
                "Do not include markdown blocks, trailing commas, or any other text."
            )
            
            response = self.llm_client.complete(
                system_prompt=REFLECTION_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                temperature=0.7,
                max_tokens=500
            )
            
            start_idx = response.find("{")
            end_idx = response.rfind("}")
            if start_idx != -1 and end_idx != -1:
                json_str = response[start_idx:end_idx+1]
                try:
                    return json.loads(json_str)
                except json.JSONDecodeError as jde:
                    logger.error("[CriticAgent] JSON Parse Error: %s. Raw LLM response: %s", jde, json_str)
                    return {}
            return {}
        except Exception as e:
            logger.error("[CriticAgent] Reflection failed: %s", e)
            return {}
