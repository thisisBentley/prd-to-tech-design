---
name: delivery
description: Assemble authoritative requirement inputs and execute the AI Native Delivery workflow to produce six candidate artifacts, seal each candidate revision, run all gates in an independent context, repair and repeat until all gates pass, then emit separate final gate report/result files and final seal. Works independently from Discovery and never writes to external systems.
metadata:
  version: 0.2.0
  phase: delivery
  entry: standalone
---

# Delivery

## Purpose

Delivery converts an authoritative requirement input into a reviewed, hash-consistent delivery bundle.

Discovery is optional. If a Concept Handoff exists, Delivery consumes it as evidence; if not, Delivery uses user-provided requirement material.

## Commands

```text
run           Generate candidates through final seal
issue         Generate/iterate Issue Description
overview      Generate/iterate Overview
prd           Generate/iterate PRD Delivery
prototype     Generate/iterate optional Prototype
seal          Freeze six candidate artifacts
gates         Run all gates in an independent context
repair        Return to Delivery and modify candidates
finalize      Emit final gate outputs and final seal
status        Report state
```

## Input assembly

Assemble all available authoritative inputs:

- Requirement text
- Issue snapshot
- Existing PRD
- Prototype or screenshots
- Requirement Brief
- Context Snapshot
- Capability Matrix
- Product decisions
- Specialist facts

Record:

```json
{
  "inputSources": [],
  "adapterUsage": [],
  "evidenceCoverage": "sufficient | partial | unavailable"
}
```

Block only when the input cannot uniquely determine business facts:

```text
BLOCKED_INSUFFICIENT_INPUT
```

Offer the user two choices:

1. Supply missing material.
2. Run Discovery.

## Artifacts

Fixed user-facing order:

```text
runRoot/01-delivery/
├── Issue_Description.md
├── Overview.html
├── PRD_DELIVERY.md
├── Prototype.html       # optional
├── Gates.md
└── Workflow.md
```

### Issue description

Fixed three sections:

1. Requirement background
2. Requirement goal
3. Detailed requirements involved

Keep it concise and business-readable. Do not update an external tracker.

### PRD

The sole business fact source. Other artifacts consume it and never redefine it.

### Prototype

Generate only when user-visible interaction changes. Otherwise record `prototypeStatus: NOT_TRIGGERED`.

## Gates and final output

Use `core/gate-policy.md`.

```text
Candidate generation
→ Candidate seal
→ Independent full review: R0 / G1 / O1 / U1 / QA / Q1
→ Failure: repair, new revision, reseal, full review again
→ Pass: Final_Gate_Review.md + R0/G1/O1/U1/QA/Q1 JSON
→ Final seal
```

Formal reviews always run all gates and never reuse a generation-session self-check. A downstream artifact failure does not rewrite G1.

## Findings and repair

Use `core/finding-ledger.md`.

Repair at most three rounds. Reuse `core/rerun-matrix.md` to determine affected gates.

## Sealing

Candidate seal records a frozen revision and all six artifact hashes. It is not final delivery.

Final seal requires:

- Final revision all gates PASS
- Candidate Gates/Workflow match final gate results
- Hashes unchanged during independent review
- Final gate report and six individual gate JSON files exist
- Blocking findings are zero
- State is DESIGN_READY

`DESIGN_READY` means the local bundle is complete. It does not imply an external issue tracker was updated.

## Boundaries

- No external writes
- No requirement exploration
- No invention of business facts
- No placeholder prototype
- No gate failure treated as success
- No conversation memory used as authoritative input
