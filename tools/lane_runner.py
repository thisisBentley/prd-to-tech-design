#!/usr/bin/env python3
"""Run multiple isolated requirement lanes up to a small concurrency ceiling."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MAX_LANES = 5


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def save(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_command(argv: list[str], cwd: Path, timeout: float) -> dict[str, Any]:
    started = time.monotonic()
    try:
        process = subprocess.run(argv, cwd=cwd, text=True, capture_output=True, timeout=timeout, check=False)
        return {
            "returnCode": process.returncode,
            "stdout": process.stdout,
            "stderr": process.stderr,
            "durationSeconds": round(time.monotonic() - started, 3),
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "returnCode": -1,
            "stdout": exc.stdout or "",
            "stderr": (exc.stderr or "") + f"\ntimeout after {timeout}s",
            "durationSeconds": round(time.monotonic() - started, 3),
            "timedOut": True,
        }
    except Exception as exc:
        return {
            "returnCode": -2,
            "stdout": "",
            "stderr": f"lane command failed: {exc}",
            "durationSeconds": round(time.monotonic() - started, 3),
        }


def run_lane(lane: dict[str, Any], workspace: Path, base_dir: Path, worker: Path, timeout: float, python: str, orchestrate: Path, loop: Path) -> dict[str, Any]:
    lane_id = str(lane.get("laneId", "")).strip()
    if not lane_id or "/" in lane_id or ".." in lane_id:
        return {"laneId": lane_id, "status": "FAIL", "error": "laneId must be a safe, non-empty identifier"}
    started_at = now()
    started = time.monotonic()
    root = workspace / lane_id
    root.mkdir(parents=True, exist_ok=True)
    requirement = Path(lane["requirement"])
    if not requirement.is_absolute():
        requirement = (base_dir / requirement).resolve()
    result: dict[str, Any] = {
        "laneId": lane_id,
        "runRoot": str(root.resolve()),
        "requirement": str(requirement),
        "startedAt": started_at,
        "status": "FAIL",
        "records": [],
    }
    if not requirement.exists():
        result.update({"error": f"requirement not found: {requirement}", "finishedAt": now(), "totalDurationSeconds": round(time.monotonic() - started, 3)})
        return result
    profile = lane.get("artifactProfile", "PRD_ONLY")
    requirement_name = lane.get("requirementName", lane_id)
    common = [python, str(orchestrate)]
    init = common + ["init", "--run-root", str(root), "--workflow-id", f"{lane_id}-workflow", "--requirement-name", requirement_name, "--requirement-id", lane_id, "--artifact-profile", profile, "--prototype-status", lane.get("prototypeStatus", "NOT_TRIGGERED"), "--ui-ownership", lane.get("uiOwnership", "NONE"), "--force"]
    init_result = run_command(init, root, timeout)
    result["records"].append({"step": "init", **init_result})
    if init_result["returnCode"] != 0:
        result.update({"error": "lane init failed", "finishedAt": now(), "totalDurationSeconds": round(time.monotonic() - started, 3)})
        return result
    plan = root / "delivery-plan.json"
    plan_result = run_command(common + ["build-delivery-plan", "--run-root", str(root), "--out", str(plan)], root, timeout)
    result["records"].append({"step": "plan", **plan_result})
    if plan_result["returnCode"] != 0:
        result.update({"error": "lane plan failed", "finishedAt": now(), "totalDurationSeconds": round(time.monotonic() - started, 3)})
        return result
    loop_result = run_command([python, str(loop), "--run-root", str(root), "--plan", str(plan), "--requirement", str(requirement), "--worker", str(worker), "--timeout", str(timeout), "--max-tasks", str(lane.get("maxTasks", 20))], root, timeout * 2)
    result["records"].append({"step": "delivery-loop", **loop_result})
    try:
        parsed = json.loads(loop_result["stdout"]) if loop_result["stdout"].strip() else {}
    except json.JSONDecodeError:
        parsed = {}
    result["delivery"] = parsed
    if loop_result["returnCode"] == 0 and parsed.get("status") in {"M1_CONTRACT_COMPLETE", "INCOMPLETE", "REPAIR_READY"}:
        result["status"] = "PASS" if parsed.get("status") == "M1_CONTRACT_COMPLETE" else parsed.get("status")
    else:
        result["error"] = "delivery loop failed"
    result["finishedAt"] = now()
    result["totalDurationSeconds"] = round(time.monotonic() - started, 3)
    result["queueWaitSeconds"] = max(0.0, round(result["totalDurationSeconds"] - sum(record.get("durationSeconds", 0) for record in result["records"]), 3))
    result["gateDurationSeconds"] = round(sum(record.get("durationSeconds", 0) for record in result["records"] if record.get("step") in {"plan", "delivery-loop"}), 3)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--max-workers", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--worker", type=Path, default=Path(__file__).resolve().parent / "deterministic_worker.py")
    args = parser.parse_args()
    if args.max_workers < 1 or args.max_workers > MAX_LANES:
        raise SystemExit(f"max-workers must be between 1 and {MAX_LANES}")
    manifest = load(args.manifest.resolve())
    lanes = manifest.get("lanes", [])
    if not lanes:
        raise SystemExit("manifest must contain at least one lane")
    if len(lanes) > MAX_LANES:
        raise SystemExit(f"lane count must be <= {MAX_LANES} in this stage")
    scripts = Path(__file__).resolve().parent
    orchestrate = scripts / "orchestrate.py"
    loop = scripts / "delivery_loop.py"
    worker = args.worker.resolve()
    if not worker.exists():
        raise SystemExit(f"worker not found: {worker}")
    started = time.monotonic()
    summaries = []
    with ThreadPoolExecutor(max_workers=args.max_workers) as executor:
        futures = {
            executor.submit(run_lane, lane, args.workspace.resolve(), args.manifest.resolve().parent, worker, args.timeout, sys.executable, orchestrate, loop): lane
            for lane in lanes
        }
        for future in as_completed(futures):
            summaries.append(future.result())
    summaries.sort(key=lambda item: item.get("laneId", ""))
    expected = len(lanes)
    passed = sum(1 for item in summaries if item.get("status") == "PASS")
    failed = [item for item in summaries if item.get("status") != "PASS"]
    result = {
        "schemaVersion": 1,
        "status": "PASS" if passed == expected else ("PARTIAL" if passed else "FAIL"),
        "requestedLanes": expected,
        "maxWorkers": args.max_workers,
        "passed": passed,
        "failed": len(failed),
        "lanes": summaries,
        "totalDurationSeconds": round(time.monotonic() - started, 3),
        "createdAt": now(),
    }
    save(args.out.resolve(), result)
    print(json.dumps({"status": result["status"], "passed": passed, "failed": len(failed), "out": str(args.out)}, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
