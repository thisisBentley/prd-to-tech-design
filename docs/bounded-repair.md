# M7.6-D Bounded Repair Controller — Shadow Mode

The Bounded Repair Controller turns a validated Change Set batch and per-round
evidence into a deterministic terminal state. It is intentionally shadow-only:
it can prepare a human submission, but it cannot submit, close an external gate or
mark a delivery complete.

## State machine

```text
OBSERVE
→ PLAN_CHANGE_SET
→ APPLY_SCOPED_PATCH
→ REBUILD
→ INDEPENDENT_VERIFY
   ├─ PASS + all Change Sets closed → READY_FOR_HUMAN_SUBMISSION
   ├─ IMPROVING + rounds remain    → NEXT_ROUND_READY
   ├─ NO_IMPROVEMENT               → STALLED
   ├─ REGRESSED                    → REGRESSED
   └─ BLOCKED                      → BLOCKED

round limit exhausted → MAX_ROUNDS_REACHED
```

## Required round evidence

```text
roundId / roundIndex / revision
changeSetIds
patch status + before/after hash + changed artifacts
rebuild status + evidence refs
independent verifier identity and context
openBlocking / closedFindings / newBlockingFindings
openRootCauseIds
baseline and current weighted score
external gate status
businessRevisionCreated
```

The controller itself computes scope compliance, independence and stop conditions;
these are not accepted as producer self-assertions.

## Commands

```bash
python3 scripts/evaluate_bounded_repair.py \
  --change-set-batch change-set-batch.json \
  --policy config/trust-kernel/bounded-repair-policy-v1.json \
  --round round-1.json \
  --out bounded-repair-run.json
```

Loop the command with the next round evidence only when the previous output is
`NEXT_ROUND_REQUIRED`. The policy hard limit is two rounds.

## Stop conditions

```text
patch fails                                  → BLOCKED
changed artifact outside Change Set scope    → BLOCKED
rebuild fails                                → BLOCKED
producer verifies its own output             → BLOCKED
non-business Change Set creates a business revision → BLOCKED
external gate is FAIL / ENVIRONMENT_BLOCKED  → BLOCKED
new blocking findings or score regression    → REGRESSED
same root cause open in consecutive rounds   → STALLED
no score / finding / blocking improvement   → STALLED
round limit reached without PASS             → MAX_ROUNDS_REACHED
```

## Hard boundary

`READY_FOR_HUMAN_SUBMISSION` is not `CLOSED`. The controller always emits:

```text
closureEligible=false
externalSubmissionAllowed=false
```

External QA/G1 and the Submission Contract remain the authority for closure. Real
shadow-mode closure requires at least two real projects; fixtures are engineering
evidence only.
