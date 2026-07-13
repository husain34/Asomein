"""
asomien/scheduler/jobs.py

Scheduler Manager — manages all APScheduler jobs with T_jitter applied to
every publish window.

Blueprint spec (Section 8 / Section 5):

T_JITTER:
    T_jitter = random.randint(-45, 45)  # minutes
    Applied fresh to each publish window each day.
    No two posts ever land on the exact same minute twice.
    Jitter offset stored on PostNode for audit.

DAILY PUBLISH SCHEDULER (runs at 07:30):
    job_schedule_todays_publishes() determines today's valid publish windows
    based on day-of-week, calculates jittered run_date jobs for each window,
    and registers them with the scheduler.

BASE WINDOWS (US Eastern):
    Morning:   09:00 — Mon/Tue/Wed/Thu/Fri
    Afternoon: 13:00 — Wed/Thu only (peak engagement days)
    Evening:   20:00 — Mon/Tue/Wed/Thu/Fri

WARMUP PHASE (Days 0–14):
    max 1 post per day — morning slot only
    jitter still applied

4-HOUR GAP GUARD:
    If hours_since_last_post < 4 → skip this window.

14-DAY WARMUP POST CAP:
    If is_warmup_phase() and posts_today >= 1 → skip.
"""

from __future__ import annotations

import logging
import random
from datetime import datetime, timedelta
from typing import Any, Optional

from asomien.core.orchestrator import MasterOrchestrator

logger = logging.getLogger(__name__)


# ── Safety config (mirrors SAFETY_CONFIG from blueprint Section 10) ───────────
JITTER_RANGE_MINUTES: int = 45          # T_jitter: ±45 minutes max
WARMUP_PHASE_DAYS: int = 14
WARMUP_MAX_POSTS_PER_DAY: int = 1
POST_WARMUP_MAX_POSTS_PER_DAY: int = 2
MIN_TIME_BETWEEN_POSTS_MINUTES: int = 240   # 4-hour gap

# Base publish windows (hour, list of weekday abbreviations)
# Days are lowercase 3-letter abbreviations: 'mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'
PUBLISH_WINDOWS: list[dict] = [
    {"hour": 9,  "days": ["mon", "tue", "wed", "thu", "fri"]},
    {"hour": 13, "days": ["wed", "thu"]},
    {"hour": 20, "days": ["mon", "tue", "wed", "thu", "fri"]},
]
AVOID_DAYS: list[str] = ["sat"]


