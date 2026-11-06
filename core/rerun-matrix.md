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
