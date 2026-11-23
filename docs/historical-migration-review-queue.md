# Historical Migration Review Queue

Historical migration planning identifies legacy gaps. It does not decide which
FR owns an ambiguous AC. The review queue turns those gaps into explicit,
hash-bound product-owner decisions while preserving fail-closed behavior.

## Flow

```text
historical migration plan(s)
→ hash verification
→ one queue item per AC and migration action
→ explicit product-owner decision record
→ adjudication result
→ approved mapping evidence or unresolved gap
```

The queue and adjudication tools never edit the source PRD, Overview or
Prototype. They produce sidecar evidence only.

## Build the queue

```bash
python3 scripts/build_historical_migration_review_queue.py \
  --plans-dir outputs/historical-migration-plans-v1 \
  --out outputs/historical-migration-review-queue-v1/review-queue.json
```

Each queue item carries:

- a deterministic `itemId`;
- the source plan path, plan SHA-256 and plan content hash;
- the subject AC, missing section, Prototype binding or Overview metadata gap;
- candidate FR links and their evidence basis;
- the exact known FR set from the source plan;
- required authority (`PRODUCT_OWNER`);
- `m7ExitEvidenceEligible=false` and `trainingEligible=false` at queue level.

## Decision contract

The decision record must bind both `queueId` and the queue file SHA-256. It must
identify an independent product owner and include an attestation. Every item
decision requires a reason and at least one evidence reference.

```json
{
  "schemaVersion": 1,
  "queueId": "HMQ-QUEUE-...",
  "queueSha256": "<sha256 of review-queue.json>",
  "reviewer": {
    "reviewerId": "product-owner-1",
    "role": "PRODUCT_OWNER",
    "independentFromAgent": true,
    "attestation": "I reviewed the cited source evidence and approve these mappings."
  },
  "decisions": [
    {
      "itemId": "HMQ-....-AC-001",
      "decision": "APPROVE_MAPPING",
      "reason": "The table row explicitly names FR-001 and the behavior matches the source.",
      "evidenceRefs": ["prd.md#AC-001"],
      "approvedFrIds": ["FR-001"]
    }
  ],
  "createdAt": "2026-11-23T00:00:00+00:00"
}
```

Allowed decisions:

| Item kind | Decision | Effect |
|---|---|---|
| `FR_AC_ASSOCIATION` | `APPROVE_MAPPING` | Creates an approved AC→FR mapping |
| `FR_AC_ASSOCIATION` | `REJECT_MAPPING` | Records that the proposed association is invalid; remains a migration gap |
| Migration task | `MARK_COMPLETED` | Records task completion with evidence |
| Any item | `DEFER` | Leaves the item explicitly unresolved |

## Apply decisions

```bash
python3 scripts/apply_historical_migration_decisions.py \
  --queue outputs/historical-migration-review-queue-v1/review-queue.json \
  --decisions outputs/historical-migration-review-queue-v1/decisions.json \
  --out outputs/historical-migration-review-queue-v1/adjudication.json
```

The adjudicator rejects:

- an unknown or duplicate item decision;
- a queue hash mismatch;
- a non-product-owner or non-independent reviewer;
- `APPROVE_MAPPING` without `approvedFrIds`;
- approved FR IDs not present in the source migration plan;
- a decision without reason or evidence;
- using `MARK_COMPLETED` on an AC mapping item.

`migrationReadyForPackaging=true` requires every AC mapping approved and every
migration task completed. It still does not make the package M7 Exit evidence.

## Authority boundary

```text
candidate link       ≠ approved mapping
queue generated      ≠ reviewed
adjudication result  ≠ package migration applied
package migration    ≠ M7 Exit PASS
migration evidence   ≠ training approval
```

The queue makes the review tractable and auditable. It does not transfer business
ownership from the product owner to the Agent.
