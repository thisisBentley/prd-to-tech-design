# State Contract

Runtime state is stored at:

```text
runRoot/.delivery/state.json
```

State is optional when Discovery or Delivery is used independently. If both run against the same requirement, state is the only handoff mechanism; conversation memory is not authoritative.

## State machine

```text
PHASE1_NOT_RUN
PHASE1_CONCEPT_DRAFT
PHASE1_CONCEPT_READY

PHASE2_DESIGN_DRAFTING
PHASE2_DESIGN_READY
```

Blocking states:

```text
BLOCKED_PRODUCT_DECISION
BLOCKED_SOURCE
BLOCKED_UI_INPUT
BLOCKED_TECH_FACT
BLOCKED_INSUFFICIENT_INPUT
FAILED
```

## Shape

```json
{
  "schemaVersion": 1,
  "requirement": {
    "id": "DEMO-001",
    "name": "Synthetic support analytics"
  },
  "runRoot": "/absolute/path",
  "createdAt": "ISO-8601",
  "updatedAt": "ISO-8601",

  "phase1": {
    "skill": "discovery",
    "status": "CONCEPT_READY",
    "briefPath": "00-discovery/Requirement_Brief.md",
    "contextSnapshotPath": "00-discovery/.context/context-snapshot.json",
    "capabilityIdeationPath": "00-discovery/.context/capability-ideation.json",
    "capabilityMatrixPath": "00-discovery/.context/capability-matrix.json",
    "openDecisions": []
  },

  "phase2": {
    "skill": "delivery",
    "status": "DESIGN_READY",
    "inputSources": [
      {"type": "requirement_text", "path": "input.md"},
      {"type": "concept_brief", "path": "00-discovery/Requirement_Brief.md"}
    ],
    "adapterUsage": [
      {"capability": "issue_tracker", "provider": "manual"},
      {"capability": "code_intelligence", "provider": "none"}
    ],
    "evidenceCoverage": "partial",
    "bundleId": "DEMO-001-20261103-001",
    "candidateRevision": "r3",
    "finalRevision": "r3",
    "reviewRunId": "review-20261106-001",
    "gates": {
      "R0": "PASS",
      "G1": "PASS",
      "O1": "PASS",
      "U1": "PASS",
      "U2": "PASS_WITH_NONBLOCKING",
      "QA": "PASS",
      "Q1": "PASS_WITH_NONBLOCKING"
    },
    "reviewEvidence": ".delivery/reviews/review-20261106-001/envelope.json"
  }
}
```

## Ownership

- Discovery writes only `phase1` and common timestamps.
- Delivery writes only `phase2` and common timestamps.
- One phase must never rewrite the other's business conclusions.
- Manual external updates do not alter local state automatically.

## Harness states

The Harness Plane adds the following control states to the stage state machine:

```text
DECISION_BLOCKED
QUALITY_BLOCKED
RECHECK_REQUIRED
ESCALATION_OPEN
RESYNC_REQUIRED
READY
```

Transition rules:

- `DECISION_BLOCKED` means Decision Readiness is not `READY/PROCEED`; PRD production cannot start.
- `QUALITY_BLOCKED` means Quality Exit has an open blocker, failed task or missing evidence.
- `RECHECK_REQUIRED` means a repair changed a frozen artifact or a root cause remains open.
- `ESCALATION_OPEN` means repeated blocking root cause or unresolved human decision; Handoff is forbidden.
- `RESYNC_REQUIRED` means PRD / Prototype / Overview revisions or domain facts disagree.
- `READY` is reachable only after deterministic Quality Exit and Gatekeeper checks pass.

Every state transition records the task, revision, evidence paths and updated hash references.
