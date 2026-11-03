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

## Sealing

A bundle may seal only when:

- Required artifacts exist
- Prototype status is explicit
- Q1 is `PASS`
- Blocking findings are zero
- Artifact hashes match `bundle.json`
- State is updated to `DESIGN_READY`
