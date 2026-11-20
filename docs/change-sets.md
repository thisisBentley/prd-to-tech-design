# M7.6-C Finding Router and Change Set

M7.6-C turns blocking findings into bounded Change Sets before any Repair Task is
created. It prevents the BOT-41040 pattern where one external finding triggered a
new revision, and repeated findings restarted unrelated work.

## Flow

```text
Blocking findings
→ root-cause grouping
→ problem classification
→ Change Set routing
→ affected artifacts / verification plan / budget
→ independent Change Set validation
→ Repair Plan
```

No Repair Plan may be generated from a legacy repair batch or from a blocked
Change Set batch.

## Classification and routing

```text
DECISION_GAP        → BUSINESS_REVISION
SOURCE_CONFLICT     → BUSINESS_REVISION
SPEC_MISSING        → BUSINESS_REVISION
ARTIFACT_DRIFT      → ARTIFACT_SYNC
IMPLEMENTATION_RISK → TECH_SOLUTION
TEST_GAP            → TEST_PLAN
EDITORIAL           → MECHANICAL_REPAIR
MECHANICAL          → MECHANICAL_REPAIR
```

Business revision is marked `true` only for the first three classes. Editorial
and mechanical fixes cannot silently bump a business revision.

## Compile and validate

```bash
python3 scripts/compile_change_sets.py \
  --review review-r1.json \
  --policy config/trust-kernel/change-set-policy-v1.json \
  --out change-set-batch.json

python3 scripts/validate_change_sets.py \
  --batch change-set-batch.json \
  --policy config/trust-kernel/change-set-policy-v1.json \
  --review review-r1.json \
  --out change-set-validation.json

python3 scripts/plan_repairs.py \
  --change-set-batch change-set-batch.json \
  --out repair-plan.json
```

## Grouping rules

- every blocking finding must declare `rootCauseId`, `stableKey` or `dedupeKey`;
- findings with the same root cause become one Change Set;
- all findings in a root cause must resolve to one problem classification;
- classification may be explicit, mapped from the legacy `repairClass`, or
  inferred from unambiguous keywords;
- ambiguous classification blocks instead of guessing;
- every Change Set must declare at least one affected artifact;
- the validation step must prove every blocking finding is covered exactly once.

## Budget

Policy defines:

```text
maxAffectedArtifacts
maxFindings
maxRepairRounds
maxChangedLines
```

Exceeding a declared budget blocks the Change Set. The Repair Plan receives the
same budget object; it cannot expand scope locally.

## Verification Plan

Each Change Set carries required verification checks from policy plus any tests
declared by the source findings. These checks are the minimum post-repair proof;
the Change Set cannot mark itself complete from a successful edit alone.

## Hard boundaries

- a Change Set is not a repair;
- a Repair Plan is not a PASS;
- business and mechanical changes must remain distinguishable;
- M7.6-C does not execute repairs, call external gates or approve training;
- Bounded Repair execution remains M7.6-D.
