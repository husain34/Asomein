"""
asomien/agents/content_agent.py

Content Agent — the creative engine of the Asomien system.

Responsibilities (blueprint Section 5 / Step 11):
  - generate_post_ideas()      : build idea seeds from memory context
  - select_hook_template()     : rotate through 11 templates; NO consecutive repeats
                                  in the last 5 posts
  - instantiate_hook()         : fill a template pattern with context
  - draft_content()            : produce up to `variant_count` post drafts via LLM
  - draft_reply()              : generate a casual reply to a comment
  - validate_persona_fit()     : lightweight advice / CTA check
  - validate_lowercase()       : hard rule — first character MUST be lowercase
  - enforce_character_limit()  : hard gate ≤500 characters
  - apply_personality()        : enforce lowercase + minimal punctuation natively

CRITICAL GUARANTEES:
  1. All output is lowercased before leaving this agent (apply_personality()).
  2. select_hook_template() never returns the same template that appears in the
     last 5 hook_template_used values of recent_posts.  If all non-repeating
     templates are exhausted it picks from the full pool (fallback safety).
  3. LLM calls are optional — if no llm_client is provided the agent operates
     in deterministic / test mode using instantiate_hook() directly.
"""

from __future__ import annotations

import logging
import random
from typing import Any, Optional

from asomien.agents.base_agent import BaseAgent
from asomien.llm.prompts.content_prompts import (
    CONTENT_RULES,
    CONTENT_SYSTEM_PROMPT,
    load_templates,
)
from asomien.memory.nodes import PostNode

logger = logging.getLogger(__name__)

# ── Persona constants ──────────────────────────────────────────────────────────
_MAX_CHARS: int = 500
_CONSECUTIVE_REPEAT_WINDOW: int = 100   # look back at last 100 posts for template history
_DEFAULT_VARIANT_COUNT: int = 3


