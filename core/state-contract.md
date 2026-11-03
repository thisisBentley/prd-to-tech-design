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
    "gates": {
      "R0": "PASS",
      "G1": "PASS",
      "O1": "PASS",
      "U1": "PASS",
      "QA": "PASS",
      "Q1": "PASS"
    }
  }
}
```

## Ownership

- Discovery writes only `phase1` and common timestamps.
- Delivery writes only `phase2` and common timestamps.
- One phase must never rewrite the other's business conclusions.
- Manual external updates do not alter local state automatically.
