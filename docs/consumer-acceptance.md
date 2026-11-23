# Consumer Acceptance Contract

M7 Exit needs evidence that the delivery artifacts are consumable by the next
business roles, not only that internal gates pass. This contract adds two consumer
proxy checks:

```text
Product Manager Consumer
Architect Consumer
```

The proxy can reject thin or incomplete artifacts. It cannot claim a real human
review happened.

## Product Manager Consumer

The product proxy requires:

- PRD review result `PASS`;
- minimum PRD content and required business topics;
- executable AC blocks with trigger/result/verification language;
- no unresolved placeholders;
- Overview binds the current PRD hash and has meaningful content in all six tabs;
- Prototype has enough machine bindings, states, exception state kinds and
  permission behavior;
- runtime evidence is `REAL_BROWSER`, current Prototype hash, and error-free;
- Overview and Prototype remain projections of the same frozen PRD.

## Architect Consumer

The architect proxy requires:

- PRD review result `PASS`;
- Decision Contract `PASS` and readiness `READY`;
- Decision Contract PRD hash matches the current PRD;
- no uncovered FR/BR/AC and no open blocking decision;
- decision readiness report `PASS`;
- source lock is locally resolvable and hash-correct;
- source lock contains at least one technical source in addition to PRD facts;
- producer, product-manager and architect contexts are distinct.

## Review authority binding

Consumer context IDs in the request are not sufficient. Each consumer report must
be backed by an independently executed Review Result and its runtime evidence:

```text
Review Result
→ Runtime Record
→ Task Manifest + sha256
→ Structured Result + sha256
→ Reviewer Transcript
```

The evaluator requires:

- reviewer role and context ID match the request;
- reviewer role differs from producer;
- `independentContext=true`, `completionStatus=complete`, verdict
  `ACCEPTED`, zero blocking findings and only passed checks;
- Runtime Record status `SUCCEEDED`;
- Runtime Record context, workflow and structured result match the Review Result;
- Task Manifest hash matches and its role/context match the reviewer;
- transcript exists and is non-empty.

A fabricated `contextId`, stale structured result hash, missing transcript or a
returned/blocked consumer review fails as `BLOCKED`.

## Case classification

```text
FIXTURE
REAL
```

A fixture may exercise the evaluator, but it is never M7 Exit evidence.
`m7ExitEvidenceEligible=true` requires:

```text
caseClassification = REAL
status = PASS
```

The final Gatekeeper requires at least two distinct real case reports:

```bash
python3 scripts/final_gatekeeper.py \
  --consumer-acceptance-report case-a.consumer-report.json \
  --consumer-acceptance-report case-b.consumer-report.json \
  ...
```

Missing reports fail closed. `--allow-missing-consumer-acceptance` remains a
legacy waiver and still records a failed check.

## Review job builder

Before PM/Architect reviews exist, build two isolated jobs from the pending consumer
request:

```bash
python3 scripts/build_consumer_review_jobs.py \
  --request consumer-request.json \
  --out-dir consumer-review-jobs
```

The builder emits:

```text
consumer-review-jobs/
├── manifest.json
├── product-manager-consumer.task.json
├── product-manager-consumer.review-plan.json
├── architect-consumer.task.json
└── architect-consumer.review-plan.json
```

Both tasks receive the same frozen input paths and hashes, but different roles,
contexts, questions, evidence targets, counterexamples and selected checks. The
builder blocks missing prototype/runtime inputs for prototype profiles and blocks
shared roles or contexts.

## Commands

```bash
python3 scripts/run_consumer_review_jobs.py \
  --request consumer-request.json \
  --manifest consumer-review-jobs/manifest.json \
  --policy config/consumer-acceptance/policy-v1.json \
  --out-dir consumer-review-execution \
  --out consumer-review-execution.json \
  --worker python3 scripts/codex_worker.py --sandbox read-only

python3 scripts/run_consumer_acceptance_pipeline.py \
  --request consumer-request.json \
  --policy config/consumer-acceptance/policy-v1.json \
  --out-dir consumer-acceptance-run \
  --out consumer-acceptance-pipeline.json \
  --worker python3 scripts/codex_worker.py --sandbox read-only

python3 scripts/evaluate_consumer_acceptance.py \
  --request consumer-request.json \
  --policy config/consumer-acceptance/policy-v1.json \
  --out consumer-report.json
```

## Boundaries

- This is an Agent consumer proxy, not a human review;
- `humanConsumerReviewRequired` is always true;
- a thin but structurally valid artifact becomes `NEEDS_REVIEW`, not `PASS`;
- missing hashes, invalid decisions, drifted sources or non-independent contexts
  become `BLOCKED`;
- the evaluator does not modify PRD, Overview, Prototype or Decision Contract;
- the evaluator does not replace PRD Review, external QA/G1, T1/R1 or G2.

## Consumer Review Job Runner

`build_consumer_review_jobs.py` freezes the two jobs. The runner executes them
through the local Agent Runtime, preserves the original task and frozen-input
hashes, writes an executed request with the two review result paths, and invokes
the Consumer Acceptance evaluator.

The runner fails closed when task, plan or input hashes drift; validates both
consumer results against `review-result.schema.json`; binds Runtime Record,
transcript, task manifest and structured-result hashes; and keeps worker failures
out of `PASS`.

`run_consumer_acceptance_pipeline.py` is the single intake entry point. It invokes
the Job Builder, Runner and evaluator in order and writes one pipeline report.
Builder or Runner failure remains visible as `FAILED` or `BLOCKED`.