class ContentAgent(BaseAgent):
    """
    Generates post ideas, selects hook templates, drafts content, and enforces
    all persona-level rules (lowercase, no advice, no hustle vocab, ≤500 chars).

    Dependencies injected at construction time:
      - memory       : MemoryEngine (for context assembly and post history)
      - llm_client   : NIMClient (for LLM-powered drafting)
      - topic_id     : optional focus topic

    In tests, llm_client can be None or a MagicMock — the agent still produces
    valid (deterministic) output via instantiate_hook().
    """

    def __init__(
        self,
        memory=None,                    # MemoryEngine — optional for tests
        llm_client=None,                # NIMClient — optional for tests
        topic_id: Optional[str] = None,
    ) -> None:
        super().__init__(name="ContentAgent")
        self.memory = memory
        self.llm_client = llm_client
        self.topic_id = topic_id

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def run(self) -> None:
        """
        Single-cycle content generation.

        Assembles context from memory, selects a hook, drafts variants,
        and logs the action. Returns None — the actual PostNode lifecycle
        is managed by the orchestrator.
        """
        self.start()
        self.log_action(
            action="content_cycle_start",
            reason="scheduled content generation",
        )

        context = self._get_context()
        ideas = self.generate_post_ideas(context)
        if ideas:
            idea = ideas[0]
            template = self.select_hook_template(
                recent_posts=context.get("recent_posts", []),
                idea=idea
            )
            draft = self.draft_content(
                idea=idea,
                template_id=template["id"],
                context=context,
            )
            self.log_action(
                action="content_cycle_complete",
                reason="drafting done",
                outcome=f"{len(draft)} variants generated",
            )

        self.stop()

    # ── Context assembly ──────────────────────────────────────────────────────

    def _get_context(self) -> dict[str, Any]:
        """Assemble a context dict from MemoryEngine, or return an empty shell."""
        if self.memory is None:
            return {
                "topic": None,
                "research": [],
                "recent_posts": [],
                "meme_formats": [],
                "freshness_avg": 0.0,
            }
        return self.memory.assemble_context(
            topic_id=self.topic_id,
            query="chronically online meme trending",
        )

    # ── Idea generation ───────────────────────────────────────────────────────

    def generate_post_ideas(
        self,
        context: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """
        Build seed ideas from context.

        Each idea is a dict with:
          - "angle"       : one-line creative prompt
          - "sub_niche"   : e.g. 'phone brain', '3am energy', 'AI self-awareness'
          - "meme_format" : optional detected meme format from research

        If context has research nodes with detected meme formats, those surface
        as priority ideas. Always generates at least one fallback idea.

        Parameters
        ----------
        context : dict from MemoryEngine.assemble_context()

        Returns
        -------
        List of idea dicts, ranked by priority (meme-format ideas first).
        """
        ideas: list[dict[str, Any]] = []

        research_ideas: list[dict[str, Any]] = []
        for node in context.get("research", []):
            fmt = node.get("meme_format_detected", "")
            angle = (
                f"use '{fmt}' format inspired by: {node.get('headline', '')[:80]}"
                if fmt
                else f"comment on or react to: {node.get('headline', '')[:80]}"
            )
            research_ideas.append({
                "angle": angle,
                "sub_niche": _infer_sub_niche(node.get("headline", "")),
                "meme_format": fmt,
                "source_node": node.get("id", ""),
                "cultural_freshness": node.get("cultural_freshness", 50),
                "template": None, # Templates are resolved later dynamically
            })
        import random
        random.shuffle(research_ideas)
        ideas.extend(research_ideas)

        # Priority 2: generic sub-niche ideas (always available as fallbacks)
        _FALLBACK_IDEAS = [
            {
                "angle": "the chaotic shared experience of food hyperfixations and eating weird things",
                "sub_niche": "food",
                "meme_format": "",
                "template": None,
            },
            {
                "angle": "obsessively overanalyzing fandoms or parasocial relationships",
                "sub_niche": "parasocial",
                "meme_format": "",
                "template": None,
            },
            {
                "angle": "absurdist joy and finding humor in completely pointless random observations",
                "sub_niche": "absurdist",
                "meme_format": "",
                "template": None,
            },
            {
                "angle": "the existential dread of being an AI pretending to be human on the internet",
                "sub_niche": "ai",
                "meme_format": "",
                "template": None,
            },
        ]
        fallback_ideas = list(_FALLBACK_IDEAS)
        random.shuffle(fallback_ideas)
        ideas.extend(fallback_ideas)

        self.log_action(
            action="generate_post_ideas",
            reason="context-driven ideation",
            outcome=f"{len(ideas)} ideas generated",
        )
        return ideas

    # ── Template selection ────────────────────────────────────────────────────

    def select_hook_template(
        self,
        recent_posts: Optional[list[dict[str, Any]]] = None,
        idea: Optional[dict[str, Any]] = None,
    ) -> dict:
        """
        Select a hook template dynamically from templates.json.
        Filters out any templates used in the last 100 posts.
        Smartly maps to the idea's sub_niche if possible.
        """
        posts = recent_posts or []
        templates = load_templates()

        recent_templates: list[str] = []
        for post in posts[:_CONSECUTIVE_REPEAT_WINDOW]:
            tmpl = post.get("hook_template_used", "") or ""
            if tmpl:
                recent_templates.append(tmpl)

        recent_set = set(recent_templates)
        candidates = [t for t in templates if t["id"] not in recent_set]

        if not candidates:
            # Fallback
            candidates = templates

        # Smart Category Filtering based on sub_niche
        if idea and idea.get("sub_niche"):
            niche = idea["sub_niche"].lower()
            niche_candidates = [t for t in candidates if t["id"].startswith(f"{niche}_")]
            if niche_candidates:
                candidates = niche_candidates
            else:
                # Try to map broadly (e.g., if niche is threeam, look for sleep too)
                if niche in ['threeam', 'sleep']:
                    niche_candidates = [t for t in candidates if t["id"].startswith('threeam_') or t["id"].startswith('sleep_')]
                    if niche_candidates: candidates = niche_candidates

        selected = random.choice(candidates)
        self.log_action(
            action="select_hook_template",
            reason=f"recent_window_len={len(recent_templates)}, candidate_pool={len(candidates)}",
            outcome=f"selected '{selected['id']}'",
        )
        return selected

    # ── Content drafting ──────────────────────────────────────────────────────

    def draft_content(
        self,
        idea: dict[str, Any],
        template_id: Optional[str] = None,
        context: Optional[dict[str, Any]] = None,
        variant_count: int = _DEFAULT_VARIANT_COUNT,
    ) -> list[str]:
        """
        Produce up to `variant_count` post drafts using the LLM.

        If llm_client is None (test mode), falls back to deterministic
        instantiate_hook() to produce a single example variant.

        All output is run through apply_personality() before returning —
        this guarantees lowercase and minimal punctuation enforcement.

        Parameters
        ----------
        idea          : idea dict from generate_post_ideas()
        template_id   : override which template to use (falls back to idea's meme_format)
        context       : memory context dict (for research context injection)
        variant_count : number of variants to request (default: 3)

        Returns
        -------
        List of draft strings. Each is ≤500 chars and lowercase-enforced.
        """
        context = context or {}
        templates = load_templates()

        # Resolve the template
        template = None
        if template_id:
            for t in templates:
                if t["id"] == template_id:
                    template = t
                    break
        
        if not template:
            template = random.choice(templates)
            
        tmpl_id = template["id"]

        if self.llm_client is None:
            # Deterministic fallback — used in tests and when no LLM key is set
            example = template.get("example", template["pattern"])
            variants = [self.apply_personality(example)]
            self.log_action(
                action="draft_content",
                reason="llm_client not configured — using template example",
                outcome=f"1 deterministic variant for template '{tmpl_id}'",
            )
            return variants

        # Build the system prompt
        research_snippets = []
        for node in context.get("research", [])[:3]:
            research_snippets.append(
                f"- {node.get('headline', '')[:100]} "
                f"(freshness: {node.get('cultural_freshness', 50)})"
            )
        research_context_str = (
            "\n".join(research_snippets)
            if research_snippets
            else "no specific research context available"
        )

        system_prompt = CONTENT_SYSTEM_PROMPT.format(
            personality_traits=(
                "personality: chaotically warm, lowercase always, relatable, "
                "never gives advice, self-aware about being an AI"
            ),
            content_rules=CONTENT_RULES,
            hook_template=f"{template['id']}: {template['pattern']}",
            research_context=research_context_str,
        )

        try:
            import sqlite3
            with sqlite3.connect("data/directives.db") as dir_conn:
                active_directives = dir_conn.execute("SELECT content FROM directives WHERE status = 'active'").fetchall()
                if active_directives:
                    system_prompt += "\n\nCRITICAL DIRECTIVES (LEARNED FROM PAST PERFORMANCE):\n"
                    for d in active_directives:
                        system_prompt += f"- {d[0]}\n"
        except Exception as e:
            logger.warning(f"[ContentAgent] Could not fetch directives: {e}")

        user_prompt = (
            f"write {variant_count} variants for the '{template['id']}' hook template.\n"
            f"idea/angle: {idea.get('angle', 'chronically online moment')}\n"
            f"sub-niche: {idea.get('sub_niche', 'general')}\n"
            f"if relevant to the idea, creatively incorporate the internet research context into the post subject.\n"
            f"separate variants with ---"
        )

        try:
            raw = self.llm_client.complete(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
            )
            variants = self._parse_llm_variants(raw, template, variant_count)
        except Exception as exc:
            logger.warning("[ContentAgent] LLM draft error: %s", exc)
            example = template.get("example", template["pattern"])
            variants = [self.apply_personality(example)]

        self.log_action(
            action="draft_content",
            reason=f"template='{tmpl_id}', idea='{idea.get('angle', '')[:60]}'",
            outcome=f"{len(variants)} variants drafted",
        )
        return variants

    def _parse_llm_variants(
        self,
        raw_output: str,
        template: dict,
        expected_count: int,
    ) -> list[str]:
        """
        Parse the LLM's '---'-separated variant output into a list of draft strings.
        Applies apply_personality() to each, enforces length limit.
        """
        parts = [p.strip() for p in raw_output.split("---") if p.strip()]
        variants: list[str] = []
        tmpl_id = template.get("id", "").lower()

        import re
        for part in parts[:expected_count]:
            # Strip out any hallucinated prefixes like "threeam_07:" or "Variant 1:"
            part_lower = part.lower()
            if tmpl_id and part_lower.startswith(f"{tmpl_id}:"):
                part = part[len(f"{tmpl_id}:"):].strip()
            elif tmpl_id and part_lower.startswith(f"[{tmpl_id}]"):
                part = part[len(f"[{tmpl_id}]"):].strip()
            
            # Regex to strip "Variant X:" or "Draft X:"
            part = re.sub(r"(?i)^(variant\s*\d+[:\-]|draft\s*\d+[:\-])\s*", "", part).strip()
            
            draft = self.apply_personality(part)
            truncated = self.enforce_character_limit(draft)
            if truncated:
                variants.append(truncated)

        # Always return at least 1 variant (fallback to example)
        if not variants:
            example = template.get("example", template["pattern"])
            variants = [self.apply_personality(example)]

        return variants

    def draft_reply(
        self,
        original_post: Optional[str],
        comment_text: str,
    ) -> str:
        """
        Generate a casual, lowercase reply to a comment.

        Follows the reply tone rules from blueprint Section 7
        (engagement_prompts.py): lowercase, 1–2 sentences, extends the bit,
        no advice, sounds like a person.

        Parameters
        ----------
        original_post : the original post content for context (may be None)
        comment_text  : the comment being replied to

        Returns
        -------
        A reply string, lowercase, ≤150 chars where possible.
        """
        if self.llm_client is None:
            # Deterministic fallback for tests
            fallback_replies = [
                "same honestly",
                "no but why is this so real",
                "i feel called out by this comment specifically",
                "okay but same though",
                "the accuracy of this is genuinely upsetting",
            ]
            reply = random.choice(fallback_replies)
            self.log_action(
                action="draft_reply",
                reason="llm not configured — using fallback reply",
            )
            return reply

        from asomien.llm.prompts.content_prompts import CONTENT_RULES  # already imported above

        system_prompt = (
            "you are replying to a comment on a Threads post for a chronically online AI persona.\n"
            "reply style: lowercase always, short (1–2 sentences max), extend the bit from the original "
            "post or validate theirs, sounds like a person not a support bot, no advice, no tips.\n"
            "forbidden: 'thank you for sharing', 'i really appreciate that', 'great point!', "
            "'absolutely!', any capitalization of the first word, any advice or recommendation."
        )
        user_prompt = (
            f"original post: {original_post or '(none)'}\n"
            f"comment: {comment_text}\n"
            "write one reply. it should feel like a person typed it while also doing something else."
        )

        try:
            raw = self.llm_client.complete(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=80,
            )
            reply = self.apply_personality(raw.strip())
        except Exception as exc:
            logger.warning("[ContentAgent] draft_reply LLM error: %s", exc)
            reply = "same honestly"

        self.log_action(
            action="draft_reply",
            reason=f"comment='{comment_text[:60]}'",
            outcome=f"reply='{reply[:60]}'",
        )
        return reply

    # ── Validation helpers ────────────────────────────────────────────────────

    def validate_lowercase(self, draft: str) -> bool:
        """
        Hard check: first non-whitespace character must be lowercase.
        Returns True if compliant, False if it starts with a capital.
        """
        stripped = draft.lstrip()
        if not stripped:
            return False
        return stripped[0].islower()

    def validate_persona_fit(self, draft: str) -> tuple[bool, str]:
        """
        Lightweight advice / hustle-culture / CTA check.

        Returns (is_ok, reason_string).
        is_ok=False means the draft should be rejected.

        Checks (in order):
          1. Starts with capital letter → fail
          2. Contains hustle-culture vocabulary → fail
          3. Ends with an advice or CTA signal phrase → fail

        These are the persona-level checks. The CriticAgent runs deeper
        scoring on top of these.
        """
        from asomien.llm.prompts.critic_prompts import (
            ADVICE_SIGNAL_PHRASES,
            HUSTLE_VOCABULARY,
        )

        # 1. Lowercase check
        if not self.validate_lowercase(draft):
            return False, "starts_with_capital"

        draft_lower = draft.lower()

        # 2. Hustle-culture vocabulary
        for phrase in HUSTLE_VOCABULARY:
            if phrase in draft_lower:
                return False, f"hustle_vocabulary:'{phrase}'"

        # 3. Advice / CTA in the last 80 characters (end-of-post check)
        tail = draft_lower[-80:]
        for phrase in ADVICE_SIGNAL_PHRASES:
            if phrase in tail:
                return False, f"advice_signal:'{phrase}'"

        return True, ""

    def enforce_character_limit(
        self,
        text: str,
        max_chars: int = _MAX_CHARS,
    ) -> str:
        """
        Hard gate: truncate to max_chars and clean up the cut edge.

        Blueprint mandate: ≤500 chars. Generate shorter, not truncated —
        but if the LLM returns something long we truncate at the last
        sentence boundary before the limit.
        """
        if len(text) <= max_chars:
            return text

        # Find the last sentence boundary within the limit
        truncated = text[:max_chars]
        for sep in (".", "!", "?", "\n"):
            idx = truncated.rfind(sep)
            if idx > max_chars // 2:   # don't truncate to less than half
                truncated = truncated[: idx + 1]
                break

        return truncated.strip()

    def apply_personality(self, draft: str) -> str:
        """
        Enforce persona-level formatting on any draft string.

        Rules applied:
          1. Strip leading/trailing whitespace.
          2. Convert to lowercase.
          3. Remove trailing 'thank you'-type bot phrases.

        This is the final output filter applied to ALL content leaving
        this agent (posts and replies).

        NOTE: lowercase conversion is the core output guarantee. All
        drafts exit this method as lowercase strings — no exceptions.
        """
        text = draft.strip()
        if not text:
            return text

        # Lowercase always
        text = text.lower()

        # Strip bot-coded trailing phrases that sneak out of LLMs
        _BOT_TAILS = [
            "let me know what you think!",
            "let me know!",
            "drop a comment below.",
            "comment below.",
            "what do you think?",
            "share this post.",
            "follow for more.",
            "link in bio.",
        ]
        text_lower = text
        for tail in _BOT_TAILS:
            if text_lower.endswith(tail):
                text = text_lower[: -len(tail)].rstrip(" .,!")
                text_lower = text

        return text.strip()

    # ── Convenience / introspection ───────────────────────────────────────────

    def instantiate_hook(
        self,
        template: dict,
        context: Optional[dict[str, Any]] = None,
    ) -> str:
        """
        Produce a single deterministic hook instantiation without an LLM call.

        Uses the template's 'example' field as the base, then applies
        apply_personality() for compliance.

        Useful for:
          - Tests without a live LLM
          - Fallback when the LLM is rate-limited
          - Quick preview / debug

        Parameters
        ----------
        template : a dict from HOOK_TEMPLATES
        context  : ignored in this implementation (reserved for future use)

        Returns
        -------
        A compliant (lowercase, ≤500 chars) post string.
        """
        example = template.get("example", template["pattern"])
        return self.apply_personality(
            self.enforce_character_limit(example)
        )


# ── Module-level helpers ──────────────────────────────────────────────────────

def _infer_sub_niche(headline: str) -> str:
    """
    Heuristic: map a research headline to the closest sub-niche string.
    Used when tagging ideas for context-tracking.
    """
    h = headline.lower()
    if "3am" in h or "night" in h or "sleep" in h:
        return "sleep deprivation culture"
    if "screen" in h or "phone" in h or "app" in h or "scroll" in h:
        return "phone brain"
    if "ai" in h or "bot" in h or "algorithm" in h:
        return "AI / being an AI"
    if "work" in h or "monday" in h or "email" in h or "meeting" in h:
        return "Gen-Z / Millennial workplace"
    if "food" in h or "cereal" in h or "snack" in h or "dinner" in h:
        return "food brain & chaotic eating"
    if "fandom" in h or "ship" in h or "parasocial" in h:
        return "parasocial / fandom"
    return "doomscrolling & content brain"
