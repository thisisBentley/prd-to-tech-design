# Agent Workflow State Machine

```text
DISCOVERY_AUTHORING
→ DELIVERY_INTAKE_REVIEW
   ├─ RETURNED → DISCOVERY_AUTHORING
   └─ ACCEPTED → DELIVERY_AUTHORING
→ DELIVERY_SEALED
→ DELIVERY_REVIEW
   ├─ RETURNED → DELIVERY_AUTHORING
   └─ ACCEPTED → TECH_PRD_DIAGNOSIS
→ TECH_PRD_DIAGNOSIS
   ├─ RETURNED → DELIVERY_AUTHORING
   └─ ACCEPTED → TECH_AUTHORING
→ TECH_SEALED
→ TECH_REVIEW
   ├─ RETURNED → TECH_AUTHORING
   └─ ACCEPTED → PRODUCT_ACCEPTANCE_REVIEW
→ PRODUCT_ACCEPTANCE_REVIEW
   ├─ RETURNED → TECH_AUTHORING
   └─ ACCEPTED → FINAL_GATEKEEPER
→ READY
```

Any required review can also produce:

```text
BLOCKED_DECISION
INCOMPLETE
ESCALATED
FAILED
```

## Transition rules

- A handoff must be registered and hash-valid before review.
- A required review must exist for the latest target revision.
- Every reviewer must differ from the producer.
- Any blocking finding blocks acceptance.
- Any `INCOMPLETE` review blocks progression.
- The Gatekeeper verifies the complete review chain before `READY`.
- A producer cannot advance state or finalize the workflow on its own.
