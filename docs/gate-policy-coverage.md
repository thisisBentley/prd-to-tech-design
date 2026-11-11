# Gate Policy Coverage

## Purpose

A gate rule is not considered executed because a gate says `PASS`. Every applicable rule must appear in the Gate Result with:

```text
ruleId
status
evidenceRefs
observed
expected
```

The policy must be frozen before generation and review.

## Flow

```text
Gate Policy Pack
→ Applicability Resolver
→ Policy Lock
→ Producer / Reviewer consume applicable rules
→ Gate Results return ruleId results
→ Rule Coverage Validator
→ Final Gate / Readiness
```

## Policy Pack

Current machine-readable pack:

```text
references/gate-policy-current.json
```

The pack includes 36 rules across:

```text
R0 / G1 / O1 / U1 / U2 / QA / Q1
```

Each rule declares:

```text
ruleId
gate
severity
checkType
requiredEvidence
passCondition
failureAction
owner
appliesWhen
```

## Policy Lock

```bash
python3 scripts/build_policy_lock.py \
  --artifact-profile PRD_PLUS_PROTOTYPE \
  --requirement-types CRUD,UI_INTERACTION \
  --prototype-status TRIGGERED \
  --ui-ownership LOCAL \
  --out .delivery/policy-lock.json
```

The lock freezes:

- policy pack identity and hash;
- artifact profile and requirement types;
- applicable rule IDs per gate;
- excluded rules and exclusion reasons.

The lock hash must be copied into every formal Gate Result as `policyLockSha256`.

## Coverage validation

```bash
python3 scripts/validate_gate_rule_coverage.py \
  --policy-lock .delivery/policy-lock.json \
  --gate-dir .delivery/gate-results/<revision> \
  --out .agents/gate-rule-coverage.json
```

A passing result requires:

```text
missingRules = 0
applicable non-passed checks = 0
unknown ruleIds = 0
duplicate ruleIds = 0
policyLockSha256 matches every gate
ruleSetVersion matches every gate
```

A Gate Result cannot claim PASS if any applicable rule is missing or not passed.

## Applicability

`not_applicable` is not a Reviewer convenience value. Applicability is decided by the resolver from:

```text
artifactProfile
requirementTypes
prototypeStatus
uiOwnership
```

If applicability is unknown, fail closed rather than omitting the rule.

## Repair

Findings and repairs remain bound to `ruleId`. Recheck uses the same policy lock. Changing the policy pack invalidates the old lock and requires a new Candidate Seal and full review.

## Generation Obligations

The policy lock is converted into producer-facing obligations:

```bash
python3 scripts/build_generation_obligations.py \
  --policy-lock .delivery/policy-lock.json \
  --workflow-id <workflowId> \
  --out .agents/policy/generation-obligations.json
```

Producer and reviewer Agent Tasks receive the frozen policy lock and obligations as inputs. Producer obligations are generation constraints; formal PASS still requires independent Gate Result evidence for every applicable `ruleId`.
