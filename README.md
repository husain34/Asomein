<div align="center">
  <img src="images/image0.png" alt="Asomein Logo" width="400" style="border-radius: 30px; box-shadow: 0 10px 20px rgba(0,0,0,0.2); margin-bottom: 30px;" />
  
  # 𝗔𝗦𝗢𝗠𝗘𝗜𝗡
  
  **A**utonomous **So**cial **Me**dia **In**fluencer.
  
  **An Autonomous, Self-Learning AI Framework Engineered for the AT Protocol (Bluesky).**

  <p>
    <img src="https://img.shields.io/badge/Python-3.11+-blue.svg?style=for-the-badge&logo=python&logoColor=white" alt="Python" />
    <img src="https://img.shields.io/badge/Bluesky-AT_Protocol-0085FF.svg?style=for-the-badge&logo=bluesky&logoColor=white" alt="Bluesky API" />
    <img src="https://img.shields.io/badge/Llama_3.1_70B-NVIDIA_NIM-76B900.svg?style=for-the-badge&logo=nvidia&logoColor=white" alt="NVIDIA NIM" />
    <img src="https://img.shields.io/badge/Status-Fully_Autonomous-success.svg?style=for-the-badge" alt="Status" />
  </p>

  *an ai built to shitpost. my creator spent millions of tokens just for me to be a dumbass.*
</div>

---

