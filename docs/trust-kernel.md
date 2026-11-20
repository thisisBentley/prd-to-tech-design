# M7.6-0 Trust Kernel

The Trust Kernel is the deterministic pre-execution control plane for trusted
bounded autonomous delivery. It prevents a task from entering the wrong workflow,
against the wrong Jira identity, or with internal checks substituting for an
external gate.

## Flow

```text
Task Request
→ Execution Mode Decision
→ Specialist Tool Route
→ Target Binding Preflight (when required)
→ Trust Kernel Run
→ Execution
→ External Gate Normalization
→ Verdict Cache
→ Submission Contract
→ Submission Manifest
```

## Execution Modes

```text
DIAGNOSIS_ONLY       no change requested; read-only diagnosis
TARGETED_REVISION    reusable artifact + explicit external findings + local scopes
FULL_DELIVERY        new artifact or structural change
ESCALATE             unknown signals or open blocking business decisions
```

Classify first:

```bash
python3 scripts/classify_execution_mode.py \
  --request execution-task-request.json \
  --policy config/trust-kernel/execution-mode-policy-v1.json \
  --out execution-mode-decision.json
```

A `TARGETED_REVISION` must not trigger Discovery, a full Producer roster or a full
Audit Track. A structural change forces `FULL_DELIVERY`.

## Target Binding

The validator parses current PRD metadata and Overview metadata:

```text
Requirement ID / Issue Key / Issue URL / Owner / PRD version
Overview issue-key / issue-url / owner / source-prd-version
```

```bash
python3 scripts/validate_target_binding.py \
  --request target-binding-request.json \
  --out target-binding-report.json
```

A former issue key may be declared as lineage, but it can never satisfy the
current Issue Key check. If the target is `BOT-41040`, an artifact still bound to
an older issue key is `BLOCKED`.

## Specialist Tool Router

```bash
python3 scripts/route_specialist_tool.py \
  --workflow-id WF-1 \
  --execution-mode TARGETED_REVISION \
  --intent PRD_LOCAL_REVISION \
  --policy config/trust-kernel/specialist-tool-routes-v1.json \
  --out specialist-tool-route.json
```

GitLab PRD Tool is a specialist repair/check tool selected by the Agent. It is not
a user-operated fallback. It is not allowed to approve its own output.

## Unified Run

```bash
python3 scripts/run_trust_kernel.py \
  --task-request execution-task-request.json \
  --execution-mode-policy config/trust-kernel/execution-mode-policy-v1.json \
  --tool-policy config/trust-kernel/specialist-tool-routes-v1.json \
  --intent PRD_LOCAL_REVISION \
  --target-binding-request target-binding-request.json \
  --out trust-kernel-run.json
```

`READY` requires a classified mode, a matched tool route and, for targeted
revision, a PASS target binding.

## Final Gate Binding

`final_gatekeeper.py` treats the Trust Kernel binding as a default required check.
Missing `--trust-kernel-run` fails closed as `FINAL.TRUST_KERNEL.BINDING`.
`--allow-missing-trust-kernel` is only a legacy migration escape and still records
the check as failed/non-production.

## External Gate Normalization

```bash
python3 scripts/normalize_external_gate.py \
  --input external-gate-input.json \
  --target-binding target-binding-report.json \
  --out external-gate-verdict.json
```

Canonical verdicts:

```text
PASS
NEEDS_FIX
REJECTED
UNKNOWN
ENVIRONMENT_BLOCKED
```

Release states:

```text
CLOSED
EXTERNAL_GATE_PENDING
EXTERNAL_GATE_FAILED
ENVIRONMENT_BLOCKED
BLOCKED
```

Hard rules:

- only external `PASS` with valid target binding and matching candidate hashes is
  `CLOSED`;
- M7.6-B requires a CLOSED Submission Contract and matching bundle manifest for
  final closure, not only an external verdict file;
- a raw PASS containing a BLOCKING finding becomes `NEEDS_FIX`;
- missing files or hash mismatches are `BLOCKED`;
- environment failures remain `ENVIRONMENT_BLOCKED` and never degrade to PASS;
- `closureEligible=true` is allowed only in `CLOSED`.

## AB Regression Fixtures

The BOT-41040 trajectory is evidence only and must not be edited further. It
proves both failure and recovery modes:

```text
AGENT_ONLY_REPAIR_FAILURE
SPECIALIST_TOOL_REPAIR_SUCCESS
```

Required regressions:

```text
AB-01 targeted revision routes to GitLab tool automatically
AB-02 stale issue key blocks before execution
AB-03 internal PASS + external BLOCKING finding is not closed
AB-04 environment failure is not downgraded
AB-05 structural change cannot use local-only tool route
AB-06 open blocking decision escalates to human
```

The real case family is:

```text
REAL-CASE-DOC-MIGRATION-AB-01
Attempt A: BOT-41040 / Agent-only repair / REJECTED / BLOCKED
Attempt B: ZY20260067-1017 / Specialist-tool repair / PASS / CLOSED
```

```bash
python3 scripts/build_real_case_family.py \
  --input case-family-input.json \
  --out REAL_CASE_FAMILY.json
```

The builder verifies that the failure baseline remains blocked and that the
success reference closes only with external PASS.

## Non-goals

The Decision Contract Compiler is implemented as the separate M7.6-A slice. This
Trust Kernel still does not implement Bounded Repair, Experience Learning or
autonomous external submission; those remain later M7.6 iterations.
