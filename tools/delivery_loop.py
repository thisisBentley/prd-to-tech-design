#!/usr/bin/env python3
"""Minimal autonomous PRD_ONLY Delivery execution loop."""
from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import sys
from pathlib import Path
from typing import Any

from agent_runtime import load, now, save, sha256
from agent_task_factory import build_agent_task
from orchestrate import sync_delivery_task_from_runtime

EXECUTION_ORDER = [
    "DECISION-READINESS",
    "PRD-PRODUCE",
    "DELIVERY-REVIEW",
    "QA-RED-TEAM",
    "TECH-PRD-DIAGNOSIS",
    "SEMANTIC-CONSISTENCY-REVIEW",
    "FINDING-CONSOLIDATE",
]
BASE_REVIEW_TASKS = ["DELIVERY-REVIEW", "QA-RED-TEAM", "TECH-PRD-DIAGNOSIS", "SEMANTIC-CONSISTENCY-REVIEW"]
RECHECK_PREFIX = "RECHECK-"
REPAIR_PREFIX = "PRD-REPAIR-"


def task_by_id(plan: dict[str, Any], task_id: str) -> dict[str, Any] | None:
    return next((item for item in plan.get("tasks", []) if item.get("taskId") == task_id), None)


def ready_tasks(plan: dict[str, Any], candidates: list[str]) -> list[str]:
    tasks = {item["taskId"]: item for item in plan.get("tasks", [])}
    result: list[str] = []
    for task_id in candidates:
        task = tasks.get(task_id)
        if not task or task.get("status") not in {"PENDING", "READY", "RUNNING", "FAILED"}:
            continue
        if task.get("required", True) is False:
            continue
        if all(tasks.get(dep, {}).get("status") == "SUCCEEDED" for dep in task.get("dependencies", [])):
            result.append(task_id)
    return result


def ordered_candidates(plan: dict[str, Any]) -> list[str]:
    tasks = plan.get("tasks", [])
    repairs = [item["taskId"] for item in tasks if item["taskId"].startswith(REPAIR_PREFIX)]
    rechecks = [item["taskId"] for item in tasks if item["taskId"].startswith(RECHECK_PREFIX)]
    tails = [task_id for task_id in ["FINAL-PACKAGE-REVIEW", "DELIVERY-GATEKEEPER", "DELIVERY-QUALITY-EXIT", "DELIVERY-HANDOFF"]]
    return ready_tasks(plan, EXECUTION_ORDER) + ready_tasks(plan, repairs) + ready_tasks(plan, rechecks) + ready_tasks(plan, tails)


def append_task(plan_path: Path, plan: dict[str, Any], task: dict[str, Any]) -> None:
    if task_by_id(plan, task["taskId"]) is None:
        plan.setdefault("tasks", []).append(task)
        plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def make_task(task_id: str, role: str, kind: str, dependencies: list[str], outputs: list[str], write_scope: list[str], **extra: Any) -> dict[str, Any]:
    result = {
        "taskId": task_id,
        "role": role,
        "kind": kind,
        "dependencies": dependencies,
        "readScope": [".agents/**", "01-delivery/**", "requirement.md"],
        "writeScope": write_scope,
        "expectedOutputs": outputs,
        "required": True,
        "status": "PENDING",
    }
    result.update(extra)
    return result


def ensure_recheck_tasks(plan_path: Path, plan: dict[str, Any]) -> list[str]:
    repair_ids = [item["taskId"] for item in plan.get("tasks", []) if item["taskId"].startswith(REPAIR_PREFIX)]
    if not repair_ids or any(task_by_id(plan, task_id)["status"] != "SUCCEEDED" for task_id in repair_ids):
        return []
    roles = {
        "RECHECK-DELIVERY-REVIEW": "delivery-reviewer",
        "RECHECK-QA-RED-TEAM": "qa-red-team",
        "RECHECK-TECH-PRD-DIAGNOSIS": "tech-prd-diagnostician",
        "RECHECK-SEMANTIC-CONSISTENCY": "semantic-consistency-reviewer",
    }
    for task_id, role in roles.items():
        append_task(plan_path, plan, make_task(
            task_id,
            role,
            "reviewer",
            repair_ids,
            [f"{role} recheck result"],
            [".agents/reviews"],
            recheckFor="requirement-blocking-marker",
        ))
    return [task_id for task_id in roles if task_by_id(plan, task_id) is not None]


