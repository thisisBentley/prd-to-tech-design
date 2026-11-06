# Finding Ledger

Findings are stored in:

```text
runRoot/01-delivery/.delivery/findings.json
```

## Stable identity

```text
findingId = <gate>:<requirementId>:<artifact>:<rootCause>
```

Do not renumber the same root cause every round or across lenses.

## Lifecycle

```text
open
in_progress
resolved
reopened
accepted_risk
closed_by_decision
```

## Required fields

```json
{
  "findingId": "U1:FR-001:Prototype:missing-empty-state",
  "title": "Empty result state is not represented",
  "lenses": ["U1", "QA"],
  "artifact": "Prototype.html",
  "requirementId": "FR-001",
  "rootCause": "missing-empty-state",
  "severity": "blocking | nonblocking",
  "status": "open",
  "owner": "product | design | engineering | qa | external",
  "evidence": [],
  "impact": "",
  "remedy": "",
  "verification": "",
  "firstSeenAt": "ISO-8601",
  "lastSeenAt": "ISO-8601",
  "unresolvedRounds": 1
}
```

Gate Result v2 stores stable finding IDs and a numeric `blockingCount`. The repair ledger must carry the full evidence and closure state.

## Repair classes

| Class | Meaning | Action |
|---|---|---|
| A | Deterministic local repair | Fix directly |
| B | Generated artifact repair | Patch, create a new revision, rerun all gates |
| C | Product decision | Generate a decision card; do not invent facts |
| D | Specialist fact | Assign to engineering, data, security, design, or another owner |

## Stop conditions

- At most three repair rounds.
- Stop if one finding is unchanged for two rounds.
- Stop if a repair increases total findings.
- Revert a repair that introduces a regression.
- Stop and transfer ownership when only C/D findings remain.
- An unclosed blocking finding prevents `DESIGN_READY`.
