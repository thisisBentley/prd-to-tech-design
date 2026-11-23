#!/usr/bin/env python3
"""Execute isolated PM/Architect consumer jobs and evaluate one case."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from semantic_convergence import canonical_hash, load, save, sha256_file
from trust_kernel import now, validate_schema_value

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "scripts" if (ROOT / "scripts").exists() else ROOT / "tools"
AGENT_RUNTIME = TOOLS / "agent_runtime.py"
EVALUATOR = TOOLS / "evaluate_consumer_acceptance.py"


def resolve(path: str | Path, base: Path) -> Path:
    value = Path(path).expanduser()
    return value.resolve() if value.is_absolute() else (base / value).resolve()


def run_command(argv: list[str], cwd: Path) -> tuple[int, str, str]:
    process = subprocess.run(argv, cwd=cwd, text=True, capture_output=True, check=False)
    return process.returncode, process.stdout, process.stderr


def validate_manifest(manifest: dict[str, Any], manifest_path: Path) -> None:
    errors = validate_schema_value(manifest, "consumer-review-job-manifest.schema.json")
    if errors:
        raise ValueError("invalid consumer review job manifest: " + "; ".join(errors))
    for item in manifest["frozenInputs"]:
        path = resolve(item["path"], manifest_path.parent)
        if not path.is_file():
            raise ValueError(f"frozen input is missing: {path}")
        if sha256_file(path) != item["sha256"]:
            raise ValueError(f"frozen input hash drift: {path}")
    for job in manifest["jobs"]:
        task = resolve(job["taskPath"], manifest_path.parent)
        plan = resolve(job["reviewPlanPath"], manifest_path.parent)
        if not task.is_file() or sha256_file(task) != job["taskSha256"]:
            raise ValueError(f"consumer task hash drift or missing: {task}")
        if not plan.is_file() or sha256_file(plan) != job["reviewPlanSha256"]:
            raise ValueError(f"consumer review plan hash drift or missing: {plan}")


def build_execution_task(source_task: dict[str, Any], source_task_path: Path, out_dir: Path, worker: list[str], role: str, timeout: float | None) -> tuple[Path, Path]:
    execution_dir = out_dir / "execution"
    execution_dir.mkdir(parents=True, exist_ok=True)
    result_path = execution_dir / f"{role}.review-result.json"
    task_path = execution_dir / f"{role}.task.json"
    task = dict(source_task)
    task["runtime"] = "process"
    task["command"] = {"argv": worker, "resultPath": str(result_path.relative_to(out_dir))}
    task["writeScope"] = [str(execution_dir.resolve())]
    if timeout is not None:
        task["timeoutSeconds"] = timeout
    save(task_path, task)
    return task_path, result_path


def execute_job(out_dir: Path, task_path: Path, timeout: float | None) -> tuple[dict[str, Any], Path]:
    command = [sys.executable, str(AGENT_RUNTIME), "spawn", "--run-root", str(out_dir), "--task", str(task_path), "--execute", "--force"]
    if timeout is not None:
        command.extend(["--timeout", str(timeout)])
    code, stdout, stderr = run_command(command, out_dir)
    payload: dict[str, Any]
    try:
        payload = json.loads(stdout) if stdout.strip() else {"status": "FAILED", "errors": [stderr[-2000:]]}
    except json.JSONDecodeError:
        payload = {"status": "FAILED", "errors": [stdout[-2000:], stderr[-2000:]]}
    record = out_dir / ".agents" / "runtime" / f"{json.loads(task_path.read_text(encoding='utf-8'))['taskId']}.json"
    if code != 0 and payload.get("status") == "SUCCEEDED":
        payload["status"] = "FAILED"
    return payload, record


def evaluate_request(request_path: Path, policy_path: Path, out_path: Path) -> tuple[int, str, str]:
    return run_command([
        sys.executable, str(EVALUATOR), "--request", str(request_path), "--policy", str(policy_path), "--out", str(out_path)
    ], request_path.parent)


def execute(args: argparse.Namespace) -> dict[str, Any]:
    request_path = args.request.resolve()
    manifest_path = args.manifest.resolve()
    out_dir = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    request = load(request_path)
    manifest = load(manifest_path)
    validate_manifest(manifest, manifest_path)
    if request.get("workflowId") != manifest.get("workflowId") or request.get("caseId") != manifest.get("caseId"):
        raise ValueError("request and review manifest identity mismatch")
    if len(manifest["jobs"]) != 2:
        raise ValueError("consumer execution requires exactly PM and Architect jobs")

    jobs: list[dict[str, Any]] = []
    executed_request = dict(request)
    executed_artifacts = dict(request.get("artifacts", {}))
    executed_request["artifacts"] = executed_artifacts
    for item in manifest["jobs"]:
        role = item["role"]
        source_task_path = resolve(item["taskPath"], manifest_path.parent)
        source_task = load(source_task_path)
        execution_task_path, result_path = build_execution_task(source_task, source_task_path, out_dir, args.worker, role, args.timeout)
        execution, runtime_record = execute_job(out_dir, execution_task_path, args.timeout)
        runtime = load(runtime_record) if runtime_record.is_file() else {}
        transcript = Path(str(runtime.get("transcriptPath", ""))) if runtime.get("transcriptPath") else out_dir / ".agents" / "runtime" / "transcripts" / f"{source_task['taskId']}.log"
        if not transcript.is_absolute():
            transcript = (out_dir / transcript).resolve()
        review_result = result_path
        if role == "product-manager-consumer":
            executed_artifacts["productManagerReview"] = str(review_result.resolve())
        else:
            executed_artifacts["architectReview"] = str(review_result.resolve())
        jobs.append({
            "role": role,
            "contextId": source_task["contextId"],
            "sourceTask": str(source_task_path),
            "sourceTaskSha256": sha256_file(source_task_path),
            "executionTask": str(execution_task_path.resolve()),
            "runtimeRecord": str(runtime_record.resolve()),
            "reviewResult": str(review_result.resolve()),
            "transcript": str(transcript),
            "status": "SUCCEEDED" if execution.get("status") == "SUCCEEDED" and review_result.is_file() else "FAILED",
            "errors": [str(item) for item in execution.get("errors", [])],
        })

    executed_request_path = out_dir / "executed-consumer-request.json"
    save(executed_request_path, executed_request)
    consumer_report_path = out_dir / "consumer-report.json"
    eval_code, eval_stdout, eval_stderr = evaluate_request(executed_request_path, args.policy.resolve(), consumer_report_path)
    report = load(consumer_report_path) if consumer_report_path.is_file() else {}
    if eval_code != 0 and not report:
        raise ValueError("consumer acceptance evaluator failed: " + (eval_stderr or eval_stdout)[-2000:])
    status = report.get("status", "BLOCKED")
    payload = {
        "schemaVersion": 1,
        "executionId": "CRE-" + canonical_hash({"manifestId": manifest["manifestId"], "worker": args.worker})[:16],
        "manifestId": manifest["manifestId"],
        "sourceManifest": str(manifest_path),
        "sourceManifestSha256": sha256_file(manifest_path),
        "workflowId": manifest["workflowId"],
        "caseId": manifest["caseId"],
        "targetRevision": manifest["targetRevision"],
        "status": status if status in {"PASS", "NEEDS_REVIEW", "BLOCKED"} else "FAILED",
        "jobs": jobs,
        "executedRequest": str(executed_request_path.resolve()),
        "consumerReport": str(consumer_report_path.resolve()),
        "worker": args.worker,
        "createdAt": now(),
    }
    errors = validate_schema_value(payload, "consumer-review-execution.schema.json")
    if errors:
        raise ValueError("invalid consumer review execution report: " + "; ".join(errors))
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--worker", nargs="+", required=True)
    parser.add_argument("--timeout", type=float)
    args = parser.parse_args()
    try:
        payload = execute(args)
    except Exception as exc:
        print(json.dumps({"status": "FAILED", "errors": [str(exc)]}, ensure_ascii=False, indent=2))
        return 1
    save(args.out.resolve(), payload)
    print(json.dumps({
        "status": payload["status"],
        "executionId": payload["executionId"],
        "consumerReport": payload["consumerReport"],
        "jobs": payload["jobs"],
        "out": str(args.out.resolve()),
    }, ensure_ascii=False, indent=2))
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
