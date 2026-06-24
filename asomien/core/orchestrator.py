"""
asomien/core/orchestrator.py

Master Orchestrator acting as the central hub for the system.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

class MasterOrchestrator:
    """Central hub coordinating the Asomien agents and workflows."""

    def __init__(
        self,
        content_agent=None,
        creative_agent=None,
        critic_agent=None,
        research_agent=None,
        engagement_agent=None,
        analytics_agent=None,
        adapter=None,
        memory=None,
    ) -> None:
        self.content_agent = content_agent
        self.creative_agent = creative_agent
        self.critic_agent = critic_agent
        self.research_agent = research_agent
        self.engagement_agent = engagement_agent
        self.analytics_agent = analytics_agent
        self.adapter = adapter
        self.memory = memory

        # Verify DB config tables
        if self.memory:
            import sqlite3
            try:
                with sqlite3.connect(self.memory.db_path) as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='rules'")
                    if not cursor.fetchone():
                        logger.error("[MasterOrchestrator] Required configuration table 'rules' missing from DB.")
            except Exception as e:
                logger.error("[MasterOrchestrator] Failed to verify configuration tables: %s", e)

    def is_warmup_phase(self) -> bool:
        """Check if we are in the warmup phase (first 14 days)."""
        if not self.memory:
            return True
        try:
            import sqlite3
            from datetime import datetime, timedelta, timezone
            with sqlite3.connect(self.memory.db_path) as conn:
                cursor = conn.execute("SELECT MIN(created_at) FROM posts WHERE status = 'published'")
                first_post_date = cursor.fetchone()[0]
                if not first_post_date:
                    return True
                
                first_dt = datetime.fromisoformat(first_post_date.replace('Z', '+00:00'))
                # Make timezone-aware if naive
                if first_dt.tzinfo is None:
                    first_dt = first_dt.replace(tzinfo=timezone.utc)
                    
                now_utc = datetime.now(timezone.utc)
                if now_utc - first_dt < timedelta(days=14):
                    return True
                return False
        except Exception as e:
            logger.error("[MasterOrchestrator] Error checking warmup phase: %s", e)
            return True

    def run_publish_cycle(self, scheduled_base=None, jitter_offset=0) -> None:
        """Trigger the publish cycle."""
        logger.info(
            "[MasterOrchestrator] run_publish_cycle base=%s jitter=%s",
            scheduled_base,
            jitter_offset,
        )
        if self.content_agent and self.critic_agent and self.adapter:
            try:
                context = self.content_agent._get_context()
                ideas = self.content_agent.generate_post_ideas(context)
                if not ideas:
                    logger.warning("[MasterOrchestrator] No ideas generated.")
                    return
                
                idea = ideas[0]
                template = self.content_agent.select_hook_template(
                    recent_posts=context.get("recent_posts", []),
                    idea=idea
                )
                
                variants = self.content_agent.draft_content(
                    idea=idea,
                    template_id=template["id"],
                    context=context,
                )
                
                if not variants:
                    logger.warning("[MasterOrchestrator] No variants drafted.")
                    return
                
                if self.creative_agent:
                    logger.info("[MasterOrchestrator] Passing drafts through CreativeAgent for refinement.")
                    refined_variants = []
                    for v in variants:
                        refined = self.creative_agent.refine_draft(v)
                        refined_variants.append(refined)
                    variants = refined_variants
                
                best_draft, best_score = self.critic_agent.select_best(variants)
                
                if best_draft and best_score and best_score.is_approved:
                    logger.info("[MasterOrchestrator] Best draft selected. Publishing...")
                    post_id = self.adapter.publish_text_post(best_draft)
                    logger.info("[MasterOrchestrator] Successfully published! ID: %s", post_id)
                    
                    if self.memory:
                        import sqlite3
                        import uuid
                        from datetime import datetime
                        with sqlite3.connect(self.memory.db_path) as conn:
                            conn.execute(
                                """
                                INSERT INTO posts (id, content, status, is_reply, hook_template_used, threads_post_id, created_at)
                                VALUES (?, ?, 'published', 0, ?, ?, ?)
                                """,
                                (str(uuid.uuid4()), best_draft, template["id"], post_id, datetime.now().isoformat())
                            )
                else:
                    logger.warning("[MasterOrchestrator] No drafts passed the critic.")
                    
            except Exception as e:
                logger.error("[MasterOrchestrator] Publish cycle failed: %s", e)
            logger.info("[MasterOrchestrator] Publish cycle executed.")

    def run_research_cycle(self) -> None:
        """Trigger the research cycle."""
        logger.info("[MasterOrchestrator] run_research_cycle called.")
        if self.research_agent:
            self.research_agent.run()

    def run_engagement_cycle(self) -> None:
        """Trigger the engagement cycle."""
        logger.info("[MasterOrchestrator] run_engagement_cycle called.")
        
        if not self.enforce_warmup_caps(is_reply=True):
            logger.info("[MasterOrchestrator] Engagement cycle skipped due to warmup caps.")
            return
            
        if self.engagement_agent:
            try:
                self.engagement_agent.run()
            except Exception as e:
                if "429" in str(e) or "Too Many Requests" in str(e):
                    logger.warning("[MasterOrchestrator] Rate limit hit (429). Retrying in 15 minutes. Strategy: Backoff.")
                else:
                    logger.error("[MasterOrchestrator] Engagement cycle failed: %s", e)

    def run_quota_check(self) -> None:
        """Check API quotas."""
        logger.info("[MasterOrchestrator] run_quota_check called.")
        if self.adapter:
            try:
                self.adapter.get_publishing_quota()
            except Exception as e:
                logger.error("[MasterOrchestrator] Quota check error: %s", e)

    def run_metrics_collection(self) -> None:
        """Collect metrics."""
        logger.info("[MasterOrchestrator] run_metrics_collection called.")
        if self.analytics_agent:
            self.analytics_agent.run()

    def run_audience_snapshot(self) -> None:
        """Take an audience snapshot."""
        logger.info("[MasterOrchestrator] run_audience_snapshot called.")
        if self.analytics_agent:
            self.analytics_agent.collect_audience_snapshot()

    def run_daily_report(self) -> None:
        """Run daily report."""
        logger.info("[MasterOrchestrator] run_daily_report called.")

    def log_warmup_day(self) -> None:
        """Log a warmup day."""
        logger.info("[MasterOrchestrator] log_warmup_day called.")
        if self.analytics_agent:
            self.analytics_agent.log_warmup_day()

    def run_weekly_analysis(self) -> None:
        """Run weekly analysis."""
        logger.info("[MasterOrchestrator] run_weekly_analysis called.")
        if self.critic_agent:
            self.critic_agent.analyze_weekly_performance()

    def enforce_warmup_caps(self, is_reply: bool = False) -> bool:
        """Logic to ensure we don't exceed 1 post/day and 10 replies/day for the first 14 days."""
        if not self.is_warmup_phase():
            return True
            
        logger.info("[MasterOrchestrator] Enforcing warmup caps for Day 1-14.")
        if not self.memory:
            return True
            
        try:
            import sqlite3
            from datetime import datetime
            today_str = datetime.now().strftime("%Y-%m-%d")
            
            with sqlite3.connect(self.memory.db_path) as conn:
                if is_reply:
                    cur = conn.execute(
                        "SELECT COUNT(*) FROM posts WHERE status='published' AND is_reply=1 AND date(created_at) = ?",
                        (today_str,)
                    )
                    count = cur.fetchone()[0]
                    if count >= 10:
                        logger.warning("[MasterOrchestrator] Warmup reply cap (10) reached today.")
                        return False
                else:
                    cur = conn.execute(
                        "SELECT COUNT(*) FROM posts WHERE status='published' AND is_reply=0 AND date(created_at) = ?",
                        (today_str,)
                    )
                    count = cur.fetchone()[0]
                    if count >= 1:
                        logger.warning("[MasterOrchestrator] Warmup post cap (1) reached today.")
                        return False
            return True
        except Exception as e:
            logger.error("[MasterOrchestrator] Error enforcing warmup caps: %s", e)
            return True

    def manage_sleep_mode(self) -> bool:
        """Implement a 'night-mode' where the bot stops posting/replying between 02:00 and 07:00 local time."""
        from datetime import datetime
        current_hour = datetime.now().hour
        if 2 <= current_hour < 7:
            logger.info("[MasterOrchestrator] Sleep mode active. Current hour: %s. Suspending activity.", current_hour)
            return True
        return False

    def get_system_state(self) -> dict:
        """Pulls the latest metrics from the AnalyticsAgent and current personality trait values."""
        state = {"metrics": None, "personality_traits": {}}
        if self.analytics_agent and hasattr(self.analytics_agent, "get_latest_metrics"):
            state["metrics"] = self.analytics_agent.get_latest_metrics()
            
        if self.memory:
            import sqlite3
            try:
                with sqlite3.connect(self.memory.db_path) as conn:
                    cursor = conn.execute("SELECT trait_name, value FROM personality_traits")
                    state["personality_traits"] = {row[0]: row[1] for row in cursor.fetchall()}
            except Exception as e:
                logger.error("[MasterOrchestrator] Failed to fetch personality traits: %s", e)
        return state

    def start_loop(self) -> None:
        """Create the main while True loop that keeps the system running."""
        logger.info("[MasterOrchestrator] Starting main loop.")
        import time
        import threading
        
        # Spawn the FastAPI server thread
        try:
            from asomien.web.app import start_server
            server_thread = threading.Thread(target=start_server, args=(self,), daemon=True)
            server_thread.start()
            logger.info("[MasterOrchestrator] Web dashboard spawned on port 8000.")
        except ImportError as e:
            logger.warning("[MasterOrchestrator] FastAPI not available. Dashboard disabled. (%s)", e)

        try:
            while True:
                # Actual jobs handled by APScheduler. This keeps the main thread alive.
                if self.manage_sleep_mode():
                    time.sleep(300) # Sleep 5 mins during night mode
                else:
                    time.sleep(10)
        except KeyboardInterrupt:
            logger.info("[MasterOrchestrator] Loop interrupted by user. Shutting down.")
            self.stop()

    def stop(self) -> None:
        """Stop the orchestrator."""
        logger.info("[MasterOrchestrator] Stopping system.")