def ensure_tail_tasks(plan_path: Path, plan: dict[str, Any]) -> bool:
    base_statuses = [task_by_id(plan, task_id) for task_id in BASE_REVIEW_TASKS]
    finding = task_by_id(plan, "FINDING-CONSOLIDATE")
    repairs = [item for item in plan.get("tasks", []) if item["taskId"].startswith(REPAIR_PREFIX)]
    rechecks = [item for item in plan.get("tasks", []) if item["taskId"].startswith(RECHECK_PREFIX)]
    if any(item is None or item.get("status") != "SUCCEEDED" for item in base_statuses + [finding]):
        return False
    if any(item.get("status") != "SUCCEEDED" for item in repairs + rechecks):
        return False
    closure_dependencies = BASE_REVIEW_TASKS + ["FINDING-CONSOLIDATE"] + [item["taskId"] for item in repairs] + [item["taskId"] for item in rechecks]
    append_task(plan_path, plan, make_task(
        "FINAL-PACKAGE-REVIEW",
        "final-package-reviewer",
        "reviewer",
        closure_dependencies,
        ["Final Package Review Result"],
        [".agents/reviews"],
    ))
    append_task(plan_path, plan, make_task(
        "DELIVERY-GATEKEEPER",
        "deterministic-gatekeeper",
        "gatekeeper",
        ["FINAL-PACKAGE-REVIEW", "FINDING-CONSOLIDATE"] + [item["taskId"] for item in repairs] + [item["taskId"] for item in rechecks],
        ["Delivery Gatekeeper Result"],
        [".agents/reviews"],
    ))
    append_task(plan_path, plan, make_task(
        "DELIVERY-QUALITY-EXIT",
        "deterministic-gatekeeper",
        "quality-gate",
        ["DELIVERY-GATEKEEPER"],
        ["Delivery Quality Exit Result"],
        [".agents/reviews"],
    ))
    append_task(plan_path, plan, make_task(
        "DELIVERY-HANDOFF",
        "prd-producer",
        "producer",
        ["DELIVERY-QUALITY-EXIT"],
        ["Delivery Handoff"],
        [".agents/handoffs"],
    ))
    return True


def ensure_escalations(run_root: Path, plan: dict[str, Any]) -> list[str]:
    """Open an escalation when a repaired root cause remains blocking after recheck."""
    rechecks = [item for item in plan.get("tasks", []) if item.get("taskId", "").startswith(RECHECK_PREFIX) and item.get("status") == "SUCCEEDED"]
    if not rechecks:
        return []
    escalations: list[str] = []
    root_causes: dict[str, list[tuple[dict[str, Any], Path]]] = {}
    for task in rechecks:
        result_path = task.get("resultPath")
        if not result_path:
            continue
        path = Path(result_path)
        if not path.exists():
            continue
        try:
            result = load(path)
        except Exception:
            continue
        for finding in result.get("findings", []) or []:
            if finding.get("severity") == "BLOCKING":
                root = str(finding.get("rootCauseId", finding.get("findingId", "UNKNOWN")))
                root_causes.setdefault(root, []).append((finding, path))
    for root, records in root_causes.items():
        escalation_dir = run_root / ".agents" / "escalations"
        escalation_dir.mkdir(parents=True, exist_ok=True)
        path = escalation_dir / f"{root}.json"
        if path.exists():
            escalations.append(str(path))
            continue
        finding, evidence_path = records[0]
        payload = {
            "schemaVersion": 1,
            "escalationId": f"ESC-{root}",
            "workflowId": plan.get("workflowId", ""),
            "fromRoles": ["semantic-consistency-reviewer", "prd-repair-agent"],
            "issue": f"Root cause {root} remains BLOCKING after reviewer recheck.",
            "evidenceRefs": [str(evidence_path.resolve())] + [str(p.resolve()) for _, p in records],
            "attemptedRounds": max(2, len(records)),
            "requestedDecision": finding.get("closeCondition", "Resolve the repeated root cause or confirm escalation disposition."),
            "status": "OPEN",
            "createdAt": now(),
            "rootCauseId": root,
        }
        save(path, payload)
        escalations.append(str(path))
    return escalations


def ensure_work_plan(run_root: Path, plan_path: Path) -> Path:
    """Build the Delivery Work Plan from frozen Intake state when absent."""
    if plan_path.exists():
        return plan_path
    state_path = run_root / ".agents" / "orchestration.json"
    if not state_path.exists():
        raise FileNotFoundError(f"Delivery Intake state not found: {state_path}")
    from build_delivery_plan import build
    state = load(state_path)
    plan = build(state, "r1")
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    save(plan_path, plan)
    return plan_path


