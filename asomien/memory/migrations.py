"""
asomien/memory/migrations.py

Executes all three SQLite database schema creations in WAL mode.
Schema is the exact DDL from Section 4 of the blueprint.

Run this module directly to initialize databases:
    python -m asomien.memory.migrations

Or call `run_migrations()` from main.py at startup.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)


# ── SQL: memory.db ────────────────────────────────────────────────────────────

MEMORY_DB_SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS topics (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    parent_id TEXT REFERENCES topics(id),
    relevance_score REAL DEFAULT 0.5,
    niche_alignment REAL DEFAULT 0.5,
    last_researched DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS research_nodes (
    id TEXT PRIMARY KEY,
    topic_id TEXT REFERENCES topics(id),
    source TEXT NOT NULL,
    headline TEXT,
    summary TEXT,
    raw_url TEXT,
    meme_format_detected TEXT,
    cultural_freshness INTEGER DEFAULT 80,
    discovered_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    expiry DATETIME,
    is_active BOOLEAN DEFAULT 1
);

CREATE TABLE IF NOT EXISTS posts (
    id TEXT PRIMARY KEY,
    topic_id TEXT REFERENCES topics(id),
    platform TEXT NOT NULL DEFAULT 'threads',
    content TEXT NOT NULL,
    post_type TEXT DEFAULT 'text',
    status TEXT DEFAULT 'draft',
    scheduled_publish_time DATETIME,
    actual_publish_time DATETIME,
    jitter_offset_minutes INTEGER DEFAULT 0,
    posted_at DATETIME,
    threads_post_id TEXT,
    threads_container_id TEXT,
    permalink TEXT,
    hook_template_used TEXT,
    is_reply BOOLEAN DEFAULT 0,
    reply_to_threads_id TEXT,
    is_sponsored BOOLEAN DEFAULT 0,
    sponsor_campaign_id TEXT,
    pre_score TEXT,
    summary TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS reflections (
    id TEXT PRIMARY KEY,
    post_id TEXT REFERENCES posts(id),
    hook_template_used TEXT,
    sub_niche TEXT,
    generated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    success_factors TEXT,
    failure_factors TEXT,
    hypotheses TEXT,
    lessons_learned TEXT,
    confidence REAL DEFAULT 0.5
);

CREATE TABLE IF NOT EXISTS rules (
    id TEXT PRIMARY KEY,
    rule_text TEXT NOT NULL,
    confidence REAL DEFAULT 0.5,
    evidence TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_validated DATETIME,
    validation_count INTEGER DEFAULT 0,
    decay_rate REAL DEFAULT 0.05,
    is_active BOOLEAN DEFAULT 1
);

CREATE TABLE IF NOT EXISTS personality_traits (
    id TEXT PRIMARY KEY,
    trait_name TEXT NOT NULL UNIQUE,
    trait_type TEXT NOT NULL,
    value REAL DEFAULT 0.5,
    description TEXT,
    last_updated DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    payload TEXT,
    produced_by TEXT,
    consumed_by TEXT,
    status TEXT DEFAULT 'pending',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    consumed_at DATETIME
);

CREATE TABLE IF NOT EXISTS creative_rules (
    id TEXT PRIMARY KEY,
    rule_text TEXT NOT NULL,
    confidence REAL DEFAULT 0.8,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_validated DATETIME,
    decay_rate REAL DEFAULT 0.05,
    is_active BOOLEAN DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_research_nodes_topic ON research_nodes(topic_id);
CREATE INDEX IF NOT EXISTS idx_research_nodes_active ON research_nodes(is_active, expiry);
CREATE INDEX IF NOT EXISTS idx_posts_status ON posts(status);
CREATE INDEX IF NOT EXISTS idx_posts_topic ON posts(topic_id);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type, status);
"""


# ── SQL: metrics.db ───────────────────────────────────────────────────────────

METRICS_DB_SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS post_metrics (
    id TEXT PRIMARY KEY,
    post_id TEXT NOT NULL,
    threads_post_id TEXT NOT NULL,
    snapshot_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    views INTEGER DEFAULT 0,
    likes INTEGER DEFAULT 0,
    replies INTEGER DEFAULT 0,
    reposts INTEGER DEFAULT 0,
    quotes INTEGER DEFAULT 0,
    shares INTEGER DEFAULT 0,
    creator_engagement_score REAL DEFAULT 0.0
);

