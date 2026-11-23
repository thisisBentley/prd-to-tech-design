# Collaboration Surface — WF-COMPLETE-DEMO

- Requirement: `REQ-COMPLETE-DEMO`
- Artifact profile: `PRD_PLUS_PROTOTYPE`
- Revision: `r1`
- Status: `ACTION_REQUIRED`
- Objective: Expense submission flow

> Read-only derived view. Final Gate, release eligibility and training approval remain unchanged.

## Change Digest

**AVAILABLE** — 1 revision/repair events, 0 changed artifacts.

- `r1`: CANDIDATE_SEALED — no artifact list

## Review Digest

**UNAVAILABLE** — 0 reviews / 0 accepted / 0 returned / 0 blocked.
- Consumer reports: 0 total / 0 real / 0 fixture; statuses=none.

## Decision Digest

**UNAVAILABLE** — 0 decisions / 0 open / 0 confirmed.

## Risk Digest

**ATTENTION** — blocking=0, nonBlocking=4, info=0.
- **NON_BLOCKING** `RISK-EVIDENCE-GAPS`: Evidence gaps remain — gaps=3
- **NON_BLOCKING** `RISK-NO-REVIEWS`: No matching independent reviews found — The surface has no review records for the current workflow/revision.
- **NON_BLOCKING** `RISK-NO-REAL-CONSUMER`: No real consumer report — Only fixture or no consumer evidence is available.
- **NON_BLOCKING** `RISK-COST-INCOMPLETE`: Cost metrics are incomplete — availability=PARTIAL

## Evidence Digest

**PARTIAL** — sources=1; SOURCE_FACT=1, MEASURED=2, DERIVED=1, REFERENCE=0, INFERENCE=0.

Evidence gaps:
- consumer acceptance reports: NONE
- optional source missing: FINDING_LEDGER
- optional source missing: REPAIR_CYCLE

## Next Action

**ACTION_REQUIRED**
- **P1** `RUN_CONSUMER_ACCEPTANCE` → consumer-review-owner: Run PM and Architect consumer acceptance and attach the reports. (No consumer acceptance report is available.)
- **P1** `RUN_INDEPENDENT_REVIEW` → review-owner: Run an independent review for the current revision. (No matching review was found.)
- **P1** `COLLECT_MISSING_EVIDENCE` → evidence-owner: Collect or explicitly classify the missing evidence. (evidenceGaps=3)
- **P2** `IMPROVE_COST_TELEMETRY` → runtime-owner: Add missing timing and context telemetry. (Cost metrics are PARTIAL or UNAVAILABLE.)

## Authority

This surface is read-only. It does not approve release, modify facts, or grant training eligibility.
