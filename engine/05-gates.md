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
.delivery/gate-results/R0.json
.delivery/gate-results/G1.json
.delivery/gate-results/O1.json
.delivery/gate-results/U1.json
.delivery/gate-results/QA.json
.delivery/gate-results/Q1.json
```

## Common result shape

```json
{
  "gate": "G1",
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
