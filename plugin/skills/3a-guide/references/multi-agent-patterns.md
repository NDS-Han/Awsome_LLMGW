# Multi-Agent Patterns

When the developer's requirements involve multiple agents working together, use this reference to help them choose the right pattern. This is an architecture decision — record it as an ADR after the choice is made.

## When to use this reference

- Developer says "multiple agents", "agents working together", "orchestrator", "pipeline"
- Requirements involve different specialized capabilities that don't belong in one agent
- Developer is considering A2A protocol

## Patterns

### Pattern 1: Single Agent with Multiple Tools

**Not actually multi-agent.** One agent has many tools. Start here — most "I need multiple agents" cases are solved by a single agent with well-defined tools.

**When to use:**
- Tasks are related and share context
- No need for independent reasoning chains
- Latency matters (no agent-to-agent overhead)

**Example:** A support agent that can search docs, check order status, and file tickets — all tools on one agent.

**Ask the developer:** "Could one agent with multiple tools handle all your use cases? What specifically requires separate agents?"

---

### Pattern 2: Coordinator (Hub-and-Spoke)

One **coordinator agent** receives requests and delegates to **specialist agents**. The coordinator decides which specialist to call and synthesizes results.

```
         User
          │
     Coordinator
      /   |   \
  Agent1 Agent2 Agent3
```

**When to use:**
- Clear separation of expertise (e.g., research agent, writing agent, review agent)
- Coordinator needs to route based on intent
- Specialists don't need to talk to each other

**Tradeoffs:**
- Simple to reason about — clear hierarchy
- Coordinator is a single point of failure
- Added latency per hop (user → coordinator → specialist → coordinator → user)

**AgentCore implementation:** A2A protocol. Coordinator discovers specialists via A2A registry.

---

### Pattern 3: Pipeline (Sequential)

Agents process work in a fixed order. Output of one agent becomes input of the next.

```
User → Agent1 → Agent2 → Agent3 → Result
```

**When to use:**
- Work has clear stages (e.g., extract → transform → validate)
- Each stage requires different expertise or model
- Order never changes

**Tradeoffs:**
- Easy to debug — linear flow
- No parallelism — total latency is sum of all stages
- Rigid — changing the order requires restructuring

**AgentCore implementation:** Chain of HTTP invocations, or Step Functions for durable orchestration.

---

### Pattern 4: Parallel Fan-out

One agent sends work to multiple agents simultaneously and aggregates results.

```
         User
          │
      Dispatcher
      /   |   \
  Agent1 Agent2 Agent3  (concurrent)
      \   |   /
      Aggregator
          │
        Result
```

**When to use:**
- Same task benefits from multiple perspectives (e.g., research from different sources)
- Independent subtasks that can run concurrently
- Latency-sensitive — parallel is faster than sequential

**Tradeoffs:**
- Faster than pipeline for independent work
- Aggregation logic can be complex
- Cost scales linearly with number of parallel agents

**AgentCore implementation:** Dispatcher agent uses A2A to invoke specialists concurrently.

---

### Pattern 5: Hierarchical (Tree)

Multi-level delegation. A top-level agent delegates to mid-level coordinators, who delegate to specialists.

```
          Manager
         /      \
   Team Lead A   Team Lead B
    /    \         /    \
  Spec1  Spec2  Spec3  Spec4
```

**When to use:**
- Large-scale systems with many specialists
- Natural organizational grouping of capabilities
- Need to limit the scope each agent reasons about

**Tradeoffs:**
- Scales to many agents
- Complex to debug — deep call chains
- High cumulative latency
- Overkill for most projects — start simpler

---

## Decision Guide

Ask these questions in order:

1. **"Can one agent with multiple tools do the job?"**
   → If yes: Pattern 1 (Single Agent). Stop here.

2. **"Is the work a fixed sequence of stages?"**
   → If yes: Pattern 3 (Pipeline).

3. **"Are subtasks independent and parallelizable?"**
   → If yes: Pattern 4 (Parallel Fan-out).

4. **"Do you need a central brain that routes to specialists?"**
   → If yes: Pattern 2 (Coordinator).

5. **"Do you need multiple levels of coordination?"**
   → If yes: Pattern 5 (Hierarchical). But strongly suggest starting with Pattern 2 and evolving.

## What to record in the ADR

When the developer chooses a pattern, record:

- **Which pattern** and why
- **How many agents** and what each one does
- **Communication protocol** (A2A, HTTP chain, Step Functions)
- **What was rejected** and why (e.g., "Considered single agent but X and Y require independent reasoning chains")

## Boundary with aws-agents

This reference helps choose the **pattern** (architecture decision). The **implementation** — creating A2A agents, configuring discovery, wiring communication — is handled by `aws-agents` skills (`agents-build`, `agents-connect`).
