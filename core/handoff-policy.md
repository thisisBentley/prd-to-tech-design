# Handoff Policy

A handoff is a frozen, hash-bound review request. Conversation memory is not a handoff.

## Required properties

- Workflow ID and revision;
- producer and intended consumers;
- exact artifact paths and SHA-256 hashes;
- confirmed decisions referenced by ID;
- open findings and unresolved unknowns;
- requested review types;
- creation timestamp.

## Review plan

Before review, the reviewer writes a plan containing:

- questions it intends to answer;
- evidence targets;
- counterexamples it will test;
- selected checks.

This makes autonomous investigation possible without making the review arbitrary or untraceable.

## Review result

A review result must include:

- reviewer and producer identities;
- target handoff and revision;
- independent-context flag;
- check ledger with evidence;
- findings with close conditions and owners;
- verdict and blocking count;
- completion status.

## Return behavior

When a review returns an artifact:

1. The same producer role revises it.
2. A new revision is created.
3. A new handoff is registered.
4. The consumer and independent reviewers review the new revision.
5. No previous PASS is reused.

## Disagreement

A disagreement must cite evidence and a concrete failure condition. After two rounds without resolution, the Orchestrator creates an escalation; it does not force a majority verdict.
