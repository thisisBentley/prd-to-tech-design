# External Delivery Artifact Contract v2.3.0

## Purpose

This source lock defines the neutral artifact contract that Delivery must satisfy
before an external review skill is invoked. The contract is deliberately kept in
the open-source core so a private environment can replace the source path with a
company-owned Skill while preserving the same machine-readable profile.

## Review timing

- Artifact structure and metadata are checked before the final seal.
- Candidate artifacts are checked after the candidate seal and before the audit stage.
- A contract violation blocks `AUDIT_READY` and therefore blocks `DESIGN_READY`.

## PRD contract

- The PRD must include document control, functional requirements, acceptance
  criteria, states and permissions, and exception/recovery sections.
- Requirement ID, version and status metadata must be visible.
- Runtime functional requirements must pair configuration-state and runtime-state ACs.

## Overview contract

- The Overview must contain the six review tabs and a source PRD hash.
- The Overview is a projection and may not introduce new business facts.

## Jira contract

- The Jira description must contain background, current state, goals and functional points.
- Every FR in the PRD must be represented in the functional points.

## Prototype contract

- Bound elements must expose `data-ai-id`, `data-ai-fr` and `data-ai-ac`.
- The manifest must include a Prototype hash and an elements array.
- Static screenshots alone are not a Prototype runtime contract.
