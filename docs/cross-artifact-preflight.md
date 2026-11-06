# Cross-Artifact Preflight

This deterministic check guards the highest-risk gaps that section-title checks miss:

| Rule | Detects |
|---|---|
| X1 | "Authorized role" without role names, field scope, or denied result |
| X2 | Export action without field/format/limit/empty/failure/permission contract or AC |
| X3 | Scenario enum without complete values or unknown-value behavior |
| X4 | Required exception fields absent from the prototype |
| X5 | `[TIMEOUT]` required as an event but represented only as an ordinary message |

It emits `cross-artifact-preflight.json` with checks, stable findings, evidence references, and `blockingFindings`.

The check is a guardrail, not a formal gate. Formal G1/U1 workers must reconcile every blocker and still perform semantic review.

Regression fixture: `tests/fixtures/zy779-regression/` reproduces the five failure classes from ZY20250117-779 without including customer data.
