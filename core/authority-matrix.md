# Authority Matrix

Authority is separated by responsibility, not by agent count.

| Role | May author | May review | May modify upstream | May approve final |
|---|---|---|---|---|
| Discovery Producer | Discovery artifacts | No | No | No |
| Delivery Intake Reviewer | Review records | Discovery sufficiency | No | No |
| Delivery Producer | Delivery candidates | No | No | No |
| Delivery Reviewer | Review records | PRD, Overview, Prototype | No | No |
| QA Red Team | Review records | Boundary, exception, permission and AC behavior | No | No |
| Tech PRD Diagnostician | Review records | PRD technical completeness | No | No |
| Tech Producer | Tech solution and architecture | No | No | No |
| Tech Reviewer | Review records | T1, R1, BA1, TA1, AX1 | No | No |
| Product Acceptance Reviewer | Review records | Requirement inheritance and product acceptance | No | No |
| Orchestrator | Tasks and state transitions | Contract validation only | No | No |
| Deterministic Gatekeeper | Gate result | Evidence, hashes, schemas and state | No | Yes |
| Human Decision Owner | Decision cards and decisions | Value/risk/irreversible choices | Through producer | No |

## Review boundary

- A consumer review asks: **“Is the upstream artifact sufficient for me to safely do my job?”**
- An independent review asks: **“What is wrong or unverifiable in this artifact?”**
- A product-acceptance review asks: **“Does the technical solution faithfully implement the product contract?”**
- The Gatekeeper asks: **“Can this claim be mechanically proven from frozen evidence?”**

## Forbidden authority combinations

- Producer and final reviewer in the same execution context.
- Reviewer modifying the artifact it reviews.
- Orchestrator overriding a failed review or Gatekeeper result.
- Human approving a mechanical gate that has no evidence.
- Any role marking `INCOMPLETE` as `PASS`.

## Artifact domain authority

| Domain | Authoritative artifact | Allowed projection | Conflict action |
|---|---|---|---|
| Business | PRD | Prototype bindings, Overview, Jira description | `RESYNC_REQUIRED` and reconciliation |
| Interaction | Prototype | Overview interaction projection | `RESYNC_REQUIRED` and paired repair |
| Projection | Overview | Review-only | Regenerate from current SYNCED Pair |
| Capability identity | Capability Context | PRD terminology and source references | Decision or Escalation when unresolved |
| Evidence | Source Provenance | All downstream evidence refs | Block when missing or hash-mismatched |

PRD and Prototype are equal only within their respective domains. No producer may silently rewrite the other domain.
