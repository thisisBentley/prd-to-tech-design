---
name: delivery
description: Assemble authoritative requirement inputs and execute the AI Native Delivery workflow to produce six candidate artifacts, seal each candidate revision, run all gates in an independent evidence-backed context, repair and repeat until all gates pass, then emit separate final gate reports/results and a final seal. Works independently from Discovery and never writes external systems.
metadata:
  version: 0.7.0
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

## Production candidate artifacts

Structural PASS is not production quality. Delivery must distinguish:

```text
BASELINE_ONLY          deterministic scaffold
PRODUCTION_CANDIDATE   semantic/provided PRD + semantic/provided downstream artifacts
```

Quality validation is performed by `tools/validate_delivery_artifacts.py`. The Pipeline can consume high-quality external artifacts through `--artifact-source-dir`; it still runs Pair, runtime, semantic coverage, Quality Exit and Handoff gates.

## Research adapter execution

Use `tools/run_research_queries.py` with an adapter config before Decision Readiness when factual gaps exist. Each adapter receives a query JSON on stdin. Timeout, retry and every failed attempt are retained.

The bundled Jira adapter is:

```text
adapters/research/providers/project_management_space_adapter.py
```

It wraps Project Management Space snapshots and does not hardcode issue fields into Delivery.

## Unified pipeline

Use `tools/delivery_pipeline.py` for a full package. It runs the PRD core, optional Research Package import, Prototype/Pair creation, final Semantic Review, Overview, Jira Description, Quality Exit, Handoff and COMPLETE-gate assessment.

`PACKAGE_READY` means the six-domain package and Quality Exit are complete. It does not mean production `COMPLETE`; the latter still requires 3-5 real production-eligible samples and a real replay.

## Research evidence and semantic quality harness

Before a missing fact becomes a product question, Delivery must execute the Research-First decision contract:

```text
fact clue
→ classify as fact or user-visible business choice
→ probe optional Jira / MCP / Git sources at runtime
→ resolve from evidence when possible
→ assign unresolved work to DELIVERY / TECH / PRODUCT
→ only PRODUCT-owned, user-visible choices become Decision Cards
```

`FACT_CONFLICT` and `NO_EVIDENCE` are not automatically product decisions. Missing interface contracts, code-verification gaps and corrupted technical attachments belong to `resolutionOwner=TECH`. They remain open technical evidence and must not be rewritten into product requirements.

Before Quality Exit, the Semantic Consistency Reviewer must execute all six axes:

- terminology and aliases;
- capability identity and verification;
- state preconditions;
- permission boundaries;
- PRD / Prototype authority sync;
- business-assertion provenance.

A PRD/Prototype conflict produces `SEMANTIC.AUTHORITY.RESYNC_REQUIRED`; it is never resolved by silently copying one side. Missing axes produce `INCOMPLETE`, not PASS.

Quality evidence is evaluated by `tools/evaluate_delivery_quality.py`. The Delivery COMPLETE gate is `tools/delivery_complete_gate.py`; `BASELINE_READY` from synthetic data is not production completion. Production completion requires 3-5 real production-eligible samples, replayed semantic review and benchmark evidence, a synchronized Pair, closed Decisions/Escalations and a zero-blocker Handoff.

## Boundaries

- No external writes.
- No requirement exploration.
- No invented business facts.
- No placeholder prototype.
- No evidence-free PASS.
- No conversation memory used as authoritative input.

## Portable Artifact Profile routing

The Delivery quality core routes by the Artifact Profile, not by external gate conventions:

- `PRD_ONLY` / `EXTERNAL_UI_BOUNDARY`: do not create a placeholder Prototype; U1/U2 are `NOT_APPLICABLE`, while PRD, data, permission, action, exception, recovery and AC checks remain required.
- `PRD_PLUS_PROTOTYPE` / `EXISTING_PROTOTYPE_REVIEW`: run Prototype Contract Preflight before the full Delivery Review Group.

Prototype Contract Preflight must verify visible interaction contracts, not only click handlers: visible label, clickability, target view, preserved context and zero unhandled runtime errors.
