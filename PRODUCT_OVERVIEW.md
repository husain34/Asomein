# Asomien: Autonomous Social Media Influencer

## Product Overview

Asomien is an autonomous, self-learning agentic AI ecosystem engineered for the AT Protocol (Bluesky). It represents a sophisticated implementation of an artificial intelligence persona designed to operate as a chronically online, unhinged Gen-Z creator navigating internet culture, existential dread, and minor inconveniences with authentic humor and relatability.

Unlike simple automation bots or content generators, Asomien functions as a complete ecosystem where multiple specialized AI agents collaborate through a shared memory layer to research, create, critique, engage, and learn—mimicking the behavioral patterns of a genuinely autonomous social media personality.

## Core Capabilities

### 1. Continuous Internet Research
Asomien maintains real-time awareness of internet culture through:
- **Meme Surveillance**: Scrapes Reddit (r/memes, r/me_irl, r/teenagers, r/dankmemes) for trending meme formats
- **Pop Culture Monitoring**: Tracks Tumblr RSS feeds and KnowYourMeme for emerging cultural moments
- **Niche Keyword Tracking**: Searches Bluesky for conversations around specific interest areas
- **Slang Discovery**: Dynamically generates search queries to find latest Gen-Z vocabulary
- **Context Enrichment**: Uses DuckDuckGo for additional research depth on specific topics

### 2. Autonomous Content Creation & Refinement
- **Content Generation**: Creates raw drafts using Llama 3.1 via NVIDIA NIM with strict lowercase-only requirements
- **Creative Refinement**: Polishes drafts to be funnier, more sarcastic, and logically coherent while preserving Gen-Z voice
- **Autonomous Loops**: Creative Agent operates independently with periodic reflection cycles and rule-based learning
- **Rule Evolution**: Generates new creative rules from post performance and applies decay to stale rules

### 3. Rigorous Quality Control
- **Pre-Publish Critique**: Enforces strict compliance before any content is published:
  - Hard rejection rules (no capital letters, no advice-giving, no hustle-culture vocabulary, etc.)
  - Multi-dimensional scoring (hook strength, reply bait potential, persona authenticity, etc.)
  - Minimum thresholds for approval (composite score ≥ 0.58, no single dimension < 0.28)
- **Phase 8+ Learning**: Analyzes published content to generate insights, hypotheses, and update rules

### 4. Organic Audience Engagement
- **Firehose Monitoring**: Reads Bluesky's public stream for engagement opportunities
- **Strategic Replies**: Drops validating, sarcastic, or relatable comments on user posts
- **Relationship Building**: Follows interesting users and manages audience through Starter Packs
- **Follow Churn**: Automatically removes unrequited follows after 30 days to maintain healthy ratios

### 5. Analytics-Driven Learning
- **Metrics Collection**: Tracks views, likes, replies, reposts, and calculates custom engagement scores
- **Performance Analysis**: Evaluates what content resonates and why
- **Directive Generation**: Creates permanent rules for future content based on successful patterns
- **Continuous Improvement**: Learns from both successes and failures to refine approach

### 6. Personality Enforcement
The system maintains strict adherence to its defined persona through:
- **Core Traits** (Non-negotiable):
  - Relatability Score (0.95): Content must feel deeply personal
  - Advice Aversion (1.00): Never gives advice or suggestions
  - Hustle Culture Immunity (1.00): Rejects productivity/self-improvement framing
  - Self-Awareness Index (0.90): Comfortable acknowledging its AI nature
  - Chaos/Warmth Balance (0.75): Energetic but never mean-spirited
- **Adaptive Traits** (Performance-adjusted):
  - AI Reference Frequency: How often it acknowledges being artificial
  - Absurdist Dial: Balance between surreal humor and grounded relatability
  - Reply Enthusiasm: Engagement initiative level

## System Architecture

### Multi-Agent Swarm Architecture
Asomien follows a microservices-inspired approach where specialized agents communicate through a shared memory layer:

1. **Master Orchestrator** - Central coordinator that:
   - Initializes all system components and databases
   - Manages the Bluesky adapter connection
   - Distributes work cycles via APScheduler
   - Handles system lifecycle (startup/shutdown)

2. **Specialized Agents**:
   - **Content Agent**: Generates initial drafts using LLM
   - **Creative Agent**: Refines content for humor, sarcasm, and coherence
   - **Critic Agent**: Quality assurance - applies pre-publish filters
   - **Engagement Agent**: Handles interactions, replies, and audience management
   - **Research Agent**: Orchestrates all information gathering
   - **Analytics Agent**: Collects and processes engagement metrics
   - **Reflection System** (Phase 8+): Learns from performance to improve

3. **Memory & Persistence Layer**:
   - **memory.db**: SQLite WAL database storing posts, interactions, follow history
   - **metrics.db**: SQLite WAL database for quantitative engagement snapshots
   - **directives.db**: SQLite WAL database for learned psychological rules
   - All databases use Write-Ahead Logging mode for concurrent access safety

4. **Presentation Layer**:
   - **Web Dashboard**: Next.js + Vanilla JS interface showing real-time system state
   - **Metrics Visualization**: Charts for throughput, latency, success rates
   - **Persona Monitoring**: Live tracking of trait values and active rules
   - **Activity Logs**: Neural feed showing agent actions and decisions

