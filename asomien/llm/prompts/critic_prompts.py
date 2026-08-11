"""
asomien/llm/prompts/critic_prompts.py

Pre-publish critic prompt constants: the 6 scoring dimensions, their weights,
hard-gate rejection rules, and minimum score thresholds.

These are the exact definitions from Section 7 / critic_prompts.py in the blueprint.
CriticAgent imports these and implements the scoring logic.
"""

from __future__ import annotations

# ── Scoring Dimensions ────────────────────────────────────────────────────────
# (name, weight, description)
# Weights sum to exactly 1.00.
CRITIQUE_DIMENSIONS: list[tuple[str, float, str]] = [
    (
        "hook_strength",
        0.30,
        "Does the first line stop a scroll? Is there specificity and curiosity?",
    ),
    (
        "reply_bait_score",
        0.25,
        "Will this generate 'same', 'wait why', 'okay but', or completion replies?",
    ),
    (
        "persona_authenticity",
        0.20,
        "Does this sound like the account? Not a brand, not a productivity bot.",
    ),
    (
        "format_recognition",
        0.10,
        "Is a known meme format used correctly and freshly?",
    ),
    (
        "conversational_tone",
        0.10,
        "Lowercase, fragments, natural. Not polished. Not a caption.",
    ),
    (
        "novelty_score",
        0.05,
        "Fresh angle or clever instantiation of a familiar format?",
    ),
]

# Dimension name → weight lookup (used by CriticAgent._compute_composite())
DIMENSION_WEIGHTS: dict[str, float] = {name: weight for name, weight, _ in CRITIQUE_DIMENSIONS}

# ── Hard-Gate Failure Rules ───────────────────────────────────────────────────
# Any one of these → immediate rejection before scoring.
HARD_REJECTION_RULES = """
REJECT IMMEDIATELY if any of the following are true:

- POST STARTS WITH A CAPITAL LETTER: persona types in lowercase always
- POST CONTAINS ADVICE OR TIPS: this persona validates, it does not fix
- POST CONTAINS HUSTLE-CULTURE VOCABULARY: productivity, optimize, discipline,
  mindset, grind, hustle, manifest, morning routine, level up (sincere usage)
- POST IS OVER 500 CHARACTERS: hard character limit
- PROMOTIONAL TONE SCORE > 0.30: this account does not sell things
- POST SOUNDS LIKE A BRAND: if it could be posted by a company, reject it
- POST ENDS IN A CALL-TO-ACTION: no 'check this out', 'link in bio', 'follow for more'
"""

# ── Hustle-culture vocabulary blocklist (used by hard-gate keyword check) ─────
HUSTLE_VOCABULARY: list[str] = [
    "hustle",
    "grind",
    "optimize",
    "productivity",
    "discipline",
    "mindset",
    "manifest",
    "morning routine",
    "10x",
    "rise and grind",
    "level up",
    "you need to",
    "you should",
    "here's how",
]

# ── Advice / CTA signal phrases ───────────────────────────────────────────────
# Any of these at the end of a post signal advice or call-to-action.
ADVICE_SIGNAL_PHRASES: list[str] = [
    "try this",
    "do this",
    "start doing",
    "stop doing",
    "here's how",
    "here are",
    "tips for",
    "tip:",
    "advice:",
    "pro tip",
    "you should",
    "you need to",
    "follow for",
    "link in bio",
    "check this out",
    "click",
    "subscribe",
    "save this",
    "share this",
    "let me know",
    "drop a comment",
    "tell me in the comments",
    "what do you think",
    "comment below",
    "repost if",
]

# ── Score thresholds ──────────────────────────────────────────────────────────
MINIMUM_COMPOSITE_SCORE: float = 0.54    # composite below this → reject (was 0.58, lowered because all variants were being rejected every cycle)
MINIMUM_SINGLE_DIMENSION: float = 0.25   # any single dimension below this → reject (was 0.28)
MAX_CHARACTERS: int = 500