CREATE TABLE IF NOT EXISTS audience_snapshots (
    id TEXT PRIMARY KEY,
    snapshot_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    followers_count INTEGER DEFAULT 0,
    profile_views INTEGER DEFAULT 0,
    link_clicks INTEGER DEFAULT 0,
    total_likes INTEGER DEFAULT 0,
    total_replies INTEGER DEFAULT 0,
    total_reposts INTEGER DEFAULT 0,
    total_quotes INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS audience_demographics (
    id TEXT PRIMARY KEY,
    snapshot_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    breakdown_type TEXT NOT NULL,
    breakdown_value TEXT NOT NULL,
    count INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS daily_stats (
    id TEXT PRIMARY KEY,
    date TEXT NOT NULL,
    posts_published INTEGER DEFAULT 0,
    replies_published INTEGER DEFAULT 0,
    total_views INTEGER DEFAULT 0,
    total_likes INTEGER DEFAULT 0,
    total_replies_received INTEGER DEFAULT 0,
    total_reposts INTEGER DEFAULT 0,
    total_quotes INTEGER DEFAULT 0,
    total_shares INTEGER DEFAULT 0,
    audience_growth INTEGER DEFAULT 0,
    avg_creator_engagement_score REAL DEFAULT 0.0
);

CREATE INDEX IF NOT EXISTS idx_post_metrics_post ON post_metrics(post_id);
CREATE INDEX IF NOT EXISTS idx_daily_stats_date ON daily_stats(date);
"""


# ── SQL: directives.db ────────────────────────────────────────────────────────

DIRECTIVES_DB_SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS directives (
    id TEXT PRIMARY KEY,
    directive_type TEXT NOT NULL,
    content TEXT,
    priority INTEGER DEFAULT 5,
    status TEXT DEFAULT 'active',
    start_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    end_time DATETIME,
    metadata TEXT
);

CREATE TABLE IF NOT EXISTS campaigns (
    id TEXT PRIMARY KEY,
    directive_id TEXT REFERENCES directives(id),
    brand_name TEXT NOT NULL,
    product_description TEXT,
    requirements TEXT,
    links TEXT,
    restrictions TEXT,
    posts_target INTEGER DEFAULT 3,
    posts_published INTEGER DEFAULT 0,
    status TEXT DEFAULT 'active',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Removed: DROP TABLE IF EXISTS monetization_signals (was destroying data on every restart)


CREATE TABLE IF NOT EXISTS reports (
    id TEXT PRIMARY KEY,
    report_type TEXT NOT NULL,
    generated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    content TEXT NOT NULL,
    period_start DATETIME,
    period_end DATETIME
);

CREATE TABLE IF NOT EXISTS warmup_log (
    id TEXT PRIMARY KEY,
    day_number INTEGER NOT NULL,
    posts_published INTEGER DEFAULT 0,
    replies_published INTEGER DEFAULT 0,
    phase_status TEXT DEFAULT 'active',
    logged_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS follow_history (
    id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    did TEXT NOT NULL UNIQUE,
    followed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    status TEXT DEFAULT 'active'
);

CREATE INDEX IF NOT EXISTS idx_directives_status ON directives(status);
CREATE INDEX IF NOT EXISTS idx_warmup_log_day ON warmup_log(day_number);
"""


# ── Migration runner ──────────────────────────────────────────────────────────

def _init_db(db_path: str, schema_sql: str) -> None:
    """
    Open a SQLite database at db_path, execute schema_sql (DDL statements),
    and verify WAL mode is active.

    Uses executescript() which handles multi-statement SQL.
    WAL mode is set by the PRAGMA at the top of each schema block.
    """
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(path))
    try:
        conn.executescript(schema_sql)
        conn.commit()

        # Verify WAL mode is active
        cursor = conn.execute("PRAGMA journal_mode;")
        mode = cursor.fetchone()[0]
        if mode != "wal":
            raise RuntimeError(
                f"[migrations] WAL mode not active on {db_path}. "
                f"Got '{mode}' instead. Check SQLite version."
            )

        logger.info(f"[migrations] {db_path}: schema OK, WAL mode confirmed.")
    finally:
        conn.close()


def run_migrations(
    memory_db_path: str = "data/memory.db",
    metrics_db_path: str = "data/metrics.db",
    directives_db_path: str = "data/directives.db",
) -> None:
    """
    Initialize all three SQLite databases with their schemas.
    All databases are opened in WAL mode as required by the blueprint.

    Safe to call multiple times — all CREATE TABLE statements use IF NOT EXISTS.
    """
    logger.info("[migrations] Running schema migrations...")

    _init_db(memory_db_path, MEMORY_DB_SCHEMA)
    _init_db(metrics_db_path, METRICS_DB_SCHEMA)
    _init_db(directives_db_path, DIRECTIVES_DB_SCHEMA)

    logger.info("[migrations] All 3 databases initialized in WAL mode. ✓")


def verify_wal_mode(db_path: str) -> bool:
    """
    Returns True if the given database is in WAL journal mode.
    Used by tests to assert compliance.
    """
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.execute("PRAGMA journal_mode;")
        mode = cursor.fetchone()[0]
        return mode == "wal"
    finally:
        conn.close()


def get_table_names(db_path: str) -> list[str]:
    """
    Returns list of user-created table names in the given database.
    Used by tests to verify schema creation.
    """
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';"
        )
        return [row[0] for row in cursor.fetchall()]
    finally:
        conn.close()


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    run_migrations()
    print("Databases initialized.")
    sys.exit(0)
