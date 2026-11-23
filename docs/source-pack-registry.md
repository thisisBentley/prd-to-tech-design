# Source Pack Registry

## Purpose

The Source Pack Registry makes material provenance, authority, allowed use and
tool applicability deterministic. It prevents three recurring failures:

```text
stale or low-authority material treated as fact
reference material silently entering runtime or training
tool availability mistaken for domain applicability or authorization
```

This registry is governance metadata. It does not prove that a source is
correct, and it never converts historical replay or fixtures into release
evidence.

## Source Classes

```text
NORMATIVE    user-confirmed rules, gates, policy packs, organizational constraints
SOURCE_FACT  Jira, PRD, code, GitLab, attachments, comments
MEASURED     runtime, audit, finding, repair, cost and consumer reports
DERIVED      summaries, indexes, episodes and attribution results
REFERENCE    external projects, skills, design articles and examples
INFERENCE    model hypotheses, unconfirmed preferences, unverified conclusions
```

Authority is fixed:

```text
USER_DECISION
> NORMATIVE
> SOURCE_FACT
> MEASURED
> DERIVED
> REFERENCE
> INFERENCE
```

A lower-authority source may never silently override a higher-authority source.
Conflicts remain explicit and either resolve by authority or require a human
decision.

## Allowed Uses

```text
DESIGN_REFERENCE
EVALUATION_CORPUS
RUNTIME_INPUT
TRAINING_CANDIDATE
```

D.12 rules:

- `REFERENCE` sources may only be `DESIGN_REFERENCE`;
- `INFERENCE` sources may not be `RUNTIME_INPUT`;
- unknown license permits `DESIGN_REFERENCE` only;
- unknown confidentiality may not enter runtime or training;
- `TRAINING_CANDIDATE` is disabled for every current source;
- historical replay is evaluation evidence, not release evidence.

## Build

```bash
python3 tools/build_source_pack.py \
  --catalog config/source-packs/current-v1.catalog.json \
  --repo-root . \
  --out config/source-packs/current-v1.json
```

The builder:

- hashes every repository/local source;
- records lock and freshness status;
- preserves explicit `NOT_PRESENT` coverage;
- rejects forbidden authority/use combinations;
- rejects duplicate IDs and unresolved conflicts.

## Validate

```bash
python3 tools/validate_source_pack.py \
  --registry config/source-packs/current-v1.json \
  --repo-root .
```

Validation fails closed on:

- schema errors;
- forbidden source class / authority combinations;
- invalid allowed-use combinations;
- training candidates in D.12;
- stale locks;
- repository hash drift;
- open conflicts;
- coverage-count mismatch.

## Tool Applicability

Specialist tool routes are domain-bound. A route declares:

```text
toolDomain
allowedTaskDomains
allowedOperations
readBoundaries
writeAuthority
sourcePackRefs
requiresHumanApproval
```

Routing order:

```text
Task Domain
→ Tool Domain Compatibility
→ Operation Authorization
→ Source Pack Binding
→ Data Boundary
→ Execute or Escalate
```

Hard rule:

```text
Tool Available ≠ Tool Applicable ≠ Tool Authorized
```

A finance or trading tool may not be selected for product-engineering work, even
when it exposes a generally useful operation such as reading documents.

## Exact Commands

```bash
python3 tools/route_specialist_tool.py \
  --workflow-id WF-1 \
  --execution-mode TARGETED_REVISION \
  --intent PRD_LOCAL_REVISION \
  --task-domain PRODUCT_ENGINEERING \
  --operation SELECT \
  --policy config/trust-kernel/specialist-tool-routes-v1.json \
  --source-pack config/source-packs/current-v1.json \
  --out route.json
```

When the domain does not match, the route status is `ESCALATE` and
`applicability.status` is `BLOCKED`.

## Non-goals

- no training approval;
- no quality score;
- no replacement for target binding, external gates or release evidence;
- no second tool router;
- no ingestion of unrelated external domains.
