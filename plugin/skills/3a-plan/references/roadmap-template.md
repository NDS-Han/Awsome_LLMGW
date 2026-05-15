# Roadmap

## Project: [Project Name]
**Created**: [date]
**Architecture**: [framework] + [protocol] + [build method]

---

## Phase 1: Scaffold

**Goal**: Project created, agent responds to basic input locally.

- [ ] Create project with `agentcore create`
- [ ] Verify project structure
- [ ] Run `agentcore dev` and test basic response
- [ ] Verify agent responds to "hello"

**Skill**: `agents-get-started`
**Milestone**: `agentcore dev` runs and agent responds.

---

## Phase 2: Implement

**Goal**: Agent handles core use cases locally.

- [ ] Define system prompt
- [ ] Add tool 1: [description]
- [ ] Add tool 2: [description]
- [ ] Connect external service: [service name]
- [ ] Add memory: [type]
- [ ] Test core use cases locally

**Skills**: `agents-build`, `agents-connect`
**Milestone**: Agent handles [core use case] via `agentcore dev`.

---

## Phase 3: Deploy

**Goal**: Agent running on AWS, accessible remotely.

- [ ] Run `3a-review pre-deploy`
- [ ] Deploy to staging with `agentcore deploy`
- [ ] Verify with `agentcore invoke`
- [ ] Test all core use cases on deployed agent
- [ ] Check logs with `agentcore logs`

**Skills**: `agents-deploy`, `agents-debug`
**Milestone**: `agentcore invoke` returns correct responses.

---

## Phase 4: Harden (if production)

**Goal**: Agent ready for real users.

- [ ] Run `3a-review pre-production`
- [ ] Add error handling and guardrails
- [ ] Configure monitoring and alerts
- [ ] Set up access controls
- [ ] Load test

**Skills**: `agents-harden`, `agents-optimize`
**Milestone**: Agent passes production readiness review.
