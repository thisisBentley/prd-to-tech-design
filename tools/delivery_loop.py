#!/usr/bin/env python3
"""Minimal PRD_ONLY Delivery execution loop."""
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
    "FINDING-CONSOLIDATE",
]


def ready_tasks(plan: dict[str, Any], execution_order: list[str] | None = None) -> list[str]:
    tasks = {item["taskId"]: item for item in plan.get("tasks", [])}
    candidates = execution_order or [item["taskId"] for item in plan.get("tasks", [])]
    result = []
    for task_id in candidates:
        task = tasks.get(task_id)
        if not task or task.get("status") not in {"PENDING", "READY", "RUNNING", "FAILED"}:
            continue
        if task.get("required", True) is False:
            continue
        if all(tasks.get(dep, {}).get("status") == "SUCCEEDED" for dep in task.get("dependencies", [])):
            result.append(task_id)
    return result

def execute_task(
    run_root: Path,
    plan_path: Path,
    task_id: str,
    requirement_path: Path,
    runtime: str,
    worker_path: Path,
    timeout: float,
) -> dict[str, Any]:
    root = run_root.resolve()
    factory = build_agent_task(root, plan_path, task_id, requirement_path, runtime=runtime, timeout_seconds=timeout)
    task_path = factory["taskPath"]
    task = load(task_path)
    result_path = root / ".agents" / "results" / f"{task_id}.result.json"
    transcript_path = root / ".agents" / "runtime" / "transcripts" / f"{task_id}.log"
    result_path.parent.mkdir(parents=True, exist_ok=True)
    transcript_path.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update({
        "AI_NATIVE_TASK_ID": task_id,
        "AI_NATIVE_WORKFLOW_ID": task["workflowId"],
        "AI_NATIVE_ROLE": task["role"],
        "AI_NATIVE_CONTEXT_ID": f"context-{task['role']}-deterministic",
        "AI_NATIVE_RUN_ROOT": str(root),
        "AI_NATIVE_TASK_MANIFEST": str(task_path),
        "AI_NATIVE_RESULT_PATH": str(result_path),
        "AI_NATIVE_TRANSCRIPT_PATH": str(transcript_path),
    })
    argv = [
        sys.executable,
        str(worker_path),
    ]
    record_path = root / ".agents" / "runtime" / f"{task_id}.json"
    record = {
        "schemaVersion": 1,
        "taskId": task_id,
        "workflowId": task["workflowId"],
        "agentId": "agent-deterministic-" + secrets.token_hex(4),
        "contextId": f"context-{task['role']}-deterministic",
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
    process = subprocess.run(argv, cwd=root, env=env, text=True, capture_output=True, timeout=timeout, check=False)
    transcript_path.write_text(process.stdout + process.stderr, encoding="utf-8")
    if process.returncode != 0:
        record["status"] = "FAILED"
        record["error"] = f"worker exited with code {process.returncode}"
        record["finishedAt"] = now()
        record["updatedAt"] = record["finishedAt"]
        record["transcriptPath"] = str(transcript_path)
        record["exitCode"] = process.returncode
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
        record["transcriptPath"] = str(transcript_path)
        save(record_path, record)
        sync = sync_delivery_task_from_runtime(root, plan_path, task_id, record_path)
        return {"status": "FAILED", "taskId": task_id, "errors": [record["error"]], "taskSync": sync}
    valid = isinstance(result, dict) and result.get("schemaVersion") == 1 and result.get("status") and isinstance(result.get("outputs"), list) and result["outputs"]
    if not valid:
        record["status"] = "FAILED"
        record["error"] = "worker returned an invalid structured result"
        record["finishedAt"] = now()
        record["updatedAt"] = record["finishedAt"]
        record["transcriptPath"] = str(transcript_path)
        save(record_path, record)
        sync = sync_delivery_task_from_runtime(root, plan_path, task_id, record_path)
        return {"status": "FAILED", "taskId": task_id, "errors": [record["error"]], "taskSync": sync}
    record["status"] = "SUCCEEDED"
    record["structuredResultPath"] = str(result_path.resolve())
    record["structuredResultSha256"] = sha256(result_path)
    record["exitCode"] = 0
    record["finishedAt"] = now()
    record["updatedAt"] = record["finishedAt"]
    record["transcriptPath"] = str(transcript_path)
    save(record_path, record)
    sync = sync_delivery_task_from_runtime(root, plan_path, task_id, record_path)
    return {
        "status": record["status"],
        "taskId": task_id,
        "record": str(record_path),
        "result": str(result_path),
        "taskSync": sync,
    }


def reconcile_reviews(root: Path, plan_path: Path) -> dict[str, Any]:
    from reconcile_delivery import reconcile
    result = reconcile(root.resolve(), plan_path.resolve())
    if result.get("status") == "PASS" and result.get("batchStatus") == "READY_FOR_REPAIR":
        batch_path = Path(result["repairBatch"])
        batch = load(batch_path)
        plan = load(plan_path)
        tasks = plan.get("tasks", [])
        task_ids = {item["taskId"] for item in tasks}
        repair_tasks = []
        for index, group in enumerate(batch.get("groups", []), start=1):
            repair_task_id = f"PRD-REPAIR-{index:02d}"
            if repair_task_id in task_ids:
                continue
            repair_tasks.append({
                "taskId": repair_task_id,
                "role": "prd-repair-agent",
                "kind": "repair",
                "dependencies": ["DELIVERY-REVIEW", "QA-RED-TEAM", "TECH-PRD-DIAGNOSIS", "FINDING-CONSOLIDATE"],
                "readScope": group.get("evidenceRefs", []),
                "writeScope": ["01-delivery/*_PRD_DELIVERY.md"],
                "expectedOutputs": [f"Repair {group.get('rootCauseId', index)}"],
                "required": True,
                "status": "PENDING",
                "repairClass": group.get("repairClass", "UNKNOWN"),
                "rootCauseId": group.get("rootCauseId", f"ROOT-{index}"),
            })
        if repair_tasks:
            tasks.extend(repair_tasks)
            plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        result["repairTasksCreated"] = len(repair_tasks)
    return result


def loop(args: argparse.Namespace) -> dict[str, Any]:
    root = args.run_root.resolve()
    plan_path = args.plan.resolve()
    requirement_path = args.requirement.resolve()
    worker_path = args.worker.resolve()
    completed: list[dict[str, Any]] = []
    for _ in range(args.max_tasks):
        plan = load(plan_path)
        candidates = ready_tasks(plan, EXECUTION_ORDER) + ready_tasks(plan, [
            item["taskId"] for item in plan.get("tasks", []) if item["taskId"].startswith("PRD-REPAIR-")
        ])
        if not candidates:
            break
        task_id = candidates[0]
        result = execute_task(root, plan_path, task_id, requirement_path, args.runtime, worker_path, args.timeout)
        completed.append(result)
        if result.get("status") != "SUCCEEDED":
            return {"status": "FAILED", "completed": completed, "stoppedAt": task_id}
        if task_id == "TECH-PRD-DIAGNOSIS":
            completed.append(reconcile_reviews(root, plan_path))
    final_plan = load(plan_path)
    statuses = {item["taskId"]: item["status"] for item in final_plan.get("tasks", [])}
    required = [status for task_id, status in statuses.items() if task_id in EXECUTION_ORDER or task_id.startswith("PRD-REPAIR-")]
    if all(status == "SUCCEEDED" for status in required) and statuses.get("FINDING-CONSOLIDATE") == "SUCCEEDED":
        loop_status = "REVIEW_DAG_COMPLETE" if not any(task_id.startswith("PRD-REPAIR-") for task_id in statuses) else "REPAIR_READY_COMPLETE"
    elif any(task_id.startswith("PRD-REPAIR-") and status == "PENDING" for task_id, status in statuses.items()):
        loop_status = "REPAIR_READY"
    else:
        loop_status = "BLOCKED_BY_FINDINGS"
    return {"status": loop_status, "completed": completed, "plan": str(plan_path)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--requirement", type=Path, required=True)
    parser.add_argument("--runtime", choices=["noop", "process", "codex"], default="noop")
    parser.add_argument("--worker", type=Path, default=Path(__file__).resolve().parent / "deterministic_worker.py")
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--max-tasks", type=int, default=12)
    args = parser.parse_args()
    result = loop(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") in {"DAG_COMPLETE", "INCOMPLETE", "REVIEW_DAG_COMPLETE", "REPAIR_READY", "REPAIR_READY_COMPLETE"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
