# Asomien Multi-Agent System - Execution Plan

## Phase 1 Audit Summary

### Unimplemented Code Identified

1. **asomien/agents/creative_agent.py**
   - `run()` method (line 58-60): Contains only `pass` statement
   - Description: "No autonomous loop for this agent, called synchronously by Orchestrator."
   - **Action Required**: Implement the autonomous loop for the CreativeAgent to enable it to operate independently

2. **asomien/agents/critic_agent.py**
   - Several stub methods marked for "Phase 8+" (lines 688-700, 701-703, 697-699, 701-703):
     - `post_publish_analysis(self, post: Any, metrics: Any) -> None`
     - `generate_hypothesis(self, observation: str) -> str`
     - `generate_reflection(self, post: Any, metrics: Any) -> None`
     - `update_rules(self, reflection: Any) -> None`
   - These methods currently only log debug/info messages and return empty values
   - **Action Required**: Implement these methods according to their documented purpose for Phase 8 functionality

3. **asomien/memory/engine.py**
   - `consolidate()` method (lines 594-598): Has basic implementation but could be enhanced
   - Currently only calls `expire_stale_nodes()` and logs
   - **Action Required**: Enhance memory consolidation to include additional cleanup and optimization tasks

### Dead/Unused Code Identified

No obvious dead code (commented-out blocks, unused imports, etc.) was found during the audit. The codebase appears to be clean with intentional stubs for future phases.

## Phase 2 Execution Plan

Based on the audit, the following changes will be implemented:

### 1. CreativeAgent Autonomous Loop Implementation

**File**: `asomien/agents/creative_agent.py`
**Change**: Replace the `pass` statement in `run()` method with an autonomous loop that:
- Periodically checks for new creative rules to update
- Runs reflection cycles on recent posts to generate new rules
- Applies rule decay to stale creative rules
- Sleeps appropriately between cycles to avoid excessive resource usage

### 2. CriticAgent Phase 8 Method Implementation

**File**: `asomien/agents/critic_agent.py`
**Changes**: Implement the stub methods for Phase 8+ functionality:

#### `post_publish_analysis(self, post: Any, metrics: Any) -> None`
- Analyze published post performance against metrics
- Generate insights for content improvement
- Store learnings in memory system

#### `generate_hypothesis(self, observation: str) -> str`
- Take an observation from post performance
- Generate a testable hypothesis about what would improve engagement
- Return hypothesis as string

#### `generate_reflection(self, post: Any, metrics: Any) -> None`
- Create a ReflectionNode based on post and metrics
- Store reflection in memory for future learning
- Include success factors, failure factors, and lessons learned

#### `update_rules(self, reflection: Any) -> None`
- Process reflection data to update creative rules
- Add new rules based on successful patterns
- Adjust confidence of existing rules based on performance
- Implement rule deduplication to prevent redundancy

### 3. Memory Engine Consolidation Enhancement

**File**: `asomien/memory/engine.py`
**Change**: Enhance the `consolidate()` method to:
- Expire stale nodes (already implemented)
- Optimize database indices
- Archive very old data if needed
- Run vacuum operation to reclaim space
- Log detailed statistics about consolidation process

## Architectural Reasoning

### Why These Changes Are Needed

1. **CreativeAgent Autonomy**: Currently the CreativeAgent relies on the Orchestrator to call its methods synchronously. Making it truly autonomous aligns with the multi-agent architecture where each agent should manage its own lifecycle and timing.

2. **CriticAgent Phase 8 Completion**: The stub methods are placeholders for advanced learning capabilities. Implementing them will enable the system to:
   - Learn from its own performance
   - Generate testable hypotheses for improvement
   - Automatically refine its creative rules
   - Create a closed-loop learning system

3. **Memory Consolidation**: Proper memory management is crucial for long-running autonomous systems. Enhanced consolidation will prevent memory bloat and ensure optimal performance over time.

### Implementation Approach

Each change will be implemented minimally but completely, following the existing code patterns and maintaining consistency with the established architecture. All implementations will:
- Follow the existing logging patterns
- Handle edge cases gracefully
- Maintain thread safety where appropriate
- Not break existing interfaces
- Include appropriate error handling

## Dependencies and Order

1. CreativeAgent run() implementation can be done independently
2. CriticAgent method implementations depend on the memory system being functional
3. Memory engine enhancements are foundational and safe to implement first

## Testing Considerations

After implementation, the following should be verified:
- All existing tests still pass
- New functionality doesn't break agent interactions
- Logging shows appropriate behavior
- No performance regressions introduced

## Completion Criteria

Phase 2 will be considered complete when:
- All unimplemented code identified in Phase 1 has been implemented
- No dead code was found requiring removal
- The system runs without errors
- Basic functionality tests pass