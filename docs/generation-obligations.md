# Generation Obligations

## Purpose

A Policy Lock decides which gate rules apply. Generation Obligations turn those rules into producer-facing work items before authoring starts.

```text
Policy Lock
→ Generation Obligations
→ Producer Task inputs
→ Artifact
→ Gate Result ruleId coverage
```

## Obligations

Each obligation contains:

```text
obligationId
ruleId
gate
ownerRole
artifact
title
requiredEvidence
passCondition
failureAction
status
sourceRef
```

The initial status is `OPEN`. Producer completion does not make it `passed`; only an independent reviewer can pass the rule.

## Build

```bash
python3 scripts/build_generation_obligations.py \
  --policy-lock .delivery/policy-lock.json \
  --workflow-id <workflowId> \
  --revision r1 \
  --out .agents/policy/generation-obligations.json
```

The Pipeline copies the result to:

```text
01-delivery/.delivery/generation-obligations.json
```

## Producer task binding

`agent_task_factory.py` automatically freezes these files into producer and reviewer inputs:

```text
.agents/policy/policy-lock.json
.agents/policy/generation-obligations.json
```

A producer task receives the Rule IDs and obligations owned by its role. A reviewer task receives the frozen policy inputs and must return every applicable `ruleId`.

## Boundary

- Producer obligations are generation constraints, not formal PASS evidence.
- Reviewer results are the formal rule evidence.
- Obligation fulfillment must never be inferred from prose alone.
- A policy change invalidates old obligations and the old policy lock.

## Obligation declarations

A Producer returns `obligationDeclarations` in its structured result. The Codex adapter writes them to:

```text
.agents/policy/declarations/<taskId>.json
```

The Pipeline collects them into:

```text
.agents/policy/obligation-declarations.json
01-delivery/.delivery/obligation-declarations.json
```

A declaration requires:

```text
obligationId
ruleId
producerRole
status = DECLARED
artifact
location
evidenceRefs
```

Only obligations with `declarationRequired=true` must be declared. Evidence and manual-decision obligations do not require a Producer declaration. `NOT_APPLICABLE` does not close a declaration-required obligation.

Validation:

```bash
python3 scripts/collect_obligation_declarations.py \
  --obligations .agents/policy/generation-obligations.json \
  --declarations-dir .agents/policy/declarations \
  --out .agents/policy/obligation-declarations.json

python3 scripts/validate_obligation_declarations.py \
  --obligations .agents/policy/generation-obligations.json \
  --declarations .agents/policy/obligation-declarations.json \
  --out .agents/policy/obligation-declarations-validation.json
```

Declarations are generation self-evidence, not formal PASS. Formal PASS still requires independent Gate Results.
