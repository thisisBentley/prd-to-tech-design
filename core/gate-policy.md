# Gate Policy

| Gate | Object | Purpose | Result values |
|---|---|---|---|
| R0 | Manifest projection | Structural and atomic requirement quality | `PASS`, `NEEDS_FIX`, `INCOMPLETE` |
| G1 | PRD | Business completeness and decision readiness | `PASS`, `NEEDS_FIX`, `INCOMPLETE` |
| O1 | PRD + Overview | Coverage, consistency, and offline rendering | `PASS`, `NEEDS_FIX`, `INCOMPLETE` |
| U1 | PRD + Prototype | Interaction and rule consistency | `PASS`, `PASS_WITH_NONBLOCKING`, `NEEDS_FIX`, `NOT_TRIGGERED`, `INCOMPLETE` |
| QA | Delivery bundle | Testability, boundary, exception, and AC coverage | `PASS`, `NEEDS_FIX`, `INCOMPLETE` |
| Q1 | Sealed bundle | Bundle-level aggregate conclusion | `PASS`, `NEEDS_FIX`, `INCOMPLETE` |

## Independence

- G1 judges business facts in the PRD.
- O1 and U1 do not rewrite G1.
- QA checks the whole requirement-facing bundle.
- A missing or failed tool run is `INCOMPLETE`, never `PASS`.

## Q1 policy

```text
If G1 is not PASS                         -> Q1 = NEEDS_FIX
If a required lens is INCOMPLETE/BLOCKED  -> Q1 = INCOMPLETE
If G1 PASS and all required lenses PASS   -> Q1 = PASS
If G1 PASS and any lens NEEDS_FIX         -> Q1 = NEEDS_FIX
```

Map `U1: PASS_WITH_NONBLOCKING` to `PASS` only when its findings are explicitly nonblocking.

## Candidate seal and independent review

1. Generate six candidate artifacts, including candidate Gates and Workflow.
2. Compute hashes for all six artifacts plus the manifest.
3. Freeze a read-only candidate revision.
4. Run all gates in an independent execution context or process: `R0 → G1 → O1 → U1 → QA → Q1`.
5. Do not use generation-session self-checks as formal PASS results.
6. Never run only a subset of gates for the formal review.

## Repair loop

If any gate fails or any candidate file changes:

- Return to Delivery.
- Regenerate the candidate artifacts.
- Create a new revision.
- Re-seal the candidate.
- Re-run the full gate set.
- Repeat until all gates pass.

## Final sealing

A bundle may receive final seal only when:

- The final frozen revision has all required artifacts
- Prototype status is explicit
- All six gate results pass
- Candidate Gates and Workflow match the final gate results
- Hashes are unchanged before and after independent review
- Final gate report and six individual gate JSON files exist
- Blocking findings are zero
- State is updated to `DESIGN_READY`