class SchedulerManager:
    """
    Manages all scheduled jobs for the Asomien system.

    Applies T_jitter to all publish windows to simulate natural human posting
    variance and avoid Meta's mechanical-timing detection heuristics.

    T_jitter range: -45 to +45 minutes from the base window time.
    Applied fresh each day — no two days share the same offset.
    The actual publish time and jitter offset are logged to PostNode for audit.

    Usage (production):
        from apscheduler.schedulers.blocking import BlockingScheduler
        scheduler = BlockingScheduler()
        manager = SchedulerManager(orchestrator=orchestrator, scheduler=scheduler)
        manager.setup_jobs(scheduler, orchestrator)
        scheduler.start()

    Usage (tests):
        manager = SchedulerManager()
        # _apply_jitter(), _get_todays_windows(), _check_publish_guards() are testable
        # without a live APScheduler instance.
    """

    JITTER_RANGE_MINUTES: int = JITTER_RANGE_MINUTES

    def __init__(
        self,
        orchestrator=None,   # MasterOrchestrator — optional for tests
        scheduler=None,      # APScheduler instance — optional for tests
        analytics=None,      # AnalyticsAgent — optional for tests
    ) -> None:
        self.orchestrator = orchestrator
        self.scheduler = scheduler
        self.analytics = analytics

    # ── T_jitter ──────────────────────────────────────────────────────────────

    def _apply_jitter(self, base_datetime: datetime) -> tuple[datetime, int]:
        """
        Apply T_jitter to a base publish datetime.

        Blueprint spec (Section 8):
            T_jitter = random.randint(-45, 45)
            return base_datetime + timedelta(minutes=T_jitter)

        Parameters
        ----------
        base_datetime : the planned publish time (pre-jitter)

        Returns
        -------
        (jittered_datetime, offset_minutes_applied)

        The offset is in range [-JITTER_RANGE_MINUTES, +JITTER_RANGE_MINUTES].
        Both the jittered time and offset are returned for PostNode audit logging.
        """
        offset = random.randint(-self.JITTER_RANGE_MINUTES, self.JITTER_RANGE_MINUTES)
        jittered = base_datetime + timedelta(minutes=offset)
        logger.debug(
            "[SchedulerManager] Jitter applied: base=%s, offset=%+d min, actual=%s",
            base_datetime.strftime("%H:%M"),
            offset,
            jittered.strftime("%H:%M"),
        )
        return jittered, offset

    # ── Window calculation ────────────────────────────────────────────────────

    def _get_todays_windows(
        self,
        today: Optional[datetime] = None,
        is_warmup: bool = False,
    ) -> list[datetime]:
        """
        Calculate today's base publish windows based on day-of-week.

        Warmup phase (days 0–14): only the morning slot (09:00), 1 post max.
        Post-warmup: all applicable windows for the day.
        Saturday is always excluded per blueprint.

        Parameters
        ----------
        today     : override for today's date (default: datetime.now())
        is_warmup : True during the 14-day warmup phase

        Returns
        -------
        List of naive datetime objects representing base publish times
        for today, in chronological order.
        """
        today = today or datetime.now()
        day_name = today.strftime("%a").lower()

        # Hard exclude Saturday
        if day_name in AVOID_DAYS:
            logger.info(
                "[SchedulerManager] Today is %s (avoid_day). No windows scheduled.",
                day_name,
            )
            return []

        windows: list[datetime] = []

        if is_warmup:
            # Warmup phase: morning slot only, 1 post per day
            base = today.replace(hour=9, minute=0, second=0, microsecond=0)
            windows.append(base)
            logger.info(
                "[SchedulerManager] Warmup phase: 1 window at 09:00 for %s", day_name
            )
        else:
            # Post-warmup: all applicable windows
            for window_spec in PUBLISH_WINDOWS:
                if day_name in window_spec["days"]:
                    base = today.replace(
                        hour=window_spec["hour"],
                        minute=0,
                        second=0,
                        microsecond=0,
                    )
                    windows.append(base)

            windows.sort()
            logger.info(
                "[SchedulerManager] %d windows for %s: %s",
                len(windows),
                day_name,
                [w.strftime("%H:%M") for w in windows],
            )

        return windows

    # ── Guard checks ──────────────────────────────────────────────────────────

    def _check_publish_guards(
        self,
        posts_today: int = 0,
        hours_since_last_post: float = 999.0,
        is_warmup: bool = False,
    ) -> tuple[bool, str]:
        """
        Run all pre-publish guard checks.  Returns (allowed, reason).

        Guard 1 — 14-day warmup post cap:
            If is_warmup and posts_today >= WARMUP_MAX_POSTS_PER_DAY (1) → block.

        Guard 2 — Post-warmup daily post cap:
            If not is_warmup and posts_today >= POST_WARMUP_MAX_POSTS_PER_DAY (2) → block.

        Guard 3 — 4-hour gap check:
            If hours_since_last_post < MIN_TIME_BETWEEN_POSTS_MINUTES/60 → block.

        All guards must pass for the publish to proceed.

        Parameters
        ----------
        posts_today           : number of posts published today (from analytics)
        hours_since_last_post : hours since the last post was published
        is_warmup             : True during the 14-day warmup phase

        Returns
        -------
        (True, "") if all guards pass, or (False, reason_string) if any block.
        """
        # Guard 1/2: Post cap
        if is_warmup:
            if posts_today >= WARMUP_MAX_POSTS_PER_DAY:
                reason = (
                    f"warmup_post_cap_reached: {posts_today}/{WARMUP_MAX_POSTS_PER_DAY}"
                )
                logger.info("[SchedulerManager] Guard blocked: %s", reason)
                return False, reason
        else:
            if posts_today >= POST_WARMUP_MAX_POSTS_PER_DAY:
                reason = (
                    f"daily_post_cap_reached: {posts_today}/{POST_WARMUP_MAX_POSTS_PER_DAY}"
                )
                logger.info("[SchedulerManager] Guard blocked: %s", reason)
                return False, reason

        # Guard 3: 4-hour gap
        min_hours = MIN_TIME_BETWEEN_POSTS_MINUTES / 60.0
        if hours_since_last_post < min_hours:
            reason = (
                f"four_hour_gap_not_met: {hours_since_last_post:.1f}h "
                f"< {min_hours:.1f}h required"
            )
            logger.info("[SchedulerManager] Guard blocked: %s", reason)
            return False, reason

        return True, ""

    # ── APScheduler job setup ─────────────────────────────────────────────────

    def setup_jobs(self, scheduler, orchestrator) -> None:
        """
        Register all recurring APScheduler jobs.

        Publish windows are NOT directly registered here — they are scheduled
        dynamically each morning by job_schedule_todays_publishes().

        Parameters
        ----------
        scheduler    : APScheduler instance (BlockingScheduler or BackgroundScheduler)
        orchestrator : MasterOrchestrator — passed through so job methods can call it
        """
        self.orchestrator = orchestrator
        self.scheduler = scheduler

        # ── Research loop: every 4 hours ──────────────────────────────────────
        scheduler.add_job(
            self.job_research,
            "interval",
            hours=4,
            id="research_loop",
            replace_existing=True,
        )

        # ── Daily publish scheduler: 07:30 ────────────────────────────────────
        # This job calculates today's windows and schedules them as run_date jobs.
        scheduler.add_job(
            self.job_schedule_todays_publishes,
            "cron",
            hour=7,
            minute=30,
            id="daily_publish_scheduler",
            replace_existing=True,
        )

        # Runs every 1 hour during the bot's 15-hour awake window (e.g. 08:00 to 22:00)
        scheduler.add_job(
            self.job_engage_replies,
            "cron",
            hour="8-22",
            minute=0,
            id="engagement_loop",
            replace_existing=True,
        )

        # ── Post metrics collection: every 30 minutes ─────────────────────────
        scheduler.add_job(
            self.job_collect_post_metrics,
            "interval",
            minutes=30,
            id="post_metrics",
            replace_existing=True,
        )

        # ── Audience snapshot: every 6 hours ─────────────────────────────────
        scheduler.add_job(
            self.job_collect_audience_snapshot,
            "interval",
            hours=6,
            id="audience_snapshot",
            replace_existing=True,
        )

        # ── Quota check: every 6 hours ────────────────────────────────────────
        scheduler.add_job(
            self.job_check_quota,
            "interval",
            hours=6,
            id="quota_check",
            replace_existing=True,
        )

        # ── Reflection / learning: every 6 hours ─────────────────────────────
        scheduler.add_job(
            self.job_reflect,
            "interval",
            hours=6,
            id="reflect_loop",
            replace_existing=True,
        )

        # ── Weekly pattern analysis: Sunday 08:00 ─────────────────────────────
        scheduler.add_job(
            self.job_weekly_analysis,
            "cron",
            day_of_week="sun",
            hour=8,
            id="weekly_analysis",
            replace_existing=True,
        )

        # ── Daily report: 23:00 ───────────────────────────────────────────────
        scheduler.add_job(
            self.job_daily_report,
            "cron",
            hour=23,
            minute=0,
            id="daily_report",
            replace_existing=True,
        )

        # ── Warmup tracker: midnight (00:05) ─────────────────────────────────
        scheduler.add_job(
            self.job_warmup_tracker,
            "cron",
            hour=0,
            minute=5,
            id="warmup_tracker",
            replace_existing=True,
        )

        # ── Sleep consolidation: 03:00 ────────────────────────────────────────
        scheduler.add_job(
            self.job_sleep_consolidate,
            "cron",
            hour=3,
            minute=0,
            id="sleep_consolidate",
            replace_existing=True,
        )

        # ── Churn follows: 04:00 ──────────────────────────────────────────────
        # ── Starter Pack: Weekly on Sunday at 10:00 ─────────────────────────
        scheduler.add_job(
            self.job_generate_weekly_starterpack,
            "cron",
            day_of_week="sun",
            hour=10,
            minute=0,
            id="weekly_starterpack",
            replace_existing=True,
        )

        logger.info("[SchedulerManager] All jobs registered.")

        # Bootstrap: schedule today's remaining windows in case the server was rebooted after 07:30
        self.job_schedule_todays_publishes()

    # ── Core daily publish job ────────────────────────────────────────────────

    def job_schedule_todays_publishes(self) -> None:
        """
        Blueprint spec (Section 8):
        Runs at 07:30 each morning. Determines today's publish windows based
        on day-of-week, then schedules jittered run_date jobs for each window.

        Warmup phase (days 0–14): only morning slot, 1 post per day max.
        Post-warmup: up to 2 posts per day, minimum 4h apart.

        Each window is scheduled as a one-off 'date' job with the jittered time,
        passing the base_time and jitter_offset as kwargs for PostNode logging.
        """
        today = datetime.now()

        # Determine warmup state
        is_warmup = False
        if self.orchestrator is not None:
            try:
                is_warmup = self.orchestrator.is_warmup_phase()
            except Exception as exc:
                logger.warning(
                    "[SchedulerManager] Could not check warmup phase: %s. "
                    "Assuming post-warmup.", exc
                )

        windows = self._get_todays_windows(today=today, is_warmup=is_warmup)

        if not windows:
            logger.info("[SchedulerManager] No publish windows for today.")
            return

        for base_time in windows:
            jittered_time, offset = self._apply_jitter(base_time)
            job_id = f"publish_{base_time.strftime('%H%M')}_{today.date()}"

            if jittered_time < datetime.now():
                logger.info(
                    "[SchedulerManager] Skipping past window: actual=%s, job_id=%s",
                    jittered_time.strftime("%H:%M"),
                    job_id,
                )
                continue

            if self.scheduler is not None:
                self.scheduler.add_job(
                    self.job_content_and_publish,
                    "date",
                    run_date=jittered_time,
                    kwargs={
                        "scheduled_base": base_time,
                        "jitter_offset": offset,
                        "is_warmup": is_warmup,
                    },
                    id=job_id,
                    replace_existing=True,
                )

            logger.info(
                "[SchedulerManager] Scheduled publish: base=%s, "
                "jitter=%+d min, actual=%s, job_id=%s",
                base_time.strftime("%H:%M"),
                offset,
                jittered_time.strftime("%H:%M"),
                job_id,
            )

    # ── Content and publish job ───────────────────────────────────────────────

    def job_content_and_publish(
        self,
        scheduled_base: Optional[datetime] = None,
        jitter_offset: int = 0,
        is_warmup: bool = False,
    ) -> None:
        """
        Guard → Generate → Critique → Publish pipeline.

        Guard logic (before any content generation):
          1. Warmup post cap (days 0–14: ≤1 post/day)
          2. Daily post cap (post-warmup: ≤2 posts/day)
          3. 4-hour gap since last post

        If any guard fails: skip silently (no error, just log).
        Otherwise: invoke the content + critic + publish pipeline via orchestrator.

        Parameters
        ----------
        scheduled_base : the pre-jitter base time (for PostNode logging)
        jitter_offset  : the T_jitter offset that was applied (for audit)
        is_warmup      : whether warmup phase is active
        """
        # Gather current state for guards
        posts_today = 0
        hours_since_last = 999.0

        if self.analytics is not None:
            try:
                posts_today = self.analytics.get_posts_published_today()
                hours_since_last = self.analytics.get_hours_since_last_post()
            except Exception as exc:
                logger.warning(
                    "[SchedulerManager] Could not get analytics data: %s. "
                    "Proceeding with guard defaults.", exc
                )

        allowed, reason = self._check_publish_guards(
            posts_today=posts_today,
            hours_since_last_post=hours_since_last,
            is_warmup=is_warmup,
        )

        if not allowed:
            logger.info(
                "[SchedulerManager] Publish guard blocked. Reason: %s", reason
            )
            return

        # Guards passed — invoke the orchestrator's publish pipeline
        logger.info(
            "[SchedulerManager] Guards passed. Firing content+publish pipeline. "
            "base=%s, jitter=%+d min",
            scheduled_base.strftime("%H:%M") if scheduled_base else "unknown",
            jitter_offset,
        )

        if self.orchestrator is not None:
            try:
                self.orchestrator.run_publish_cycle(
                    scheduled_base=scheduled_base,
                    jitter_offset=jitter_offset,
                )
            except Exception as exc:
                logger.error(
                    "[SchedulerManager] Publish cycle error: %s", exc
                )

    # ── Other recurring job stubs ─────────────────────────────────────────────
    # Each is fully named to match the blueprint class spec.
    # Phase-specific logic is filled in the corresponding phase.

    def job_research(self) -> None:
        """Every 4 hours: trigger ResearchAgent cycle."""
        logger.debug("[SchedulerManager] job_research fired.")
        if self.orchestrator is not None:
            try:
                self.orchestrator.run_research_cycle()
            except Exception as exc:
                logger.error("[SchedulerManager] Research cycle error: %s", exc)

    def job_engage_replies(self) -> None:
        """Every 10 minutes: trigger EngagementAgent to check and reply."""
        logger.debug("[SchedulerManager] job_engage_replies fired.")
        if self.orchestrator is not None:
            try:
                self.orchestrator.run_engagement_cycle()
            except Exception as exc:
                logger.error("[SchedulerManager] Engagement cycle error: %s", exc)

    def job_collect_post_metrics(self) -> None:
        """Every 30 minutes: collect metrics for recent published posts."""
        logger.debug("[SchedulerManager] job_collect_post_metrics fired.")
        if self.orchestrator is not None:
            try:
                self.orchestrator.run_metrics_collection()
            except Exception as exc:
                logger.error("[SchedulerManager] Metrics collection error: %s", exc)

    def job_collect_audience_snapshot(self) -> None:
        """Every 6 hours: collect audience-level metrics snapshot."""
        logger.debug("[SchedulerManager] job_collect_audience_snapshot fired.")
        if self.orchestrator is not None:
            try:
                self.orchestrator.run_audience_snapshot()
            except Exception as exc:
                logger.error("[SchedulerManager] Audience snapshot error: %s", exc)

    def job_reflect(self) -> None:
        """Every 6 hours: run CriticAgent reflection and rule updates."""
        logger.debug("[SchedulerManager] job_reflect fired.")
        if self.orchestrator and self.orchestrator.critic_agent and self.orchestrator.memory:
            try:
                import sqlite3
                from datetime import datetime, timedelta
                
                # 1. Query the last 24h of PostNodes from the database
                cutoff = (datetime.now() - timedelta(hours=24)).isoformat()
                with sqlite3.connect(self.orchestrator.memory.db_path) as conn:
                    conn.row_factory = sqlite3.Row
                    conn.execute("ATTACH DATABASE 'data/metrics.db' AS metrics")
                    cursor = conn.execute(
                        """
                        SELECT p.*, 
                               COALESCE(pm.views, 0) as views, 
                               COALESCE(pm.likes, 0) as likes, 
                               COALESCE(pm.replies, 0) as replies 
                        FROM posts p
                        LEFT JOIN metrics.post_metrics pm ON p.id = pm.post_id
                        WHERE p.created_at >= ? AND p.status = 'published'
                        ORDER BY p.created_at DESC
                        """, 
                        (cutoff,)
                    )
                    recent_posts = [dict(r) for r in cursor.fetchall()]
                    
                # 2. Pass this data to CriticAgent via run_daily_reflection
                if hasattr(self.orchestrator.critic_agent, 'run_daily_reflection'):
                    reflection_data = self.orchestrator.critic_agent.run_daily_reflection(recent_posts)
                else:
                    reflection_data = self.orchestrator.critic_agent.generate_reflection(None, None)
                    
                # 3. Apply learned personality shifts and decay
                self.orchestrator.critic_agent.update_rules(reflection_data)
                if hasattr(self.orchestrator.critic_agent, 'decay_rules'):
                    self.orchestrator.critic_agent.decay_rules()
                    
                # 4. Creative Agent Reflection
                if hasattr(self.orchestrator, 'creative_agent') and self.orchestrator.creative_agent:
                    if hasattr(self.orchestrator.creative_agent, 'run_creative_reflection'):
                        creative_reflection_data = self.orchestrator.creative_agent.run_creative_reflection(recent_posts)
                        self.orchestrator.creative_agent.update_rules(creative_reflection_data)
                    if hasattr(self.orchestrator.creative_agent, 'decay_rules'):
                        self.orchestrator.creative_agent.decay_rules()
                    
            except Exception as exc:
                logger.error("[SchedulerManager] job_reflect error: %s", exc)

    def job_sleep_consolidate(self) -> None:
        """03:00 daily: memory consolidation during low-activity window."""
        logger.debug("[SchedulerManager] job_sleep_consolidate fired.")
        if self.orchestrator and self.orchestrator.memory:
            try:
                import sqlite3
                import uuid
                
                # Move temporary interaction nodes into long-term summary nodes
                with sqlite3.connect(self.orchestrator.memory.db_path) as conn:
                    cursor = conn.execute(
                        "SELECT id, content FROM posts WHERE status = 'published' "
                        "AND is_reply = 1 AND created_at >= datetime('now', '-1 day')"
                    )
                    interactions = cursor.fetchall()
                    
                    if interactions:
                        summary_text = "Daily interaction summary: " + " | ".join([row[1][:50] for row in interactions])
                        conn.execute(
                            """
                            INSERT INTO research_nodes (id, source, headline, summary, discovered_at, is_active)
                            VALUES (?, ?, ?, ?, datetime('now'), 1)
                            """,
                            (str(uuid.uuid4()), "consolidation", "Daily User Interactions", summary_text)
                        )
                        logger.info("[SchedulerManager] Consolidated %d interactions into long-term memory.", len(interactions))
                        
                if hasattr(self.orchestrator.memory, 'consolidate'):
                    self.orchestrator.memory.consolidate()
            except Exception as exc:
                logger.error("[SchedulerManager] job_sleep_consolidate error: %s", exc)

    def job_daily_report(self) -> None:
        """23:00 daily: generate and store the daily performance report."""
        logger.debug("[SchedulerManager] job_daily_report fired.")
        if self.orchestrator is not None:
            try:
                self.orchestrator.run_daily_report()
            except Exception as exc:
                logger.error("[SchedulerManager] Daily report error: %s", exc)

    def job_check_quota(self) -> None:
        """Every 6 hours: check Threads API publishing quota."""
        logger.debug("[SchedulerManager] job_check_quota fired.")
        if self.orchestrator is not None:
            try:
                self.orchestrator.run_quota_check()
            except Exception as exc:
                logger.error("[SchedulerManager] Quota check error: %s", exc)

    def job_warmup_tracker(self) -> None:
        """00:05 daily: log daily warmup stats and check phase completion."""
        logger.debug("[SchedulerManager] job_warmup_tracker fired.")
        if self.orchestrator is not None:
            try:
                self.orchestrator.log_warmup_day()
            except Exception as exc:
                logger.error("[SchedulerManager] Warmup tracker error: %s", exc)

    def job_weekly_analysis(self) -> None:
        """Sunday 08:00: weekly pattern analysis across all published posts."""
        logger.debug("[SchedulerManager] job_weekly_analysis fired.")
        if self.orchestrator is not None:
            try:
                self.orchestrator.run_weekly_analysis()
            except Exception as exc:
                logger.error("[SchedulerManager] Weekly analysis error: %s", exc)

    def job_generate_weekly_starterpack(self) -> None:
        """Weekly: generate a starter pack of top interacted users."""
        logger.debug("[SchedulerManager] job_generate_weekly_starterpack fired.")
        if self.orchestrator is not None:
            try:
                self.orchestrator.engagement_agent.generate_weekly_starterpack()
            except Exception as exc:
                logger.error("[SchedulerManager] Starter pack error: %s", exc)
