---
name: delivery
description: Assemble authoritative requirement inputs and execute the AI Native Delivery workflow to produce six candidate artifacts, seal each candidate revision, run all gates in an independent evidence-backed context, repair and repeat until all gates pass, then emit separate final gate reports/results and a final seal. Works independently from Discovery and never writes external systems.
metadata:
  version: 0.4.0
  phase: delivery
  entry: standalone
---

# Delivery

## Purpose

Delivery converts an authoritative requirement input into a reviewed, hash-consistent delivery bundle.

It has two distinct roles:

- **Delivery Producer** authors candidates but cannot approve them.
- **Delivery Reviewer + QA Red Team** review frozen candidates in separate contexts.

When an upstream Discovery handoff exists, **Delivery Intake Reviewer** must accept its sufficiency before authoring starts.

## Commands

```text
run           Generate candidates through final seal
issue         Generate or iterate Issue Description
overview      Generate or iterate Overview
prd           Generate or iterate PRD Delivery
prototype     Generate or iterate optional Prototype
seal          Freeze six candidate artifacts
review-job    Export an immutable independent review job
gates         Run all gates in an independent worker
repair        Return to Delivery after Finding Enrichment and modify candidates
finalize      Validate final evidence and emit final seal
status        Report state
```

## Input assembly and intake

Assemble all authoritative inputs and record `inputSources`, `adapterUsage`, and `evidenceCoverage`.

Before writing a PRD, perform Delivery Intake Review. Reject a Discovery handoff when sources, evidence, decisions or unknowns are insufficient. Do not fill missing product facts inside Delivery.

## Independent review

After sealing:

```text
Delivery Producer
→ Delivery Reviewer
→ QA Red Team
→ Tech PRD Diagnostician
```

The first two reviews are independent quality reviews of the delivery bundle. The Tech PRD Diagnostician is a cross-stage consumer review performed before technical authoring. A producer cannot write formal gate results or close reviewer findings by explanation.

## Artifacts

```text
runRoot/01-delivery/
├── Issue_Description.md
├── Overview.html
├── PRD_DELIVERY.md
├── Prototype.html
├── Gates.md
└── Workflow.md
```

PRD is the sole business fact source. The prototype is generated only when user-visible interaction, permissions, state, fields, or feedback change.

## Gates

Use `core/gate-policy.md` and `skills/delivery/references/gate-result-contract.md`.

```text
Candidate generation
→ Candidate seal
→ Export review job
→ Independent worker: R0 / G1 / O1 / U1 / U2 / QA / Q1
→ Failure or incomplete evidence: Finding Enrichment, repair, new revision, full rerun
→ Evidence-backed PASS
→ Final gate outputs + final seal
```

A PASS without an executed check ledger, evidence references, object hashes, a review worker, and zero blockers is invalid. Never treat an empty findings array as proof.

The generating session must not write formal gate results. It seals candidates and exports a job; `agents/review-gates.md` defines the independent worker.

## Final seal

Final seal requires:

- bundle, state, candidate seal and final seal agree on revision;
- all seven Gate Result v2 files validate;
- Q1 is recomputed from upstream results;
- candidate and final hashes are stable;
- Gates.md and Workflow.md exactly match final results;
- Decision Context is READY;
- Delivery Intake Review accepted the Discovery handoff when one is used;
- Delivery Reviewer and QA Red Team accepted the latest frozen revision;
- Tech PRD Diagnostician accepted the PRD for technical design;
- any findings have a READY Finding Repair Context and zero open blockers;
- final report and seven gate JSON files exist;
- state is `DESIGN_READY`.

## Boundaries

- No external writes.
- No requirement exploration.
- No invented business facts.
- No placeholder prototype.
- No evidence-free PASS.
- No conversation memory used as authoritative input.
