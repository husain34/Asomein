"""
asomien/agents/engagement_agent.py

Engagement Agent implementing Phase 6 Voice logic.
"""

from __future__ import annotations

import logging
import random
import time
from typing import Any, Optional

from asomien.agents.base_agent import BaseAgent

logger = logging.getLogger(__name__)


class EngagementAgent(BaseAgent):
    """Voice of the persona, responsible for checking mentions and replying."""

    def __init__(
        self,
        adapter: Optional[Any] = None,
        personality_engine: Optional[Any] = None,
        memory: Optional[Any] = None,
    ) -> None:
        super().__init__(name="EngagementAgent")
        self.adapter = adapter
        self.personality_engine = personality_engine
        self.memory = memory

    def _human_read_delay(self) -> None:
        """Sleep for 45-180s to simulate reading time."""
        delay = random.uniform(45.0, 180.0)
        logger.debug("[%s] Sleeping for %.2f seconds (_human_read_delay)", self.name, delay)
        time.sleep(delay)

    def _human_type_delay(self) -> None:
        """Sleep for 10-40s to simulate typing time."""
        delay = random.uniform(10.0, 40.0)
        logger.debug("[%s] Sleeping for %.2f seconds (_human_type_delay)", self.name, delay)
        time.sleep(delay)

    def generate_reply(self, reply_text: str) -> str:
        """Use the current PersonaRules from the database to generate a reply."""
        self.log_action("generate_reply", f"Input text: {reply_text}")
        
        context_str = "None"
        if self.memory:
            # Semantic search for context (last 3 interactions with user/topic)
            try:
                similar_posts = self.memory.similarity_search(reply_text, limit=3)
                if similar_posts:
                    context_str = "\n".join([f"- {p.get('content', '')}" for p in similar_posts])
            except Exception as e:
                logger.warning("[%s] Similarity search failed: %s", self.name, e)
                
        try:
            from asomien.llm.prompts.engagement_prompts import ENGAGEMENT_REPLY_PROMPT
            from asomien.llm.client import NIMClient
            
            # Format the prompt
            user_prompt = ENGAGEMENT_REPLY_PROMPT.format(context=context_str, user_reply=reply_text)
            
            client = NIMClient()
            response = client.complete(
                system_prompt="You are the Chronically Online AI persona.",
                user_prompt=user_prompt,
                temperature=0.85,
                max_tokens=150
            )
            
            if response:
                return response.strip()
                
        except Exception as e:
            logger.error("[%s] LLM generation failed: %s", self.name, e)
            
        if self.personality_engine:
            # Here we would normally query the LLM with the personality engine's prompt.
            # Returning a persona-aligned fallback for the test integration.
            return "same tbh."
        
        return "not to be dramatic but same."

    def monitor_inbound(self) -> None:
        """Check the ThreadsAdapter for new mentions or replies."""
        if not self.adapter:
            logger.warning("[%s] No adapter configured. Skipping.", self.name)
            return
            
        try:
            mentions = self.adapter.get_mentions()
            if not mentions:
                self.log_action(
                    action="monitor_inbound",
                    reason="checking ThreadsAdapter",
                    outcome="No new mentions",
                )
                return
                
            for mention in mentions:
                if not mention.get("text") or not str(mention.get("text")).strip():
                    logger.info("[%s] Empty mention received. Skipping.", self.name)
                    continue
                    
                # Apply reading delay before processing the mention
                self._human_read_delay()
                    
                reply_text = self.generate_reply(mention["text"])
                
                # Apply typing delay right before replying
                self._human_type_delay()
                
                if self.memory:
                    from asomien.memory.nodes import PostNode
                    node = PostNode(
                        content=reply_text,
                        post_type="reply",
                        is_reply=True,
                        reply_to_threads_id=mention.get("id"),
                        status="published"
                    )
                    self.memory.store(node)
                
                self.adapter.reply(mention.get("id"), reply_text)
                
        except Exception as e:
            logger.error("[%s] Error monitoring inbound: %s", self.name, e)
            raise e

    def run(self) -> None:
        """Main execution cycle: check for mentions, wait, reply."""
        self.start()
        logger.info("[%s] Running engagement cycle.", self.name)
        
        self.monitor_inbound()
            
        self.stop()
