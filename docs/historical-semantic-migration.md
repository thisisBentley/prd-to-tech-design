# Historical Semantic Migration

Historical semantic migration prepares evidence-backed suggestions for converting
legacy packages into the current contract. It never edits the source package and
never invents FR/AC relationships.

## Flow

```text
Legacy PRD / Overview / Prototype
→ extract FR and AC objects
→ create candidate FR↔AC links
→ classify confidence and evidence basis
→ report unresolved ACs
→ recommend Overview and Prototype migrations
```

## Candidate link rules

```text
EXPLICIT_REFERENCE  FR id appears in the same AC line or table row
TABLE_CELL          FR id appears in another table cell of the same AC row
LOCAL_SECTION       only one unambiguous FR appears in the local window
TEXT_SIMILARITY     lexical similarity above threshold with a unique winner
```

Ambiguous local windows, multiple equally strong candidates, or generic AC text
remain unresolved. The planner does not turn a guess into `HIGH` confidence.

## Commands

```bash
python3 scripts/plan_historical_semantic_migration.py \
  --spec config/consumer-acceptance/historical-replay-samples-v1.json \
  --out-dir outputs/historical-migration-plans-v1
```

## Outputs

```text
CASE.migration-plan.json
summary.json
```

Each plan contains:

```text
PRD sections and missing topics
FR objects and evidence
AC objects and candidate FR ids
FR↔AC candidate links with confidence
unresolved ACs
legacy/modern Prototype binding counts
Overview source/hash and tab migration actions
```

## Boundaries

- does not modify historical source packages;
- does not infer business rules;
- does not approve candidate mappings;
- does not replace human review of ambiguous ACs;
- does not make historical replay eligible for M7 Exit;
- all migrated candidates require review before rebinding current gates.
