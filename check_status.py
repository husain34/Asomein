import sqlite3
from datetime import datetime

conn = sqlite3.connect('data/memory.db')

r1 = conn.execute("SELECT COUNT(*) FROM posts WHERE status='published' AND date(created_at)=date('now')").fetchone()
r2 = conn.execute("SELECT content, created_at FROM posts WHERE status='published' ORDER BY created_at DESC LIMIT 1").fetchone()
r3 = conn.execute("SELECT COUNT(*) FROM posts WHERE status='published'").fetchone()

print("=== POST STATUS ===")
print(f"Posts published TODAY: {r1[0]}")
print(f"Total posts ever:      {r3[0]}")
print(f"Last post content:     {r2[0] if r2 else 'None'}")
print(f"Last post timestamp:   {r2[1] if r2 else 'None'}")

# How long ago was the last post?
if r2 and r2[1]:
    try:
        last_dt = datetime.fromisoformat(r2[1].replace('Z', '+00:00').split('+')[0])
        diff = datetime.utcnow() - last_dt
        hours = diff.total_seconds() / 3600
        print(f"Hours since last post: {hours:.1f}h")
    except Exception as e:
        print(f"Could not parse timestamp: {e}")
