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

## Commands

```bash
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
