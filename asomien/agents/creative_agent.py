"""
asomien/agents/creative_agent.py

Creative Agent — acts as a Gen-Z editor to refine drafts produced by the ContentAgent.
"""

from __future__ import annotations

import logging
import random
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Optional

from asomien.agents.base_agent import BaseAgent
from asomien.llm.prompts.creative_prompts import (
    CREATIVE_EDITOR_SYSTEM_PROMPT,
    SEEDED_CREATIVE_RULES,
)

logger = logging.getLogger(__name__)

class CreativeAgent(BaseAgent):
    """
    Takes raw drafts from ContentAgent and refines them to be funnier,
    more sarcastic, and logically coherent while maintaining the Gen-Z persona.
    """

    def __init__(self, memory=None, llm_client=None) -> None:
        super().__init__(name="CreativeAgent")
        self.memory = memory
        self.llm_client = llm_client
        self._seed_rules_if_empty()

    def _seed_rules_if_empty(self) -> None:
        """Seed initial creative rules if the table is empty."""
        if not self.memory:
            return
        try:
            with sqlite3.connect(self.memory.db_path) as conn:
                cursor = conn.execute("SELECT COUNT(*) FROM creative_rules")
                count = cursor.fetchone()[0]
                if count == 0:
                    logger.info("[CreativeAgent] Seeding initial creative rules.")
                    for rule in SEEDED_CREATIVE_RULES:
                        conn.execute(
                            """
                            INSERT INTO creative_rules (id, rule_text, confidence, created_at, is_active)
                            VALUES (?, ?, 0.8, ?, 1)
                            """,
                            # FIX BUG-08: Use timezone-aware UTC datetime.
                            (str(uuid.uuid4()), rule, datetime.now(timezone.utc).isoformat())
                        )
        except Exception as e:
            logger.error("[CreativeAgent] Failed to seed rules: %s", e)

    def run(self) -> None:
        """No autonomous loop for this agent, called synchronously by Orchestrator."""
        pass

    def get_active_rules(self) -> list[str]:
        """Fetch active creative rules from memory."""
        if not self.memory:
            return SEEDED_CREATIVE_RULES
            
        try:
            with sqlite3.connect(self.memory.db_path) as conn:
                cursor = conn.execute(
                    "SELECT rule_text FROM creative_rules WHERE is_active = 1 ORDER BY confidence DESC LIMIT 10"
                )
                rules = [row[0] for row in cursor.fetchall()]
                if not rules:
                    return SEEDED_CREATIVE_RULES
                return rules
        except Exception as e:
            logger.error("[CreativeAgent] Failed to fetch creative rules: %s", e)
            return SEEDED_CREATIVE_RULES

    def refine_draft(self, draft: str) -> str:
        """
        Passes a draft to the LLM to rewrite it according to creative rules.
        """
        if not self.llm_client:
            logger.info("[CreativeAgent] No LLM client. Passing draft through unedited.")
            return draft

        rules = self.get_active_rules()
        rules_str = "\n".join([f"- {r}" for r in rules])
        
        system_prompt = CREATIVE_EDITOR_SYSTEM_PROMPT.format(editing_rules=rules_str)
        user_prompt = f"Here is the raw draft:\n{draft}\n\nRewrite this to be funnier, more sarcastic, and make sense. Keep the core idea. Return ONLY the final text."

        try:
            raw = self.llm_client.complete(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=0.8, # slightly higher temp for creativity
                max_tokens=150
            )
            # Clean up any potential LLM artifacts
            refined = raw.strip()
            # Enforce lowercase
            refined = refined.lower()
            
            self.log_action(
                action="refine_draft",
                reason="applying creative editor rules",
                outcome=f"Original length: {len(draft)} -> Refined length: {len(refined)}",
            )
            return refined
        except Exception as exc:
            logger.warning("[CreativeAgent] LLM edit error: %s", exc)
            return draft

    def update_rules(self, reflection: dict) -> None:
        """Update creative rules based on reflection learnings."""
        logger.info("[CreativeAgent] Updating rules with reflection data.")
        if not self.memory or not reflection:
            return
            
        try:
            lessons = reflection.get("new_rules", [])
            # FIX BUG-07: Open one connection for all rules (atomic, faster).
            # FIX BUG-08: Use timezone-aware UTC datetime.
            with sqlite3.connect(self.memory.db_path) as conn:
                for rule in lessons:
                    conn.execute(
                        """
                        INSERT INTO creative_rules (id, rule_text, confidence, created_at, is_active)
                        VALUES (?, ?, 0.6, ?, 1)
                        """,
                        (str(uuid.uuid4()), rule, datetime.now(timezone.utc).isoformat())
                    )
        except Exception as e:
            logger.error("[CreativeAgent] Failed to update creative rules: %s", e)

    def decay_rules(self) -> None:
        """Decay confidence on stale creative rules."""
        logger.info("[CreativeAgent] Running decay_rules().")
        if not self.memory:
            return
            
        try:
            from datetime import timedelta
            # FIX BUG-06: Use timezone-aware UTC datetime so the comparison
            # against stored UTC ISO strings works correctly.
            cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()

            with sqlite3.connect(self.memory.db_path) as conn:
                conn.execute(
                    """
                    UPDATE creative_rules
                    SET confidence = MAX(0.1, confidence - decay_rate)
                    WHERE last_validated IS NOT NULL
                      AND last_validated < ?
                    """,
                    (cutoff,)
                )
        except Exception as e:
            logger.error("[CreativeAgent] Failed to decay creative rules: %s", e)

    def run_creative_reflection(self, recent_posts: list[dict]) -> dict:
        """
        Generate reflection using the CREATIVE_REFLECTION_PROMPT based on recent posts.
        Returns a parsed JSON dictionary containing new creative rules.
        """
        if not self.llm_client:
            logger.warning("[CreativeAgent] No LLM client available for reflection.")
            return {}
            
        try:
            from asomien.llm.prompts.creative_prompts import CREATIVE_REFLECTION_PROMPT
            import json
            
            context_str = "\n".join([f"- Post: {p.get('content', '')} | Views: {p.get('views', 0)} | Likes: {p.get('likes', 0)} | Replies: {p.get('replies', 0)}" for p in recent_posts])
            user_prompt = CREATIVE_REFLECTION_PROMPT.format(context_str=context_str)
            
            response = self.llm_client.complete(
                system_prompt="You are a JSON generator.",
                user_prompt=user_prompt,
                temperature=0.7,
                max_tokens=300
            )
            
            start_idx = response.find("{")
            end_idx = response.rfind("}")
            if start_idx != -1 and end_idx != -1:
                json_str = response[start_idx:end_idx+1]
                try:
                    return json.loads(json_str)
                except json.JSONDecodeError as jde:
                    logger.error("[CreativeAgent] JSON Parse Error: %s. Raw: %s", jde, json_str)
                    return {}
            return {}
        except Exception as e:
            logger.error("[CreativeAgent] Reflection failed: %s", e)
            return {}
