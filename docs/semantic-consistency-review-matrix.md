# Semantic Consistency Review Matrix

The Semantic Consistency Reviewer is an independent, read-only Delivery reviewer. It consumes a frozen semantic evidence ledger and may not modify PRD, Prototype or Overview.

## Required axes

| Axis | What must be proven | Blocking examples | Deterministic finding root cause |
|---|---|---|---|
| Terminology | Canonical name, alias and new term are grounded | Existing `场景意图` is treated as a newly invented term | `SEMANTIC.TERMINOLOGY.GROUNDING` |
| Capability identity | Declared and verified status agree | PRD calls an existing capability `NEW`; verification says `VERIFIED_EXISTING` | `SEMANTIC.CAPABILITY.IDENTITY` |
| State | Visible state has source, transition and precondition | Empty-state UI exists but no state can reach it | `SEMANTIC.STATE.PRECONDITION` |
| Permission | Each role/action/resource tuple is explicitly allow or deny | Creator can edit, viewer sees an enabled action, no condition is stated | `SEMANTIC.PERMISSION.UNSPECIFIED` / `SEMANTIC.PERMISSION.CONFLICT` |
| Authority sync | PRD and Prototype agree on shared semantics | Prototype changed a label/condition but PRD did not | `SEMANTIC.AUTHORITY.RESYNC_REQUIRED` |
| Provenance | Every business assertion has a requirement, decision or evidence source | Reviewer invents a business rule from inference | `SEMANTIC.PROVENANCE.UNSOURCED` |

## Authority rules

```text
Business facts       -> PRD is authoritative
Interaction facts    -> Prototype is authoritative
Overview             -> projection only
Capability identity  -> Capability Context plus verification evidence
Shared semantics     -> must agree across authority domains
Any unresolved gap   -> Research first, Decision only after evidence is exhausted
```

A PRD/Prototype conflict is not repaired by silently copying either side. It opens a paired reconciliation and is resynced until `pairStatus=SYNCED`.

## Decision matrix

| Evidence state | Verdict | Action |
|---|---|---|
| All six axes executed and no blocking findings | `ACCEPTED` | Continue to Quality Exit |
| Any executed axis has a blocking finding | `RETURNED` | Targeted semantic Repair + Recheck |
| Any required axis has no claims or was not executed | `INCOMPLETE` | Do not infer success; collect review evidence |
| Research shows a genuine business choice remains | `NEEDS_BUSINESS_DECISION` | Decision Card with research references |
| Research result is conflicting or absent | `FACT_CONFLICT` / `NO_EVIDENCE` | Targeted investigation or documented escalation |

## Deterministic regression

`tests/test_semantic_consistency_cases.py` covers terminology conflict, capability misclassification, state precondition, permission conflict, PRD/Prototype authority conflict, unsourced business assertion, missing-axis incompleteness and the accepted control.

## Integration contract

The reviewer writes a `review-result` with reviewer role `semantic-consistency-reviewer`. Each of the six `SEMANTIC.*` checks must be present. Quality Exit and Delivery COMPLETE Gate must reject a semantic review that is incomplete or has blockers. An LLM may populate the evidence ledger, but it cannot override deterministic findings.
