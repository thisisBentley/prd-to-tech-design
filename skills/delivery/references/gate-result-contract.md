# Gate Result v2

A formal result must include:

- `schemaVersion: 2`, `gate`, `revision`, `frozenCopy`;
- `independentContext: true` and a `reviewRunId`;
- the exact `ruleSetVersion` and consumed-object SHA-256 hashes;
- a complete `checks[]` ledger;
- non-empty `evidenceRefs` for every check;
- `blockingCount` and `completionStatus`;
- `tool` and `checkedAt`.

PASS or PASS_WITH_NONBLOCKING requires at least one executable check, zero blockers, and no `unverified` or `not_executed` check. Empty `findings` is not evidence.

An empty check ledger, a failed tool, or unreachable material must be `INCOMPLETE`. `INCOMPLETE` blocks finalization.

See `schemas/gate-result.schema.json`, `schemas/delivery-gate-summary.schema.json`, and `schemas/review-evidence.schema.json`.

## Upstream consumption

The worker must reconcile:

- `*-PRD-review-findings.json`;
- `*-G1-review-result.json`;
- `*-U1-review-result.json`;
- `*-U2-review-result.json`.

An upstream blocker or missing required upstream machine result cannot be hidden by a downstream PASS.
