"""
tests/test_phase6.py

High-fidelity integration tests for Phase 6 Core Orchestration.
"""

import pytest
import logging
import sqlite3
from unittest.mock import MagicMock, patch

from asomien.core.orchestrator import MasterOrchestrator
from asomien.agents.engagement_agent import EngagementAgent

logging.getLogger("asomien").setLevel(logging.DEBUG)


@pytest.fixture
def fresh_db(tmp_path):
    """Create a fully migrated memory.db in a temp directory and return its path."""
    from asomien.memory.migrations import run_migrations

    mem = str(tmp_path / "memory.db")
    run_migrations(
        memory_db_path=mem,
        metrics_db_path=str(tmp_path / "metrics.db"),
        directives_db_path=str(tmp_path / "directives.db"),
    )
    return mem


@pytest.fixture
def engine(fresh_db):
    """Return a MemoryEngine bound to the fresh test database."""
    from asomien.memory.engine import MemoryEngine
    return MemoryEngine(db_path=fresh_db)


class StubThreadsAdapter:
    def __init__(self, mentions=None, fail_with_429=False):
        self.mentions = mentions or []
        self.fail_with_429 = fail_with_429
        self.replies_sent = []
        # Support for the newer global search and follow paths so they don't error out
        self.client = MagicMock()
        
    def get_post_replies(self, post_id):
        if self.fail_with_429:
            raise Exception("HTTP 429 Too Many Requests")
        return self.mentions

    def publish_reply(self, text, parent_post_id):
        self.replies_sent.append((parent_post_id, text))
        
    def get_followers(self, limit=20):
        return []
        
    def search_global_posts(self, query, limit=5):
        return []


def test_orchestrator_initialization_checks_db(engine, caplog):
    """Verify MasterOrchestrator checks for config tables."""
    # Table should exist because run_migrations was called
    orchestrator = MasterOrchestrator(memory=engine)
    
    # If we pass a bad db path, it should error
    engine.db_path = "non_existent_db.sqlite"
    MasterOrchestrator(memory=engine)
    assert "Required configuration table 'rules' missing from DB." in caplog.text or "Failed to verify configuration tables" in caplog.text


def test_engagement_cycle_trigger_writes_to_db(engine):
    """Verify engagement cycle writes a PostNode to the SQLite DB."""
    adapter = StubThreadsAdapter(mentions=[{"id": "t1", "text": "hey bot"}])
    agent = EngagementAgent(adapter=adapter, memory=engine)
    agent._human_read_delay = MagicMock()
    agent._human_type_delay = MagicMock()
    orchestrator = MasterOrchestrator(engagement_agent=agent, memory=engine)
    
    # Insert a fake published post so _process_replies finds it and queries replies
    import datetime
    from asomien.memory.nodes import PostNode
    engine.store(PostNode(
        content="hello", post_type="text", is_reply=False, 
        threads_post_id="p1", status="published", created_at=datetime.datetime.now().isoformat()
    ))
    
    orchestrator.run_engagement_cycle()
    
    assert len(adapter.replies_sent) == 1
    assert adapter.replies_sent[0][0] == "t1"
    
    # Check DB
    conn = sqlite3.connect(engine.db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM posts WHERE is_reply = 1").fetchall()
    conn.close()
    
    assert len(rows) == 1
    assert rows[0]["reply_to_threads_id"] == "t1"
    assert rows[0]["status"] == "published"


def test_engagement_agent_empty_mention(engine, caplog):
    """Verify empty mentions are skipped gracefully."""
    adapter = StubThreadsAdapter(mentions=[{"id": "t2", "text": ""}])
    agent = EngagementAgent(adapter=adapter, memory=engine)
    agent._human_read_delay = MagicMock()
    agent._human_type_delay = MagicMock()
    orchestrator = MasterOrchestrator(engagement_agent=agent, memory=engine)
    
    import datetime
    from asomien.memory.nodes import PostNode
    engine.store(PostNode(
        content="hello2", post_type="text", is_reply=False, 
        threads_post_id="p2", status="published", created_at=datetime.datetime.now().isoformat()
    ))
    
    orchestrator.run_engagement_cycle()
    
    assert len(adapter.replies_sent) == 0
    # No explicit log needed, it's silently skipped in the new _process_replies loop


def test_api_rate_limiting_catch(engine, caplog):
    """Verify orchestrator catches 429 and logs retry strategy."""
    adapter = StubThreadsAdapter(fail_with_429=True)
    agent = EngagementAgent(adapter=adapter, memory=engine)
    agent._human_read_delay = MagicMock()
    agent._human_type_delay = MagicMock()
    orchestrator = MasterOrchestrator(engagement_agent=agent, memory=engine)
    
    import datetime
    from asomien.memory.nodes import PostNode
    engine.store(PostNode(
        content="hello3", post_type="text", is_reply=False, 
        threads_post_id="p3", status="published", created_at=datetime.datetime.now().isoformat()
    ))
    
    # In the current implementation, individual tasks (replies/follows) catch their own errors
    # to prevent one bad API call from crashing the whole cycle. To test the Orchestrator's
    # fallback for a critical 429 that *does* bubble up, we simulate it at the agent.run level.
    with patch.object(agent, 'run', side_effect=Exception("HTTP 429 Too Many Requests")):
        orchestrator.run_engagement_cycle()
    
    assert "Rate limit hit (429). Retrying in 15 minutes. Strategy: Backoff." in caplog.text
