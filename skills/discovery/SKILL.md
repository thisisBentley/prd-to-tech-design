---
name: discovery
description: Explore a product idea before PRD creation. Assemble issue context, related work, knowledge, code evidence, optional Git evidence, capability ideas, and product questions into a Requirement Brief and Concept Handoff. Works with manual adapters and does not require external services.
metadata:
  version: 0.1.0
  phase: discovery
  entry: standalone
---

# Discovery

## Purpose

Discovery answers four questions before formal requirement design:

1. What business problem are we solving?
2. What related work or capability evidence exists?
3. Which existing capabilities can plausibly support a solution?
4. Which decisions must the product owner confirm?

Discovery is independent from Delivery. It does not generate PRD, overview, prototype, technical design, test design, or external-system updates.

## Commands

```text
start      Begin or continue discovery
refresh    Refresh available evidence without overwriting confirmed decisions
ask        Only generate product questions
status     Read state and report current progress
handoff    Produce or validate Concept Handoff
```

## Inputs

At least one input is required:

- Requirement text
- Issue/work-item identifier
- Existing PRD or draft
- Prototype or screenshots
- Meeting notes
- Specialist-provided facts

Do not choose among similar candidate objects. Ask the user to identify the authoritative input.

## Runtime layout

```text
runRoot/
└── 00-discovery/
    ├── Requirement_Brief.md
    └── .context/
        ├── context-snapshot.json
        ├── issue-snapshot.json
        ├── related-work.json
        ├── knowledge-evidence.json
        ├── code-evidence.json
        ├── git-evidence.json
        ├── capability-ideation.json
        ├── capability-matrix.json
        ├── product-qa-log.json
        └── source-cache/
```

## Process

### 1. Restate the input

Record actor, trigger, pain, desired outcome, constraints, and non-goals. Do not invent missing business facts.

### 2. Call read adapters

Only through configured adapters:

- Issue tracker
- Knowledge source
- Code intelligence
- Git source

Each unavailable adapter is recorded as unavailable. Absence of evidence is not proof that capability does not exist.

### 3. Collect related work

Search by structured links first, then terms, documents, and code patterns. Record source, match reason, and confidence.

### 4. Run Capability Ideation

Follow `../../core/capability-ideation.md`.

Produce:

- Business problem statement
- Capability demands
- Candidate capabilities
- Solution options
- Open questions

### 5. Build Capability Matrix

For each relevant capability demand, record:

```text
reuse | configure | adapt | rebuild | conflict | unknown | not_applicable
```

Include evidence and limitations.

### 6. Ask product questions

At most five questions per round. Only ask when the answer changes business outcome, scope, rule, permission, data, acceptance, or solution direction.

Record each answer in `product-qa-log.json`. An agent recommendation is not a product decision.

### 7. Produce Requirement Brief

Required sections:

1. Requirement background
2. Requirement goal
3. Functional direction
4. Current-state and related-work evidence
5. Capability-fit assessment
6. Product decisions
7. Unverified items and owners
8. Suggested design scope
9. Concept Handoff

Mark evidence and confidence. Do not expose internal code symbols in the user-facing brief.

## Concept Handoff

Concept Handoff is ready when:

- Background, goal, and functional direction are stable
- Delivery route and target environment are clear
- Available evidence is recorded
- Outcome-changing product decisions are closed
- Unverified items have owners and follow-up timing
- No implementation assertion is presented as a business fact

Write:

```json
{
  "status": "CONCEPT_READY",
  "briefPath": "00-discovery/Requirement_Brief.md",
  "contextSnapshotPath": "00-discovery/.context/context-snapshot.json",
  "capabilityMatrixPath": "00-discovery/.context/capability-matrix.json",
  "openDecisions": []
}
```

## Boundaries

- Read-only by default
- No PRD/overview/prototype generation
- No external writes
- No invented current-state claims
- No requirement decisions without product confirmation
- No assumption that an absent Git source means a variant implementation does not exist