def execute_task(
    run_root: Path,
    plan_path: Path,
    task_id: str,
    requirement_path: Path,
    runtime: str,
    worker_path: Path,
    timeout: float,
    bypass_inner_sandbox: bool = False,
) -> dict[str, Any]:
    root = run_root.resolve()
    factory = build_agent_task(root, plan_path, task_id, requirement_path, runtime=runtime, timeout_seconds=timeout)
    task_path = factory["taskPath"]
    task = load(task_path)
    execution_id = secrets.token_hex(6)
    result_path = root / ".agents" / "results" / f"{task_id}.result.json"
    artifact_path = root / ".agents" / "artifacts" / "PRD_DELIVERY.md"
    review_path = root / ".agents" / "reviews" / f"{task_id}.review.json"
    transcript_path = root / ".agents" / "runtime" / "transcripts" / f"{task_id}-{execution_id}.log"
    result_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    review_path.parent.mkdir(parents=True, exist_ok=True)
    transcript_path.parent.mkdir(parents=True, exist_ok=True)
    context_id = f"context-{task['role']}-{execution_id}"
    env = os.environ.copy()
    if bypass_inner_sandbox:
        env["AI_NATIVE_SEMANTIC_BYPASS_INNER_SANDBOX"] = "1"
    env.update({
        "AI_NATIVE_TASK_ID": task_id,
        "AI_NATIVE_WORKFLOW_ID": task["workflowId"],
        "AI_NATIVE_ROLE": task["role"],
        "AI_NATIVE_CONTEXT_ID": context_id,
        "AI_NATIVE_RUN_ROOT": str(root),
        "AI_NATIVE_TASK_MANIFEST": str(task_path),
        "AI_NATIVE_RESULT_PATH": str(result_path),
        "AI_NATIVE_ARTIFACT_PATH": str(artifact_path),
        "AI_NATIVE_REVIEW_PATH": str(review_path),
        "AI_NATIVE_TARGET_REVISION": str(task.get("revision", "r1")),
        "AI_NATIVE_TRANSCRIPT_PATH": str(transcript_path),
        "AI_NATIVE_TIMEOUT": str(max(1.0, timeout - 5.0)),
    })
    record_path = root / ".agents" / "runtime" / f"{task_id}.json"
    record = {
        "schemaVersion": 1,
        "taskId": task_id,
        "workflowId": task["workflowId"],
        "agentId": f"agent-{task['role']}-{execution_id}",
        "contextId": context_id,
        "runtime": runtime,
        "status": "RUNNING",
        "taskManifest": str(task_path.resolve()),
        "taskManifestSha256": sha256(task_path),
        "createdAt": now(),
        "updatedAt": now(),
        "startedAt": now(),
    }
    save(record_path, record)
    sync = sync_delivery_task_from_runtime(root, plan_path, task_id, record_path)
    if sync.get("status") == "FAIL":
        return {"status": "FAIL", "errors": sync.get("errors", []), "taskId": task_id}
    try:
        process = subprocess.run([sys.executable, str(worker_path)], cwd=root, env=env, text=True, capture_output=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        record["status"] = "FAILED"
        record["error"] = f"timeout after {timeout}s"
        record["finishedAt"] = now()
        record["updatedAt"] = record["finishedAt"]
        record["transcriptPath"] = str(transcript_path)
        save(record_path, record)
        sync = sync_delivery_task_from_runtime(root, plan_path, task_id, record_path)
        return {"status": "FAILED", "taskId": task_id, "errors": [record["error"]], "taskSync": sync}
    transcript_path.write_text(process.stdout + process.stderr, encoding="utf-8")
    record["transcriptPath"] = str(transcript_path)
    if process.returncode != 0:
        record["status"] = "FAILED"
        record["error"] = f"worker exited with code {process.returncode}"
        record["exitCode"] = process.returncode
        record["finishedAt"] = now()
        record["updatedAt"] = record["finishedAt"]
        save(record_path, record)
        sync = sync_delivery_task_from_runtime(root, plan_path, task_id, record_path)
        return {"status": "FAILED", "taskId": task_id, "errors": [record["error"]], "taskSync": sync}
    try:
        result = load(result_path)
    except (OSError, json.JSONDecodeError) as exc:
        record["status"] = "FAILED"
        record["error"] = f"invalid worker result: {exc}"
        record["finishedAt"] = now()
        record["updatedAt"] = record["finishedAt"]
        save(record_path, record)
        sync = sync_delivery_task_from_runtime(root, plan_path, task_id, record_path)
        return {"status": "FAILED", "taskId": task_id, "errors": [record["error"]], "taskSync": sync}
    valid = isinstance(result, dict) and result.get("schemaVersion") == 1 and result.get("status") and isinstance(result.get("outputs"), list) and result["outputs"]
    if not valid:
        record["status"] = "FAILED"
        record["error"] = "worker returned an invalid structured result"
        record["finishedAt"] = now()
        record["updatedAt"] = record["finishedAt"]
        save(record_path, record)
        sync = sync_delivery_task_from_runtime(root, plan_path, task_id, record_path)
        return {"status": "FAILED", "taskId": task_id, "errors": [record["error"]], "taskSync": sync}
    record["status"] = "SUCCEEDED"
    record["structuredResultPath"] = str(result_path.resolve())
    record["structuredResultSha256"] = sha256(result_path)
    record["exitCode"] = 0
    record["finishedAt"] = now()
    record["updatedAt"] = record["finishedAt"]
    save(record_path, record)
    sync = sync_delivery_task_from_runtime(root, plan_path, task_id, record_path)
    payload = {
        "status": record["status"],
        "taskId": task_id,
        "record": str(record_path),
        "result": str(result_path),
        "taskSync": sync,
    }
    for key in ("reviewResultPath", "handoffPath", "prdArtifactPath", "repairedArtifactPath", "verdict"):
        if key in result:
            payload[key] = result[key]
    return payload


def reconcile_reviews(root: Path, plan_path: Path) -> dict[str, Any]:
    from reconcile_delivery import reconcile
    result = reconcile(root.resolve(), plan_path.resolve())
    if result.get("status") == "PASS" and result.get("batchStatus") == "READY_FOR_REPAIR":
        batch = load(Path(result["repairBatch"]))
        plan = load(plan_path)
        existing = {item["taskId"] for item in plan.get("tasks", [])}
        repair_dependencies = BASE_REVIEW_TASKS + ["FINDING-CONSOLIDATE"]
        for index, group in enumerate(batch.get("groups", []), start=1):
            task_id = f"{REPAIR_PREFIX}{index:02d}"
            if task_id in existing:
                continue
            append_task(plan_path, plan, make_task(
                task_id,
                "prd-repair-agent",
                "repair",
                repair_dependencies,
                [f"Repair {group.get('rootCauseId', index)}"],
                ["01-delivery/*_PRD_DELIVERY.md", ".agents/artifacts"],
                repairClass=group.get("repairClass", "UNKNOWN"),
                rootCauseId=group.get("rootCauseId", f"ROOT-{index}"),
                sourceBatch=str(Path(result["repairBatch"]).resolve()),
            ))
        result["repairTasksCreated"] = sum(1 for item in plan.get("tasks", []) if item["taskId"].startswith(REPAIR_PREFIX))
    return result


def block_decision_readiness(root: Path, plan_path: Path, result_path: Path) -> dict[str, Any]:
    plan = load(plan_path)
    task = task_by_id(plan, "DECISION-READINESS")
    context = load(result_path)
    reason = {
        "status": "BLOCKED",
        "taskId": "DECISION-READINESS",
        "readiness": context.get("readiness"),
        "decision": context.get("decision"),
        "blockingConditions": context.get("blockingConditions", []),
        "requiredDecisions": context.get("requiredDecisions", []),
        "evidenceRefs": context.get("evidenceRefs", []),
        "closeCondition": "Decision Readiness must be READY with decision=PROCEED before PRD production.",
    }
    block_path = root / ".agents" / "decisions" / "decision-readiness-block.json"
    save(block_path, reason)
    if task is not None:
        task["status"] = "FAILED"
        task["error"] = "Decision Readiness is not READY; Delivery is blocked before PRD production."
        task["failureClass"] = "DECISION_READINESS"
        task["decisionBlockPath"] = str(block_path)
        task["completedAt"] = now()
        save(plan_path, plan)
    return {"status": "DECISION_BLOCKED", "taskId": "DECISION-READINESS", "decisionBlockPath": str(block_path), "reason": reason}


def loop(args: argparse.Namespace) -> dict[str, Any]:
    root = args.run_root.resolve()
    plan_path = (args.plan or (root / ".agents" / "delivery-work-plan.json")).resolve()
    ensure_work_plan(root, plan_path)
    requirement_path = args.requirement.resolve()
    worker_path = args.worker.resolve()
    research_capabilities_path = root / ".agents" / "context" / "research-capabilities.json"
    research_capabilities_result = None
    if args.research_capabilities == "auto" and args.runtime == "codex" and not research_capabilities_path.exists():
        detector = Path(__file__).resolve().parent / "detect_research_capabilities.py"
        detection = subprocess.run([sys.executable, str(detector), "--cwd", str(root), "--out", str(research_capabilities_path)], text=True, capture_output=True, check=False)
        research_capabilities_result = {"returnCode": detection.returncode, "stdout": detection.stdout, "stderr": detection.stderr}
        if detection.returncode != 0:
            return {"status": "RESEARCH_CAPABILITY_ERROR", "completed": [], "failed": [{"taskId": "RESEARCH-CAPABILITY-DETECT", "error": detection.stderr or detection.stdout}], "researchCapabilitiesPath": str(research_capabilities_path)}
    deterministic_worker_path = Path(__file__).resolve().parent / "deterministic_worker.py"
    completed: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    attempts: dict[str, int] = {}
    failure_retries = 0 if args.runtime != "codex" else args.failure_retries
    for _ in range(args.max_tasks):
        plan = load(plan_path)
        candidates = ordered_candidates(plan)
        if not candidates:
            ensure_recheck_tasks(plan_path, plan)
            plan = load(plan_path)
            candidates = ordered_candidates(plan)
        if not candidates:
            ensure_escalations(root, plan)
            ensure_tail_tasks(plan_path, plan)
            plan = load(plan_path)
            candidates = ordered_candidates(plan)
        if not candidates:
            break
        task_id = candidates[0]
        attempts[task_id] = attempts.get(task_id, 0) + 1
        deterministic_task = task_id in {"DELIVERY-GATEKEEPER", "DELIVERY-QUALITY-EXIT", "DELIVERY-HANDOFF"}
        effective_worker = deterministic_worker_path if deterministic_task else worker_path
        result = execute_task(
            root, plan_path, task_id, requirement_path,
            "noop" if deterministic_task else args.runtime,
            effective_worker, args.timeout,
            bypass_inner_sandbox=args.bypass_inner_sandbox,
        )
        completed.append(result)
        if task_id == "DECISION-READINESS" and result.get("status") == "SUCCEEDED":
            decision_result = Path(result["result"])
            decision = load(decision_result)
            if decision.get("readiness") != "READY" or decision.get("decision") != "PROCEED":
                blocked = block_decision_readiness(root, plan_path, decision_result)
                failed.append(blocked)
                return {"status": "DECISION_BLOCKED", "completed": completed, "failed": failed, "stoppedAt": task_id, "decisionBlockPath": blocked["decisionBlockPath"]}
        if result.get("status") != "SUCCEEDED":
            failed.append({
                "taskId": task_id,
                "attempts": attempts.get(task_id, 0),
                "error": result.get("errors", [result.get("error", "task failed")]),
            })
            if attempts.get(task_id, 0) >= failure_retries:
                return {"status": "FAILED", "completed": completed, "failed": failed, "stoppedAt": task_id}
            continue
        if task_id == "TECH-PRD-DIAGNOSIS":
            completed.append(reconcile_reviews(root, plan_path))
        plan = load(plan_path)
        ensure_recheck_tasks(plan_path, plan)
        plan = load(plan_path)
        ensure_escalations(root, plan)
        ensure_tail_tasks(plan_path, plan)
    final_plan = load(plan_path)
    statuses = {item["taskId"]: item.get("status") for item in final_plan.get("tasks", [])}
    if statuses.get("DELIVERY-HANDOFF") == "SUCCEEDED" and statuses.get("DELIVERY-GATEKEEPER") == "SUCCEEDED":
        loop_status = "M1_CONTRACT_COMPLETE"
    elif any(statuses.get(task_id) == "FAILED" for task_id in statuses):
        loop_status = "FAILED_SAFE"
    elif any(task_id.startswith(REPAIR_PREFIX) and status == "PENDING" for task_id, status in statuses.items()):
        loop_status = "REPAIR_READY"
    else:
        loop_status = "INCOMPLETE"
    result = {"status": loop_status, "completed": completed, "failed": failed, "plan": str(plan_path)}
    if research_capabilities_result is not None:
        result["researchCapabilities"] = research_capabilities_result
        result["researchCapabilitiesPath"] = str(research_capabilities_path)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--requirement", type=Path, required=True)
    parser.add_argument("--runtime", choices=["noop", "process", "codex"], default="noop")
    parser.add_argument("--worker", type=Path, default=Path(__file__).resolve().parent / "deterministic_worker.py")
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--max-tasks", type=int, default=20)
    parser.add_argument("--failure-retries", type=int, default=0)
    parser.add_argument("--bypass-inner-sandbox", action="store_true")
    parser.add_argument("--research-capabilities", choices=["auto", "off"], default="auto")
    args = parser.parse_args()
    result = loop(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") in {"M1_CONTRACT_COMPLETE", "INCOMPLETE", "REPAIR_READY"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
