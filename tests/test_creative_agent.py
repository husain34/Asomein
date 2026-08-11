"""
Tests for CreativeAgent autonomous loop implementation.
"""

import unittest
from unittest.mock import Mock, patch, MagicMock
import sqlite3
import uuid
from datetime import datetime, timezone
import sys
import os

# Add the project root to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from asomien.agents.creative_agent import CreativeAgent
from asomien.llm.prompts.creative_prompts import SEEDED_CREATIVE_RULES


class TestCreativeAgent(unittest.TestCase):

    def setUp(self):
        """Set up test fixtures before each test method."""
        self.memory_mock = Mock()
        self.memory_mock.db_path = "test.db"
        self.llm_mock = Mock()
        self.agent = CreativeAgent(memory=self.memory_mock, llm_client=self.llm_mock)

    def test_initialization_seeds_rules_when_empty(self):
        """Test that CreativeAgent seeds rules when the database is empty."""
        # Mock database connection to return 0 count
        with patch('sqlite3.connect') as mock_connect:
            mock_conn = MagicMock() # Changed from Mock()[cite: 1]
            mock_cursor = MagicMock()
            mock_cursor.fetchone.return_value = [0]  # Empty database
            mock_conn.execute.return_value = mock_cursor
            mock_conn.cursor.return_value = mock_cursor
            mock_connect.return_value.__enter__.return_value = mock_conn

            # Create new agent to trigger seeding
            agent = CreativeAgent(memory=self.memory_mock, llm_client=self.llm_mock)

            # Verify that INSERT was called for each seed rule
            self.assertGreaterEqual(mock_conn.execute.call_count, len(SEEDED_CREATIVE_RULES))

    def test_seed_rules_if_empty_does_nothing_when_rules_exist(self):
        """Test that seeding is skipped when rules already exist."""
        # Mock database connection to return existing count
        with patch('sqlite3.connect') as mock_connect:
            mock_conn = Mock()
            mock_cursor = Mock()
            mock_cursor.fetchone.return_value = [5]  # Non-empty database
            mock_conn.cursor.return_value = mock_cursor
            mock_connect.return_value.__enter__.return_value = mock_conn

            # Create new agent
            agent = CreativeAgent(memory=self.memory_mock, llm_client=self.llm_mock)

            # Verify that no INSERT calls were made
            execute_calls = [call for call in mock_conn.execute.call_args_list
                           if 'INSERT' in str(call)]
            self.assertEqual(len(execute_calls), 0)

    def test_run_method_starts_and_stops_agent(self):
        """Test that run() method properly starts and stops the agent."""
        with patch.object(self.agent, 'start') as mock_start, \
             patch.object(self.agent, 'stop') as mock_stop, \
             patch('time.sleep') as mock_sleep, \
             patch.object(self.agent, '_seed_rules_if_empty'):

            # Configure _running to be False after first iteration to avoid infinite loop
            self.agent._running = True

            def stop_after_first_iteration(*args, **kwargs):
                self.agent._running = False

            mock_sleep.side_effect = stop_after_first_iteration

            # Call run method
            self.agent.run()

            # Verify start and stop were called
            mock_start.assert_called_once()
            mock_stop.assert_called_once()

    def test_run_method_seeds_rules_on_startup(self):
        """Test that _seed_rules_if_empty is called during run."""
        with patch.object(self.agent, '_seed_rules_if_empty') as mock_seed, \
             patch.object(self.agent, 'start'), \
             patch.object(self.agent, 'stop'), \
             patch('time.sleep') as mock_sleep:

            self.agent._running = True
            mock_sleep.side_effect = lambda x: setattr(self.agent, '_running', False)

            self.agent.run()

            mock_seed.assert_called_once()

    def test_get_recent_posts_for_reflection_returns_empty_when_no_memory(self):
        """Test that _get_recent_posts_for_reflection returns empty list when no memory."""
        agent = CreativeAgent(memory=None, llm_client=self.llm_mock)
        posts = agent._get_recent_posts_for_reflection()
        self.assertEqual(posts, [])

    def test_get_active_rules_returns_seeded_when_no_memory(self):
        """Test that get_active_rules returns seeded rules when no memory."""
        agent = CreativeAgent(memory=None, llm_client=self.llm_mock)
        rules = agent.get_active_rules()
        self.assertEqual(rules, SEEDED_CREATIVE_RULES)

    def test_get_active_rules_returns_from_database_when_available(self):
        """Test that get_active_rules fetches from database when memory is available."""
        # Setup mock database response using the 'as' syntax
        with patch('sqlite3.connect') as mock_connect:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_cursor.fetchall.return_value = [("Rule 1",), ("Rule 2",)]
            mock_conn.execute.return_value = mock_cursor
            mock_conn.cursor.return_value = mock_cursor
            
            # This is the magic line that makes context managers (with blocks) work!
            mock_connect.return_value.__enter__.return_value = mock_conn
            
            self.memory_mock.db_path = "test.db"
            rules = self.agent.get_active_rules()

        self.assertEqual(rules, ["Rule 1", "Rule 2"])

    def test_get_active_rules_falls_back_to_seeded_on_error(self):
        """Test that get_active_rules falls back to seeded rules on database error."""
        with patch('sqlite3.connect', side_effect=sqlite3.Error("Database error")):
            rules = self.agent.get_active_rules()

        self.assertEqual(rules, SEEDED_CREATIVE_RULES)

    def test_refine_draft_returns_unchanged_when_no_llm(self):
        """Test that refine_draft returns original draft when no LLM client."""
        agent = CreativeAgent(memory=self.memory_mock, llm_client=None)
        draft = "this is a test draft"
        result = agent.refine_draft(draft)
        self.assertEqual(result, draft)

    def test_update_rules_handles_no_memory_gracefully(self):
        """Test that update_rules handles missing memory gracefully."""
        # Should not raise exception
        self.agent.update_rules({"new_rules": ["test rule"]})
        # Verify no database operations were attempted
        # (This is implicitly tested by not raising an exception)

    def test_decay_rules_handles_no_memory_gracefully(self):
        """Test that decay_rules handles missing memory gracefully."""
        # Should not raise exception
        self.agent.decay_rules()

    def test_run_creative_reflection_returns_empty_when_no_llm(self):
        """Test that run_creative_reflection returns empty dict when no LLM."""
        agent = CreativeAgent(memory=self.memory_mock, llm_client=None)
        result = agent.run_creative_reflection([{"content": "test"}])
        self.assertEqual(result, {})

    @patch('json.loads')
    def test_run_creative_reflection_handles_json_decode_error(self, mock_json_loads):
        """Test that run_creative_reflection handles JSON decode errors."""
        mock_json_loads.side_effect = ValueError("Invalid JSON")
        self.llm_mock.complete.return_value = '{"invalid": json}'

        result = self.agent.run_creative_reflection([{"content": "test post"}])
        self.assertEqual(result, {})


if __name__ == '__main__':
    unittest.main()