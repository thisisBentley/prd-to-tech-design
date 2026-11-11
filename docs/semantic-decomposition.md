# Semantic Decomposition and Integration Review

## Purpose

Long PRDs can be locally correct while still failing globally. The failure mode is usually not missing prose but duplicated facts, implicit dependencies and missing cross-unit contracts. This layer decomposes a frozen Delivery bundle into semantic units, reviews each unit with only its direct dependencies, then reviews the edges and the integrated product contract.

It does not create business facts. It makes existing facts inspectable and reviewable.

## Four layers

```text
Global Contracts
→ Feature Slices / ACs / Interaction Contracts / Journeys
→ Dependency Edges
→ Local + Edge + Global Integration Review
```

### Global contracts

Single-authority contracts for:

- scope and goals;
- roles and permissions;
- states and transitions;
- enums and terminology;
- existing-capability baseline;
- feature index.

Features reference these contracts; they must not silently redefine them.

### Semantic units

| Kind | Authority | Example |
|---|---|---|
| `FEATURE_SLICE` | PRD | `FR-011 global filter and export` |
| `ACCEPTANCE_CRITERION` | PRD | `AC-010 export scope and feedback` |
| `INTERACTION_CONTRACT` | Prototype manifest | `UI-GLOBAL-FILTER` |
| `JOURNEY` | PRD goals | `G-002 identify service gaps` |

Each unit has a stable ID, source reference, evidence, direct dependencies and bound IDs.

### Edges

Supported relations:

```text
DEPENDS_ON
VERIFIED_BY
VERIFIES
BINDS_UI
COVERS
```

A structurally present edge is not automatically semantically correct. Edge review checks whether the target authority is right and whether the edge covers the full claim.

### Review layers

```text
CONTRACT  -> global contract coherence
LOCAL     -> one feature slice and only its direct AC / UI / contract dependencies
EDGE      -> cross-unit semantic validity
GLOBAL    -> contradictions, orphans, duplicate authority and false closure
```

## Generation Contract

The pre-PRD contract checks the input before authoring:

```text
scope / goals / actors / flow / rules / states / exceptions /
acceptance / decisions / capability evidence / conditional requirements
```

Conditional requirement types include:

```text
CRUD, CORE_WRITE, MULTI_SYSTEM, ASYNC, AI_LLM,
HIGH_CONCURRENCY, LEGACY_CHANGE, MIGRATION,
COMPATIBILITY, UI_INTERACTION, FRONTEND_BACKEND
```

Statuses follow the PRD toolbox model:

```text
pass / warn / needs_role / needs_product / block
```

## Commands

Build the pre-PRD contract:

```bash
python3 scripts/build_generation_contract.py \
  --requirement <requirement.md> \
  --workflow-id <workflowId> \
  --requirement-id <requirementId> \
  --artifact-profile PRD_PLUS_PROTOTYPE \
  --decision-context <decision-context.json> \
  --capability-context <capability-context.json> \
  --out .agents/context/generation-contract.json
```

Build the semantic model:

```bash
python3 scripts/build_delivery_semantic_model.py \
  --prd 01-delivery/PRD_DELIVERY.md \
  --workflow-id <workflowId> \
  --revision r1 \
  --artifact-profile PRD_PLUS_PROTOTYPE \
  --prototype .agents/m2/Prototype.html \
  --manifest .agents/m2/prototype-manifest.json \
  --generation-contract .agents/context/generation-contract.json \
  --out .agents/semantics/delivery-semantic-model.json
```

Run deterministic structural review:

```bash
python3 scripts/review_delivery_semantics.py \
  --model .agents/semantics/delivery-semantic-model.json \
  --out .agents/semantics/semantic-integration-review.json
```

Export isolated review jobs for independent semantic reviewers:

```bash
python3 scripts/export_semantic_review_jobs.py \
  --model .agents/semantics/delivery-semantic-model.json \
  --out-dir .agents/semantics/review-jobs
```

Run every isolated job through a worker and consolidate the results:

```bash
python3 scripts/run_semantic_review_jobs.py \
  --manifest .agents/semantics/review-jobs/job-manifest.json \
  --worker-command python3 scripts/semantic_review_worker.py \
  --results-dir .agents/semantics/review-results \
  --out .agents/semantics/semantic-aggregate.json
```

The worker command receives one job JSON on stdin and must return one `review-result.schema.json` object on stdout. `semantic_review_worker.py` is the Codex adapter; a fake or process worker can implement the same contract.

Consolidate reviewer results manually when workers run outside the harness:


```bash
python3 scripts/consolidate_semantic_review_results.py \
  --manifest .agents/semantics/review-jobs/job-manifest.json \
  --results-dir .agents/semantics/review-results \
  --out .agents/semantics/semantic-aggregate.json
```

## Pipeline modes

`delivery_pipeline.py` supports two independent controls:

```text
--generation-contract-mode off|advisory|gate
--semantic-decomposition-mode off|advisory|gate
--semantic-aggregate <semantic-aggregate.json>
```

`advisory` records evidence without blocking the pipeline. `gate` requires a READY generation contract and an independent semantic aggregate in `PASS` or `PASS_WITH_NONBLOCKING`; a deterministic structural review alone is not enough for gate mode. Start in advisory mode, calibrate against real samples, then promote each control to `gate`.

## Non-negotiable rules

- A local PASS is not a global PASS.
- A structurally present edge is not a semantically verified edge.
- `FR` and `AC` must remain traceable.
- UI bindings must resolve to existing PRD units.
- Permission and state features must reference the single global contract.
- Every review job is frozen input; reviewers do not receive producer private reasoning.
- Missing review jobs are BLOCKING, not skipped.
