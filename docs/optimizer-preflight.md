# Bounded Optimizer Preflight v0

## Purpose

The Optimizer Preflight decides whether the system may prepare a human-reviewed
Change Set proposal. It does not apply changes.

Required conditions:

```text
real Repair -> Re-audit -> Consumer Acceptance loop
Observer has complete inputs
Human adjudication is recorded
Observer has an actionable recommendation
Episode and Observer revisions match
```

## Authority

```text
readOnly: true
mayApply: false
releaseEligible: false
trainingEligible: false
resultAuthority: NONE
```

When any prerequisite is missing, the result is `BLOCKED` and no proposals are
emitted. When all prerequisites pass, the result is
`READY_FOR_HUMAN_CHANGE_SET`; proposals still require a separate Change Set,
human review, bounded Repair, independent verification and Gate.

## Build

```bash
python3 tools/build_optimizer_preflight.py \
  --episode .agents/quality/project-episode.json \
  --observer .agents/quality/observer-report.json \
  --decision-dir .agents/decisions \
  --out .agents/quality/optimizer-preflight.json
```

## Prerequisites

The preflight checks:

- Episode is COMPLETE;
- at least one REAL Consumer Acceptance report exists;
- at least one Repair round exists;
- Final Gate is PASS;
- Observer is READY with no evidence gaps;
- at least one confirmed or closed human decision exists;
- Observer and Episode target the same revision;
- at least one actionable Observer recommendation exists.

## Output

A ready proposal has:

```text
proposalId
recommendationId
priority
owner
action
sourceRefs
applyStatus = REQUIRES_HUMAN_CHANGE_SET
```

The preflight never writes PRD, Prototype, Prompt, Change Set batch or model
weights.

## Validate

```bash
python3 tools/validate_optimizer_preflight.py \
  --preflight .agents/quality/optimizer-preflight.json
```

## Pipeline

The Delivery Pipeline always builds the preflight after Observer validation. A
BLOCKED preflight is recorded as conditional engineering evidence and does not
block ordinary Delivery finalization. D.19 execution remains blocked until the
real closed-loop prerequisites pass.
