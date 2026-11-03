# Rerun Matrix

Gate results bind to artifact hashes. Reuse prior results only when relevant hashes are unchanged.

| Changed object | Rerun |
|---|---|
| PRD business meaning | R0 + G1 + O1 + U1 + QA + Q1 |
| Manifest projection | R0 + QA + Q1 |
| Issue description | QA + Q1 |
| Overview | O1 + QA + Q1 |
| Prototype | U1 + QA + Q1 |
| Evidence or product decision | Affected requirement lens + G1 + QA + Q1 |
| Technical design | Design-stage gate, if configured |
| Implementation | Test-stage gate, if configured |

## Rules

- Do not rerun the entire workflow when one downstream artifact changes.
- Do not infer reuse from filenames or attachment IDs.
- Record every rerun under `.delivery/runs/`.
- If a gate tool fails, mark its result `INCOMPLETE`; do not treat failure as success or as a requirement failure.
