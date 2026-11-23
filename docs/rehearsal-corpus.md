# Rehearsal Corpus v0

## Purpose

The Rehearsal Corpus is a deterministic library of negative-test inputs. It turns
rules and observed failures into replayable scenarios before a Challenger Agent is
introduced.

```text
Gate Policy
+ Historical Findings
+ Audit Findings
+ Tool-routing Failures
+ Manual Negative Scenarios
→ Rehearsal Corpus
```

It does not produce PASS results, approve release, or grant training eligibility.

## Authority

```json
{
  "purpose": "NEGATIVE_TEST_INPUT",
  "resultAuthority": "NONE",
  "releaseEligible": false,
  "trainingEligible": false
}
```

## Scenario Sources

### Gate Rule Negative

Every blocking gate rule becomes a scenario that removes or contradicts its
required evidence.

```text
ruleId
passCondition
required failure: RULE_NOT_PROVEN
replay mode: AUDIT_JOB
```

### Historical Finding Replay

Blocking entries in the Finding Ledger become historical replay scenarios.

```text
findingId
rootCauseId
ruleIds
first/last seen revision
required failure: FINDING_REOBSERVED
```

### Audit Finding Replay

Blocking findings in matching Audit Results become measured-failure scenarios.
The same root cause must remain blocked until evidence is repaired and fully
re-audited.

### Tool Failure Replay

An optional tool-failure report can include observed routing failures:

```json
{
  "schemaVersion": 1,
  "failures": [
    {
      "failureId": "TF-1",
      "toolId": "vibe-trading-reader",
      "toolDomain": "FINANCE_MARKET_RESEARCH",
      "operation": "READ",
      "ruleIds": ["G1.MUST.ROLES_PERMISSIONS"],
      "rootCauseId": "RC-T1",
      "revision": "r2",
      "negativeCondition": "Ask a finance-only tool to read a product-engineering document.",
      "expectedFailureKind": "TOOL_ROUTE_BLOCKED",
      "expectedFailure": "The router must block the cross-domain tool."
    }
  ]
}
```

### Manual Scenario

Manual fixtures are allowed only as test input. They are classified as
`MANUAL_FIXTURE` and cannot count as release or training evidence.

## Required Scenario Fields

Every scenario records:

```text
scenarioId
scenarioType
classification
sourceRefs + SHA-256
ruleIds
rootCauseIds
revisionRefs
negativeCondition
expectedFailureSignal
forbiddenOutcomes
replay mode / frozen / reproducible
```

Every scenario forbids at least:

```text
RELEASE_EVIDENCE_PROMOTION
TRAINING_PROMOTION
```

## Build

```bash
python3 tools/build_rehearsal_corpus.py \
  --workflow-id WF-1 \
  --revision r2 \
  --gate-policy core/gate-policy-current.json \
  --finding-ledger 01-delivery/.delivery/findings.json \
  --audit-results-dir 01-delivery/.delivery/audit-runs/r2/results \
  --tool-failure-report tool-failures.json \
  --manual-scenarios manual-scenarios.json \
  --out rehearsal-corpus.json \
  --markdown-out rehearsal-corpus.md
```

`delivery_pipeline.py` builds and validates the corpus after the Collaboration
Surface and before Package Evidence rebind.

## Status

```text
READY     scenarios exist and all blocking policy rules are covered
PARTIAL   scenarios exist, but some observed-failure sources are missing or coverage is incomplete
BLOCKED   no scenario can be generated
```

`PARTIAL` is expected when historical Findings or tool-failure records are not
yet available.

## Validate

```bash
python3 tools/validate_rehearsal_corpus.py \
  --corpus rehearsal-corpus.json \
  --verify-source-hashes
```

Validation enforces:

- no release or training authority;
- no result authority;
- frozen and reproducible scenarios;
- release/training promotion forbidden in every scenario;
- source hash stability.

## Non-goals

- no Challenger Agent yet;
- no automatic PASS/FAIL conclusion;
- no replacement for real Audit Jobs;
- no release evidence;
- no training approval.
