# Gate Policy

| Gate | Object | Purpose | Result values |
|---|---|---|---|
| R0 | Manifest projection | Structural and atomic requirement quality | `PASS`, `NEEDS_FIX`, `INCOMPLETE` |
| G1 | PRD | Business completeness and decision readiness | `PASS`, `NEEDS_FIX`, `INCOMPLETE` |
| O1 | PRD + Overview | Coverage, consistency, and offline rendering | `PASS`, `NEEDS_FIX`, `INCOMPLETE` |
| U1 | PRD + Prototype | Interaction and rule consistency | `PASS`, `PASS_WITH_NONBLOCKING`, `NEEDS_FIX`, `NOT_TRIGGERED`, `INCOMPLETE` |
| U2 | Prototype + UI standards | Design-standard consistency and required runtime checks | `PASS`, `PASS_WITH_NONBLOCKING`, `NEEDS_FIX`, `NOT_APPLICABLE`, `INCOMPLETE` |
| QA | Delivery bundle | Testability, boundary, exception, and AC coverage | `PASS`, `NEEDS_FIX`, `INCOMPLETE` |
| Q1 | Sealed bundle | Recomputed bundle aggregate conclusion | `PASS`, `PASS_WITH_NONBLOCKING`, `NEEDS_FIX`, `INCOMPLETE` |

## Evidence-first PASS policy

A formal gate may report `PASS` or `PASS_WITH_NONBLOCKING` only when the v2 Gate Result contains:

1. the sealed revision and frozen copy;
2. hashes of every object consumed by the gate;
3. a complete check ledger for `ruleSetVersion`;
4. at least one executable check for PASS;
5. non-empty evidence references for every check;
6. no `unverified` or `not_executed` check in a passing result;
7. consistent blocking counts.

An evidence-free PASS is invalid. An empty `findings` array never proves that checks ran. If checks cannot run, the gate result is `INCOMPLETE` and the bundle cannot finalize.

## Independence

- G1 judges business facts in the PRD.
- O1 and U1 do not rewrite G1.
- QA checks the whole requirement-facing bundle.
- A missing or failed tool run is `INCOMPLETE`, never `PASS`.
- `independentContext` must be backed by a review worker envelope, not manually asserted.

## Independent worker

Every formal round creates a `reviewRunId`. The generating session creates a sealed job only; the review worker executes `R0 → G1 → O1 → U1 → U2 → QA → Q1` on the frozen copy. The worker records:

- worker kind and identity (`subagent` or `process`);
- input hashes;
- immutable review transcript/evidence path.

The generator session must not edit gate result JSON. If the worker cannot start, every affected result is `INCOMPLETE`.

## Q1 policy

Q1 is recomputed from actual gate results, never copied from expectations:

```text
If R0/G1/O1/U1/U2/QA are not all PASS or PASS_WITH_NONBLOCKING -> Q1 = NEEDS_FIX
If any required lens is INCOMPLETE/BLOCKED/NOT_RUN             -> Q1 = INCOMPLETE
If all upstream gates pass and no blocking finding exists       -> Q1 = PASS_WITH_NONBLOCKING
    Q1 may be narrowed to PASS only when no findings exist.
If G1 is not PASS                                              -> Q1 = NEEDS_FIX
```

`PASS_WITH_NONBLOCKING` requires every upstream blocking count to be zero and at least one recorded nonblocking finding. Q1 must consume upstream findings; it must not invent a clean result.

## Candidate seal and independent review

1. Generate six candidate artifacts, including candidate Gates and Workflow.
2. Compute hashes for all six artifacts plus the manifest.
3. Freeze a read-only candidate revision and write a complete candidate seal.
4. Create a review worker job with the revision and hashes.
5. The worker runs all gates in an independent context or process: `R0 → G1 → O1 → U1 → U2 → QA → Q1`.
6. Do not use generation-session self-checks as formal PASS results.
7. Never run only a subset of gates for the formal review.

## Repair loop

If any gate fails, any check cannot run, or any candidate file changes:

- Return to Delivery.
- Enrich findings before repair.
- Regenerate the candidate artifacts.
- Create a new revision.
- Re-seal the candidate.
- Re-run the full gate set with a new review worker.
- Repeat until all gates pass.

## Final sealing

A bundle may receive final seal only when:

- the candidate seal and final seal use the same revision;
- bundle/state revisions and hashes agree;
- all seven gate v2 results pass validation;
- Gate and Workflow documents show exactly the final gate results;
- hashes are unchanged before and after independent review;
- Decision Context readiness is `READY`;
- findings, if any, have a `READY` Finding Repair Context with zero open blockers;
- final gate report and seven individual gate JSON files exist;
- open blocking findings are zero;
- no required gate is `INCOMPLETE`;
- state is updated to `DESIGN_READY`.

## Delivery Quality Exit

Quality Exit is the final Harness gate before Delivery Handoff. It is distinct from the semantic Final Package Review and from the deterministic Gatekeeper.

Required checks:

1. Decision Readiness is `READY` with decision `PROCEED`;
2. all required reviewers and rechecks are complete;
3. blocking findings are zero;
4. Work Plan contains no failed task;
5. open Escalations are zero;
6. applicable Artifact Pair is `SYNCED`;
7. unresolved Prototype Delta is zero;
8. stale Overview is zero;
9. evidence files and input/output hashes exist;
10. the final result can be replayed from the frozen revision.

A failed Quality Exit writes a block evidence file and prevents a READY Handoff.
