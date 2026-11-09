#!/usr/bin/env python3
"""Minimal executable runtime adapter for Delivery sub-agent tasks."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from validate_agent_contracts import validate_file


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def save(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def valid_runtime(runtime: str) -> bool:
    return runtime in {"noop", "codex", "process"}


def validate_task(task: dict[str, Any], root: Path) -> list[str]:
    errors: list[str] = []
    runtime = task.get("runtime", "noop")
    if not valid_runtime(runtime):
        errors.append(f"unsupported runtime: {runtime}")
    if not task.get("taskId") or "/" in str(task["taskId"]) or ".." in str(task["taskId"]):
        errors.append("taskId must be a non-empty path-safe identifier")
    for item in task.get("inputs", []):
        path = Path(item["path"])
        if not path.is_absolute():
            path = root / path
        if not path.exists():
            errors.append(f"missing input: {path}")
        elif sha256(path) != item.get("sha256"):
            errors.append(f"input hash mismatch: {path}")
    if task.get("reviewMode") in {"consumer-review", "independent-review"} and task.get("readOnlyFrozenInputs") is not True:
        errors.append("review task requires readOnlyFrozenInputs=true")
    return errors


def result_errors(result: Any) -> list[str]:
    if not isinstance(result, dict):
        return ["structured result must be a JSON object"]
    if result.get("schemaVersion") != 1:
        return ["structured result requires schemaVersion=1"]
    if not isinstance(result.get("status"), str) or not result["status"]:
        return ["structured result requires non-empty status"]
    if not isinstance(result.get("outputs"), list) or not result["outputs"]:
        return ["structured result requires non-empty outputs"]
    for output in result["outputs"]:
        if not isinstance(output, dict) or not isinstance(output.get("path"), str) or not output["path"]:
            return ["every structured result output requires path"]
    return []


def runtime_environment(root: Path, task: dict[str, Any]) -> dict[str, str]:
    env = os.environ.copy()
    env.update({
        "AI_NATIVE_TASK_ID": str(task["taskId"]),
        "AI_NATIVE_WORKFLOW_ID": str(task["workflowId"]),
        "AI_NATIVE_ROLE": str(task["role"]),
        "AI_NATIVE_CONTEXT_ID": str(task.get("contextId", "")),
        "AI_NATIVE_RUN_ROOT": str(root),
    })
    return env


def launch(args: argparse.Namespace, root: Path, task: dict[str, Any], agent_id: str, record_path: Path) -> list[str]:
    runtime = task.get("runtime", "noop")
    command = task.get("command")
    record = load(record_path)
    transcript = ""
    return_code: int | None = 0
    error = ""
    try:
        if runtime == "noop":
            if command is None:
                record["status"] = "RUNNING"
                record["startedAt"] = now()
                save(record_path, record)
                return []
            errors = result_errors(load(root / command["resultPath"]))
            if errors:
                return errors
        else:
            if not isinstance(command, dict):
                return [f"runtime={runtime} requires command"]
            argv = command.get("argv")
            if not isinstance(argv, list) or not argv or not all(isinstance(item, str) for item in argv):
                return ["command.argv must be a non-empty string array"]
            result_path = command.get("resultPath")
            if not isinstance(result_path, str) or not result_path:
                return ["command.resultPath is required"]
            record["status"] = "RUNNING"
            record["startedAt"] = now()
            save(record_path, record)
            timeout = args.timeout if args.timeout is not None else task.get("timeoutSeconds")
            if timeout is not None and (not isinstance(timeout, (int, float)) or timeout <= 0):
                return ["timeoutSeconds must be a positive number"]
            executable = shutil.which(argv[0]) if "/" not in argv[0] else argv[0]
            if not executable:
                return [f"executable not found: {argv[0]}"]
            transcript_path = root / ".agents" / "runtime" / "transcripts" / f"{task['taskId']}.log"
            transcript_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                completed = subprocess.run(
                    argv,
                    cwd=root,
                    env=runtime_environment(root, task),
                    text=True,
                    capture_output=True,
                    timeout=timeout,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                transcript = "".join(exc.stdout or []) + "".join(exc.stderr or [])
                transcript_path.write_text(transcript, encoding="utf-8")
                record["transcriptPath"] = str(transcript_path)
                record["error"] = f"timeout after {timeout}s"
                save(record_path, record)
                return [record["error"]]
            transcript = completed.stdout + completed.stderr
            transcript_path.write_text(transcript, encoding="utf-8")
            record["transcriptPath"] = str(transcript_path)
            return_code = completed.returncode
            if return_code != 0:
                error = f"runtime exited with code {return_code}"
                record["error"] = error
                save(record_path, record)
                return [error, completed.stderr[-2000:]]
            result_file = root / result_path
            if not result_file.exists():
                return [f"structured result not found: {result_file}"]
            try:
                result = load(result_file)
            except (OSError, json.JSONDecodeError) as exc:
                return [f"invalid structured result: {exc}"]
            errors = result_errors(result)
            if errors:
                return errors
    except Exception as exc:  # Runtime boundaries must fail closed.
        error = f"runtime dispatch failed: {exc}"
        record["error"] = error
        save(record_path, record)
        return [error]
    record["exitCode"] = return_code
    save(record_path, record)
    return []


def spawn(args: argparse.Namespace) -> dict[str, Any]:
    root = args.run_root.resolve()
    task_path = args.task.resolve()
    task = load(task_path)
    errors = validate_file(task_path) + validate_task(task, root)
    if errors:
        return {"status": "FAIL", "errors": errors}
    runtime_dir = root / ".agents" / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    record_path = runtime_dir / f"{task['taskId']}.json"
    if record_path.exists() and not args.force:
        return {"status": "EXISTS", "record": str(record_path)}
    agent_id = args.agent_id or "agent-" + secrets.token_hex(4)
    context_id = task.get("contextId") or f"context-{task['role']}-{agent_id}"
    if task.get("contextId") != context_id:
        task["contextId"] = context_id
        task_path.write_text(json.dumps(task, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    record = {
        "schemaVersion": 1,
        "taskId": task["taskId"],
        "workflowId": task["workflowId"],
        "agentId": agent_id,
        "contextId": context_id,
        "runtime": task.get("runtime", "noop"),
        "status": "SPAWNED",
        "taskManifest": str(task_path),
        "taskManifestSha256": sha256(task_path),
        "createdAt": now(),
        "updatedAt": now(),
    }
    save(record_path, record)
    if args.execute:
        errors = launch(args, root, task, agent_id, record_path)
        record = load(record_path)
        record["status"] = "FAILED" if errors else "SUCCEEDED"
        record["finishedAt"] = now()
        record["updatedAt"] = record["finishedAt"]
        if not errors and isinstance(task.get("command"), dict) and task["command"].get("resultPath"):
            result_file = root / task["command"]["resultPath"]
            record["structuredResultPath"] = str(result_file.resolve())
            record["structuredResultSha256"] = sha256(result_file)
        if errors:
            record["error"] = errors[0]
        save(record_path, record)
        if errors:
            return {"status": "FAILED", "taskId": task["taskId"], "errors": errors, "record": str(record_path)}
        return {"status": "SUCCEEDED", "taskId": task["taskId"], "agentId": agent_id, "contextId": context_id, "record": str(record_path)}
    return {"status": "SPAWNED", "taskId": task["taskId"], "agentId": agent_id, "contextId": context_id, "record": str(record_path)}


def collect(args: argparse.Namespace) -> dict[str, Any]:
    root = args.run_root.resolve()
    path = root / ".agents" / "runtime" / f"{args.task_id}.json"
    if not path.exists():
        return {"status": "FAIL", "errors": [f"missing runtime record: {path}"]}
    record = load(path)
    if record["status"] not in {"SPAWNED", "RUNNING"}:
        return {"status": "FAIL", "errors": [f"task cannot collect from status={record['status']}"]}
    if args.cancel:
        record["status"] = "CANCELLED"
        record["finishedAt"] = now()
        record["updatedAt"] = record["finishedAt"]
        if args.error:
            record["error"] = args.error
        save(path, record)
        return {"status": "CANCELLED", "taskId": args.task_id, "record": str(path)}
    if args.error:
        record["status"] = "FAILED"
        record["error"] = args.error
    else:
        result_path = Path(args.result) if args.result else None
        if result_path is None:
            result_path = Path(record.get("structuredResultPath", "")) if record.get("structuredResultPath") else None
        if result_path is None:
            record["status"] = "FAILED"
            record["error"] = "structured result is required"
            record["finishedAt"] = now()
            record["updatedAt"] = record["finishedAt"]
            save(path, record)
            return {"status": "FAILED", "taskId": args.task_id, "errors": [record["error"]], "record": str(path)}
        if not result_path.exists():
            record["status"] = "FAILED"
            record["error"] = f"structured result not found: {result_path}"
            record["finishedAt"] = now()
            record["updatedAt"] = record["finishedAt"]
            save(path, record)
            return {"status": "FAILED", "taskId": args.task_id, "errors": [record["error"]], "record": str(path)}
        try:
            result = load(result_path)
        except (OSError, json.JSONDecodeError) as exc:
            record["status"] = "FAILED"
            record["error"] = f"invalid structured result: {exc}"
            record["finishedAt"] = now()
            record["updatedAt"] = record["finishedAt"]
            save(path, record)
            return {"status": "FAILED", "taskId": args.task_id, "errors": [record["error"]], "record": str(path)}
        errors = result_errors(result)
        if errors:
            record["status"] = "FAILED"
            record["error"] = errors[0]
            record["finishedAt"] = now()
            record["updatedAt"] = record["finishedAt"]
            save(path, record)
            return {"status": "FAILED", "taskId": args.task_id, "errors": errors, "record": str(path)}
        record["status"] = "SUCCEEDED"
        record["structuredResultPath"] = str(result_path.resolve())
        record["structuredResultSha256"] = sha256(result_path)
    record["finishedAt"] = record.get("finishedAt") or now()
    record["updatedAt"] = now()
    save(path, record)
    return {
        "status": record["status"],
        "taskId": args.task_id,
        "record": str(path),
        "structuredResultPath": record.get("structuredResultPath"),
        "structuredResultSha256": record.get("structuredResultSha256"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    spawn_parser = sub.add_parser("spawn")
    spawn_parser.add_argument("--run-root", type=Path, required=True)
    spawn_parser.add_argument("--task", type=Path, required=True)
    spawn_parser.add_argument("--agent-id")
    spawn_parser.add_argument("--timeout", type=float)
    spawn_parser.add_argument("--execute", action="store_true")
    spawn_parser.add_argument("--force", action="store_true")
    collect_parser = sub.add_parser("collect")
    collect_parser.add_argument("--run-root", type=Path, required=True)
    collect_parser.add_argument("--task-id", required=True)
    collect_parser.add_argument("--result", type=Path)
    collect_parser.add_argument("--error")
    collect_parser.add_argument("--cancel", action="store_true")
    args = parser.parse_args()
    result = spawn(args) if args.cmd == "spawn" else collect(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") not in {"FAIL", "FAILED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
