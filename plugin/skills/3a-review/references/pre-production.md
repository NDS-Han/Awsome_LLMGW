# Pre-Production Review Checklist

Run this before promoting to production or exposing to real users.

## Deployment Verified

| # | Check | How to verify |
|---|---|---|
| 1 | Agent deployed and running | `agentcore status` shows ACTIVE |
| 2 | All resources healthy | `agentcore status` shows no errors |
| 3 | Invoke succeeds end-to-end | `agentcore invoke` with test input returns expected output |

## Security

> 보안 점검 항목의 상세 기준은 [AWS Prescriptive Guidance — Security for Agentic AI](https://docs.aws.amazon.com/prescriptive-guidance/latest/agentic-ai-security/introduction.html) 참고

| # | Check | How to verify |
|---|---|---|
| 4 | No secrets in source code | Grep for API keys, passwords, tokens |
| 5 | IAM roles follow least privilege | Review IAM role policies attached to agent |
| 6 | Input validation on user-facing inputs | Agent handles malicious or unexpected input gracefully |
| 7 | Guardrails configured | Bedrock guardrails or policy engine applied if needed |

## Reliability

| # | Check | How to verify |
|---|---|---|
| 8 | Error handling tested | Agent returns graceful responses on tool failures |
| 9 | Timeout behavior verified | Agent handles slow external services without hanging |
| 10 | Retry logic for external calls | Transient failures don't crash the agent |

## Observability

| # | Check | How to verify |
|---|---|---|
| 11 | Logs accessible | `agentcore logs` returns recent invocations |
| 12 | Errors are logged with context | Failed invocations include enough detail to diagnose |
| 13 | Monitoring/alerts configured | CloudWatch alarms or equivalent set up |

## Performance

| # | Check | How to verify |
|---|---|---|
| 14 | Response time acceptable | Test invocations complete within latency requirement |
| 15 | Concurrent usage tested | Multiple simultaneous invocations succeed |

## Operational Readiness

| # | Check | How to verify |
|---|---|---|
| 16 | Rollback plan documented | Know how to revert to previous version |
| 17 | On-call or escalation path defined | Someone owns this agent in production |
| 18 | Runbook for common issues | Document known failure modes and fixes |
| 19 | Cost estimate reviewed | Understand expected Bedrock/compute costs |

## Architecture Alignment

| # | Check | How to verify |
|---|---|---|
| 20 | All requirements met | Cross-reference `.3a/requirements.md` with deployed agent |
| 21 | All ADRs still valid | No outdated decisions in `.3a/decisions/` |
