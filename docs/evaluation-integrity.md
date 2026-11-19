# Evaluation Integrity and Capability Attribution

An evaluation result is usable only when the task can be answered within its
declared evidence scope.

```text
Task contract
→ Evidence scope
→ Task integrity audit
→ Fair baseline run
→ Human blind review
→ Capability attribution
```

## Task Integrity Gate

Run the static task/evidence audit before comparing models:

```bash
python3 scripts/audit_evaluation_integrity.py \
  --tasks golden-validation-v2.jsonl \
  --tasks golden-test-v2.jsonl \
  --issue-root issues \
  --policy evaluation-integrity-policy.json \
  --out evaluation-integrity-report.json \
  --strict
```

A task is invalid when:

- a declared evidence ref does not exist;
- the task asks for work on source artifacts that are not in its evidence scope;
- a required artifact type cannot be matched to an allowed evidence ref;
- duplicate task/version identities exist.

Do not count invalid tasks as model-capability failures. Preserve the old task as
historical evidence, create a new task version and rerun in the new scope.

## Capability Attribution

```bash
python3 scripts/analyze_capability_attribution.py \
  --integrity evaluation-integrity-report.json \
  --capability-gap capability-gap-report.json \
  --out capability-attribution-report.json
```

Allowed decisions are deliberately conservative:

```text
modelParameterGap: NOT_PROVEN | PROVEN
harnessSkillContextGap: NOT_PROVEN | PROVEN
training: HOLD | CANDIDATE_FOR_NARROW_SFT
```

A model-parameter gap requires all of the following:

```text
fair tasks with complete evidence
→ explicit skill and output contract
→ stable failure across independent tasks and splits
→ human blind review confirms semantic failure
→ approved gold samples and isolated validation/test
→ narrow trainable capability
```

Loss reduction, longer JSON or a low lexical recall score cannot prove model
capability improvement.

## Evaluation Run Integrity

Before scoring a new task set, verify that every baseline produced exactly the
expected validation and test task IDs:

```bash
python3 scripts/audit_evaluation_run.py \
  --integrity evaluation-integrity-report.json \
  --tasks golden-validation-v2.jsonl \
  --tasks golden-test-v2.jsonl \
  --predictions-dir predictions-v2 \
  --runtime-blocker B2_CODEX_APP_SERVER_OPERATION_NOT_PERMITTED \
  --out evaluation-run-report.json \
  --strict
```

Missing, extra, duplicate or partial predictions make the run non-closable.
Runtime blockers stay explicit; old predictions cannot stand in for a new model
run. `closureEligible=true` requires task integrity PASS and complete B0/B1/B2
prediction sets for both splits.
