---
name: tech-solution
description: Convert an accepted Delivery handoff into a technically feasible, testable and operable technical solution while preserving product decisions. Produces technical evidence, decision closure, architecture when triggered, verification entries and a frozen handoff for independent and product-acceptance review.
metadata:
  version: 0.1.0
  phase: tech-solution
  entry: standalone
---

# Tech Solution

## Purpose

Turn the accepted product contract into an implementable technical solution without reopening product decisions.

## Inputs

- accepted Delivery handoff;
- PRD and optional Prototype;
- Delivery gate outcomes and source provenance;
- technical evidence from adapters, code, interfaces and user-provided facts;
- confirmed Decision Context.

## Required work

1. Lock sources, revisions and hashes.
2. Reconnoiter technical evidence.
3. Close technical defaults and external contracts without changing user results.
4. Build requirement, change, evidence and verification ledgers.
5. Trigger architecture work when the decision rules require it.
6. Produce the technical solution candidate.
7. Freeze and hand off for review.

## Review chain

```text
Tech Producer
→ Tech Reviewer (T1/R1 and architecture when triggered)
→ Product Acceptance Reviewer (requirement inheritance)
→ Gatekeeper
```

## Forbidden

- changing product scope, rules, permissions or acceptance;
- treating current code behavior as a product requirement;
- filling PRD gaps inside the solution;
- self-approving T1/R1;
- entering final readiness without Product Acceptance Review.
