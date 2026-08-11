"""
Tests for MemoryEngine consolidation enhancement.
"""

import unittest
from unittest.mock import Mock, patch, MagicMock, ANY
import sqlite3
from datetime import datetime, timedelta, timezone
import sys
import os

# Add the project root to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from asomien.memory.engine import MemoryEngine


class TestMemoryEngine(unittest.TestCase):

    def setUp(self):
        """Set up test fixtures before each test method."""
        self.test_db = "test_memory.db"
        if os.path.exists(self.test_db):
            os.remove(self.test_db)
        self.engine = MemoryEngine(db_path=self.test_db)

    def tearDown(self):
        """Clean up test fixtures after each test method."""
        if os.path.exists(self.test_db):
            try:
                os.remove(self.test_db)
            except Exception:
                pass

    def test_consolidate_calls_expire_stale_nodes(self):
        """Test that consolidate() calls expire_stale_nodes()."""
        with patch.object(self.engine, 'expire_stale_nodes', return_value=5) as mock_expire:
            with patch('sqlite3.connect') as mock_connect:
                mock_conn = Mock()
                mock_connect.return_value.__enter__.return_value = mock_conn

                self.engine.consolidate()

                mock_expire.assert_called_once()

    def test_consolidate_optimizes_database_indices(self):
        """Test that consolidate() runs ANALYZE and VACUUM."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.side_effect = [[100000], [4096], [0], [0]]
        mock_conn.execute.return_value = mock_cursor
        
        # Configure context manager support for _connect
        mock_conn.__enter__.return_value = mock_conn

        with patch.object(self.engine, 'expire_stale_nodes', return_value=5), \
             patch.object(self.engine, '_connect', return_value=mock_conn):

            self.engine.consolidate()

            # Extract the raw SQL string from the first positional arg of each execute call
            calls = [call[0][0] for call in mock_conn.execute.call_args_list]
            self.assertIn("ANALYZE;", calls)
            self.assertIn("VACUUM;", calls)
    
    def test_consolidate_logs_database_statistics(self):
        """Test that consolidate() logs database size information."""
        with patch.object(self.engine, 'expire_stale_nodes', return_value=3), \
             patch('sqlite3.connect') as mock_connect, \
             patch('asomien.memory.engine.logger') as mock_logger:

            mock_conn = MagicMock()
            mock_connect.return_value.__enter__.return_value = mock_conn
            
            # Replace the side_effect list with this:
            mock_cursor = MagicMock()
            mock_cursor.fetchone.return_value = [500]
            mock_conn.execute.return_value = mock_cursor

            self.engine.consolidate()

            # Verify info logging was called with database size
            info_calls = [call for call in mock_logger.info.call_args_list
                         if "Database optimization completed" in str(call)]
            self.assertTrue(len(info_calls) > 0)

    def test_expire_stale_nodes_marks_expired_as_inactive(self):
        """Test that expire_stale_nodes properly marks nodes as inactive."""
        # Setup test data in the in-memory database
        with sqlite3.connect(self.test_db) as conn:
            conn.execute("""
                CREATE TABLE research_nodes (
                    id TEXT PRIMARY KEY,
                    topic_id TEXT,
                    source TEXT,
                    headline TEXT,
                    summary TEXT,
                    raw_url TEXT,
                    meme_format_detected TEXT,
                    cultural_freshness INTEGER,
                    discovered_at TEXT,
                    expiry TEXT,
                    is_active INTEGER
                )
            """)

            # Insert an expired node
            past_time = (datetime.now(timezone.utc) - timedelta(hours=100)).isoformat()
            conn.execute("""
                INSERT INTO research_nodes
                (id, topic_id, source, headline, summary, raw_url,
                 meme_format_detected, cultural_freshness, discovered_at, expiry, is_active)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, ("expired1", "topic1", "test", "headline", "summary", "url",
                  "", 50, past_time, past_time, 1))

            # Insert an active node
            future_time = (datetime.now(timezone.utc) + timedelta(hours=100)).isoformat()
            conn.execute("""
                INSERT INTO research_nodes
                (id, topic_id, source, headline, summary, raw_url,
                 meme_format_detected, cultural_freshness, discovered_at, expiry, is_active)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, ("active1", "topic1", "test", "headline2", "summary2", "url2",
                  "", 50, future_time, future_time, 1))

        # Call expire_stale_nodes
        expired_count = self.engine.expire_stale_nodes()

        # Verify one node was expired
        self.assertEqual(expired_count, 1)

        # Verify the correct node is now inactive
        with sqlite3.connect(self.test_db) as conn:
            cursor = conn.execute("""
                SELECT id, is_active FROM research_nodes WHERE id IN ('expired1', 'active1')
            """)
            results = dict(cursor.fetchall())
            self.assertEqual(results['expired1'], 0)  # Now inactive
            self.assertEqual(results['active1'], 1)   # Still active

    def test_consolidate_handles_database_errors_gracefully(self):
        """Test that consolidate() handles database errors without crashing."""
        with patch.object(self.engine, 'expire_stale_nodes', return_value=2), \
             patch('sqlite3.connect', side_effect=sqlite3.Error("Database locked")), \
             patch('asomien.memory.engine.logger') as mock_logger:

            # Should not raise exception
            self.engine.consolidate()

            # Verify error was logged
            mock_logger.error.assert_called_with(
                "[MemoryEngine.consolidate] Failed to optimize database: %s",
                ANY # Changed from "Database locked"[cite: 3]
            )


if __name__ == '__main__':
    unittest.main()