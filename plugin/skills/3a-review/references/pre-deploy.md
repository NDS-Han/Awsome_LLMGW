# Pre-Deploy Review Checklist

Run this before starting Phase 3 (Deploy).

## Agent Functionality

| # | Check | How to verify |
|---|---|---|
| 1 | System prompt defined | `main.py` contains a non-default system prompt |
| 2 | Core tools implemented | Tools listed in requirements are present in agent code |
| 3 | Core use cases work locally | `agentcore dev` + test each use case |

## External Connections

| # | Check | How to verify |
|---|---|---|
| 4 | All gateways configured | `agentcore/agentcore.json` lists required gateways |
| 5 | API credentials available | Environment variables or secrets configured |
| 6 | Gateway connections tested | Each gateway responds to a test call |

## Memory (if applicable)

| # | Check | How to verify |
|---|---|---|
| 7 | Memory type matches requirements | `agentcore/agentcore.json` memory config matches ADR |
| 8 | Memory behavior tested locally | Agent maintains context as expected |

## AWS Prerequisites

| # | Check | How to verify |
|---|---|---|
| 9 | AWS credentials configured | `aws sts get-caller-identity` succeeds |
| 10 | Region configured | `aws configure get region` returns expected region |
| 11 | `aws-targets.json` matches credentials | Account and region match caller identity |
| 12 | Bedrock model access enabled | Target model is accessible in the configured region |

## Code Quality

| # | Check | How to verify |
|---|---|---|
| 13 | No hardcoded secrets | Grep for API keys, passwords, tokens in source files |
| 14 | Dependencies declared | `pyproject.toml` lists all required packages |
| 15 | Error handling for external calls | External API calls have try/except or equivalent |

## Architecture Alignment

| # | Check | How to verify |
|---|---|---|
| 16 | Implementation matches ADRs | Tools, framework, protocol match recorded decisions |
| 17 | No unrecorded decisions | No major deviations from architecture without an ADR |
