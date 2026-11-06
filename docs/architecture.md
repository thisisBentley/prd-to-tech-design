# Architecture

```text
Human Decision Owner
        │
   Orchestrator
        │
┌───────┼───────────────────┬──────────────────┐
│       │                   │                  │
Discovery Producer   Delivery Producer    Tech Producer
│       │                   │                  │
│       │◄ Delivery Intake  │                  │
│       │   Reviewer         │                  │
│       │                   │◄ Tech PRD         │
│       │                   │   Diagnostician   │
│       │                   │                  │
│       │             Delivery Reviewer   Tech Reviewer
│       │             QA Red Team         Product Acceptance
│       │                   │                  │
└───────┴───────────────┬───┴──────────────────┘
                        │
              Deterministic Gatekeeper
                        │
                      READY
```

### Delivery internals

```text
Accepted inputs
→ Six candidate artifacts
→ Candidate seal / frozen revision
→ Review job export
→ Independent Gate Result v2 review R0/G1/O1/U1/U2/QA/Q1
→ Finding repair loop when required
→ Final gate outputs + final seal
```

## Layers

| Layer | Responsibility | External dependency |
|---|---|---|
| Skills | User-facing stage workflows and boundaries | None |
| Agents | Role authority, isolation and collaboration | Agent runtime |
| Core | Contracts, methodology, policy | None |
| Engine | Stage contracts and artifact generation | None |
| Adapters | Environment-specific I/O | Optional and configurable |
| Templates | Artifact scaffolding | None |
| Schemas | Runtime data validation | None |

## Invariants

1. PRD is the sole business fact source.
2. Generated artifacts never define new business facts.
3. Gate results are independent lenses.
4. Q1 is the only aggregate conclusion.
5. Findings share one root-cause identity.
6. Formal gate rounds always run all gates on a frozen revision; hashes prove the reviewed copy did not change.
7. Producers cannot approve their own work.
8. Downstream consumers may reject upstream handoffs but must not rewrite upstream facts.
9. Reviews bind to frozen handoff hashes and distinct contexts.
10. The deterministic Gatekeeper cannot be overridden by agent consensus.
11. External writes are explicit, adapter-based, and confirmed.
