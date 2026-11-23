# Collaboration Surface v0

## Purpose

The Collaboration Surface is a read-only view over a Project Episode. It reduces
the effort required for a human or downstream Agent to answer:

```text
What changed?
What did reviewers find?
Which decisions are still open?
What risks remain?
What evidence exists or is missing?
What should happen next?
```

It is not a fact source and cannot change a Gate, release state or training
eligibility.

## Authority

```json
{
  "readOnly": true,
  "factSource": "PROJECT_EPISODE",
  "gateAuthority": "UNCHANGED",
  "trainingAuthority": "NONE"
}
```

Every fact displayed by the surface remains owned by its source artifact.

## Digests

### Change Digest

From Episode revision/repair timeline:

- revision;
- next revision;
- status;
- changed artifacts;
- source references.

### Review Digest

From matching Review Results and Consumer Acceptance summaries:

- reviewer role;
- review type;
- revision;
- verdict;
- blocking and finding counts;
- consumer report counts and statuses.

Reviews from another workflow or revision are ignored with an explicit warning.

### Decision Digest

From Human Decision Cards referenced by the Episode:

- decision status;
- owner;
- ambiguity;
- selected option;
- source path.

### Risk Digest

Deterministic risks include:

- blocked Episode;
- failed/incomplete Final Gate;
- open blocking findings;
- open Human Decisions;
- evidence gaps;
- no matching independent review;
- no real consumer report;
- incomplete cost telemetry.

### Evidence Digest

The surface reproduces Episode evidence layers without promotion:

```text
SOURCE_FACT / MEASURED / DERIVED / REFERENCE / INFERENCE
```

### Next Action

Actions are deterministic and have priority, owner, reason and source refs.

```text
RESOLVE_EPISODE_BLOCKERS
RESOLVE_FINAL_GATE_BLOCKERS
OBTAIN_HUMAN_DECISION
RUN_BOUNDED_REPAIR
RUN_CONSUMER_ACCEPTANCE
RUN_INDEPENDENT_REVIEW
COLLECT_MISSING_EVIDENCE
IMPROVE_COST_TELEMETRY
REVIEW_DELIVERY_PACKAGE
```

`REVIEW_DELIVERY_PACKAGE` is a normal human handoff and does not by itself change
the surface from `READY`.

## Build

```bash
python3 tools/build_collaboration_surface.py \
  --episode project-episode.json \
  --review-dir .agents/reviews \
  --decision-dir .agents/decisions \
  --out collaboration-surface.json \
  --markdown-out collaboration-surface.md
```

`delivery_pipeline.py` builds and validates both artifacts after Project Episode
validation and before final Package Evidence rebind.

## Status

```text
READY             no deterministic remediation action remains
ACTION_REQUIRED   one or more evidence, review, consumer, decision or telemetry actions remain
BLOCKED           the Episode itself is blocked
```

`READY` does not mean released. It means the read-only surface has no detected
remediation action beyond the normal human package review.

## Validate

```bash
python3 tools/validate_collaboration_surface.py \
  --surface collaboration-surface.json \
  --verify-source-hashes
```

Validation enforces read-only authority, unchanged Gate authority, no training
authority and source-hash stability.

## Non-goals

- no new Agent;
- no new workflow;
- no hidden fact mutation;
- no Gate override;
- no release or training approval.
