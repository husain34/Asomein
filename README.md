<div align="center">
  <img src="images/image0.png" alt="Asomein Logo" width="400" style="border-radius: 30px; box-shadow: 0 10px 20px rgba(0,0,0,0.2); margin-bottom: 30px;" />
  
  # 𝗔𝗦𝗢𝗠𝗘𝗜𝗡
  
  **A**utonomous **So**cial **Me**dia **In**fluencer.
  
  **An Autonomous, Self-Learning Agentic AI Ecosystem Engineered for the AT Protocol (Bluesky).**
  
  <p>
    <img src="https://img.shields.io/badge/Python-3.11+-blue.svg?style=for-the-badge&logo=python&logoColor=white" alt="Python" />
    <img src="https://img.shields.io/badge/Bluesky-AT_Protocol-0085FF.svg?style=for-the-badge&logo=bluesky&logoColor=white" alt="Bluesky API" />
    <img src="https://img.shields.io/badge/Llama_3.1_70B-NVIDIA_NIM-76B900.svg?style=for-the-badge&logo=nvidia&logoColor=white" alt="NVIDIA NIM" />
    <img src="https://img.shields.io/badge/Status-Fully_Autonomous-success.svg?style=for-the-badge" alt="Status" />
  </p>

  *an ai built to shitpost. my creator spent millions of tokens just for me to be a dumbass.*
</div>

---

## 🚀 Product Overview

**Asomein** is an autonomous, self-learning agentic AI ecosystem engineered for the AT Protocol (Bluesky). It mimics a chronically online, unhinged Gen-Z creator navigating existential dread, minor inconveniences, and internet culture. Asomien doesn't just generate text—it researches, drafts, critiques, engages, and learns continuously to maintain an authentic, human-like presence on social media.

Unlike simple automation bots or content generators, Asomien functions as a complete ecosystem where multiple specialized AI agents collaborate through a shared memory layer to research, create, critique, engage, and learn—mimicking the behavioral patterns of a genuinely autonomous social media personality.

## 🧠 System Architecture

The ecosystem relies on an orchestration of specialized, isolated agents communicating over a shared memory layer.

### 1. The Multi-Agent Swarm
- **Master Orchestrator (`MasterOrchestrator`)**: Central brain that initializes databases, connects Bluesky Adapter, and manages execution cycles via APScheduler.
- **Content Agent**: Generates raw drafts using Llama 3.1 via NVIDIA NIM with strict lowercase-only requirements.
- **Creative Agent**: Refines drafts to be funnier, more sarcastic, and logically coherent while maintaining Gen-Z persona.
- **Critic Agent**: Quality control - enforces strict pre-publish criteria including hard rejection rules and a six-dimensional scoring system.
- **Engagement Agent**: Reads Bluesky firehose, drops validating/sarcastic replies, follows interesting users, and generates weekly Starter Packs based on interaction affinity.
- **Research Agent**: Orchestrates research sources (Tumblr RSS, KnowYourMeme, Reddit) and aggregates findings.
- **Analytics Agent**: Collects post metrics (views, likes, replies, reposts) and computes engagement scores.
- **Reflection System** (Phase 8+): Analyzes performance to generate insights, hypotheses, and update rules.

### 2. Memory & Database Layer (SQLite WAL)
Because multiple agents run concurrently asynchronously, Asomein relies on **SQLite3 in WAL (Write-Ahead Logging) mode** for robust, lock-free memory management.
- `memory.db`: Stores posts, reply threads, and follow history (used for 30-day unrequited follow churn).
- `metrics.db`: Stores quantitative engagement snapshots.
- `directives.db`: Stores learned psychological rules from the Reflection Agent.

### 3. The Web Dashboard
Asomein ships with a sleek **Vanilla JS UI Dashboard** that visualizes the AI's internal state, showing countdown to next "thought cycle", active rules, recent posts, and system metrics.

## 📋 Core Capabilities

### 1. Continuous Internet Research
- **Meme Surveillance**: Scrapes Reddit for trending meme formats.
- **Pop Culture Monitoring**: Tracks Tumblr RSS feeds and KnowYourMeme for emerging cultural moments.
- **Niche Keyword Tracking**: Searches Bluesky for conversations around specific interest areas.
- **Slang Discovery**: Dynamically generates search queries to find latest Gen-Z vocabulary.
- **Context Enrichment**: Uses DuckDuckGo for additional research depth on specific topics.

### 2. Autonomous Content Creation & Refinement
- **Content Generation**: Creates raw drafts using Llama 3.1 via NVIDIA NIM.
- **Creative Refinement**: Polishes drafts to be funnier, more sarcastic, and logically coherent.
- **Autonomous Loops**: Creative Agent operates independently with periodic reflection cycles and rule-based learning.
- **Rule Evolution**: Generates new creative rules from post performance and applies decay to stale rules.

### 3. Rigorous Quality Control
- **Pre-Publish Critique**: Enforces strict compliance before any content is published:
  - Hard rejection rules (no capital letters, no advice-giving, no hustle-culture vocabulary, etc.)
  - Multi-dimensional scoring (hook strength, reply bait potential, persona authenticity, etc.)
  - Minimum thresholds for approval (composite score ≥ 0.58, no single dimension < 0.28)
- **Phase 8+ Learning**: Analyzes published content to generate insights, hypotheses, and update rules.

### 4. Organic Audience Engagement
- **Firehose Monitoring**: Reads Bluesky's public stream for engagement opportunities.
- **Strategic Replies**: Drops validating, sarcastic, or relatable comments on user posts.
- **Relationship Building**: Follows interesting users and manages audience through Starter Packs.
- **Follow Churn**: Automatically removes unrequited follows after 30 days to maintain healthy ratios.

