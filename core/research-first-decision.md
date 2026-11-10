# Research-First Decision Harness

## Principle

A product question is the **last resort**, not the first response to ambiguity.

```text
Clue
→ classify the question
→ search authoritative existing facts
→ resolve if a unique answer exists
→ present evidence if sources conflict
→ ask the product owner only when no existing fact determines the business outcome
```

## Two categories

| Category | Examples | Default action |
|---|---|---|
| Fact question | existing field mapping, current behavior, historical implementation, API semantics, permission rules already implemented | Research PRD, Jira, MCP, code, Git and runtime evidence |
| Business decision | two equally valid outcomes with different user-visible business results and no existing precedent | Decision Card after research is complete |

## Capability-aware requirement

Research-First is conditional on the Agent Capability Registry:

```text
source configured and probe succeeds -> research required
source not configured               -> normal decision flow
source configured but probe errors  -> return the actual error; do not relabel it as unavailable
```

When at least one configured source is available, research is required for factual gaps. Other configured sources may return errors; those errors are retained as evidence rather than silently ignored.

## Required research sources

For an available capability, use the cheapest source that can close the question, in this order:

1. current PRD and frozen Decision Context;
2. current Jira/TAPD item, linked items, attachments and comments;
3. historical requirements and previous technical solutions;
4. MCP code/mainline search, symbol and route lookup;
5. Git history and merged changes;
6. runtime logs, configuration and tests when available.

The order is a default, not a prohibition. A source may be skipped when it is unavailable, but the reason must be recorded.

## Research record

Every clue that may become a decision must produce a `research-record`:

```text
clue
clueType
researchPlan
sourcesChecked
findings
verdict
decisionRequired
decisionRationale (required only for NEEDS_BUSINESS_DECISION)
evidenceRefs
budget
```

Verdicts:

```text
FACT_RESOLVED
FACT_CONFLICT
NO_EVIDENCE
NEEDS_BUSINESS_DECISION
```

Only `NEEDS_BUSINESS_DECISION` may create a Decision Card. `FACT_RESOLVED` must be written back into PRD / capability context and must not ask the product owner. `FACT_CONFLICT` and `NO_EVIDENCE` first go to a targeted investigation; if still unresolved, they may become a Decision Card with the evidence gap stated.

## Decision Card precondition

A Decision Card must include:

```text
researchRecordPath
researchVerdict = NEEDS_BUSINESS_DECISION
researchEvidenceRefs
whyDecisionRequired
options
recommendation
defaultAndRisk
```

A card with `researchVerdict=FACT_RESOLVED` is invalid. A card with no research record is invalid.

## Cost and context control

Research is bounded by `ResearchBudget`:

```text
search calls
deep reads
artifact downloads
raw evidence characters
ledger characters
```

Use query deduplication, cached snapshots and evidence references instead of copying full source text into every Agent context. Stop when the core question is uniquely answered or the remaining sources are repetitive/unavailable.

## Downstream reuse

The same Research Record is passed to Delivery and Tech Solution. Tech Solution may perform targeted technical follow-ups, but must not repeat the entire investigation or reinterpret a resolved product fact.
