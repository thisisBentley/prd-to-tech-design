# Artifact Contract

Delivery produces six primary artifacts in this order, then a separate final gate evidence set:

```text
runRoot/01-delivery/
├── Issue_Description.md
├── Overview.html
├── PRD_DELIVERY.md
├── Prototype.html       # optional
├── Gates.md
├── Workflow.md
└── gate-outputs/
    ├── Final_Gate_Review.md
    ├── R0.json
    ├── G1.json
    ├── O1.json
    ├── U1.json
    ├── QA.json
    └── Q1.json
```

## 1. Issue description

Required. A short business summary intended for a tracker or work item.

Fixed sections:

1. Requirement background
2. Requirement goal
3. Detailed requirements involved

Rules:

- Background and goal: one or two sentences each.
- Detailed requirements: three to six items; at most eight for a complex requirement.
- Use plain business language.
- Do not expose internal requirement IDs, priority labels, field specifications, or acceptance-matrix detail.
- Do not automatically update an external tracker.

## 2. Overview

Required. A single-file offline review page.

Recommended sections:

- Background and summary
- Goals and scope
- Solution and flow
- Features and rules
- Prototype and interaction
- Acceptance and assurance

The overview must not invent facts absent from the PRD.

## 3. PRD

Required. The sole business fact source.

It should define:

- Background, actors, goals, scope, and non-goals
- Functional requirements
- Business and interaction rules
- States, permissions, and data contracts
- Exceptions and recovery behavior
- Acceptance criteria
- Change history and open questions

## 4. Prototype

Optional. Generated only when user-visible interaction changes.

Trigger examples:

- New page or entry
- Changed operation path
- User-visible state
- Official copy
- Field visibility, validation, or feedback
- Permission, disabled, failure, or recovery result

If not triggered, record `prototypeStatus: NOT_TRIGGERED`; do not create a placeholder.

## 5. Gates report

Required. Candidate version is generated before candidate seal; final version must reflect the final independent review. Records gate results, findings, owners, unverified items, revisions, and final gate output paths.

## 6. Workflow summary

Required. Records status, candidate and final revisions, stages, input sources, adapters, decisions, all six artifact hashes, seal history, repair rounds, gate rounds, unverified items, and next action.

## 7. Final gate evidence

Required after the final independent review passes:

- `Final_Gate_Review.md`
- One JSON file for each of R0, G1, O1, U1, QA, and Q1

These are separate deliverables. They do not replace the six primary artifacts and do not alter PRD format.

## Runtime projections

```text
runRoot/01-delivery/.delivery/
├── requirements.json
├── bundle.json
├── findings.json
├── candidate-seal.json
├── final-seal.json
├── candidate-revisions/
├── gate-results/<revision>/
├── gate-result-index.json
└── runs/
```

These are audit files, not user-facing deliverables and not second fact sources.
