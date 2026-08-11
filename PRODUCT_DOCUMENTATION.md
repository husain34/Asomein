# Asomien: Autonomous Social Media Influencer

## Overview

Asomien is an autonomous, self-learning agentic AI ecosystem engineered for the AT Protocol (Bluesky). It mimics a chronically online, unhinged Gen-Z creator navigating existential dread, minor inconveniences, and internet culture. Asomien doesn't just generate text—it researches, drafts, critiques, engages, and learns continuously to maintain an authentic, human-like presence on social media.

## Core Abilities

### 1. Autonomous Research
- Scrapes external sources (Tumblr RSS, KnowYourMeme, Reddit) for meme templates and cultural trends
- Searches Bluesky for niche-specific content using keyword tracking
- Fetches latest Gen-Z slang dynamically from web searches
- Stores findings with appropriate expiry (48h for memes, 72h for standard research)

### 2. Content Generation & Refinement
- **Content Agent**: Drafts organic, lowercase-only, unhinged posts using Llama 3.1 via NVIDIA NIM
- **Creative Agent**: Refines drafts to be funnier, more sarcastic, and logically coherent while maintaining Gen-Z persona
- Operates through autonomous loops with reflection cycles and rule-based learning

### 3. Quality Control
- **Critic Agent**: Enforces strict pre-publish criteria including:
  - Hard rejection rules (no capitals, no advice, no hustle-culture vocabulary, etc.)
  - Six-dimensional scoring system (hook strength, reply bait, persona authenticity, etc.)
  - Minimum thresholds for approval (composite score ≥ 0.58, no dimension < 0.28)
  - Phase 8+ capabilities for post-hoc analysis, hypothesis generation, and rule updates

### 4. Audience Engagement
- **Engagement Agent**: Reads Bluesky firehose, drops validating/sarcastic replies, follows interesting users
- Generates weekly Starter Packs based on interaction affinity
- Implements 30-day unrequited follow churn to maintain healthy follower ratios

### 5. Analytics & Learning
- **Analytics Agent**: Collects post metrics (views, likes, replies, reposts) and computes engagement scores
- **Reflection Capabilities** (Phase 8): Analyzes top-performing posts to generate new directives
- Learns from performance to optimize future content through permanent rule updates

### 6. Personality Enforcement
- **Personality Engine**: Ensures strict adherence to core traits:
  - Lowercase always (non-negotiable)
  - Advice aversion (hard zero - never gives advice)
  - Hustle culture immunity (rejects productivity/self-improvement framing)
  - High relatability score (0.95)
  - Chaos/warmth balance (0.75)
  - Self-awareness index (0.90)

## System Architecture

### Multi-Agent Swarm
1. **Master Orchestrator**: Central brain that initializes databases, connects Bluesky Adapter, and manages execution cycles via APScheduler
2. **Content Agent**: Generates raw drafts using LLM
3. **Creative Agent**: Refines drafts for humor, sarcasm, and coherence
4. **Critic Agent**: Quality control - rejects non-compliant content before publishing
5. **Engagement Agent**: Handles replies, follows, and Starter Pack generation
6. **Research Agent**: Orchestrates research sources and aggregates findings
7. **Analytics Agent**: Collects and processes engagement metrics
8. **Reflection Capabilities**: Post-hoc analysis for learning (Phase 8+)

### Memory & Database Layer
- **memory.db**: Stores posts, reply threads, and follow history (30-day unrequited follow churn)
- **metrics.db**: Stores quantitative engagement snapshots
- **directives.db**: Stores learned psychological rules from Reflection Agent
- All databases use SQLite3 in WAL (Write-Ahead Logging) mode for concurrent access

### Web Dashboard
- Next.js + Vanilla JS UI that visualizes internal state
- Shows countdown to next "thought cycle" (Engagement, Research, or Analytics)
- Displays active rules, recent posts, and system metrics

## Technical Implementation

### Language & Dependencies
- Python 3.11+ for core agent logic
- Node.js for PM2 and Next.js dashboard
- NVIDIA NIM API for Llama 3.1 70B inference
- Bluesky AT Protocol for social media interactions

### Key Design Patterns
- **Autonomous Loops**: Agents operate independently with sleep/wake cycles
- **Memory-First Approach**: All agents interact through shared memory layer
- **Phase-Based Development**: Features rolled out in phases (currently implementing Phase 2)
- **Fail-Safe Mechanisms**: Hard rules enforced at prompt level and via Critic Agent
- **Extensible Architecture**: New agents and capabilities can be added without disrupting core

## Current Development Phase

Based on the execution plan, the system is currently implementing **Phase 2**, which includes:

1. **CreativeAgent Autonomous Loop**: Implemented independent operation with reflection cycles and rule decay
2. **CriticAgent Phase 8 Methods**: Implemented post-publish analysis, hypothesis generation, reflection creation, and rule updates
3. **MemoryEngine Consolidation Enhancement**: Added database optimization, vacuuming, and detailed logging to consolidate()

## Known Limitations & Future Work

### Current Limitations
- Hallucination of metrics (LLM sometimes jokes about performance)
- Context window creep from growing directives.db
- SQLite concurrency limits at extreme scale
- Platform lock-in to Bluesky AT Protocol

### Planned Enhancements (Phase 3+)
- Semantic search and embedding capabilities
- Advanced learning systems with permanent directive management
- Cross-platform expansion readiness
- Enhanced analytics and predictive modeling

## Installation & Deployment

Asomien is designed for continuous operation and recommended deployment with PM2:

```bash
# Setup
python -m venv venv
source venv/bin/activate  # Windows: .\venv\Scripts\activate
pip install -r requirements.txt

# Environment (.env file)
NVIDIA_NIM_API_KEY="your_key"
BLUESKY_HANDLE="your.handle.bsky.social"
BLUESKY_APP_PASSWORD="your-password"

# Start
npm install -g pm2
pm2 start ecosystem.config.js
pm2 logs asomien-bot

# Dashboard
cd web_dashboard
python server.py  # Available at http://localhost:8000
```

## Conclusion

Asomien represents a sophisticated approach to autonomous social media agency, combining multiple specialized agents with shared memory, strict personality enforcement, and continuous learning capabilities. Its architecture enables genuine autonomy while maintaining the specific Gen-Z persona that defines its appeal.