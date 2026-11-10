# Harness Plane

The Harness Plane is a cross-cutting control plane shared by Discovery, Delivery and Tech Solution. It is not a fourth Agent and it does not author business facts.

```text
┌──────────────────────────────────────────────────────────────┐
│                        Harness Plane                         │
│ Authority · Context · Task/Runtime · Review/Repair            │
│ Escalation · Quality Exit · Replay/Audit                      │
└───────────────┬───────────────────────┬──────────────────────┘
                │                       │
      Discovery Agent → Delivery Agent → Tech Solution Agent
```

## Responsibilities

| Plane | Responsibility | Hard rule |
|---|---|---|
| Authority | Define which artifact owns which fact domain | No silent cross-domain overwrite |
| Context | Assemble frozen facts, decisions, capabilities and provenance | Every input is hash-bound |
| Research / Decision | Resolve factual gaps before asking for business choices | Research is required only for configured, probeable sources; a Decision Card requires a research record when research is available |
| Capability Registry | Detect optional Jira, MCP and Git research sources | Probe results are runtime facts, never hardcoded availability |
| Task / Runtime | Bound reads, writes, time, runtime and cancellation | Agents write only within task scope |
| Review / Repair | Independent review, finding, repair, recheck | Producer cannot approve itself |
| Escalation | Repeated root causes, unresolved decisions and human choices | Open escalation blocks READY |
| Quality Exit | Aggregate evidence before Handoff | Failed quality exit cannot produce READY Handoff |
| Replay / Audit | Preserve state, transcript, evidence and hashes | Final claims must be replayable |

## Domain authority

- **PRD** is authoritative for business goals, scope, rules, states, permissions, data meaning and acceptance criteria.
- **Prototype** is authoritative for interaction-domain facts: pages, entry points, visible controls, visible states, field visibility, interaction feedback and visible copy.
- **Overview** is a projection of a synchronized Pair and may not create new business facts.
- **Jira description** is a derived project-management projection and is not a fact source.
- **Capability Context** is authoritative only for the recorded identity, aliases, provenance, confidence and reuse boundary of an existing capability.

PRD and Prototype are equal within their own domains. A semantic conflict produces `RESYNC_REQUIRED`; it never produces an automatic overwrite.

## Context freeze

Every Agent Task receives a frozen Context Pack containing, when applicable:

```text
Requirement
Decision Context
Capability Context
Source Provenance
Artifact Profile
Authority Matrix
Upstream results and hashes
Repair Context
```

A reviewer receives a read-only frozen copy. A repair task receives only the artifact and scope it is authorized to modify.

## Research-first decision

```text
clue
→ classify as fact or business decision
→ inspect Agent Capability Registry
→ if a source is configured: probe it at runtime
→ if available: search Jira / MCP / Git / runtime / tests
→ if not configured: use the normal decision flow
→ if configured but error: return the actual error; do not relabel it as unavailable
→ resolve facts directly
→ retain conflicting evidence and recommend
→ ask the product only when a real business choice remains undecided
```

Only `NEEDS_BUSINESS_DECISION` research may create a Decision Card. A factual gap with existing evidence must not be escalated to the product. Availability of optional Jira, MCP and Git capabilities is always dynamic and evidence-based.

## Quality exit

Quality Exit runs after final review and before Delivery Handoff. It verifies:

```text
Decision Readiness = READY / PROCEED
Required reviews closed
Blocking findings = 0
Failed Work Plan tasks = 0
Open Escalations = 0
Applicable Pair = SYNCED
Unresolved delta = 0
Stale projection = 0
Evidence and hashes exist
```

## Failure safety

- Invalid structured output is `FAILED`, never `PASS`.
- Timeout, cancellation and interrupted execution remain auditable.
- A repeated blocking root cause creates an Escalation.
- An open Escalation or unresolved Decision blocks Handoff.
- Gatekeeper decisions cannot be overridden by natural-language consensus.
