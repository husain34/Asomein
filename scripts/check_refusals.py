import sqlite3

conn = sqlite3.connect('data/memory.db')

total = conn.execute("SELECT COUNT(*) FROM posts WHERE is_reply=1").fetchone()[0]

refusals = conn.execute(
    "SELECT COUNT(*) FROM posts WHERE is_reply=1 AND ("
    "content LIKE '%I cannot%' OR "
    "content LIKE '%cannot provide%' OR "
    "content LIKE '%cannot help%' OR "
    "content LIKE '%as an AI%' OR "
    "content LIKE '%I am unable%'"
    ")"
).fetchone()[0]

print(f"Total replies published : {total}")
print(f"Refusal replies         : {refusals}")
print(f"Clean replies           : {total - refusals}")
print()
print("Sample refusals:")
rows = conn.execute(
    "SELECT content FROM posts WHERE is_reply=1 AND ("
    "content LIKE '%I cannot%' OR "
    "content LIKE '%cannot provide%' OR "
    "content LIKE '%cannot help%' OR "
    "content LIKE '%as an AI%' OR "
    "content LIKE '%I am unable%'"
    ") LIMIT 10"
).fetchall()
for r in rows:
    print(f"  - {r[0][:100]}")

conn.close()
