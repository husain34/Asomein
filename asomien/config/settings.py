"""
asomien/config/settings.py

Central configuration system. Loads environment variables via pydantic-settings
and bundles the full SAFETY_CONFIG (Section 10 of the blueprint).
"""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# ── SAFETY_CONFIG ─────────────────────────────────────────────────────────────
# Exact replica of Section 10 in blueprint. Do NOT remove or alter any key.
# These are load-bearing constants — the warmup caps and human-simulation
# delay ranges are enforced by the orchestrator and engagement agent directly
# from this dict at runtime.
SAFETY_CONFIG: dict[str, Any] = {
    # ── Warmup phase (Days 0–14: Sandbox Escape) ─────────────────────────────
    "warmup_phase_days": 14,
    "warmup_max_posts_per_day": 1,
    "warmup_max_replies_per_day": 5,
    "warmup_human_approval_required": True,

    # ── Post-warmup posting limits ────────────────────────────────────────────
    "max_posts_per_day": 3,
    "max_ai_replies_per_day": 30,
    "max_deletions_per_day": 10,
    "min_time_between_posts_minutes": 240,

    # ── Scheduler jitter ──────────────────────────────────────────────────────
    "jitter_range_minutes": 45,        # T_jitter: random ±0–45 min offset per publish
    "jitter_enabled": True,            # cannot be disabled without code change

    # ── Human simulation delays (Engagement Agent) ────────────────────────────
    "reply_read_delay_min_seconds": 45,    # minimum reading delay before drafting reply
    "reply_read_delay_max_seconds": 180,   # maximum reading delay
    "reply_type_delay_min_seconds": 10,    # minimum typing delay before sending reply
    "reply_type_delay_max_seconds": 40,    # maximum typing delay

    # ── Optimal publish windows (US Eastern) ─────────────────────────────────
    "publish_windows_utc_offset_hours": -5.0,
    "publish_windows": [
        {"hour": 9,  "days": ["mon", "tue", "wed", "thu", "fri"]},
        {"hour": 13, "days": ["wed", "thu"]},
        {"hour": 20, "days": ["mon", "tue", "wed", "thu", "fri"]},
    ],
    "avoid_days": ["sat"],

    # ── LLM budget ────────────────────────────────────────────────────────────
    "max_llm_calls_per_hour": 35,

    # ── Human oversight ───────────────────────────────────────────────────────
    "require_human_approval_first_n_days": 14,   # extended to match warmup phase

    # ── Content guardrails ────────────────────────────────────────────────────
    "max_characters_per_post": 500,
    "research_expiry_hours_meme": 48,       # meme research decays faster
    "research_expiry_hours_standard": 72,

    # ── Topic blocklist ───────────────────────────────────────────────────────
    "topic_blocklist": [
        "politics",
        "stocks", "trading", "crypto",
        "religion",
        "violence",
        "productivity",
        "self-improvement",
        "morning routine",
        "hustle",
    ],

    # ── Content guardrails ────────────────────────────────────────────────────
    "max_promotional_tone_score": 0.30,
    "advice_detection_enabled": True,
    "hustle_vocabulary_blocklist": [
        "hustle", "grind", "optimize", "productivity", "discipline",
        "mindset", "manifest", "morning routine", "10x", "rise and grind",
        "level up", "you need to", "you should", "here's how",
    ],

    # ── Monetization gate ─────────────────────────────────────────────────────
    "monetization_module_enabled": False,   # disabled during warmup phase
}


class Settings(BaseSettings):
    """
    Application-wide settings. Reads from .env file (or environment variables).
    All values map directly to the blueprint spec.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── NVIDIA NIM ────────────────────────────────────────────────────────────
    nvidia_nim_api_key: str = ""
    nim_model: str = "meta/llama-3.1-70b-instruct"
    nim_base_url: str = "https://integrate.api.nvidia.com/v1"
    nim_rate_limit_per_minute: int = 40
    nim_rate_limit_soft_cap: int = 35    # buffer under hard limit

    # ── Bluesky API ───────────────────────────────────────────────────────────
    bluesky_handle: str = "asomein.bsky.social"
    bluesky_app_password: str = "no72-emsr-w2gb-jnpg"

    # ── Reddit API ────────────────────────────────────────────────────────────
    reddit_client_id: str = ""
    reddit_client_secret: str = ""
    reddit_user_agent: str = "asomien/1.0"

    # ── Database paths ────────────────────────────────────────────────────────
    memory_db_path: str = "data/memory.db"
    metrics_db_path: str = "data/metrics.db"
    directives_db_path: str = "data/directives.db"
    scheduler_db_path: str = "data/scheduler.db"

    # ── Account warm-up baseline ──────────────────────────────────────────────
    # Set to the actual Threads account creation date.
    # Warmup phase = (today - account_created_at) < 14 days.
    account_created_at: str = ""   # YYYY-MM-DD format; defaults to today on first run

    # ── Scheduler / publish windows ───────────────────────────────────────────
    publish_utc_offset_hours: float = -5.0

    # ── Runtime mode ─────────────────────────────────────────────────────────
    asomien_env: str = "development"   # 'development' | 'production'

    # ── Logging ───────────────────────────────────────────────────────────────
    log_level: str = "INFO"
    log_file: str = "logs/actions.log"

    # ── Paths ─────────────────────────────────────────────────────────────────
    reports_dir: str = "reports/daily"
    data_dir: str = "data"

    @model_validator(mode="after")
    def set_account_created_at_default(self) -> "Settings":
        """If account_created_at is not set, default to today (first run)."""
        if not self.account_created_at:
            self.account_created_at = date.today().isoformat()
        return self

    @property
    def account_created_datetime(self) -> datetime:
        """Parse account_created_at string into a datetime at midnight."""
        return datetime.fromisoformat(self.account_created_at).replace(
            hour=0, minute=0, second=0, microsecond=0
        )

    @property
    def is_warmup_phase(self) -> bool:
        """
        Returns True during the 14-day warmup window.
        Warmup = (now - account_created_at) < warmup_phase_days.
        """
        elapsed = datetime.now() - self.account_created_datetime
        return elapsed < timedelta(days=SAFETY_CONFIG["warmup_phase_days"])

    @property
    def warmup_day_number(self) -> int:
        """Returns the current warmup day (0-indexed: Day 0 is creation day)."""
        elapsed = datetime.now() - self.account_created_datetime
        return max(0, elapsed.days)

    @property
    def is_development(self) -> bool:
        return self.asomien_env.lower() == "development"

    @property
    def is_production(self) -> bool:
        return self.asomien_env.lower() == "production"

    def get_safety_config(self) -> dict[str, Any]:
        """Return the full SAFETY_CONFIG dict."""
        return SAFETY_CONFIG

    def ensure_data_dirs(self) -> None:
        """Create data, logs, and reports directories if they don't exist."""
        for path_str in [self.data_dir, "logs", self.reports_dir]:
            Path(path_str).mkdir(parents=True, exist_ok=True)


# ── Module-level singleton ────────────────────────────────────────────────────
# Import this in all modules: `from asomien.config.settings import settings`
settings = Settings()
