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
            
            # Format the prompt
            user_prompt = ENGAGEMENT_REPLY_PROMPT.format(context=context_str, user_reply=reply_text)
            
            if not getattr(self, "llm_client", None):
                from asomien.llm.client import NIMClient
                from asomien.config.settings import settings
                self.llm_client = NIMClient(api_key=settings.nvidia_nim_api_key)
                
            response = self.llm_client.complete(
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

    def _process_replies(self) -> None:
        """Task 1: Check the adapter for new mentions or replies on recent posts."""
        try:
            import sqlite3
            with sqlite3.connect(self.memory.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute(
                    "SELECT threads_post_id FROM posts WHERE status='published' AND threads_post_id IS NOT NULL ORDER BY created_at DESC LIMIT 5"
                )
                recent_post_ids = [row["threads_post_id"] for row in cursor.fetchall()]

            if not recent_post_ids:
                return

            all_unanswered_replies = []
            
            for post_id in recent_post_ids:
                try:
                    replies = self.adapter.get_post_replies(post_id)
                except Exception as e:
                    logger.error("[%s] Failed to fetch replies for post %s: %s", self.name, post_id, e)
                    continue
                for reply in replies:
                    reply_id = reply.get("id")
                    if not reply_id or not str(reply.get("text")).strip():
                        continue
                    
                    with sqlite3.connect(self.memory.db_path) as conn:
                        cur = conn.execute(
                            "SELECT COUNT(*) FROM posts WHERE reply_to_threads_id = ?",
                            (reply_id,)
                        )
                        if cur.fetchone()[0] == 0:
                            all_unanswered_replies.append(reply)

            if not all_unanswered_replies:
                return
                
            for mention in all_unanswered_replies:
                self._human_read_delay()
                reply_text = self.generate_reply(mention.get("text", ""))
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
                
                self.adapter.publish_reply(text=reply_text, parent_post_id=mention.get("id"))
                logger.info("[%s] Successfully replied to comment %s", self.name, mention.get("id"))
                
        except Exception as e:
            logger.error("[%s] Error running cycle: %s", self.name, e)

    def _record_follow(self, did: str) -> None:
        if self.adapter.follow(did):
            try:
                import sqlite3
                from datetime import datetime
                with sqlite3.connect(self.memory.db_path) as conn:
                    conn.execute(
                        "INSERT OR IGNORE INTO follow_history (did, followed_at, status) VALUES (?, ?, ?)",
                        (did, datetime.now().isoformat(), "active")
                    )
                    conn.commit()
            except Exception as e:
                logger.error("[%s] Error recording follow: %s", self.name, e)

    def churn_unrequited_follows(self) -> None:
        """Unfollow users who haven't followed back after 30 days, or if they unfollowed us."""
        try:
            import sqlite3
            from datetime import datetime, timedelta
            thirty_days_ago = (datetime.now() - timedelta(days=30)).isoformat()
            
            with sqlite3.connect(self.memory.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cur = conn.execute("SELECT did FROM follow_history WHERE status='active' AND followed_at <= ?", (thirty_days_ago,))
                old_follows = cur.fetchall()
                
            for row in old_follows:
                did = row['did']
                try:
                    profile = self.adapter.client.get_profile(did)
                    # profile.viewer.followed_by is the URI if they follow us, or None
                    if profile.viewer is None or not profile.viewer.followed_by:
                        logger.info("[%s] User %s did not follow back after 30 days (or unfollowed). Unfollowing.", self.name, did)
                        if self.adapter.unfollow(did):
                            with sqlite3.connect(self.memory.db_path) as conn:
                                conn.execute("UPDATE follow_history SET status='unfollowed' WHERE did=?", (did,))
                                conn.commit()
                except Exception as e:
                    logger.error("[%s] Error checking/unfollowing %s: %s", self.name, did, e)
        except Exception as e:
            logger.error("[%s] Error in churn_unrequited_follows: %s", self.name, e)

    def _process_follow_backs(self) -> None:
        """Task A: Follow-back routine."""
        try:
            if not hasattr(self.adapter, "get_followers"):
                return
            followers = self.adapter.get_followers(limit=20)
            for f in followers:
                if f.get("viewer_following") is None:
                    # Apply small delay so we don't spam follows all at once
                    time.sleep(random.uniform(2.0, 5.0))
                    self._record_follow(f.get("did"))
        except Exception as e:
            logger.error("[%s] Error processing follow backs: %s", self.name, e)

    def _process_global_search(self) -> None:
        """Task B & C: Smart Liking and Organic Commenting using Global Search."""
        try:
            if not hasattr(self.adapter, "search_global_posts"):
                return
                
            if not getattr(self, "llm_client", None):
                from asomien.llm.client import NIMClient
                from asomien.config.settings import settings
                self.llm_client = NIMClient(api_key=settings.nvidia_nim_api_key)

            # Organically generate a search keyword via LLM
            keyword_prompt = (
                "Give me exactly ONE short, relatable Gen-Z search term/phrase (e.g., 'existential dread', 'tbh', 'the audacity', 'im screaming', 'my toxic trait'). "
                "Make it random and fresh every time. Return ONLY the search term, nothing else, no quotes."
            )
            query_response = self.llm_client.complete(
                system_prompt="You are a Gen-Z trend generator. Output only the requested phrase.",
                user_prompt=keyword_prompt,
                temperature=0.9,
                max_tokens=15
            )
            
            query = query_response.strip().strip("'").strip('"') if query_response else "my toxic trait"
            logger.info("[%s] LLM generated global search query: '%s'", self.name, query)
            
            timeline = self.adapter.search_global_posts(query=query, limit=10)
            if not timeline:
                return

            likes_given = 0
            comments_given = 0
            follows_given = 0

            for post in timeline:
                if likes_given >= 3 and comments_given >= 1 and follows_given >= 2:
                    break
                    
                text = post.get("text", "")
                post_uri = post.get("uri")
                author_did = post.get("author_did")
                if len(text) < 10:
                    continue
                    
                import sqlite3
                with sqlite3.connect(self.memory.db_path) as conn:
                    cur = conn.execute(
                        "SELECT COUNT(*) FROM posts WHERE reply_to_threads_id = ?",
                        (post_uri,)
                    )
                    if cur.fetchone()[0] > 0:
                        continue
                    
                prompt = (
                    f"Evaluate this post: '{text}'\n"
                    "Score it from 0 to 10 on how well it fits the Gen-Z, relatable, brainrot, chronically-online aesthetic. "
                    "CRITICAL RULES: If the post is NOT in English, YOU MUST SCORE IT A 0. "
                    "If the post mentions politics, news, sports, tech reviews, or serious global events, YOU MUST SCORE IT A 0. "
                    "It MUST be a personal complaint, sarcastic joke, or relatable life observation to score above a 7. "
                    "Only reply with a JSON object like {\"score\": 8, \"reason\": \"very relatable personal complaint\"}"
                )
                response = self.llm_client.complete(
                    system_prompt="You are an extremely strict vibe evaluator. Return ONLY valid JSON.",
                    user_prompt=prompt,
                    temperature=0.1,
                    max_tokens=100
                )
                
                try:
                    import json
                    clean_resp = response.strip()
                    if clean_resp.startswith("```json"):
                        clean_resp = clean_resp[7:-3]
                    elif clean_resp.startswith("```"):
                        clean_resp = clean_resp[3:-3]
                    data = json.loads(clean_resp)
                    score = int(data.get("score", 0))
                except Exception:
                    score = 0

                if score >= 7 and likes_given < 3:
                    self._human_read_delay()
                    self.adapter.like_post(uri=post_uri, cid=post.get("cid"))
                    likes_given += 1
                    
                    if score >= 9:
                        if follows_given < 2 and author_did:
                            self._record_follow(author_did)
                            follows_given += 1
                            logger.info("[%s] Organically followed user %s based on high vibe score", self.name, author_did)
                        
                        if comments_given < 1:
                            reply_text = self.generate_reply(text)
                            self._human_type_delay()
                            
                            from asomien.memory.nodes import PostNode
                            node = PostNode(
                                content=reply_text,
                                post_type="reply",
                                is_reply=True,
                                reply_to_threads_id=post_uri,
                                status="published"
                            )
                            self.memory.store(node)
                            
                            self.adapter.publish_reply(text=reply_text, parent_post_id=post_uri)
                            logger.info("[%s] Organically commented on global post %s", self.name, post_uri)
                            comments_given += 1

        except Exception as e:
            logger.error("[%s] Error processing global search: %s", self.name, e)

    def monitor_inbound(self) -> None:
        """Run all engagement tasks: Replies, Follow-Backs, and Global Search interactions."""
        if not self.adapter or not self.memory:
            logger.warning("[%s] No adapter or memory configured. Skipping.", self.name)
            return
            
        self._process_replies()
        self._process_follow_backs()
        self._process_global_search()

    def run(self) -> None:
        """Main execution cycle: check for mentions, wait, reply."""
        self.start()
        logger.info("[%s] Running engagement cycle.", self.name)
        
        self.monitor_inbound()
            
        self.stop()
