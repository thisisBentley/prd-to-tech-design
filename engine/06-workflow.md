# Stage 06 · Workflow Summary and Sealing

## Goal

Record execution truth and seal the bundle.

## Workflow summary sections

1. Current status
2. Completed stages
3. Input sources and adapters
4. Product decisions
5. Gate results
6. Repair rounds
7. Artifact hashes
8. Unverified items
9. Next action

## Bundle

`.delivery/bundle.json`:

```json
{
  "schemaVersion": 1,
  "bundleId": "DEMO-001-20261103-001",
  "status": "DESIGN_READY",
  "artifacts": {
    "issueDescription": {"path": "Issue_Description.md", "sha256": "..."},
    "overview": {"path": "Overview.html", "sha256": "..."},
    "prd": {"path": "PRD_DELIVERY.md", "sha256": "..."},
    "prototype": {"path": "Prototype.html", "status": "TRIGGERED", "sha256": "..."},
    "gates": {"path": "Gates.md", "sha256": "..."},
    "workflow": {"path": "Workflow.md", "sha256": "..."}
  },
  "gates": {
    "R0": "PASS",
    "G1": "PASS",
    "O1": "PASS",
    "U1": "PASS",
    "QA": "PASS",
    "Q1": "PASS"
  },
  "openBlockingFindings": 0
}
```

## Sealing checks

- All required artifacts exist
- Prototype status is explicit
- Q1 is PASS
- No open blocking findings
- Hashes match
- State is updated to DESIGN_READY
