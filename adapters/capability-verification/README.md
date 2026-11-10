# Capability Verification Adapter Contract

Capability Context is not authoritative merely because a model wrote it. The lifecycle is:

```text
Candidate extraction
→ Human confirmation: “this is an existing capability”
→ MCP / Jira / Git verification
→ Capability Verification Record
→ Capability Context status = VERIFIED_EXISTING / VERIFIED_EXTENSION / VERIFIED_NEW
→ Delivery consumption
```

## Candidate extraction

Discovery or Delivery Semantic Reviewer may extract a candidate from the requirement:

```json
{
  "canonicalNameCandidate": "场景意图",
  "candidateStatus": "CANDIDATE_EXISTING",
  "aliases": ["场景意图识别"],
  "evidenceRefs": ["requirement.md"]
}
```

A candidate is not proof and must not be used as a confirmed existing capability.

## Human confirmation

When the Decision Owner confirms that the candidate is an existing capability, the orchestrator creates a verification request. The confirmation only authorizes verification; it does not create evidence.

## Verification sources

The adapter must query at least one authoritative source, and normally two when available:

- **MCP code/mainline adapter**: symbols, routes, schemas, tools, implementation references;
- **Jira/TAPD adapter**: historical requirements, delivery records, attachments and comments;
- **Git adapter**: historical commits, merged changes and implementation history.

Every result must retain source reference, query scope, revision/hash when available and a concise evidence summary.

## Verification result

Only a `Capability Verification Record` with `verificationStatus=VERIFIED_EXISTING`, `VERIFIED_EXTENSION` or `VERIFIED_NEW` may update Capability Context. `HOLD` or `REJECTED` blocks reuse and creates a Decision/Escalation path.

The fixture under `examples/harness/` is test data only. It is not production evidence and must never be presented as MCP/Jira/Git verification.
