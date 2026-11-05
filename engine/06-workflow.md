# Stage 06 · Workflow Summary and Sealing

## Goal

Record execution truth, seal candidate revisions, run independent full-gate reviews, and finalize only after all gates pass.

## Workflow summary sections

1. Current status
2. Candidate revision and final revision
3. Completed stages
4. Input sources and adapters
5. Product decisions
6. Candidate seal and final seal
7. Gate rounds and final results
8. Repair rounds
9. All six artifact hashes
10. Final gate output paths
11. Unverified items
12. Next action

## Bundle

`.delivery/bundle.json`:

```json
{
  "schemaVersion": 2,
  "bundleId": "DEMO-001-20261105-001",
  "status": "DESIGN_READY",
  "candidateRevision": "r2",
  "finalRevision": "r2",
  "candidateSeal": ".delivery/candidate-seal.json",
  "finalSeal": ".delivery/final-seal.json",
  "artifacts": {
    "issueDescription": {"path": "Issue_Description.md", "sha256": "..."},
    "overview": {"path": "Overview.html", "sha256": "..."},
    "prd": {"path": "PRD_DELIVERY.md", "sha256": "..."},
    "prototype": {"path": "Prototype.html", "status": "TRIGGERED", "sha256": "..."},
    "gates": {"path": "Gates.md", "sha256": "..."},
    "workflow": {"path": "Workflow.md", "sha256": "..."},
    "manifest": {"path": ".delivery/requirements.json", "sha256": "..."}
  },
  "gateOutputs": {
    "review": "gate-outputs/Final_Gate_Review.md",
    "R0": "gate-outputs/R0.json",
    "G1": "gate-outputs/G1.json",
    "O1": "gate-outputs/O1.json",
    "U1": "gate-outputs/U1.json",
    "QA": "gate-outputs/QA.json",
    "Q1": "gate-outputs/Q1.json"
  },
  "gates": {"R0":"PASS","G1":"PASS","O1":"PASS","U1":"PASS","QA":"PASS","Q1":"PASS"},
  "gateRounds": 2,
  "hashStableDuringFinalReview": true,
  "openBlockingFindings": 0
}
```

## Candidate sealing checks

- Six candidate artifacts and manifest exist
- Candidate revision is recorded
- All hashes are computed
- Frozen copy is read-only

## Final sealing checks

- All six final gate results are PASS
- Candidate Gates and Workflow match final gate results
- Hashes are unchanged before and after independent review
- Final gate report and six gate JSON files exist
- No open blocking findings
- State is updated to DESIGN_READY