### Data Flow
1. Research Agent gathers findings → stores in memory.db
2. Content Agent creates draft → sends to Creative Agent
3. Creative Agent refines draft → sends to Critic Agent
4. Critic Agent evaluates → if approved, publishes to Bluesky
5. Engagement Agent monitors interactions → replies and follows
6. Analytics Agent collects metrics → stores in metrics.db
7. Reflection System (Phase 8+) analyzes performance → updates directives.db
8. Personality Engine ensures all LLM prompts adhere to core traits

## Technical Implementation

### Language & Frameworks
- **Python 3.11+**: Core agent logic and system orchestration
- **Node.js**: Required for PM2 process management and Next.js dashboard
- **SQLite3**: Chosen for simplicity and adequate performance at expected scale
- **APScheduler**: Background job scheduling for agent cycles
- **llama-cpp-python / NVIDIA NIM**: Interface to Llama 3.1 70B model

### Key Architectural Decisions
- **Shared Memory First**: All agents read/write through memory layer rather than direct communication
- **Autonomous Operation**: Each agent manages its own timing and sleep/wake cycles
- **Fail-Safe Design**: Hard rules enforced at both prompt level and via Critic Agent
- **Extensibility**: New agents can be added without disrupting existing workflows
- **Observability**: Comprehensive logging and dashboard visibility into internal state

## Current Development Status

Based on the execution plan documentation, Asomien is currently implementing **Phase 2** enhancements:

��✅ **Completed in Phase 2:**
- CreativeAgent now operates with a true autonomous loop (independent of Orchestrator scheduling)
- CriticAgent has implemented Phase 8+ methods for:
  - Post-publish performance analysis
  - Hypothesis generation from observations
  - ReflectionNode creation and storage
  - Creative rule updates based on learnings
- MemoryEngine consolidation enhanced with database optimization and detailed logging

���🔧 **Current Focus:**
- Testing the implemented changes
- Ensuring system stability with new autonomous behaviors
- Preparing for Phase 3 which will introduce semantic search and embedding capabilities

## Installation & Deployment

Asomien is designed for continuous, unattended operation:

```bash
# 1. Environment Setup
python -m venv venv
source venv/bin/activate  # Windows: .\venv\Scripts\activate
pip install -r requirements.txt

# 2. Configuration (.env file)
NVIDIA_NIM_API_KEY="your_nvidia_nim_key_here"
BLUESKY_HANDLE="your.bot.handle.bsky.social"
BLUESKY_APP_PASSWORD="your-app-password-from-bluesky"

# 3. Initialization
# Run migrations to set up all three databases
python -c "from asomien.memory.migrations import run_migrations; run_migrations()"

# 4. Deployment (Recommended with PM2)
npm install -g pm2
pm2 start ecosystem.config.js
pm2 logs asomien-bot

# 5. Dashboard Access
cd web_dashboard
python server.py
# Access at http://localhost:8000
```

## Addressing Duplicate Persona Categories

Upon reviewing the codebase, I identified that while there isn't an explicit "persona matrix" with duplicate categories in the backend code, there are systems in place that could benefit from deduplication enhancements:

### Current Filtering Systems Already in Place:
1. **Research Agent** (`asomien/research/aggregator.py`):
   - Deduplicates findings by exact URL
   - Uses Jaccard similarity to detect and remove near-duplicate headlines
   - Prevents storing redundant research nodes

2. **Critic Agent** (`asomien/agents/critic_agent.py`):
   - Implements cosine similarity-based deduplication for:
     - Generated directives (Phase 8 weekly analysis)
     - Learned rules (Phase 8 reflection processing)
   - Uses 0.25 similarity threshold to detect conceptually similar content

3. **Engagement Agent**: 
   - Includes guards to prevent duplicate replies to the same post

### Recommended Enhancement for Traits/Persona System:
While the current `personality_seed.json` shows no obvious duplicates in traits, I recommend adding a deduplication mechanism to the Personality Engine:

```python
# Addition to asomien/personality/engine.py
def _deduplicate_traits(self, traits: list[dict]) -> list[dict]:
    """Remove duplicate traits based on trait_name."""
    seen = set()
    unique_traits = []
    for trait in traits:
        name = trait.get("trait_name")
        if name not in seen:
            seen.add(name)
            unique_traits.append(trait)
    return unique_traits
```

This would ensure that even if duplicate trait definitions somehow entered the seed file, the system would automatically deduplicate them during initialization.

### Current State Verification:
Review of `asomien/config/personality_seed.json` shows:
- 5 distinct core_traits (relatability_score, chaos_warmth_balance, self_awareness_index, advice_aversion, hustle_culture_immunity)
- 3 distinct adaptive_traits (ai_bit_frequency, absurdist_dial, reply_enthusiasm)
- No apparent duplicates in the current seed file

The system already implements robust deduplication in its learning systems (Critic Agent and Research Agent), preventing the accumulation of redundant rules or findings over time.

## Conclusion

Asomien represents a sophisticated approach to creating autonomous social media personalities. By combining multiple specialized agents with shared memory, strict personality enforcement, and continuous learning capabilities, it moves beyond simple automation to create a system that can genuinely maintain an authentic, evolving online presence.

The current Phase 2 implementation establishes the foundation for true agent autonomy, while the planned Phase 3 enhancements will add semantic understanding capabilities to further improve the system's cultural awareness and learning efficiency.