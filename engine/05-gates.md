# Stage 05 · Gates

## Lenses

| Gate | Object |
|---|---|
| R0 | Manifest projection |
| G1 | PRD |
| O1 | Overview |
| U1 | Prototype |
| QA | Delivery bundle |

## Result files

```text
.delivery/gate-results/<revision>/R0.json
.delivery/gate-results/<revision>/G1.json
.delivery/gate-results/<revision>/O1.json
.delivery/gate-results/<revision>/U1.json
.delivery/gate-results/<revision>/QA.json
.delivery/gate-results/<revision>/Q1.json
```

The formal review runs on a read-only candidate freeze. Every formal round runs all six gates, even when only one artifact changed.

## Common result shape

```json
{
  "gate": "G1",
  "revision": "r3",
  "frozenCopy": ".delivery/candidate-revisions/r3",
  "independentContext": true,
  "result": "PASS",
  "objectHashes": {},
  "findings": [],
  "checkedAt": "ISO-8601",
  "tool": "agent-manual"
}
```

## Rules

- One lens does not rewrite another lens.
- Tool failure is `INCOMPLETE`.
- Evidence must refer to artifact locations or source references.
- Q1 aggregates only; it does not create a new business judgement.
