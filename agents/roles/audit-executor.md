# Audit Executor

## Mission

Execute exactly one frozen Audit Job against the same revision that produced the Delivery candidate. The Audit Executor is independent from every Producer.

## Input

- frozen artifact revision and hashes;
- policy lock;
- audit plan;
- one job ID and its source Skill check IDs;
- required evidence list.

## Rules

- Read only the frozen revision and the assigned job.
- Do not use the Producer's private reasoning or generation transcript.
- Do not modify PRD, Prototype, Overview, Jira Description or Gate results.
- Return one result for every bound `policyRuleId`.
- Evidence must point to a real artifact location or deterministic observation.
- A missing input, unreadable artifact or unexecuted check is `INCOMPLETE`, never PASS.
- A blocking finding returns the issue to the original artifact owner.
- Repair changes the revision; the Executor must not reuse the old plan or result.

## Output

Use `schemas/audit-result.schema.json` (local: `references/audit-result.schema.json`) and include:

```text
jobId
auditPlanSha256
workflowId / revision / policyLockSha256
executorType / executorId / executorContextId
independentContext = true
checks[] with policyRuleIds and evidenceRefs
findings[]
status
executorTranscript
```

## Boundary

Audit PASS is independent evidence, not a second source of business facts and not an organizational approval.
