# Delivery Operating Procedure

## Purpose

The Delivery Operating Procedure (DOP) is a read-only composition of the
existing Delivery control plane. It gives producers, reviewers, operators and
downstream agents one deterministic view of:

```text
Goal
Subgoals and progress
Guardrails
Tool authority
Context policy
State contract
Stop policy
Revision policy
Exit criteria
```

It does not create a second workflow engine, a second policy system or another
Agent. Existing contracts remain authoritative.

## Source Contracts

```text
Generation Contract       goal and requirement types
Delivery Plan             subgoals and ownership
Policy Lock               applicable/excluded rules
Generation Obligations    guardrail obligations
Specialist Tool Routes    domain and operation authority
Source Pack Registry      context provenance and allowed use
Run Budget                time/context/transcript limits
Bounded Repair Policy     repair-round authority
```

The DOP records every source path and SHA-256.

## Build

```bash
python3 tools/build_delivery_operating_procedure.py \
  --workflow-id WF-1 \
  --requirement-id REQ-1 \
  --artifact-profile PRD_ONLY \
  --revision r1 \
  --requirement requirement.md \
  --generation-contract generation-contract.json \
  --policy-lock policy-lock.json \
  --obligations generation-obligations.json \
  --plan delivery-plan.json \
  --tool-policy config/trust-kernel/specialist-tool-routes-v1.json \
  --budget config/run-budgets/default.json \
  --repair-policy config/trust-kernel/bounded-repair-policy-v1.json \
  --source-pack config/source-packs/current-v1.json \
  --out delivery-operating-procedure.json
```

`delivery_pipeline.py` builds and validates this artifact before the Producer core
starts. The procedure path and hash are attached to `package-evidence.json`.

## Fail-Closed Checks

The builder rejects inconsistent contracts:

```text
generation workflow / profile mismatch
policy-lock profile mismatch
obligations workflow / policy hash mismatch
delivery-plan workflow / profile mismatch
empty delivery plan
tool route without domain, operation or source authority
tool source ref not allowed as runtime input
run-budget vs repair-policy round mismatch
missing requirement source
missing objective
```

These checks detect contract drift. Open obligations do not block procedure
construction: they remain visible as `guardrails.obligationsOpen` and must close
before Exit.

## Stop Conditions

```text
SOURCE_DRIFT_OR_STALE_LOCK
OPEN_BLOCKING_DECISION
NEW_BLOCKING_FINDING
NO_MEASURABLE_IMPROVEMENT
REGRESSION
MAX_REPAIR_ROUNDS_REACHED
RUN_BUDGET_EXCEEDED
INDEPENDENT_REVIEW_UNAVAILABLE
```

## Revision Policy

```text
every Repair produces a new revision
derived evidence must be rebuilt
Package Evidence must bind to candidate-seal.revision
stale evidence is forbidden
```

## Exit Criteria

```text
EXIT.GENERATION_OBLIGATIONS
EXIT.ARTIFACT_QUALITY
EXIT.FINAL_GATE
EXIT.READINESS
EXIT.COST_LEDGER
```

The DOP defines required Exit criteria; it does not self-certify them.

## Validate

```bash
python3 tools/validate_delivery_operating_procedure.py \
  --procedure delivery-operating-procedure.json \
  --verify-source-hashes
```

Validation checks the schema, non-BLOCKED status and source-hash stability.

## Non-goals

- no new Agent;
- no second Router;
- no replacement for Policy Lock, Audit, readiness or final Gate;
- no release evidence or training approval;
- no autonomous Prompt modification.
