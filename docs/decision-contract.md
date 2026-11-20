# M7.6-A Decision Contract Compiler

The Decision Contract turns a natural-language assertion that "the requirement is
settled" into a deterministic, reviewable contract. It links business decisions
to the semantic objects they decide and to the objects that verify them.

## Flow

```text
Decision Context
+ Delivery Semantic Model
+ Optional Decision Impact Graph
→ compile_decision_contract.py
→ Decision Contract
→ validate_decision_readiness.py
→ READY / BLOCKED
```

A `FULL_DELIVERY` task must not start artifact production from an incomplete
Decision Contract. An internal decision verdict is not an external Gate PASS.

## Commands

```bash
python3 scripts/compile_decision_contract.py \
  --prd PRD_DELIVERY.md \
  --decision-context decision-context.json \
  --semantic-model semantic-model.json \
  --decision-impact-graph decision-impact-graph.json \
  --workflow-id WF-1 \
  --revision r1 \
  --out decision-contract.json

python3 scripts/validate_decision_readiness.py \
  --contract decision-contract.json \
  --prd PRD_DELIVERY.md \
  --workflow-id WF-1 \
  --revision r1 \
  --out decision-readiness.json
```

`--semantic-model` and `--decision-impact-graph` are optional at the CLI boundary
so an operator can generate a diagnostic contract. They are not optional for a
passing production readiness result: a missing semantic model produces a
blocking `SEMANTIC_MODEL_MISSING` finding.

## Readiness Rules

A decision is closed only when:

```text
status is confirmed / closed
owner is present
selectedOptionId is present
```

A closed decision must have:

```text
at least one affected object
at least one verification object
a non-empty expected invariant
```

A contract is `READY` only when:

- no blocking decision is open;
- every `FR-*`, `BR-*`, and `AC-*` unit in the semantic model is traceable to at
  least one decision;
- every affected and verification object exists in the semantic model;
- every blocking finding count is zero;
- the semantic model is bound by path and SHA-256;
- the PRD hash still matches the contract's bound revision.

Affected and verification objects both count as decision traceability. An AC can
be covered as the verification object of a decision even when it is not an
affected object. The traceability field `uncoveredP0P1ObjectIds` is retained for
contract compatibility, but its M7.6-A semantics are all required `FR/BR/AC`
objects; priority fields cannot hide an uncovered AC.

## Blocking Findings

```text
SEMANTIC_MODEL_MISSING
UNDECIDED_P0_P1_OBJECT
OPEN_BLOCKING_DECISION
CLOSED_DECISION_HAS_NO_SELECTED_OPTION
CLOSED_DECISION_HAS_NO_AFFECTED_OBJECT
CLOSED_DECISION_HAS_NO_VERIFICATION_OBJECT
CLOSED_DECISION_HAS_NO_EXPECTED_INVARIANT
DECISION_TARGET_NOT_IN_SEMANTIC_MODEL
```

Every finding must cite the PRD, the Decision Context and, when available, the
semantic model or impact graph evidence.

## Boundary

M7.6-A closes decision completeness and traceability inside the local delivery
pipeline. It does not replace external Jira QA/G1 gates, does not approve a
candidate for submission and does not authorize training. Those remain M7.6-B
and later milestones.
