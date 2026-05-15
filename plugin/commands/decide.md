---
name: 3a-decide
description: Record an architecture decision as an ADR in .3a/decisions/.
---

The developer wants to record an architecture decision.

## Process

1. Read `.3a/decisions/` to find the next ADR number.
2. Ask the developer:
   - "어떤 결정을 내리셨나요?" (선택한 내용)
   - "다른 대안 대신 이것을 선택한 이유는 무엇인가요?" (배경과 맥락)
   - "이 결정으로 인한 영향은 무엇인가요?" (수용한 트레이드오프)
3. Write the ADR to `.3a/decisions/NNN-[topic].md`:

```markdown
# NNN: [Decision Title]

## Status
Accepted

## Context
[Why this decision was needed — the problem, constraints, and alternatives considered]

## Decision
[What was decided and why]

## Consequences
[What follows — benefits, tradeoffs, and risks accepted]
```

4. Update `.3a/architecture.md` if this decision changes the architecture summary.

Arguments provided: $ARGUMENTS
