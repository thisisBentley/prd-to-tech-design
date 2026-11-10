# PRD_DELIVERY

## Requirement Summary
Expense submission flow.

## Functional Requirements
- FR-001: User submits an expense request.

## Acceptance Criteria
- AC-001: Expense submission is verified for FR-001.

## Permissions
- submitter ALLOWED submit expense

## States
- draft: reachable from expense form with precondition defined

## Exceptions and Recovery
- validation failure keeps draft state and shows the field error

## Non-Goals
- No approval workflow.
