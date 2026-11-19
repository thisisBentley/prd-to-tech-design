# Agent Contract Compiler

## Purpose

The Agent Contract Compiler prevents different parts of the system from using
different output protocols:

```text
runtime prompt
→ training target
→ dataset validator
→ reviewer rubric
→ gate result
```

All of them must be derived from one released contract.

## Contract release

Source profiles live under `config/agent-contracts/`. The compiled release is a
frozen artifact with per-contract hashes:

```bash
python3 scripts/build_agent_contract.py \
  --profile config/agent-contracts/agent-contract-profiles-v1.json \
  --out config/agent-contracts/agent-contract-release-v1.json
```

## Result validation

A result is valid only when all of the following hold:

- it matches `agent-result.schema.json`;
- `contractId`, `contractVersion` and `taskId` match the task;
- `taskStatus` and `reviewVerdict` are both allowed by the contract;
- every required section exists;
- evidence meets the minimum count;
- every evidence reference comes from the frozen Context Pack;
- `reviewVerdict=FINDINGS` contains at least one structured finding;
- `reviewVerdict=REPAIR_PLAN` carries findings and repair conclusions;
- `taskStatus=BLOCKED/UNKNOWN` explains why the task cannot be completed.

```bash
python3 scripts/validate_agent_result.py \
  --release config/agent-contracts/agent-contract-release-v1.json \
  --result result.json \
  --context-pack context.json \
  --out validation.json \
  --json
```

## Dataset compilation

Legacy records may use `DRAFT_REFERENCE`, `reviewVerdict`, or free-form arrays.
The compiler maps those fields into the released result envelope without
inventing evidence:

```bash
python3 scripts/compile_training_record.py \
  --input first-batch-candidate.jsonl \
  --release config/agent-contracts/agent-contract-release-v1.json \
  --out first-batch-contract-v1.jsonl \
  --context-dir contexts \
  --dataset-root /path/to/dataset \
  --strict
```

Important rules:

- `DRAFT_REFERENCE` never survives compilation;
- `reviewVerdict=FINDINGS` without structured findings fails closed to
  `taskStatus=UNKNOWN / reviewVerdict=NOT_APPLICABLE`;
- `REPAIR_PLAN` is preserved only when findings and repair conclusions exist;
- `taskStatus=BLOCKED/UNKNOWN` remains visible in the audit report;
- compilation does not grant training approval.

## Dataset audit

```bash
python3 scripts/audit_dataset_contract.py \
  --input first-batch-contract-v1.jsonl \
  --release config/agent-contracts/agent-contract-release-v1.json \
  --dataset-root /path/to/dataset \
  --out dataset-contract-audit.json \
  --strict
```

The audit checks:

- target schema, `taskStatus` and `reviewVerdict`;
- prompt `outputContract` equality with the released contract;
- evidence reference existence;
- unresolved references;
- legacy `status` / `DRAFT_REFERENCE` leakage;
- pending training approval as a warning, not a contract failure.

## Runtime binding

An Agent Task may opt into contract enforcement by carrying:

```text
contractId
contractVersion
contractReleasePath
contextPackPath
contextPackSha256
```

When `contractId` is present, `agent_runtime.py` validates the structured result
through `validate_agent_result.py` rather than accepting an arbitrary JSON
object. Tasks without those fields remain backward compatible during migration.

## Boundaries

- The LLM proposes conclusions, findings and repair plans.
- The deterministic validator decides whether the envelope is valid.
- The Gatekeeper decides whether the artifact is accepted.
- A contract-valid result is not a Gate PASS and is never training approval.
