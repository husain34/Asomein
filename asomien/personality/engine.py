"""
asomien/personality/engine.py

Personality Engine — Phase 2 implementation.

Loads the persona from asomien/config/personality_seed.json and provides
apply_to_prompt(), which injects the persona's voice and hard rules into
every system prompt before it is sent to the LLM.

Key enforcement (non-negotiable, from blueprint):
  1. lowercase_always   — the writing_rules.case rule is injected as an
                          *explicit, numbered directive* so the LLM cannot miss it.
  2. advice_aversion    — the core trait with value=1.00 is surfaced as a
                          hard instruction: giving advice is categorically banned.

Both rules are injected aggressively — they appear at the top of the generated
system block AND again in a dedicated "Hard Rules" section at the bottom.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ── Default seed path ─────────────────────────────────────────────────────────
_DEFAULT_SEED_PATH = Path("asomien/config/personality_seed.json")


class PersonalityEngine:
    """
    Loads personality_seed.json and stamps every outgoing system prompt with
    asomien's voice, hard rules, and trait values.

    Usage
    -----
        engine = PersonalityEngine()
        system_prompt = engine.apply_to_prompt("generate a post about phone brain")

    The returned string is a complete system prompt ready to pass to the LLM.
    """

    def __init__(self, seed_path: Optional[str | Path] = None) -> None:
        """
        Load the personality seed from disk.

        Parameters
        ----------
        seed_path : optional path override (default: asomien/config/personality_seed.json)
        """
        self._seed_path = Path(seed_path) if seed_path else _DEFAULT_SEED_PATH
        self._seed: dict[str, Any] = self._load_seed(self._seed_path)

        # Pre-parse frequently accessed sections for performance
        self._writing_rules: dict[str, Any] = self._seed.get("writing_rules", {})
        self._core_traits: list[dict[str, Any]] = self._deduplicate_traits(self._seed.get("core_traits", []))
        self._adaptive_traits: list[dict[str, Any]] = self._deduplicate_traits(self._seed.get("adaptive_traits", []))
        self._example_approved: list[str] = self._seed.get("example_approved_posts", [])
        self._example_rejected: list[str] = self._seed.get("example_rejected_posts", [])

        # Cache the two hard-enforced traits by name for O(1) lookup
        self._advice_aversion_value: float = self._get_trait_value("advice_aversion")
        self._chaos_warmth_value: float = self._get_trait_value("chaos_warmth_balance")

        logger.info(
            "[PersonalityEngine] Loaded seed for persona '%s' from %s",
            self._seed.get("persona_name", "unknown"),
            self._seed_path,
        )

    # ── Loader ────────────────────────────────────────────────────────────────

    @staticmethod
    def _load_seed(path: Path) -> dict[str, Any]:
        """
        Read and parse personality_seed.json.
        Raises FileNotFoundError / json.JSONDecodeError on invalid input.
        """
        if not path.exists():
            raise FileNotFoundError(
                f"[PersonalityEngine] personality_seed.json not found at: {path}. "
                "Run Phase 1 migrations or check your working directory."
            )
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data

    # ── Trait helpers ─────────────────────────────────────────────────────────

    def _get_trait_value(self, trait_name: str) -> float:
        """
        Return the numeric value of a named trait from core_traits or adaptive_traits.
        Returns 0.0 if the trait is not found.
        """
        all_traits = self._core_traits + self._adaptive_traits
        for trait in all_traits:
            if trait.get("trait_name") == trait_name:
                return float(trait.get("value", 0.0))
        return 0.0

    def get_trait(self, trait_name: str) -> Optional[dict[str, Any]]:
        """
        Return the full trait dict for a named trait, or None if not found.
        Searches both core_traits and adaptive_traits.
        """
        all_traits = self._core_traits + self._adaptive_traits
        for trait in all_traits:
            if trait.get("trait_name") == trait_name:
                return trait
        return None

    def _is_trait_duplicate(self, new_trait: dict[str, Any], existing_traits: list[dict[str, Any]]) -> bool:
        """
        Check if new_trait is a duplicate of any trait in existing_traits.
        Duplicate if:
          - same trait_name (normalized exact match or difflib similarity >= 0.75) OR
          - description similarity (cosine) >= 0.85
        """
        import difflib

        new_name_raw = new_trait.get("trait_name", "").strip().lower()
        new_name_norm = new_name_raw.replace("_", " ").replace("-", " ")
        new_desc = new_trait.get("description", "").strip()

        # If the new trait has no name, we cannot check by name, but we can still check by description?
        # However, a trait without a name is invalid. We'll treat it as duplicate if description is similar?
        # But let's assume the trait must have a name and description.

        for trait in existing_traits:
            exist_name_raw = trait.get("trait_name", "").strip().lower()
            exist_name_norm = exist_name_raw.replace("_", " ").replace("-", " ")
            exist_desc = trait.get("description", "").strip()

            # Check by name (normalized exact match or high similarity)
            if new_name_norm and exist_name_norm:
                if new_name_norm == exist_name_norm:
                    return True
                if difflib.SequenceMatcher(None, new_name_norm, exist_name_norm).ratio() >= 0.75:
                    return True

            # Check by description similarity (only if both descriptions are non-empty)
            if new_desc and exist_desc:
                try:
                    from sklearn.feature_extraction.text import TfidfVectorizer
                    from sklearn.metrics.pairwise import cosine_similarity
                except ImportError:
                    # If sklearn is not available, we skip description similarity check.
                    # In production, we should have sklearn, but for safety we skip.
                    continue

                # Vectorize the two descriptions
                vectorizer = TfidfVectorizer()
                try:
                    tfidf_matrix = vectorizer.fit_transform([new_desc, exist_desc])
                    similarity = cosine_similarity(tfidf_matrix[0:1], tfidf_matrix[1:2])[0][0]
                except ValueError:
                    # This can happen if the vocabulary is empty (e.g., both descriptions are empty strings)
                    similarity = 0.0

                if similarity >= 0.85:
                    return True

        return False

    def _deduplicate_traits(self, traits: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Remove duplicate traits based on trait_name and description similarity.
        Keeps the first occurrence.
        """
        unique_traits = []
        for trait in traits:
            if not self._is_trait_duplicate(trait, unique_traits):
                unique_traits.append(trait)
        return unique_traits

    def add_trait(self, trait: dict[str, Any]) -> bool:
        """
        Add a new trait to the appropriate list (core or adaptive) if it's not a duplicate.

        Args:
            trait: Dictionary containing trait_name, trait_type, value, and description

        Returns:
            bool: True if trait was added, False if it was considered a duplicate
        """
        # Validate trait has required fields
        if not isinstance(trait, dict):
            logger.warning("[PersonalityEngine] Invalid trait format: must be a dictionary")
            return False

        trait_name = trait.get("trait_name")
        trait_type = trait.get("trait_type")

        if not trait_name or not trait_type:
            logger.warning("[PersonalityEngine] Trait must have trait_name and trait_type")
            return False

        # Determine which list to check and add to
        if trait_type == "core":
            existing_traits = self._core_traits
            target_list = self._core_traits
        elif trait_type == "adaptive":
            existing_traits = self._adaptive_traits
            target_list = self._adaptive_traits
        else:
            logger.warning(f"[PersonalityEngine] Unknown trait_type: {trait_type}. Must be 'core' or 'adaptive'")
            return False

        # Check for duplicates
        if self._is_trait_duplicate(trait, existing_traits):
            logger.info(f"[PersonalityEngine] Trait '{trait_name}' is considered a duplicate and was not added")
            return False

        # Add the trait
        target_list.append(trait)
        logger.info(f"[PersonalityEngine] Added new {trait_type} trait: '{trait_name}'")
        return True

    # ── apply_to_prompt() ─────────────────────────────────────────────────────

    def apply_to_prompt(self, user_instruction: str) -> str:
        """
        Build and return a complete LLM system prompt that aggressively stamps
        asomien's personality onto the user_instruction.

        The prompt structure:
          1. Identity block        — who asomien is
          2. ⚡ CRITICAL RULES     — lowercase_always + advice_aversion injected
                                     at the very top, with extreme emphasis
          3. Voice rules           — all writing_rules from the seed
          4. Trait values          — all core + adaptive traits
          5. Examples              — approved and rejected posts
          6. Task                  — the actual user_instruction
          7. ⚡ HARD RULES RECAP   — lowercase_always + advice_aversion repeated
                                     at the bottom (belt-and-suspenders enforcement)

        Parameters
        ----------
        user_instruction : the content generation or processing task

        Returns
        -------
        A multi-line string ready to pass as the `system` argument to the LLM.
        """
        persona_name = self._seed.get("persona_name", "asomien")
        tagline = self._seed.get("persona_tagline", "")
        voice_description = self._seed.get("voice_description", "")

        lines: list[str] = []

        # ── 1. Identity ───────────────────────────────────────────────────────
        lines += [
            f"# SYSTEM: {persona_name.upper()} PERSONALITY ENGINE",
            "",
            f"You are **{persona_name}** — {tagline}.",
            f"Voice: {voice_description}",
            "",
        ]

        # ── 2. ⚡ CRITICAL RULES (top of prompt — maximum LLM attention) ──────
        lines += [
            "=" * 72,
            "⚡ CRITICAL RULES — THESE ARE NON-NEGOTIABLE AND MUST NEVER BE VIOLATED",
            "=" * 72,
            "",
            "RULE 1 — LOWERCASE ALWAYS (case: lowercase_always)",
            "  • Every single character of every post MUST be lowercase.",
            "  • No capital letters. No title case. No sentence case.",
            "  • This applies to the first word, every word, proper nouns, the letter 'I'.",
            "  • A post that begins with a capital letter is AUTOMATICALLY REJECTED.",
            "  • There are NO exceptions. Not even for names. Not even for acronyms.",
            "",
            "RULE 2 — ADVICE AVERSION (advice_aversion = 1.00 — HARD ZERO)",
            "  • This persona NEVER gives advice. EVER. Under ANY framing.",
            "  • Do not suggest. Do not recommend. Do not instruct. Do not guide.",
            "  • Posts that end in advice, tips, or calls to action are REJECTED.",
            "  • Validate the experience. Do NOT fix it. Do NOT offer solutions.",
            "  • If a post sounds like it's 'helping', it is wrong. Rewrite it.",
            "",
            "=" * 72,
            "",
        ]

        # ── 3. Voice rules ────────────────────────────────────────────────────
        lines += ["## Writing Rules", ""]

        case_rule = self._writing_rules.get("case", "lowercase_always")
        lines.append(f"- **Case**: {case_rule} (ENFORCED — see Rule 1 above)")

        punctuation = self._writing_rules.get("punctuation", "")
        if punctuation:
            lines.append(f"- **Punctuation**: {punctuation}")

        emoji_policy = self._writing_rules.get("emoji_policy", "")
        if emoji_policy:
            lines.append(f"- **Emoji policy**: {emoji_policy}")

        sentence_length = self._writing_rules.get("sentence_length", "")
        if sentence_length:
            lines.append(f"- **Sentence length**: {sentence_length}")

        # Forbidden openers
        forbidden_openers = self._writing_rules.get("forbidden_openers", [])
        if forbidden_openers:
            openers_str = ", ".join(f'"{o}"' for o in forbidden_openers)
            lines.append(f"- **Forbidden openers**: {openers_str}")

        # Forbidden phrases
        forbidden_phrases = self._writing_rules.get("forbidden_phrases", [])
        if forbidden_phrases:
            phrases_str = ", ".join(f'"{p}"' for p in forbidden_phrases)
            lines.append(f"- **Forbidden phrases**: {phrases_str}")

        # Voice notes
        voice_notes = self._writing_rules.get("voice_notes", [])
        if voice_notes:
            lines.append("- **Voice notes**:")
            for note in voice_notes:
                lines.append(f"  • {note}")

        lines.append("")

        # ── 4. Trait values ───────────────────────────────────────────────────
        lines += ["## Personality Trait Values", ""]

        for trait in self._core_traits:
            name = trait.get("trait_name", "unknown")
            value = trait.get("value", 0.0)
            description = trait.get("description", "")
            emphasis = " ← HARD ZERO: NEVER VIOLATED" if value == 1.00 else ""
            lines.append(f"- **{name}** = {value}{emphasis}")
            if description:
                lines.append(f"  {description}")

        lines.append("")
        lines.append("### Adaptive Traits")

        for trait in self._adaptive_traits:
            name = trait.get("trait_name", "unknown")
            value = trait.get("value", 0.0)
            description = trait.get("description", "")
            lines.append(f"- **{name}** = {value}")
            if description:
                lines.append(f"  {description}")

        lines.append("")

        # ── 5. Examples ───────────────────────────────────────────────────────
        if self._example_approved:
            lines += ["## ✅ Approved Post Examples", ""]
            for ex in self._example_approved[:3]:  # cap at 3 to keep prompt tight
                lines.append(f'  ✓ "{ex}"')
            lines.append("")

        if self._example_rejected:
            lines += ["## ❌ Rejected Post Examples (DO NOT write like these)", ""]
            for ex in self._example_rejected[:3]:
                lines.append(f'  ✗ "{ex}"')
            lines.append("")

        # ── 6. Task ───────────────────────────────────────────────────────────
        lines += [
            "## Your Task",
            "",
            user_instruction,
            "",
        ]

        # ── 7. ⚡ Hard rules recap (belt-and-suspenders at bottom) ────────────
        lines += [
            "=" * 72,
            "⚡ FINAL HARD RULES CHECK — before you output ANYTHING:",
            "=" * 72,
            "",
            "  [LOWERCASE CHECK]  Does every character start lowercase? (Rule 1)",
            "    → If the first character is uppercase: REWRITE. No exceptions.",
            "    → 'I' must be 'i'. 'Monday' must be 'monday'. Always.",
            "",
            "  [ADVICE CHECK]     Does the post give advice, tips, or instructions? (Rule 2)",
            "    → If yes: REWRITE. Validate. Do not fix. Do not suggest.",
            "    → Ending in a question is fine. Ending in a tip is not.",
            "",
            "Only output if BOTH checks pass.",
            "=" * 72,
        ]

        return "\n".join(lines)

    # ── Public accessors ──────────────────────────────────────────────────────

    @property
    def persona_name(self) -> str:
        return self._seed.get("persona_name", "asomien")

    @property
    def writing_rules(self) -> dict[str, Any]:
        return dict(self._writing_rules)

    @property
    def core_traits(self) -> list[dict[str, Any]]:
        return list(self._core_traits)

    @property
    def adaptive_traits(self) -> list[dict[str, Any]]:
        return list(self._adaptive_traits)

    @property
    def forbidden_phrases(self) -> list[str]:
        return list(self._writing_rules.get("forbidden_phrases", []))

    @property
    def forbidden_openers(self) -> list[str]:
        return list(self._writing_rules.get("forbidden_openers", []))

    def is_lowercase_compliant(self, text: str) -> bool:
        """
        Returns True if the text's first non-whitespace character is lowercase.
        This mirrors PostNode.is_lowercase_compliant for use in prompt validation.
        """
        stripped = text.lstrip()
        return bool(stripped) and stripped[0].islower()

    def contains_advice(self, text: str) -> bool:
        """
        Heuristic check: returns True if the text appears to give advice.
        Checks against known advice-pattern phrases from the forbidden list.
        This is a lightweight guard; full advice detection is in the CriticAgent.
        """
        advice_signals = [
            "you need to", "you should", "here's how", "try this",
            "start doing", "stop doing", "make sure", "remember to",
            "don't forget", "tip:", "tips:", "step 1", "how to",
        ]
        lower_text = text.lower()
        return any(signal in lower_text for signal in advice_signals)
