#!/usr/bin/env python3
"""Run the M7.6-0 trust kernel as one deterministic pre-execution gate."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from trust_kernel import canonical_hash, classify_task, load, now, route_specialist_tool, save_json, validate_schema_value, validate_target_binding


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-request", type=Path, required=True)
    parser.add_argument("--execution-mode-policy", type=Path, required=True)
    parser.add_argument("--tool-policy", type=Path, required=True)
    parser.add_argument("--intent", required=True)
    parser.add_argument("--target-binding-request", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    task = load(args.task_request.resolve())
    execution = classify_task(task, load(args.execution_mode_policy.resolve()), args.execution_mode_policy.resolve())
    route = route_specialist_tool(task["workflowId"], execution["mode"], args.intent, load(args.tool_policy.resolve()), args.tool_policy.resolve())
    target_binding = None
    if args.target_binding_request is not None:
        target_binding = validate_target_binding(load(args.target_binding_request.resolve()))

    if execution["status"] != "CLASSIFIED" or route["status"] != "ROUTED":
        status = "ESCALATE"
    elif execution["mode"] == "TARGETED_REVISION" and (target_binding is None or target_binding.get("status") != "PASS"):
        status = "BLOCKED"
    else:
        status = "READY"

    payload_without_id = {
        "schemaVersion": 1,
        "workflowId": task["workflowId"],
        "taskId": task["taskId"],
        "status": status,
        "executionDecision": execution,
        "selectedToolRoute": route,
        "targetBinding": target_binding,
        "createdAt": now(),
    }
    result = {"runId": "TRUST-KERNEL-" + canonical_hash(payload_without_id)[:16], **payload_without_id}
    errors = validate_schema_value(result, "trust-kernel-run.schema.json")
    if errors:
        raise ValueError("; ".join(errors))
    save_json(args.out, result)
    print(json.dumps({
        "status": result["status"],
        "mode": execution["mode"],
        "toolId": (route.get("selectedTool") or {}).get("toolId"),
        "targetBinding": None if target_binding is None else target_binding["status"],
        "out": str(args.out.resolve()),
    }, ensure_ascii=False, indent=2))
    return 0 if status == "READY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
