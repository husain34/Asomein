import sqlite3
import os
import sys

# Ensure we can import from asomien
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from asomien.config.settings import settings
from atproto import Client

def main():
    handle = settings.bluesky_handle
    password = settings.bluesky_app_password

    print(f"Logging in as {handle}...")
    client = Client()
    try:
        client.login(handle, password)
    except Exception as e:
        print(f"Failed to login: {e}")
        return

    print("Fetching recent posts from Bluesky...")
    try:
        # Get up to 100 recent posts from the bot's own profile
        # atproto SDK uses client.get_author_feed
        response = client.get_author_feed(actor=handle, limit=100)
        feed_items = response.feed
    except Exception as e:
        print(f"Failed to fetch feed: {e}")
        return

    db_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'memory.db')
    print(f"Connecting to DB at {db_path}...")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    
    # Get all published posts that are missing a URI
    cursor = conn.execute(
        "SELECT id, content FROM posts WHERE status='published' AND (threads_post_id = '' OR threads_post_id IS NULL)"
    )
    missing_posts = cursor.fetchall()
    print(f"Found {len(missing_posts)} posts in memory.db missing URIs.")

    updated_count = 0
    for db_post in missing_posts:
        db_text = db_post['content'].strip()
        match_uri = None
        
        for item in feed_items:
            # item.post.record.text contains the actual text content
            try:
                post_text = item.post.record.text.strip()
                if post_text == db_text:
                    match_uri = item.post.uri
                    break
            except Exception:
                pass
                
        if match_uri:
            conn.execute("UPDATE posts SET threads_post_id = ? WHERE id = ?", (match_uri, db_post['id']))
            updated_count += 1
            print(f"Matched and updated post ID: {db_post['id']} -> {match_uri}")

    conn.commit()
    conn.close()
    
    print(f"Done. Successfully backfilled URIs for {updated_count} posts.")

if __name__ == "__main__":
    main()
