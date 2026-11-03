# Artifact Contract

Delivery produces six primary artifacts in this order:

```text
runRoot/01-delivery/
├── Issue_Description.md
├── Overview.html
├── PRD_DELIVERY.md
├── Prototype.html       # optional
├── Gates.md
└── Workflow.md
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

Required. Human-readable summary of gate results, findings, owners, unverified items, and rerun scope.

## 6. Workflow summary

Required. Records status, stages, input sources, adapters, decisions, artifact hashes, repairs, unverified items, and next action.

## Runtime projections

```text
runRoot/01-delivery/.delivery/
├── requirements.json
├── bundle.json
├── findings.json
├── gate-results/
└── runs/
```

These are audit files, not user-facing deliverables and not second fact sources.
