# Independent Audit Track

## Purpose

The Audit Track is the second, independent execution path over a frozen Delivery revision. It does not generate the PRD, Prototype or Gate result and it does not replace formal `R0/G1/O1/U1/U2/QA/Q1` gates.

```text
Generation Track                     Audit Track
----------------                     -----------
Generation Obligations               Audit Profile
Producer artifacts                   Toolbox Rule Crosswalk
Producer declarations                Rule-bound audit jobs
Candidate Seal                       Independent executor results
          \                           /
           \                         /
            Finding + Repair + New Revision
                      |
                Full re-audit and full gate replay
```

The two tracks must bind the same:

```text
workflowId
revision
policyLockSha256
candidate-seal frozenCopy
frozen artifact hashes
```

The Audit Track runs against the Candidate Seal's immutable `frozenCopy`, after candidate sealing and before `final-seal.json` exists. A finalized bundle cannot be audited retroactively.

A changed artifact, policy lock or crosswalk invalidates both tracks.

## Why two tracks

A Producer is good at semantic construction and repair. A rule-specific Skill or deterministic checker is good at exhaustive, mechanical checks. Re-running the same general Producer prompt is not an independent audit.

The Audit Track therefore requires:

1. one frozen audit plan;
2. one independent executor context per job;
3. explicit `policyRuleIds` evidence in each result;
4. coverage of every applicable policy rule;
5. separate `EDGE_REVIEW` and `GLOBAL_INTEGRATION_REVIEW` jobs;
6. findings that return to the original owner;
7. a full re-audit after any repair.

Single-rule PASS does not imply package PASS. Global review is mandatory.

## Contracts

| Contract | Purpose |
|---|---|
| `schemas/audit-profile.schema.json` | Selects gates, executor types and minimum rule coverage |
| `schemas/toolbox-rule-crosswalk.schema.json` | Maps Policy Rule IDs to Skill checks and executor types |
| `schemas/audit-plan.schema.json` | Frozen executable audit jobs |
| `schemas/audit-result.schema.json` | Independent result for one audit job |
| `schemas/audit-summary.schema.json` | Package-level audit coverage and blockers |
| `schemas/audit-run-report.schema.json` | Per-job runner execution, context IDs and artifact immutability proof |

Executor types:

```text
DETERMINISTIC -> tool or fixed checker
SEMANTIC      -> independent Skill / Reviewer context
HUMAN         -> explicit product or technical decision
```

## Profiles

Bundled profiles:

```text
config/audit-profiles/prd-only.json
config/audit-profiles/prd-prototype.json
config/audit-profiles/ai-llm.json
config/audit-profiles/migration.json
config/audit-profiles/high-risk.json
```

`HIGH_RISK_AUDIT` requires two executor types per applicable rule. It intentionally blocks when the selected crosswalk does not provide that depth.

The reference crosswalk is:

```text
config/audit-crosswalk/delivery-toolbox-v2.json
```

It maps all 39 current policy rules, including Decision Impact, Runtime AC and external Skill contract hardening. Organizations can replace it with their own crosswalk without changing the audit execution contract.

## Pre-finalization stage

The Pipeline now builds the Candidate Seal automatically before the Audit Stage. The builder creates `requirements.json`, derives the candidate Issue/Gates/Workflow projections when absent, copies the candidate files into `.delivery/candidate-revisions/<revision>/`, computes their hashes and writes `candidate-seal.json`.

The reusable builder is:

```bash
python3 tools/build_candidate_bundle.py \
  --bundle 01-delivery \
  --workflow-id <workflowId> \
  --requirement-name "<需求名称>" \
  --revision r1 \
  --prd 01-delivery/PRD_DELIVERY.md \
  --overview 01-delivery/Overview.html \
  --jira 01-delivery/Jira_Description.md
```

The orchestrated entry point enforces lifecycle order:

```bash
python3 tools/run_delivery_audit_stage.py \
  --run-root <runRoot> \
  --bundle 01-delivery \
  --workflow-id <workflowId> \
  --revision r1 \
  --profile config/audit-profiles/prd-prototype.json \
  --crosswalk config/audit-crosswalk/delivery-toolbox-v2.json \
  --worker python3 tools/audit_worker.py
```

It fails when:

- the Candidate Builder cannot create or reuse `candidate-seal.json`;
- `final-seal.json` already exists;
- the Candidate Seal revision or artifact hashes do not match the frozen copy;
- the frozen copy has changed.

Only `AUDIT_PASS` permits the pipeline to continue toward finalization.

## Bounded repair cycle and finding ledger

The standalone repair cycle is available for controlled runs. It now persists findings in `.delivery/findings.json`, deduplicates the same `findingId` across Audit Jobs, stops when a finding survives two repair rounds, blocks a repair that increases total findings, and resolves findings only after a full `AUDIT_PASS`:

```bash
python3 tools/run_audit_repair_cycle.py \
  --run-root <runRoot> \
  --bundle 01-delivery \
  --workflow-id <workflowId> \
  --requirement-name "<需求名称>" \
  --profile config/audit-profiles/prd-only.json \
  --crosswalk config/audit-crosswalk/delivery-toolbox-v2.json \
  --audit-worker python3 tools/audit_worker.py \
  --repair-worker python3 tools/audit_repair_worker.py
```

