# Pre-Implementation Review Checklist

Run this before starting Phase 2 (Implement).

## Requirements

| # | Check | How to verify |
|---|---|---|
| 1 | Requirements documented | `.3a/requirements.md` exists and has all sections filled |
| 2 | Core capabilities defined | At least 2 capabilities listed in requirements |
| 3 | External dependencies identified | Dependencies section filled (or explicitly "none") |

## Architecture Decisions

| # | Check | How to verify |
|---|---|---|
| 4 | Framework decision recorded | `.3a/decisions/` contains framework ADR |
| 5 | Protocol decision recorded | `.3a/decisions/` contains protocol ADR |
| 6 | Build method decision recorded | `.3a/decisions/` contains build method ADR |
| 7 | Memory decision recorded | `.3a/decisions/` contains memory ADR |

## Project Scaffold

| # | Check | How to verify |
|---|---|---|
| 8 | AgentCore project created | `agentcore/agentcore.json` exists |
| 9 | Local dev server works | `agentcore dev` starts without errors |
| 10 | Agent responds to basic input | `agentcore dev` + test invocation succeeds |

## Roadmap

| # | Check | How to verify |
|---|---|---|
| 11 | Roadmap exists | `.3a/roadmap.md` exists |
| 12 | Phase 2 tasks are specific | Each task describes a concrete deliverable, not vague goals |
