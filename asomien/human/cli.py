"""
asomien/human/cli.py

CLI Controller for interacting with the Asomien memory database.
Provides commands like status, approve, and directive logging.
"""

import sqlite3
import logging
import uuid
from datetime import datetime

logger = logging.getLogger(__name__)

class CLIController:
    def __init__(self, memory_db_path="data/memory.db", directives_db_path="data/directives.db"):
        self.memory_db_path = memory_db_path
        self.directives_db_path = directives_db_path

    def approve_post(self, post_id: str):
        """Query posts where status='draft' and update to 'queued'."""
        try:
            with sqlite3.connect(self.memory_db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT id FROM posts WHERE id=? AND status='draft'", (post_id,))
                if cursor.fetchone():
                    cursor.execute("UPDATE posts SET status='queued' WHERE id=?", (post_id,))
                    conn.commit()
                    print(f"Success: Post {post_id} approved and queued for publish.")
                else:
                    print(f"Error: Post {post_id} not found or not in 'draft' status.")
        except Exception as e:
            print(f"Database error: {e}")

    def status(self):
        """Query warmup_log and posts to summarize the daily state."""
        published_count = 0
        draft_count = 0
        queued_count = 0
        warmup_day = 0

        # Gather Posts Status
        try:
            with sqlite3.connect(self.memory_db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM posts WHERE status='published'")
                row = cursor.fetchone()
                published_count = row[0] if row else 0
                
                cursor.execute("SELECT COUNT(*) FROM posts WHERE status='draft'")
                row = cursor.fetchone()
                draft_count = row[0] if row else 0

                cursor.execute("SELECT COUNT(*) FROM posts WHERE status='queued'")
                row = cursor.fetchone()
                queued_count = row[0] if row else 0
        except Exception as e:
            print(f"Posts database error: {e}")

        # Gather Warmup Status
        try:
            with sqlite3.connect(self.directives_db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='warmup_log'")
                if cursor.fetchone():
                    cursor.execute("SELECT MAX(day_number) FROM warmup_log")
                    res = cursor.fetchone()
                    warmup_day = res[0] if res and res[0] else 0
        except Exception as e:
            print(f"Directives database error: {e}")

        print("\n=== ASOMIEN SYSTEM STATUS ===")
        print(f"Warmup Day:                {warmup_day}")
        print(f"Published Posts Total:     {published_count}")
        print(f"Posts Queued for Publish:  {queued_count}")
        print(f"Draft Posts Pending Review:{draft_count}")
        print("=============================\n")

    def add_directive(self, text: str):
        """Add a human override directive into the directives DB."""
        try:
            with sqlite3.connect(self.directives_db_path) as conn:
                cursor = conn.cursor()
                directive_id = str(uuid.uuid4())
                cursor.execute(
                    "INSERT INTO directives (id, directive_type, content, start_time) VALUES (?, ?, ?, ?)",
                    (directive_id, "human_override", text, datetime.utcnow().isoformat())
                )
                conn.commit()
                print(f"Directive added successfully. ID: {directive_id}")
        except Exception as e:
            print(f"Database error while adding directive: {e}")
