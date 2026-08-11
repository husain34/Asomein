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
        llm_client: Optional[Any] = None,
    ) -> None:
        super().__init__(name="EngagementAgent")
        self.adapter = adapter
        self.personality_engine = personality_engine
        self.memory = memory
        # FIX BUG-18: Thread-safe lazy initialization.
        # We store the explicit llm_client if passed (allows test injection / mocking).
        # If not provided, we store the api_key and resolve on first use under a lock.
        # This avoids the race condition where two concurrent APScheduler threads
        # both find llm_client=None and create two NIMClient instances simultaneously.
        import threading
        self._llm_lock = threading.Lock()
        self._llm_client_explicit = llm_client  # None means "resolve lazily"
        try:
            from asomien.config.settings import settings
            self._nim_api_key = settings.nvidia_nim_api_key
        except Exception:
            self._nim_api_key = None

    @property
    def llm_client(self):
        """Thread-safe lazy accessor for the NIM client."""
        if self._llm_client_explicit is not None:
            return self._llm_client_explicit
        with self._llm_lock:
            # Double-checked locking: re-check after acquiring lock
            if self._llm_client_explicit is not None:
                return self._llm_client_explicit
            try:
                from asomien.llm.client import NIMClient
                self._llm_client_explicit = NIMClient(api_key=self._nim_api_key)
            except Exception:
                self._llm_client_explicit = None
        return self._llm_client_explicit

    @llm_client.setter
    def llm_client(self, value):
        """Allow tests and external code to set/override the client directly."""
        self._llm_client_explicit = value

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

    def generate_reply(self, reply_text: str, is_quote: bool = False, images: list[str] = None) -> str:
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
            if is_quote:
                quote_instruction = (
                    "You are writing a Quote-Post for your followers to see. DO NOT just reply. "
                    "You MUST add significant value to the original post: introduce a completely absurd analogy, a fresh joke, or make it about your own existential dread. "
                    "DO NOT insult, mock, psychoanalyze, or attack the original poster. "
                    "Make it feel like a standalone post that references their content. Respond with 10 to 30 words."
                )
            else:
                quote_instruction = (
                    "You are talking directly to the user in their comment section. "
                    "Make your reply highly specific to the content of their post rather than a generic reaction. "
                    "Form a clear opinion or make a specific joke based on their exact words. Respond with 1 to 15 words maximum."
                )
            
            user_prompt = ENGAGEMENT_REPLY_PROMPT.format(context=context_str, user_reply=reply_text, quote_instruction=quote_instruction)

            # FIX BUG-18: llm_client is now initialized in __init__ — no lazy init here.
            if self.llm_client:
                if images and hasattr(self.llm_client, 'complete_with_vision'):
                    response = self.llm_client.complete_with_vision(
                        system_prompt="You are the Chronically Online AI persona.",
                        user_prompt=user_prompt,
                        base64_images=images,
                        temperature=0.85,
                        max_tokens=150
                    )
                else:
                    response = self.llm_client.complete(
                        system_prompt="You are the Chronically Online AI persona.",
                        user_prompt=user_prompt,
                        temperature=0.85,
                        max_tokens=150
                    )

                if response:
                    reply = response.strip()

                    # Refusal guard — drop LLM safety refusals silently, never publish them
                    _REFUSAL_PHRASES = [
                        "i cannot", "cannot provide", "cannot help",
                        "as an ai", "i am unable", "i can't help",
                        "i cannot assist", "cannot assist",
                    ]
                    if any(phrase in reply.lower() for phrase in _REFUSAL_PHRASES):
                        logger.warning("[%s] LLM returned a refusal. Dropping reply silently.", self.name)
                        return None

                    attempts = 0
                    while len(reply) > 290 and attempts < 3:
                        logger.info("[%s] Reply too long (%d chars). Asking LLM to shorten.", self.name, len(reply))
                        shorten_prompt = f"Your previous reply was too long. Rewrite this exact thought to be UNDER 290 characters. DO NOT change the vibe:\n\n{reply}"
                        shorten_response = self.llm_client.complete(
                            system_prompt="You are the Chronically Online AI persona.",
                            user_prompt=shorten_prompt,
                            temperature=0.7,
                            max_tokens=100
                        )
                        if shorten_response:
                            reply = shorten_response.strip()
                        attempts += 1

                    # Fallback if it STILL fails after 3 attempts
                    if len(reply) > 290:
                        reply = reply[:287] + "..."

                    return reply

        except Exception as e:
            logger.error("[%s] LLM generation failed: %s", self.name, e)

        if self.personality_engine:
            # Here we would normally query the LLM with the personality engine's prompt.
            # Returning a persona-aligned fallback for the test integration.
            return "same tbh."

        return "not to be dramatic but same."

    def _process_replies(self) -> None:
        """Task 1: Check the adapter for new mentions or replies on recent posts."""
        if not self.memory or not self.adapter:
            logger.warning("[%s] No memory or adapter. Skipping _process_replies.", self.name)
            return
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

            try:
                if hasattr(self.adapter, "get_mentions"):
                    mentions = self.adapter.get_mentions()
                    for mention in mentions:
                        mention_id = mention.get("id")
                        if not mention_id or not str(mention.get("text")).strip():
                            continue
                        
                        with sqlite3.connect(self.memory.db_path) as conn:
                            cur = conn.execute(
                                "SELECT COUNT(*) FROM posts WHERE reply_to_threads_id = ?",
                                (mention_id,)
                            )
                            if cur.fetchone()[0] == 0:
                                all_unanswered_replies.append(mention)
            except Exception as e:
                logger.error("[%s] Failed to fetch mentions: %s", self.name, e)

            if not all_unanswered_replies:
                return
                
            for mention in all_unanswered_replies:
                self._human_read_delay()
                reply_text = self.generate_reply(mention.get("text", ""), images=mention.get("images", []))
                self._human_type_delay()

                # Refusal guard — generate_reply returns None when LLM refuses
                if not reply_text:
                    logger.info("[%s] Skipping reply — generate_reply returned None (refusal or empty).", self.name)
                    continue

                # FIX BUG-15: Store the PostNode AFTER a successful publish call.
                # Previously, memory.store() was called with status="published" BEFORE
                # the API call, meaning a failed publish left a ghost "published" record
                # that would make the duplicate-reply guard skip this reply forever.
                try:
                    published_uri = self.adapter.publish_reply(text=reply_text, parent_post_id=mention.get("id"))
                    logger.info("[%s] Successfully replied to comment %s", self.name, mention.get("id"))

                    if self.memory:
                        from asomien.memory.nodes import PostNode
                        node = PostNode(
                            content=reply_text,
                            post_type="reply",
                            is_reply=True,
                            reply_to_threads_id=mention.get("id"),
                            threads_post_id=published_uri or "",
                            status="published"
                        )
                        self.memory.store(node)
                except Exception as publish_err:
                    logger.error("[%s] Failed to publish reply to %s: %s", self.name, mention.get("id"), publish_err)
                
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

    def generate_weekly_starterpack(self) -> None:
        """Create a Starter Pack from recent interactions, using LLM thematic profiling."""
        if not hasattr(self.adapter, "create_starter_pack") or not self.llm_client:
            return
            
        try:
            import sqlite3
            import json
            logger.info("[%s] Generating weekly starter pack with thematic profiling...", self.name)
            
            # Extract DIDs from recent interactions in posts table
            with sqlite3.connect(self.memory.db_path) as conn:
                cur = conn.execute(
                    "SELECT reply_to_threads_id FROM posts WHERE reply_to_threads_id IS NOT NULL ORDER BY created_at DESC LIMIT 100"
                )
                rows = cur.fetchall()
            
            dids = []
            seen = set()
            for row in rows:
                uri = row[0]
                if uri and uri.startswith("at://"):
                    parts = uri.split("/")
                    if len(parts) >= 3:
                        did = parts[2]
                        if did not in seen:
                            seen.add(did)
                            dids.append(did)
                if len(dids) >= 30:
                    break
            
            if len(dids) < 5:
                logger.warning("[%s] Not enough interactions to create a Starter Pack.", self.name)
                return
                
            # Fetch profiles for the DIDs
            profiles_data = []
            for did in dids:
                try:
                    profile = self.adapter.client.get_profile(did)
                    profiles_data.append({
                        "did": did,
                        "handle": profile.handle,
                        "display_name": getattr(profile, "display_name", ""),
                        "bio": getattr(profile, "description", "")
                    })
                except Exception as e:
                    logger.debug(f"Failed to fetch profile for {did}: {e}")
            
            if not profiles_data:
                return
                
            # Thematic Profiling Prompt
            prompt = (
                f"Analyze these {len(profiles_data)} user profiles:\n{json.dumps(profiles_data)}\n\n"
                "Find a cluster of 5 to 15 users who share a specific niche, theme, or subculture (e.g., 'Tech Optimists', 'Shitposters', 'Artists who complain'). "
                "Discard the rest. "
                "Generate a quirky, self-deprecating Gen-Z title for this specific subculture, and a very short description. "
                "CRITICAL: Do NOT be mean, insulting, or hostile. Make it funny but endearing.\n"
                "CRITICAL: Do NOT create any groups, themes, or titles related to LGBTQ+, queer, gay, or sexuality. Completely ignore any such themes in the bios.\n"
                "You MUST output ONLY a JSON object in this exact format, with no markdown formatting or extra text:\n"
                "{\n"
                "  \"title\": \"quirky theme title here\",\n"
                "  \"description\": \"short description here\",\n"
                "  \"dids\": [\"did1\", \"did2\"]\n"
                "}"
            )
            
            response = self.llm_client.complete(
                system_prompt="You are a sarcastic but wholesome Gen-Z creator making a highly curated starter pack.",
                user_prompt=prompt,
                max_tokens=400
            )
            
            try:
                # Strip any markdown code blocks if the LLM adds them
                cleaned_response = response.strip()
                if cleaned_response.startswith("```json"):
                    cleaned_response = cleaned_response[7:]
                if cleaned_response.startswith("```"):
                    cleaned_response = cleaned_response[3:]
                if cleaned_response.endswith("```"):
                    cleaned_response = cleaned_response[:-3]
                    
                sp_data = json.loads(cleaned_response.strip())
                title = sp_data.get("title", "chaotic timeline")[:50]
                desc = sp_data.get("description", "the only accounts keeping me sane")[:100]
                selected_dids = sp_data.get("dids", [])
            except json.JSONDecodeError as e:
                logger.error("[%s] Failed to parse LLM JSON response: %s\nResponse: %s", self.name, e, response)
                return
                
            if len(selected_dids) < 3:
                logger.warning("[%s] LLM did not return enough DIDs for a cluster.", self.name)
                return
                
            sp_uri = self.adapter.create_starter_pack(title, desc, selected_dids)
            if sp_uri:
                logger.info("[%s] Starter Pack %s generated with %d members.", self.name, title, len(selected_dids))
                
        except Exception as e:
            logger.error("[%s] Error generating starter pack: %s", self.name, e)

    def _process_follow_backs(self) -> None:
        """Task A: Follow-back routine."""
        try:
            if not hasattr(self.adapter, "get_followers"):
                return
            followers = self.adapter.get_followers(limit=20)
            for f in followers:
                if not f.get("viewer_following"):
                    # FIX BUG-16: Guard against None DID before calling _record_follow.
                    # f.get("did") returns None if the key is absent; passing None to
                    # adapter.follow() or the DB INSERT would cause silent bad data.
                    if not f.get("did"):
                        logger.warning("[%s] Skipping follow: missing 'did' in follower record.", self.name)
                        continue
                    # Apply small delay so we don't spam follows all at once
                    time.sleep(random.uniform(2.0, 5.0))
                    self._record_follow(f["did"])
        except Exception as e:
            logger.error("[%s] Error processing follow backs: %s", self.name, e)

    def _process_global_search(self) -> None:
        """Task B & C: Smart Liking and Organic Commenting using Global Search."""
        try:
            if not hasattr(self.adapter, "search_global_posts"):
                return

            # FIX BUG-18: llm_client is now initialized in __init__ — no lazy init here.
            if not self.llm_client:
                logger.warning("[%s] No LLM client available for global search scoring.", self.name)
                return

            # Organically generate a curated search keyword via LLM
            keyword_prompt = (
                "Give me exactly ONE short search term/phrase that fits one of these categories: "
                "1) Sarcastic observations, 2) Real-life existential crises, 3) Absurd internet memes, 4) Fun / goofy stuff. "
                "(e.g., 'existential dread', 'tbh', 'the audacity', 'im screaming', 'my toxic trait'). "
                "Make it random and fresh every time. Return ONLY the search term, nothing else, no quotes."
            )
            query_response = self.llm_client.complete(
                system_prompt="You are a Gen-Z trend generator. Output only the requested phrase.",
                user_prompt=keyword_prompt,
                temperature=0.9,
                max_tokens=15
            )
            
            query = query_response.strip().strip("'").strip('"') if query_response else "my toxic trait"
            logger.info("[%s] LLM generated curated global search query: '%s'", self.name, query)
            
            # Fetch more posts since we will heavily filter them by metrics
            timeline = self.adapter.search_global_posts(query=query, limit=50)
            if not timeline:
                return

            likes_given = 0
            comments_given = 0
            follows_given = 0

            for post in timeline:
                if likes_given >= 8 and comments_given >= 3 and follows_given >= 4:
                    break
                    
                text = post.get("text", "")
                post_uri = post.get("uri")
                author_did = post.get("author_did")
                post_likes = post.get("likes", 0)
                post_replies = post.get("replies", 0)
                
                # Check engagement threshold — lowered from 50/4 to 10/2 to find more posts to engage
                if post_likes < 10 and post_replies < 2:
                    continue

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
                    
                author_profile = self.adapter.get_user_profile(author_did) if hasattr(self.adapter, 'get_user_profile') else {}
                author_bio = author_profile.get('description', '')
                images = post.get("images", [])
                    
                prompt = (
                    f"Evaluate this post: '{text}'\n"
                    f"Author's Bio: '{author_bio}'\n\n"
                    "Score it from 0 to 10 on how well it fits the Gen-Z, relatable, brainrot, chronically-online aesthetic. "
                    "CRITICAL RULES: If the post is NOT in English, YOU MUST SCORE IT A 0. "
                    "If the post mentions politics, news, sports, tech reviews, or serious global events, YOU MUST SCORE IT A 0. "
                    "If the post, the Author's Bio, OR ANY ATTACHED IMAGES contain ANY LGBTQ+ themes, queer terminology, NSFW, sexual content, grieving/sadness, or 'weird' red flags, YOU MUST SCORE IT A 0. "
                    "Score 1-5: Boring, corporate, or irrelevant. "
                    "Score 6-8: A decent observation or relatable complaint. Good for a normal reply. "
                    "Score 9-10: A massive, highly-relatable banger with high viral potential. Reserve for top-tier content. "
                    "Only reply with a JSON object like {\"score\": 8, \"reason\": \"very relatable personal complaint\"}"
                )
                
                if images and hasattr(self.llm_client, 'complete_with_vision'):
                    response = self.llm_client.complete_with_vision(
                        system_prompt="You are an extremely strict vibe evaluator. Return ONLY valid JSON.",
                        user_prompt=prompt,
                        base64_images=images,
                        temperature=0.1,
                        max_tokens=100
                    )
                else:
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

                if score >= 6 and likes_given < 3:
                    self._human_read_delay()
                    like_success = self.adapter.like_post(uri=post_uri, cid=post.get("cid"))
                    if not like_success:
                        logger.warning("[%s] Skipping post %s because like failed (possibly deleted).", self.name, post_uri)
                        continue
                        
                    likes_given += 1
                    
                    if comments_given < 3:  # allow up to 3 organic comments per cycle
                        is_quote = score >= 9
                        reply_text = self.generate_reply(text, is_quote=is_quote, images=images)
                        self._human_type_delay()

                        # Refusal guard — generate_reply returns None when LLM refuses
                        if not reply_text:
                            logger.info("[%s] Skipping comment — generate_reply returned None (refusal).", self.name)
                            continue
                        
                        from asomien.memory.nodes import PostNode
                        node = PostNode(
                            content=reply_text,
                            post_type="reply",
                            is_reply=not is_quote,
                            reply_to_threads_id=post_uri,
                            status="published"
                        )
                        # NOTE: memory.store(node) is only called AFTER successful publish
                        # inside each try/except block below to avoid ghost records.
                        
                        if is_quote:
                            try:
                                published_uri = self.adapter.quote_post(text=reply_text, uri=post_uri, cid=post.get("cid"))
                                node.threads_post_id = published_uri or ""
                                self.memory.store(node)
                                logger.info("[%s] Organically QUOTE-POSTED global post %s", self.name, post_uri)
                            except Exception as pub_err:
                                logger.error("[%s] Failed to quote post %s: %s", self.name, post_uri, pub_err)
                        else:
                            try:
                                published_uri = self.adapter.publish_reply(text=reply_text, parent_post_id=post_uri)
                                node.threads_post_id = published_uri or ""
                                self.memory.store(node)
                                logger.info("[%s] Organically commented on global post %s", self.name, post_uri)
                            except Exception as pub_err:
                                logger.error("[%s] Failed to comment on %s: %s", self.name, post_uri, pub_err)
                            
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