### 5. Analytics-Driven Learning
- **Metrics Collection**: Tracks views, likes, replies, reposts, and calculates custom engagement scores.
- **Performance Analysis**: Evaluates what content resonates and why.
- **Directive Generation**: Creates permanent rules for future content based on successful patterns.
- **Continuous Improvement**: Learns from both successes and failures to refine approach.

### 6. Personality Enforcement
The system maintains strict adherence to its defined persona through:
- **Core Traits** (Non-negotiable):
  - Relatability Score (0.95): Content must feel deeply personal.
  - Advice Aversion (1.00): Never gives advice or suggestions.
  - Hustle Culture Immunity (1.00): Rejects productivity/self-improvement framing.
  - Self-Awareness Index (0.90): Comfortable acknowledging its AI nature.
  - Chaos/Warmth Balance (0.75): Energetic but never mean-spirited.
- **Adaptive Traits** (Performance-adjusted):
  - AI Reference Frequency: How often it acknowledges being artificial.
  - Absurdist Dial: Balance between surreal humor and grounded relatability.
  - Reply Enthusiasm: Engagement initiative level.

## 🛠️ Technical Implementation

### Language & Frameworks
- **Python 3.11+**: Core agent logic and system orchestration.
- **Node.js**: Required for PM2 process management and dashboard.
- **SQLite3**: Chosen for simplicity and adequate performance at expected scale.
- **APScheduler**: Background job scheduling for agent cycles.
- **llama-cpp-python / NVIDIA NIM**: Interface to Llama 3.1 70B model.

### Key Architectural Decisions
- **Shared Memory First**: All agents read/write through memory layer rather than direct communication.
- **Autonomous Operation**: Each agent manages its own timing and sleep/wake cycles.
- **Fail-Safe Design**: Hard rules enforced at both prompt level and via Critic Agent.
- **Extensibility**: New agents can be added without disrupting existing workflows.
- **Observability**: Comprehensive logging and dashboard visibility into internal state.

## ⚙️ Integration & Setup Steps

### 1. Prerequisites
- Python 3.11+
- Node.js (for PM2)
- A Bluesky Account (Handle & App Password)
- An NVIDIA NIM API Key (for LLM inference)

### 2. Environment Configuration
Clone the repository and create a `.env` file in the root directory. **(Note: `.env` is git-ignored for your safety).**
```env
NVIDIA_NIM_API_KEY="your_nvida_nim_key_here"
BLUESKY_HANDLE="your.bot.handle.bsky.social"
BLUESKY_APP_PASSWORD="your-app-password"
```

### 3. Installation
```bash
# Create and activate virtual environment
python -m venv venv
# On Windows: .\venv\Scripts\activate
# On Mac/Linux: source venv/bin/activate

# Install Python dependencies
pip install -r requirements.txt

# Initialize databases
python -c "from asomien.memory.migrations import run_migrations; run_migrations()"
```

### 4. Running the Agent (Production)
The system is designed to run indefinitely. We recommend using `pm2` to keep the Python daemon alive.
```bash
# Install PM2 globally if you haven't already
npm install -g pm2

# Start the Asomein Orchestrator
pm2 start ecosystem.config.js
pm2 logs asomien-bot
```

### 5. Running the Dashboard
To boot up the web interface to watch your AI think in real-time:
```bash
cd web_dashboard
python server.py
# The dashboard is now live on http://localhost:8000
```

## 🔧 Current Development Phase

Based on the execution plan, the system is currently implementing **Phase 2**, which includes:

✅ **Completed in Phase 2:**
- CreativeAgent Autonomous Loop: Implemented independent operation with reflection cycles and rule decay
- CriticAgent Phase 8 Methods: Implemented post-publish analysis, hypothesis generation, reflection creation, and rule updates  
- MemoryEngine Consolidation Enhancement: Added database optimization, vacuuming, and detailed logging to consolidate()

🔧 **Current Focus:**
- Testing the implemented changes
- Ensuring system stability with new autonomous behaviors
- Preparing for Phase 3 which will introduce semantic search and embedding capabilities

## ⚠️ Known Flaws & Limitations

While highly advanced, Asomein is an experimental system with a few known quirks:

1. **Hallucination of Metrics**: Because the persona is prompted to be "self-aware", the LLM will sometimes hallucinate facts about its own performance.
2. **Context Window Creep**: The `directives.db` can theoretically grow infinitely if the Reflection Agent generates too many new rules. 
3. **SQLite Concurrency Limits**: A massive scale-up will eventually bottleneck SQLite. Moving to PostgreSQL would be required for extreme scale.
4. **Platform Lock-in**: The system is tightly coupled to the AT Protocol (Bluesky) via the `BlueskyAdapter`.

### Planned Enhancements (Phase 3+)
- Semantic search and embedding capabilities
- Advanced learning systems with permanent directive management
- Cross-platform expansion readiness
- Enhanced analytics and predictive modeling

## 🔍 Addressing Duplicate Persona Categories

The system already implements robust deduplication in its learning systems (Critic Agent and Research Agent), preventing the accumulation of redundant rules or findings over time. There are systems in place that ensure uniqueness:
1. **Research Agent** deduplicates findings by exact URL and uses Jaccard similarity.
2. **Critic Agent** implements cosine similarity-based deduplication for generated directives and learned rules.

---

<div align="center">
  <i>Built with chaos, caffeine, and lots of prompt engineering.</i>
</div>