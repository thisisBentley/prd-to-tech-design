# M3 Failure and Recovery Matrix

M3 is complete only when every failure is deterministic, safely stopped, auditable and recoverable without skipping Review / Repair / Recheck.

| Failure | Required behavior | Evidence |
|---|---|---|
| Decision Readiness `NOT_READY` / `HOLD` | stop before PRD Producer; write decision block evidence; no READY Handoff | `tests/test_delivery_loop.py::test_decision_readiness_hold_blocks_before_prd` |
| Reviewer `RETURNED` | return to PRD Repair; legacy reviews remain evidence but do not override latest Recheck | `tests/test_m3_failures.py::test_reviewer_returned_creates_repair_and_recheck_round` |
| Repair introduces a new blocking root cause | create a new Repair round and Recheck; do not close the package | `tests/test_m3_failures.py::test_reviewer_returned_creates_repair_and_recheck_round` |
| Same root cause remains after Recheck | create an OPEN Escalation; block Gatekeeper and Quality Exit | `tests/test_m3_failures.py::test_repeated_root_cause_creates_escalation_and_blocks_quality_exit` |
| Open Decision Card | block READY; require Research Record and product confirmation | `tests/test_research_first.py::QualityExitResearchTests::test_quality_exit_blocks_open_decision_without_research` |
| Open Escalation | Gatekeeper returns `BLOCKED`; no READY Handoff | `tests/test_m3_failures.py::test_repeated_root_cause_creates_escalation_and_blocks_quality_exit` |
| Invalid structured result | Runtime collect fails closed; Work Plan becomes FAILED | `tests/test_agent_runtime.py::test_invalid_structured_result_fails_closed` |
| Runtime timeout / non-zero exit / cancel | Runtime record and Work Plan remain FAILED/CANCELLED with evidence | `tests/test_agent_runtime.py::test_timeout_writes_failed_audit_record`, `tests/test_agent_runtime.py::test_collect_failure_and_cancel_are_auditable` |
| Interrupted main loop | audit persisted plan/runtime; recover a complete runtime result or mark the task rerunnable | `tests/test_m3_recovery.py` |
| Corrupted successful evidence | recovery audit blocks continuation instead of skipping the task | `tests/test_m3_recovery.py::test_loop_refuses_to_continue_when_recovery_audit_blocks` |
| Runtime vs Work Plan mismatch | cross-plane validator blocks Quality Exit | `tests/test_m3_state_consistency.py::test_runtime_task_status_mismatch_blocks` |
| ReviewGroup stale aggregate | cross-plane validator recomputes and blocks on mismatch | `tests/test_m3_state_consistency.py::test_stale_review_group_blocks` |
| Natural-language Gatekeeper override | no override API; deterministic gate remains authoritative | `tests/test_m3_failures.py::test_repeated_root_cause_creates_escalation_and_blocks_quality_exit` |

## Recovery rules

```text
RUNNING + complete Runtime Result -> recover SUCCEEDED
RUNNING + missing/corrupt evidence -> mark rerunnable FAILED
SUCCEEDED + missing result/runtime -> recovery BLOCKED
Dependency not SUCCEEDED -> recovery BLOCKED
```

The loop writes `.agents/recovery/latest.json` before resuming. A blocked recovery report stops the loop with `RECOVERY_BLOCKED`.