The cycle requires a repair worker to report changed active artifacts. It then creates a new revision, rebuilds Candidate Seal and runs a full Audit again. Old frozen copies and old audit results remain historical evidence.

The default Delivery Pipeline can invoke the same bounded cycle:

```bash
python3 tools/delivery_pipeline.py ... \
  --audit-mode gate \
  --repair-mode bounded \
  --repair-worker python3 tools/audit_repair_worker.py \
  --repair-rederive-mode gate
```

After a repair, `tools/rederive_delivery_evidence.py` rebuilds semantic evidence, generation obligations, hardening reports, artifact quality and Candidate Seal for the new revision. Semantic review reuse is allowed only when every semantic-ledger artifact hash is unchanged. When artifacts changed, or the existing semantic ledger cannot prove complete coverage, the re-derivation blocks and requires a refreshed semantic producer output. The final revision is propagated to Delivery Plan, review outputs, Handoff and Package Evidence.

The ledger lifecycle is:

```text
observed / observed_again
→ repair_started
→ not_observed_pending_full_pass (when another failure is still blocking)
→ reopened (if it appears again after an absence)
→ resolved_by_full_reaudit (only after AUDIT_PASS)
```

`Delivery Readiness` validates the ledger when `.delivery/findings.json` exists. A non-current revision, unresolved finding or open blocking finding fails `INTEGRITY.FINDING_LEDGER`.

Remaining limitation: a changed artifact cannot reuse an old semantic Review. When deterministic re-derivation cannot prove complete semantic coverage, the Pipeline blocks until an external semantic producer refreshes the ledger/review and producer declarations are regenerated for the new revision.

## Build the audit plan separately

```bash
python3 tools/build_audit_plan.py \
  --policy-lock .delivery/policy-lock.json \
  --artifact-root 01-delivery \
  --profile config/audit-profiles/prd-prototype.json \
  --crosswalk config/audit-crosswalk/delivery-toolbox-v2.json \
  --workflow-id <workflowId> \
  --revision r1 \
  --out .delivery/audit-plan.json
```

The plan freezes both the policy lock and an `artifactHashes` snapshot. In the pre-finalization stage, `--artifact-root` is the Candidate Seal `frozenCopy`, not the mutable live bundle. If the live candidate artifacts change after sealing, the builder requires a new revision instead of silently replacing the frozen copy.

Plan construction fails closed when:

- an applicable Policy Rule has no crosswalk mapping;
- the profile requires more executor types than the crosswalk supplies;
- a required global review is missing;
- a referenced Skill is not declared;
- the same audit job is produced twice.

## Run audit jobs

Each job is executed in a separate process by the runner:

```bash
python3 tools/run_audit_jobs.py \
  --run-root <runRoot> \
  --plan .delivery/audit-plan.json \
  --worker python3 tools/audit_worker.py \
  --out-dir .delivery/audit-results \
  --summary .delivery/audit-summary.json \
  --report .delivery/audit-runner-report.json
```

The worker command contract is:

```text
<worker> --job <frozen-job.json> --out <audit-result.json>
```

The runner:

- creates one unique executor context per job;
- binds every job to the same Plan hash, revision and Policy Lock;
- verifies the artifact snapshot before and after every job;
- rejects any result produced by a worker that changed an artifact;
- verifies result identity and rule coverage before accepting it;
- supports `--resume` only for existing results bound to the same Plan.

`tools/audit_worker.py` is the Codex adapter. It uses a read-only sandbox and refuses to simulate `HUMAN` audit jobs. A human executor must supply a genuine human result through the same worker contract.

For each job, `checks[].policyRuleIds` must be explicit. Every rule bound to the job must have non-empty evidence and `status=passed` for a non-blocking result.

## Aggregate results

The runner can aggregate directly with `--summary`. To aggregate separately:

```bash
python3 tools/validate_audit_results.py \
  --plan .delivery/audit-plan.json \
  --results-dir .delivery/audit-results \
  --out .delivery/audit-summary.json
```

Aggregation fails closed when:

- a job result is missing or duplicated;
- a result is not bound to the current plan hash, revision or policy lock;
- an executor type differs from the frozen job;
- a bound rule is omitted from checks;
- a check has no evidence;
- a blocking finding remains;
- global integration review is missing.

Successful output:

```text
AUDIT_PASS
```

## Readiness integration

When `audit-plan.json`, `audit-summary.json` and `audit-runner-report.json` exist in `.delivery/`, readiness validates them automatically. A production run can force the requirement:

```bash
python3 tools/verify_delivery_bundle_integrity.py \
  --bundle 01-delivery \
  --require-audit \
  --out .agents/delivery-readiness.json
```

A required audit that is missing, stale, incomplete or blocked produces:

```text
AUDIT_BLOCKED
```

and cannot produce `DESIGN_READY`.

## Boundary

- Audit results are independent evidence, not a second artifact source.
- Audit findings route back to the artifact owner.
- Repair creates a new revision.
- The old audit plan and all old results remain historical evidence.
- The new revision requires a new plan and full audit.
- Audit Track PASS still does not replace organizational approval or a formal G1/G2/G3 decision.
