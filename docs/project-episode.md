# Project Episode v0

## Purpose

A Project Episode is the replayable record of one Delivery run, keyed by:

```text
workflowId + requirementId + revision
```

It assembles existing evidence rather than creating new facts or another workflow.
It is a **derived** artifact and does not approve release, quality or training.

## Inputs

```text
Delivery Operating Procedure
Delivery Handoff
Finding Ledger
Repair Cycle
Cost / Revision Ledger
Consumer Acceptance Reports
Final Gate
Human Decision records
```

Core sources:

```text
Delivery Operating Procedure
Delivery Handoff
Cost / Revision Ledger
Final Gate
```

Missing core source or workflow/revision mismatch → `BLOCKED`.

Optional missing evidence → `PARTIAL` with explicit `evidenceGaps`.

## Evidence Layers

```text
SOURCE_FACT  handoff and human decisions
MEASURED     findings, repair, cost, consumer reports, final gate
DERIVED      Delivery Operating Procedure
REFERENCE    optional external references
INFERENCE    optional model hypotheses
```

The Episode never promotes lower-layer content into source fact automatically.

## Build

```bash
python3 tools/build_project_episode.py \
  --run-root . \
  --workflow-id WF-1 \
  --requirement-id REQ-1 \
  --artifact-profile PRD_ONLY \
  --revision r2 \
  --procedure delivery-operating-procedure.json \
  --handoff delivery-ready.handoff.json \
  --finding-ledger findings.json \
  --repair-cycle repair-cycle-report.json \
  --cost-ledger cost-revision-ledger.json \
  --final-gate final-package-gate.json \
  --consumer-report consumer-report.json \
  --decision-dir decisions \
  --out project-episode.json
```

`delivery_pipeline.py` builds and validates the Episode after the Cost Ledger and
before the Complete Gate. Its path and SHA-256 are attached to Package Evidence.

## Status

```text
COMPLETE  all core sources available, no evidence gap, human decisions recorded
PARTIAL   core sources valid but optional evidence or human adjudication is missing
BLOCKED   missing core source or workflow/revision conflict
```

`PARTIAL` is valid for engineering use. It is not release evidence.

## Timeline

The Episode records deterministic events from:

- revision statuses in the Cost Ledger;
- Repair stages;
- Consumer Acceptance Reports;
- the Final Gate.

## Training Boundary

Project Episode v0 always emits:

```json
{
  "trainingEligibility": {
    "eligible": false,
    "status": "BLOCKED",
    "reasons": [
      "D14_EPISODE_TRAINING_DISABLED",
      "HUMAN_ADJUDICATION_NOT_RECORDED"
    ]
  }
}
```

An Episode can be replayed and analyzed, but it cannot be promoted to training or
model optimization in this iteration.

## Validate

```bash
python3 tools/validate_project_episode.py \
  --episode project-episode.json \
  --verify-source-hashes
```

Validation enforces the schema, non-BLOCKED status, source hash stability and
`trainingEligibility.eligible=false`.

## Non-goals

- no training approval;
- no quality certification;
- no hidden root-cause inference;
- no automatic Prompt or model modification;
- no replacement for the Final Gate or human adjudication.