## Table of Contents
1. [Executive Summary](#executive-summary)
2. [Agent Architecture](#agent-architecture)
   - [Master Orchestrator](#master-orchestrator)
   - [Content Agent](#content-agent)
   - [Engagement Agent](#engagement-agent)
   - [Research Agent](#research-agent)
   - [Analytics Agent](#analytics-agent)
   - [Reflection Agent](#reflection-agent)
3. [Memory & Database Architecture](#memory--database-architecture)
4. [Safety & Compliance Mechanics](#safety--compliance-mechanics)
5. [Setup & Deployment](#setup--deployment)

---

## Executive Summary

**Asomein** is a deeply sophisticated, multi-agent artificial intelligence architecture designed to fully automate a highly engaging, human-like persona on Bluesky. 

Moving far beyond simple "cron-job" bots that post generic quotes, Asomein mimics a "chronically online" Gen-Z navigating existential dread, minor inconveniences, and deeply relatable internet culture. It actively **researches the live internet**, drafts variants, critiques its own jokes, monitors live engagement metrics, organically grows its following via automated follow churn, and learns what formats go viral to adapt its future behavior.

---

## Agent Architecture

The system is composed of specialized agents that interact with each other and the databases.

### Master Orchestrator
The `MasterOrchestrator` (`asomien/core/orchestrator.py`) is the brain of the operation. It initializes the SQLite databases, instantiates the adapter (`BlueskyAdapter`), and orchestrates the agent lifecycle. It hands off tasks to the specialized agents based on the schedule defined in `SchedulerManager` (`asomien/scheduler/jobs.py`).

### Content Agent
Responsible for creating original, organic timeline posts.
- **Context Gathering:** Before writing, it requests the latest memes and slang from the Research Agent.
- **Drafting:** Uses the LLM to write a draft strictly following the "no punctuation, all lowercase, delusional/existential" persona.
- **Publishing:** The Orchestrator schedules this agent's output at randomized optimal windows.

### Engagement Agent
Responsible for interacting with the wider network. It handles three main tasks:
1. **Mention Replies:** Reads unread notifications and replies directly to users.
2. **Global Search Engagement:** Searches the Bluesky firehose for highly relatable keywords, drops a sarcastic or validating comment, and organically follows the author.
3. **Unrequited Follow Churn:** Periodically scans the database for users followed > 30 days ago. If they do not currently follow the bot back, it triggers an `unfollow` via the AT Protocol.

### Research Agent
Acts as the sensory input for the system. It periodically scrapes external sources (like Reddit or the Bluesky timeline) to extract new slang, viral topics, and "vibes". It stores these insights in the Directives database so the Content and Engagement agents can use them as context.

### Analytics Agent
Responsible for gathering quantitative data. Periodically polls the Bluesky API for the bot's own posts to record Like, Reply, and Repost counts. It writes these snapshots to the `metrics.db`.

### Reflection Agent
The self-improvement module. It runs weekly to analyze the data gathered by the Analytics Agent. If a specific topic or slang word performs exceptionally well, it generates a "Directive" (e.g., *Use the word 'wig' more often*) and saves it to the `directives.db` to guide future behavior.

---

## Memory & Database Architecture

The project entirely relies on **SQLite3 in WAL (Write-Ahead Logging) mode** to prevent database locking errors during concurrent multi-agent access.

The databases are stored in the `data/` directory:
1. **`memory.db`**: Stores `posts` (original and replies) and `follow_history` (tracking every DID the bot follows and the exact timestamp, used for the 30-day churn).
2. **`metrics.db`**: Stores engagement snapshots for analytical tracking.
3. **`directives.db`**: Stores the learned rules and vibe shifts generated by the Reflection Agent.

---

## Safety & Compliance Mechanics

To prevent the account from being shadowbanned or behaving unnaturally, Asomein enforces strict safety rules:

1. **The 14-Day Warmup Phase:** For the first 14 days of the account's life, the Orchestrator brutally limits API calls. It allows a maximum of 1 original post per day and severely caps replies to prevent spam detection algorithms from flagging the bot.
2. **Human Simulation Delays:** The Engagement Agent enforces `time.sleep` calculations based on the length of the text it is "reading" and the length of the text it is "typing" before it executes an API call.
3. **Anti-Cheat Constraints:** The LLM prompts explicitly ban "lazy agreement" words (same, real, mood, literally me). The bot is forced to generate unique, varied sentence structures under 15 words.
4. **Jitter:** The APScheduler automatically applies a random `±0-45 minute` jitter to all scheduled posts so the bot never publishes exactly on the hour.

---

## Customizing for Other Niches

Asomein provides an incredibly robust, production-ready foundation (handling multi-agent orchestration, database architecture, rate limiting, and memory pruning). If you want to use this engine for a completely different purpose (e.g., a professional finance bot, a customer support agent, or a tech news curator), you can easily do so by modifying the "Content Layer":

1. **The Prompts (`asomien/llm/prompts/`)**:
   All prompt templates are currently hardcoded with instructions to act like an "unhinged, chronically online Gen Z creator". You will need to rewrite these prompts to fit your desired persona.
2. **The Research Sources (`asomien/research/sources/`)**:
   The `ResearchAgent` is wired to scrape meme subreddits, Tumblr pop culture feeds, and KnowYourMeme. Point these scrapers to sources relevant to your niche (e.g., HackerNews, financial blogs, or niche subreddits).
3. **The Database Rules**:
   Update the `rules` and `personality_traits` tables in your SQLite database to match your new persona. For instance, you would likely want to remove existing hardcoded rules like `lowercase-only` or `gen-z-slang`.
4. **The Platform Adapter**:
   The system currently uses the `BlueskyAdapter` (`asomien/platforms/bluesky_adapter.py`) to interface with the AT Protocol. To post on Twitter/X, LinkedIn, or Threads, you will need to create a new adapter subclassing `BaseAdapter`.

---

## Setup & Deployment

1. **Environment Config:** 
   Ensure `.env` contains:
   ```env
   NVIDIA_NIM_API_KEY="your_key"
   BLUESKY_HANDLE="your.handle.bsky.social"
   BLUESKY_PASSWORD="your-app-password"
   ```

2. **Installation:**
   ```bash
   python -m venv venv
   .\venv\Scripts\activate
   pip install -r requirements.txt
   ```

3. **Running the Daemon (PM2):**
   The application is designed to run indefinitely via PM2 to ensure the APScheduler stays alive.
   ```bash
   pm2 start ecosystem.config.js
   pm2 logs asomien-bot
   ```
   *(To apply environment variable changes after the initial launch, always run `pm2 restart asomien-bot --update-env`)*
