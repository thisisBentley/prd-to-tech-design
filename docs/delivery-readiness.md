# Delivery Readiness

`DESIGN_READY` is not a single gate boolean. It requires three base components; an explicitly required Audit Track adds a fourth blocking dimension.

```text
CONTENT_READY   semantic package is complete and machine-bindable
EVIDENCE_READY  gates, hashes and final seal are internally consistent
BUNDLE_READY    final delivery root is self-contained and replayable
DESIGN_READY    CONTENT_READY && EVIDENCE_READY && BUNDLE_READY
AUDIT_READY     required audit plan is current, complete and AUDIT_PASS
DESIGN_READY    ... && AUDIT_READY when --require-audit is enabled
```

## CONTENT_READY

- PRD exists and contains traceable `FR-*` and `AC-*` identifiers.
- An independent semantic review is accepted, or a semantic aggregate is `PASS` / `PASS_WITH_NONBLOCKING`.
- When a Prototype exists, its Manifest exists and stable machine bindings are complete:
  - `data-ai-id`;
  - `data-ai-fr`;
  - `data-ai-ac`;
  - meaningful `states`;
  - Manifest IDs equal HTML IDs;
  - Manifest hashes match the Prototype;
  - every PRD FR/AC is bound to a UI element.

Line numbers and natural-language source references are supplementary evidence, not a substitute for machine bindings.

## EVIDENCE_READY

- All seven gates exist and pass, or are explicitly not applicable.
- Every Gate Result shares one `reviewRunId`.
- Gate `objectHashes` match the candidate seal and current bytes.
- Final-seal artifact hashes match current bytes.
- Final-seal gate results match the Gate Result files.
- Any hash-stability observation inside a gate equals that gate's `objectHashes`.
- Independent execution and unchanged-artifact flags are both true.

A gate that contains contradictory hashes is invalid even if its own result says PASS.

## BUNDLE_READY

The final delivery root must contain:

```text
PRD_DELIVERY.md
Prototype.html (when triggered)
prototype-manifest.json (when Prototype is triggered)
Overview.html
Jira_Description.md
Gates.md
Workflow.md
requirements.json
.delivery/decision-context.json
.delivery/gate-results/<revision>/
.delivery/review-evidence (when applicable)
.delivery/final-seal.json
```

Artifacts that exist only in `.delivery/candidate-revisions/<revision>/` do not make the final package self-contained.

## AUDIT_READY

When `.delivery/audit-plan.json`, `.delivery/audit-summary.json` and `.delivery/audit-runner-report.json` exist, readiness validates all three automatically. `--require-audit` makes them mandatory.

The summary must:

- be `AUDIT_PASS`;
- bind the current audit plan hash;
- bind the same revision and `policyLockSha256`;
- match the frozen artifact snapshot;
- contain no missing job, missing rule, failed job or blocking finding;
- show every job as `EXECUTED` or `RESUMED` with `artifactStable=true`.

A failing required audit produces `AUDIT_BLOCKED`. Audit PASS is supplementary evidence and still does not replace organizational approval.

## Result statuses

| Status | Meaning |
|---|---|
| `DESIGN_READY` | all base components pass and any required audit passes |
| `CONTENT_BLOCKED` | content or machine binding is incomplete |
| `EVIDENCE_BLOCKED` | gate/hash/review evidence is inconsistent |
| `BUNDLE_BLOCKED` | final package is missing required files or evidence |
| `EVIDENCE_AND_BUNDLE_BLOCKED` | both evidence and bundle are incomplete |
| `AUDIT_BLOCKED` | base components pass but the required Audit Track is missing, stale or blocked |

## Commands

```bash
python3 scripts/validate_prototype_binding.py \
  --prototype <Prototype.html> \
  --manifest <prototype-manifest.json> \
  --prd <PRD_DELIVERY.md> \
  --json

python3 scripts/verify_delivery_bundle_integrity.py \
  --bundle 01-delivery \
  --out .agents/delivery-readiness.json
```

`final_gatekeeper.py` runs both checks and exposes `contentReady`, `evidenceReady`, `bundleReady`, `auditReady` and `designReady` in its composite result.
