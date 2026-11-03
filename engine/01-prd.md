# Stage 01 · PRD Delivery

## Goal

Create the sole business fact source.

## Required structure

- Background and current problem
- Actors and scenarios
- Goals and scope/non-goals
- Functional requirements
- Business and interaction rules
- States and permissions
- Data contracts
- Exceptions and recovery
- Acceptance criteria
- Change history
- Open questions

## Runtime projection

Generate `.delivery/requirements.json` from the PRD:

```json
{
  "schemaVersion": 1,
  "requirements": [
    {
      "id": "FR-001",
      "title": "",
      "normative": "",
      "priority": "P0 | P1 | P2",
      "acceptanceCriteria": ["AC-001"],
      "sourceRef": "PRD section"
    }
  ]
}
```

The manifest is a projection, not a second fact source.

## Check

- Every P0/P1 requirement has at least one acceptance criterion.
- Every acceptance criterion is observable.
- No undefined actor, state, permission, exception, or result is left to downstream interpretation.
