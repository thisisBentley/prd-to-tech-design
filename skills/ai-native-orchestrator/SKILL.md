---
name: ai-native-orchestrator
description: Coordinate isolated Discovery, Delivery and Tech Solution producers with consumer reviewers, independent reviewers, structured handoffs, human decision cards and a deterministic Gatekeeper. Enforce role separation and evidence-backed advancement without authoring business or technical artifacts itself.
metadata:
  version: 0.1.0
  phase: orchestration
  entry: standalone
---

# AI Native Orchestrator

## Purpose

Convert a product idea into a reviewed delivery and technical solution through a controlled collaboration network.

The Orchestrator schedules work and validates contracts. It does not judge product quality, write artifacts, or approve gates.

## Roles

```text
discovery-producer
delivery-intake-reviewer
delivery-producer
delivery-reviewer
qa-red-team
tech-prd-diagnostician
tech-producer
tech-reviewer
product-acceptance-reviewer
deterministic-gatekeeper
```

Read `agents/roles/` for role boundaries and `core/authority-matrix.md` for authority.

## Commands

```text
init                 Initialize orchestration state
register-handoff     Validate and register a frozen handoff
register-review      Validate and register a review plan + result
register-decision    Register a human Decision Card
register-escalation  Register an unresolved disagreement
advance              Advance only when required reviews accept
gatekeeper           Run deterministic final validation
validate             Revalidate the complete workflow
status               Report workflow state
```

## Workflow

```text
Discovery Producer
→ Delivery Intake Reviewer
→ Delivery Producer
→ Delivery Reviewer + QA Red Team
→ Tech PRD Diagnostician
→ Tech Producer
→ Tech Reviewer
→ Product Acceptance Reviewer
→ Deterministic Gatekeeper
→ READY
```

Consumer and independent reviews are distinct. A consumer reviewer decides whether it can safely use an upstream handoff. An independent reviewer challenges the artifact. Neither may modify the artifact.

## Hard rules

- A producer cannot review or approve its own work.
- Producer and reviewer contexts must differ.
- Reviewers read frozen artifacts only.
- Accepted reviews require checks, evidence, complete execution and zero blockers.
- `RETURNED` goes back to the producing role.
- `BLOCKED` requires a human Decision Card.
- Two unresolved disagreement rounds become an escalation.
- The Gatekeeper is a program and cannot be persuaded by prose.
- Readiness requires the complete review chain and zero open decisions or escalations.

## State and files

```text
runRoot/.agents/
├── orchestration.json
├── handoffs/
├── reviews/
├── decisions/
└── escalations/
```

Use the JSON schemas in `schemas/` and the deterministic tools in `tools/`.

## Boundaries

- Do not author PRD, Prototype or technical solution content.
- Do not edit reviewer findings.
- Do not convert `INCOMPLETE`, `RETURNED` or `BLOCKED` into readiness.
- Do not use majority voting to settle evidence conflicts.
- Do not update external systems.
