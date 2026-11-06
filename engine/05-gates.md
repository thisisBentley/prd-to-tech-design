# Stage 05 · Gates

## Lenses

| Gate | Object |
|---|---|
| R0 | Manifest projection |
| G1 | PRD business semantics |
| O1 | PRD + Overview |
| U1 | PRD + Prototype consistency |
| U2 | Prototype + UI standards |
| QA | Delivery bundle testability |
| Q1 | Sealed-bundle aggregate |

## Result files

```text
.delivery/gate-results/<revision>/R0.json
.delivery/gate-results/<revision>/G1.json
.delivery/gate-results/<revision>/O1.json
.delivery/gate-results/<revision>/U1.json
.delivery/gate-results/<revision>/U2.json
.delivery/gate-results/<revision>/QA.json
.delivery/gate-results/<revision>/Q1.json
.delivery/reviews/<reviewRunId>/envelope.json
```

The formal review runs on a read-only candidate freeze. Every formal round runs all seven gates, even when only one artifact changed.

## Required v2 result shape

```json
{
  "schemaVersion": 2,
  "gate": "G1",
  "revision": "r3",
  "frozenCopy": ".delivery/candidate-revisions/r3",
  "independentContext": true,
  "reviewRunId": "review-20261106-001",
  "result": "PASS",
  "ruleSetVersion": "prd-admission-1.0",
  "objectHashes": {
    "PRD_DELIVERY.md": "sha256"
  },
  "checks": [
    {
      "checkId": "G1.MUST.5.5.roles",
      "status": "passed",
      "evidenceRefs": ["PRD §3.8"],
      "observed": "role matrix is explicit",
      "expected": "roles and denied result are unique"
    }
  ],
  "findings": [],
  "blockingCount": 0,
  "completionStatus": "complete",
  "tool": "review-worker",
  "checkedAt": "ISO-8601"
}
```

## Mandatory checks

- R0: manifest projection, requirement identity, revision/hash agreement, required artifact presence.
- G1: all eight PRD admission MUST checks, every triggered CONDITIONAL check, role/permission matrix, action/export contract, enum dictionary, exception recovery, and AC traceability.
- O1: six tabs, PRD-only facts, links, and offline rendering.
- U1: PRD requirement-to-page mapping, role/permission states, action results, enum consistency, field mapping, exception rendering, timeout/event distinction, reverse Prototype-only rule check.
- U2: all applicable UI standards and required runtime checks.
- QA: testability, boundaries, exceptions, and AC coverage.
- Q1: recomputation only.

## Rules

- One lens does not rewrite another lens.
- Tool failure or an unreachable artifact is `INCOMPLETE`.
- A PASS result must have an executable check ledger with evidence.
- Evidence must refer to exact PRD sections, stable IDs, HTML locations, selectors, runtime observations, or source references.
- Q1 aggregates and recomputes only; it does not create a new business judgement.
- The candidate-producing session must not directly edit formal gate result JSON.
