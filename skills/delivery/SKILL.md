---
name: delivery
description: Assemble authoritative requirement inputs and execute the AI Native Delivery workflow to produce Issue Description, Overview, PRD Delivery, optional Prototype, Gates, and Workflow Summary. Works independently from Discovery and never writes to external systems.
metadata:
  version: 0.1.0
  phase: delivery
  entry: standalone
---

# Delivery

## Purpose

Delivery converts an authoritative requirement input into a reviewed, hash-consistent delivery bundle.

Discovery is optional. If a Concept Handoff exists, Delivery consumes it as evidence; if not, Delivery uses user-provided requirement material.

## Commands

```text
run           Execute through Design Ready
issue         Generate/iterate Issue Description
overview      Generate/iterate Overview
prd           Generate/iterate PRD Delivery
prototype     Generate/iterate optional Prototype
gates         Run available gates
repair        Repair A/B findings
seal          Validate and seal bundle
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

## Gates

Use `core/gate-policy.md`:

```text
R0 / G1 / O1 / U1 / QA / Q1
```

Maintain independent gate results. A downstream artifact failure does not rewrite G1.

## Findings and repair

Use `core/finding-ledger.md`.

Repair at most three rounds. Reuse `core/rerun-matrix.md` to determine affected gates.

## Sealing

Seal only when:

- Required artifacts exist
- Prototype status is explicit
- Q1 is PASS
- Blocking findings are zero
- Hashes match bundle metadata
- State is DESIGN_READY

`DESIGN_READY` means the local bundle is complete. It does not imply an external issue tracker was updated.

## Boundaries

- No external writes
- No requirement exploration
- No invention of business facts
- No placeholder prototype
- No gate failure treated as success
- No conversation memory used as authoritative input
