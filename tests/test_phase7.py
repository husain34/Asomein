"""
tests/test_phase7.py

Integration tests for Phase 7: Persona Injection and Semantic Search.
"""

import pytest
import sqlite3
from unittest.mock import patch, MagicMock

from asomien.memory.engine import MemoryEngine
from asomien.agents.engagement_agent import EngagementAgent
from asomien.memory.nodes import PostNode
from asomien.memory.embedder import Embedder

try:
    import sentence_transformers
    HAS_SENTENCE_TRANSFORMERS = True
except ImportError:
    HAS_SENTENCE_TRANSFORMERS = False


@pytest.fixture
def fresh_db(tmp_path):
    """Create a fresh in-memory database using migrations."""
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
    """Return a MemoryEngine bound to the test database."""
    return MemoryEngine(db_path=fresh_db)


class StubThreadsAdapter:
    def __init__(self, mentions=None):
        self.mentions = mentions or []
        self.replies_sent = []
        self.client = MagicMock()

    def get_post_replies(self, post_id):
        return self.mentions

    def publish_reply(self, text, parent_post_id):
        self.replies_sent.append((parent_post_id, text))
        
    def get_followers(self, limit=20):
        return []
        
    def search_global_posts(self, query, limit=5):
        return []


@pytest.mark.skipif(not HAS_SENTENCE_TRANSFORMERS, reason="sentence-transformers not installed")
def test_embedder_vector_verification():
    """Verify Embedder returns correct vector shapes."""
    embedder = Embedder(model_name="all-MiniLM-L6-v2")
    vec = embedder.get_embedding("test string for embedding")
    
    assert isinstance(vec, list)
    assert len(vec) == 384
    assert all(isinstance(x, float) for x in vec)


@pytest.mark.skipif(not HAS_SENTENCE_TRANSFORMERS, reason="sentence-transformers not installed")
def test_similarity_search_returns_relevant_nodes(engine):
    """Verify similarity_search finds semantic matches over exact string matches."""
    # Insert posts with different themes
    engine.store(PostNode(content="feeling extremely tired today", post_type="text", status="published"))
    engine.store(PostNode(content="the weather is quite sunny outside", post_type="text", status="published"))
    engine.store(PostNode(content="i love eating apples and bananas", post_type="text", status="published"))
    
    # Query for "exhausted" which is semantically close to "tired" but shares no words
    results = engine.similarity_search("exhausted", limit=1)
    
    assert len(results) == 1
    # It should match the tired post
    assert "tired" in results[0]["content"]


@patch.object(MemoryEngine, "similarity_search")
def test_persona_injection_and_constraint_enforcement(mock_search, engine):
    """
    Verify EngagementAgent retrieves context from DB and properly constraints output.
    """
    mock_search.return_value = [{"content": "just spent 4 hours staring at a wall."}]
    
    adapter = StubThreadsAdapter(mentions=[{"id": "m1", "text": "how do you stay productive?"}])
    agent = EngagementAgent(adapter=adapter, memory=engine)
    
    # Insert a fake published post so _process_replies has a post to check
    import datetime
    engine.store(PostNode(
        content="hello", post_type="text", is_reply=False, 
        threads_post_id="p1", status="published", created_at=datetime.datetime.now().isoformat()
    ))
    
    # Disable delays for fast testing
    agent._human_read_delay = MagicMock()
    agent._human_type_delay = MagicMock()
    
    with patch("asomien.llm.client.NIMClient.complete") as mock_complete:
        # Mock LLM returning a valid persona response
        mock_response = "i don't even know what productivity is. literally just rotting in bed right now."
        mock_complete.return_value = mock_response
        
        agent.monitor_inbound()
        
        # 1. Integration Logic: Verify MemoryEngine context was injected into the LLM call
        assert mock_complete.call_count >= 1
        # The first call is to generate_reply
        sent_prompt = mock_complete.call_args_list[0][1]["user_prompt"]
        
        assert "just spent 4 hours staring at a wall." in sent_prompt
        assert "how do you stay productive?" in sent_prompt
        
        # 2. Verify adapter received the generated reply (not the fallback string)
        assert len(adapter.replies_sent) == 1
        reply_text = adapter.replies_sent[0][1]
        
        assert reply_text != "not to be dramatic but same."
        assert reply_text != "same tbh."
        assert reply_text == mock_response
        
        # 3. Constraint Enforcement: Check properties of the response
        # Strictly lowercase
        assert reply_text == reply_text.lower()
        
        # No emojis (basic ascii check since we mocked without emojis)
        assert all(ord(c) < 128 for c in reply_text), "Found non-ASCII characters (potential emojis)"
        
        # 1-2 sentences constraint
        sentences = [s for s in reply_text.replace("?", ".").replace("!", ".").split(".") if s.strip()]
        assert 1 <= len(sentences) <= 2


@patch.object(MemoryEngine, "similarity_search")
def test_engagement_agent_calls_similarity_search(mock_search, engine):
    """Verify EngagementAgent actively calls similarity_search."""
    mock_search.return_value = [{"content": "mocked similar post"}]
    
    adapter = StubThreadsAdapter(mentions=[{"id": "m2", "text": "testing search"}])
    agent = EngagementAgent(adapter=adapter, memory=engine)
    
    import datetime
    engine.store(PostNode(
        content="hello", post_type="text", is_reply=False, 
        threads_post_id="p2", status="published", created_at=datetime.datetime.now().isoformat()
    ))
    
    agent._human_read_delay = MagicMock()
    agent._human_type_delay = MagicMock()
    
    with patch("asomien.llm.client.NIMClient.complete") as mock_complete:
        mock_complete.return_value = "response"
        agent.monitor_inbound()
        
        mock_search.assert_called_once_with("testing search", limit=3)
        
        # Check that 'mocked similar post' made it into the prompt (first LLM call)
        sent_prompt = mock_complete.call_args_list[0][1]["user_prompt"]
        assert "mocked similar post" in sent_prompt
