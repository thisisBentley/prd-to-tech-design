# Semantic Convergence

## Purpose

Semantic Convergence makes repair progress computable before any Agent is
allowed to self-correct over multiple rounds.

```text
Delivery Semantic Model
→ Semantic Ledger
→ Candidate Invariant Registry
→ Baseline Finding Snapshot
→ Current Finding Snapshot
→ Convergence Gate
```

The layer answers one question:

> Did the repair genuinely reduce semantic risk without reopening old issues,
> breaking locked invariants, drifting scope or hiding findings?

## Roadmap State Snapshot

The Roadmap is a state source only when the iteration, milestone, Skill version,
dataset status and baseline are aligned.

```bash
python3 scripts/build_roadmap_state.py \
  --roadmap ROADMAP_CURRENT_V1.md \
  --changelog ROADMAP_CHANGELOG_V1.md \
  --version-manifest version-manifest.json \
  --dataset-status DATASET_STATUS.json \
  --expected-milestone M7.5-D1 \
  --out ROADMAP_STATE_V1.json \
  --strict
```

```bash
python3 scripts/validate_roadmap_state.py \
  --snapshot ROADMAP_STATE_V1.json \
  --roadmap ROADMAP_CURRENT_V1.md \
  --changelog ROADMAP_CHANGELOG_V1.md \
  --version-manifest version-manifest.json \
  --dataset-status DATASET_STATUS.json \
  --expected-milestone M7.5-D1
```

## Semantic Ledger

The ledger consumes the existing Delivery Semantic Model. It does not create a
second semantic decomposition.

```bash
python3 scripts/build_semantic_ledger.py \
  --semantic-model delivery-semantic-model.json \
  --out semantic-ledger.json
```

Objects include:

```text
GLOBAL_CONTRACT / PERMISSION / STATE
FEATURE_SLICE
BUSINESS_RULE
INTERACTION_RULE
AC
INTERACTION_CONTRACT
JOURNEY
```

## Invariant Registry

Only explicit source material becomes a candidate invariant:

- `业务规则` section;
- AC `THEN` statement;
- permission / state global contracts;
- Decision Impact Graph `expectedInvariant`.

```bash
python3 scripts/build_invariant_registry.py \
  --ledger semantic-ledger.json \
  --decision-impact-graph decision-impact-graph.json \
  --out invariant-registry.json
```

The builder emits `CANDIDATE` only. Promotion to `ACTIVE` or `LOCKED` requires an
independent reviewer or human decision.

```bash
python3 scripts/apply_invariant_review.py \
  --registry invariant-registry.json \
  --review invariant-review-result.json \
  --out reviewed-invariant-registry.json
```

The review must bind the registry hash, use an independent reviewer role and cite
evidence for every accepted or locked invariant.

Before promotion, run the deterministic source-grounding audit:

```bash
python3 scripts/audit_invariant_candidates.py \
  --registry invariant-registry.json \
  --ledger semantic-ledger.json \
  --review-out invariant-review-result.json \
  --audit-out invariant-source-audit.json \
  --reviewer-role independent-source-checker
```

Every substantive invariant line must be locatable in the bound PRD. A grounded
candidate can become `ACTIVE`; an aggregate that contains unbound lines must stay
`CANDIDATE` through `DEFER`. The source audit never promotes directly to
`LOCKED`, because source grounding is not a human acceptance decision.

Decision-to-target rules are closed:

```text
ACCEPT → ACTIVE / LOCKED
DEFER  → CANDIDATE
REJECT → DEPRECATED
```

## Convergence Gate

```bash
python3 scripts/evaluate_convergence.py \
  --baseline baseline-findings.json \
  --current current-findings.json \
  --history prior-findings-r1.json \
  --history prior-findings-r2.json \
  --policy convergence-policy.json \
  --invariant-registry invariant-registry.json \
  --out convergence-report.json
```

Execution metrics are attached to each snapshot so quality risk, elapsed time and
token usage share the same workflow and revision:

```bash
python3 scripts/attach_execution_metrics.py \
  --snapshot current-findings.json \
  --out current-findings.metrics.json \
  --availability COMPLETE \
  --repair-rounds 2 \
  --elapsed-ms 45000 \
  --input-tokens 12000 \
  --output-tokens 3000 \
  --context-object-count 18 \
  --source-ref runs/current/telemetry.json
```

Historical evidence without telemetry must use `UNAVAILABLE`, not inferred or
fabricated numbers. A strict policy can require `COMPLETE` metrics before closure.

Finding identity is:

```text
rootCauseId + sorted(affectedObjectIds)
```

A changed `findingId` alone cannot hide a repeated issue.

Gate checks:

```text
new blocking finding = 0
reopened root cause = 0
invariant violation = 0
semantic drift = 0
scope drift = 0
repeated rootCause = 0
token total = input + output when values are claimed as COMPLETE
weighted blocking score strictly decreases, or reaches 0
LOCKED coverage is non-vacuous and every LOCKED invariant is verified
```

A rootCause open across more than `maxOpenRootCauseRounds` distinct revisions is a
repeated root cause. This catches a recurring defect even when the finding ID or
wording changes between rounds. LOCKED coverage is not allowed to pass vacuously:
if coverage is required, the registry must contain at least one LOCKED invariant.

Statuses:

```text
PASS        score is 0 and no integrity failure
IMPROVING   score decreased but remains above 0
STALLED     score did not decrease and remains above 0
REGRESSED   score increased
BLOCKED     new blocking, reopen, repeated rootCause, invariant violation, drift or metric inconsistency
INCOMPLETE  LOCKED coverage is incomplete/vacuous, or required metrics are incomplete
```

Only `PASS` may close the convergence gate. `IMPROVING` is a valid reason to run
another bounded repair round, not a reason to declare completion.

## Historical Replay

Historical transition analysis is diagnostic only:

```bash
python3 scripts/audit_convergence_history.py \
  --snapshots r0.json r1.json r3.json r4.json r5.json \
  --policy historical-policy.json \
  --invariant-registry reviewed-invariant-registry.json \
  --out convergence-history-audit.json
```

The output is always `closureEligible=false`. It may relax current-revision
binding because old snapshots are historical evidence, but it must never be used
as the closure report for the latest revision.
