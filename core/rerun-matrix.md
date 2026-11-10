# Rerun Matrix

Formal gate rounds are always full: `R0 + G1 + O1 + U1 + U2 + QA + Q1`.

Hashes do not reduce formal gate scope. They prove that the independent review used the same frozen revision that was sealed.

| Changed object | Formal action |
|---|---|
| Any of the six candidate artifacts | Create a new revision, seal, rerun all gates |
| Manifest | Create a new revision, seal, rerun all gates |
| Evidence or product decision | Update candidate artifacts, create a new revision, seal, rerun all gates |
| Technical design | Design-stage gate, if configured |
| Implementation | Test-stage gate, if configured |

## Rules

- Do not selectively skip a formal gate.
- Keep failed revisions and gate results.
- Do not reuse a previous PASS after any candidate artifact changes.
- If a gate tool fails or a required check cannot execute, mark the gate `INCOMPLETE`; never treat it as PASS.
- A repaired gate must retain the original finding IDs and evidence until the new worker closes them.

## Harness reruns and escalation

| Event | Required action |
|---|---|
| Decision Readiness changes | Block before Producer; reopen Decision Context and rerun from Decision Readiness |
| Capability Context or Source Provenance changes | Create a new Context revision and rerun affected semantic reviews |
| Authority Matrix or domain conflict changes | Rebuild Pair, rerun Consistency and all affected reviews |
| Semantic Reviewer finding | Repair by root cause, rerun affected reviewers and Semantic Reviewer |
| Same blocking root cause remains after recheck | Create Escalation; block Quality Exit until resolved |
| Reviewer `RETURNED` | Return to the originating Producer/Repair task; do not skip the review |
| Interrupted main Agent | Resume from persisted state; do not skip incomplete tasks or gates |
| Quality Exit changes | Rerun Quality Exit and deterministic Gatekeeper before Handoff |
