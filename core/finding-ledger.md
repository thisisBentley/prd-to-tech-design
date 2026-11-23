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

## Batch repair

Independent review results are consolidated by `rootCauseId` before the Producer repairs anything. A batch must carry evidence refs, owners, expected invariants, regression tests and close conditions. Mixed workflow IDs or revisions fail safe to manual triage.

## Runtime ledger

The executable ledger is `tools/finding_ledger.py` and its contract is `schemas/finding-ledger.schema.json`. Audit results are deduplicated by stable `findingId` before ledger updates, so the same finding reported by multiple jobs counts as one finding with multiple source results.

```bash
python tools/finding_ledger.py --ledger 01-delivery/.delivery/findings.json sync \
  --findings .agents/audit/repair-findings-r1.json \
  --workflow-id <workflowId> --revision r1

python tools/finding_ledger.py --ledger 01-delivery/.delivery/findings.json repairing \
  --target-revision r2

python tools/finding_ledger.py --ledger 01-delivery/.delivery/findings.json close \
  --revision r2 --evidence .agents/audit/stage-r2.json
```

Only a full `AUDIT_PASS` may close findings. A finding absent from one failed audit remains pending; if it later reappears it is marked `reopened` rather than immediately treated as unchanged for two rounds.

External Skill findings enter through `tools/import_external_skill_findings.py`. Stable identity is derived from Skill ID, external finding ID, policy rule, artifact and root cause; title wording changes do not create a new ledger row.

```bash
python tools/import_external_skill_findings.py \
  --input external-skill-report.json \
  --skill-id bot-prd-specs-gitlab \
  --workflow-id <workflowId> \
  --revision <revision> \
  --out .agents/audit/external-findings.json \
  --sync-ledger \
  --ledger 01-delivery/.delivery/findings.json

# The one-command form above normalizes the external batch and updates the
# current-revision Finding Ledger atomically from the caller's perspective.

python tools/consolidate_findings.py \
  --review .agents/reviews/RR-delivery.json \
  --review .agents/reviews/RR-qa.json \
  --out .agents/repair-batch.json
```
