# Stage 00 · Input Assembly

## Goal

Collect authoritative requirement inputs before generating artifacts.

## Inputs

- User-provided requirement text
- Manual issue snapshot
- Optional Discovery outputs
- Optional existing PRD/prototype/knowledge evidence

## Output

`.delivery/input-assembly.json`:

```json
{
  "requirement": {"id": "DEMO-001", "name": "Synthetic support analytics"},
  "inputSources": [],
  "adapterUsage": [],
  "evidenceCoverage": "partial",
  "lockedAt": "ISO-8601"
}
```

## Rules

- Do not choose among ambiguous candidate inputs.
- Do not infer facts from conversation memory.
- If authoritative facts are insufficient, return `BLOCKED_INSUFFICIENT_INPUT`.
