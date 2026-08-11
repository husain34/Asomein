"""
Tests for CriticAgent Phase 8 method implementations.
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

from asomien.agents.critic_agent import CriticAgent
from asomien.memory.nodes import PostNode, ReflectionNode


class TestCriticAgent(unittest.TestCase):

    def setUp(self):
        """Set up test fixtures before each test method."""
        self.memory_mock = Mock()
        self.llm_mock = Mock()
        self.agent = CriticAgent(llm_client=self.llm_mock, memory=self.memory_mock)

    def test_post_publish_analysis_handles_no_memory_gracefully(self):
        """Test that post_publish_analysis handles missing memory gracefully."""
        agent = CriticAgent(llm_client=self.llm_mock, memory=None)
        # Should not raise exception
        agent.post_publish_analysis(PostNode(id="test", content="test"),
                                  Mock(creator_engagement_score=5.0))
    
    @patch('asomien.agents.critic_agent.logger')
    def test_post_publish_analysis_logs_when_called(self, mock_logger):
        """Test that post_publish_analysis logs when called with memory."""
        post = PostNode(id="test123", content="test content")
        metrics = Mock()
        metrics.creator_engagement_score = 7.5
        metrics.views = 1000
        metrics.likes = 50
        metrics.replies = 10

        self.agent.post_publish_analysis(post, metrics)

        # Verify logging was called
        mock_logger.info.assert_called()

    def test_generate_hypothesis_returns_empty_for_empty_observation(self):
        """Test that generate_hypothesis returns empty string for empty observation."""
        result = self.agent.generate_hypothesis("")
        self.assertEqual(result, "")

        result = self.agent.generate_hypothesis("   ")
        self.assertEqual(result, "")

    def test_generate_hypothesis_returns_proper_hypothesis(self):
        """Test that generate_hypothesis returns appropriate hypotheses."""
        # Test low engagement
        result = self.agent.generate_hypothesis("engagement is low")
        self.assertIn("Hypothesis:", result)
        self.assertIn("specificity and relatability", result)

        # Test low views
        result = self.agent.generate_hypothesis("views are poor")
        self.assertIn("Hypothesis:", result)
        self.assertIn("trending hashtags", result)

        # Test low likes
        result = self.agent.generate_hypothesis("likes are low")
        self.assertIn("Hypothesis:", result)
        self.assertIn("hook strength and humor density", result)

        # Test low replies
        result = self.agent.generate_hypothesis("replies are poor")
        self.assertIn("Hypothesis:", result)
        self.assertIn("open-ended questions", result)

        # Test generic observation
        result = self.agent.generate_hypothesis("something else")
        self.assertIn("Hypothesis:", result)
        self.assertIn("Adjusting content approach", result)

    def test_generate_reflection_handles_no_memory_gracefully(self):
        """Test that generate_reflection handles missing memory gracefully."""
        agent = CriticAgent(llm_client=self.llm_mock, memory=None)
        # Should not raise exception
        agent.generate_reflection(PostNode(id="test", content="test"),
                                Mock(creator_engagement_score=5.0))

    def test_generate_reflection_creates_and_stores_reflection(self):
        """Test that generate_reflection creates and stores a ReflectionNode."""
        post = PostNode(id="post123", content="test content")
        metrics = Mock()
        metrics.creator_engagement_score = 7.5
        metrics.views = 1500
        metrics.likes = 75
        metrics.replies = 15
        metrics.reposts = 5
        metrics.quotes = 2

        self.agent.generate_reflection(post, metrics)

        # Verify that memory.store was called
        self.memory_mock.store.assert_called_once()

        # Verify the stored object is a ReflectionNode
        stored_arg = self.memory_mock.store.call_args[0][0]
        self.assertIsInstance(stored_arg, ReflectionNode)
        self.assertEqual(stored_arg.post_id, "post123")

    def test_update_rules_handles_no_memory_gracefully(self):
        """Test that update_rules handles missing memory gracefully."""
        # Should not raise exception
        self.agent.update_rules({"trait_adjustments": {}, "new_rules": []})

    def test_decay_rules_handles_no_memory_gracefully(self):
        """Test that decay_rules handles missing memory gracefully."""
        # Should not raise exception
        self.agent.decay_rules()

    def test_consolidate_memory_is_deferred_to_phase8(self):
        """Test that consolidate_memory logs deferral message."""
        with patch('asomien.agents.critic_agent.logger') as mock_logger:
            self.agent.consolidate_memory()
            mock_logger.debug.assert_called_with("[CriticAgent] consolidate_memory deferred to Phase 8.")

    def test_run_daily_reflection_returns_empty_when_no_llm(self):
        """Test that run_daily_reflection returns empty dict when no LLM."""
        agent = CriticAgent(memory=self.memory_mock, llm_client=None)
        result = agent.run_daily_reflection([{"content": "test"}])
        self.assertEqual(result, {})

    @patch('json.loads')
    def test_run_daily_reflection_handles_json_decode_error(self, mock_json_loads):
        """Test that run_daily_reflection handles JSON decode errors."""
        mock_json_loads.side_effect = ValueError("Invalid JSON")
        self.llm_mock.complete.return_value = '{"invalid": json}'

        result = self.agent.run_daily_reflection([{"content": "test post"}])
        self.assertEqual(result, {})


if __name__ == '__main__':
    unittest.main()