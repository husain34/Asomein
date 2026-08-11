import os
from dotenv import load_dotenv
import sqlite3

# Load env
load_dotenv()

from asomien.llm.client import NIMClient
from asomien.agents.critic_agent import CriticAgent

directives_db_path = r"c:\Users\HusainPc\Desktop\Asomein\data\directives.db"

def get_active_rules():
    with sqlite3.connect(directives_db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT id, content FROM directives WHERE status = 'active'").fetchall()
        return [r["content"] for r in rows]

print("--- Active Rules BEFORE Test ---")
for r in get_active_rules():
    print(f"- {r}")

print("\n--- Initializing Critic Agent ---")
try:
    llm = NIMClient()
    agent = CriticAgent(llm_client=llm)
    print("Calling analyze_weekly_performance()...")
    agent.analyze_weekly_performance()
except Exception as e:
    print(f"Error during execution: {e}")

print("\n--- Active Rules AFTER Test ---")
for r in get_active_rules():
    print(f"- {r}")
