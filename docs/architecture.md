# Architecture

```text
User
 ├── Discovery Skill
 │    ├── adapters (read-only, optional)
 │    ├── Capability Ideation
 │    ├── Capability Matrix
 │    └── Requirement Brief / Concept Handoff
 │
 └── Delivery Skill
      └── Workflow Engine
           ├── Input assembly
           ├── PRD + manifest
           ├── Issue description
           ├── Overview
           ├── Optional prototype
           ├── Gates R0/G1/O1/U1/QA/Q1
           ├── Finding ledger
           ├── Repair/rerun
           └── Sealed bundle
```

## Layers

| Layer | Responsibility | External dependency |
|---|---|---|
| Skills | User-facing process and boundaries | None |
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
6. Reruns are driven by hashes.
7. External writes are explicit, adapter-based, and confirmed.
