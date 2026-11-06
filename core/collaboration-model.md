# Multi-Agent Collaboration Model

The workflow is a **controlled collaboration network**, not an open-ended multi-agent conversation.

## Operating model

```text
Stage Producer
    produces a frozen handoff
        ↓
Consumer Reviewer
    decides whether it can safely consume the handoff
        ↓
Independent Reviewer
    challenges the artifact independently
        ↓
Gatekeeper
    verifies evidence, hashes and final readiness
        ↓
Human Decision Owner
    resolves only value judgments, irreversible choices and unresolved disagreement
```

The workflow remains ordered:

```text
Discovery → Delivery → Tech Solution → Final readiness
```

Review relationships are cross-stage:

| Producer | Consumer | Independent review | Modification owner |
|---|---|---|---|
| Discovery | Delivery Intake Reviewer | Discovery Challenger | Discovery |
| Delivery | Tech PRD Diagnostician | Delivery Reviewer + QA Red Team | Delivery |
| Tech Solution | Product Acceptance Reviewer | Tech Reviewer | Tech Solution |

## Non-negotiable principles

1. **Producer cannot approve its own work.** The producer role and reviewer role must differ.
2. **Downstream is the first consumer.** A downstream stage can reject upstream input before starting work.
3. **Consumers cannot rewrite upstream facts.** They return a finding to the upstream owner.
4. **Independent review uses a separate context.** It reads frozen artifacts and contracts, not the producer's private reasoning.
5. **Agreement is not evidence.** Majority voting never overrides missing evidence or an unresolved blocker.
6. **The Gatekeeper is deterministic.** It is a program, not an LLM, and cannot be persuaded by prose.
7. **Human decisions are explicit.** Ambiguity that changes business outcomes becomes a Decision Card.
8. **Disagreement is structured.** After two unresolved rounds, the workflow escalates rather than forcing consensus.

## Review verdicts

| Verdict | Meaning | Allowed next action |
|---|---|---|
| `ACCEPTED` | Evidence is sufficient and no blocker remains | Advance |
| `ACCEPTED_WITH_ACTIONS` | Advance, but non-blocking actions must be tracked | Advance with tracked actions |
| `RETURNED` | The upstream artifact must be revised | Return to upstream producer |
| `BLOCKED` | A human or specialist decision is required | Stop and request decision |
| `INCOMPLETE` | Review did not actually complete | Never treat as PASS |

## Why this model exists

A single agent can produce an artifact and then optimistically approve it. Multiple agents chatting can also converge on the same mistaken assumption. This model prevents both by combining:

- role separation;
- frozen handoffs;
- consumer review;
- independent review;
- evidence contracts;
- deterministic gatekeeping;
- human authority only where it belongs.
