#!/usr/bin/env python3
"""Turn a validated Change Set batch into bounded Repair Agent tasks."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPAIR_CLASS_BY_TRACK = {
    "BUSINESS_REVISION": "SEMANTIC",
    "ARTIFACT_SYNC": "ARTIFACT_CONTRACT",
    "TECH_SOLUTION": "RUNTIME",
    "TEST_PLAN": "EVIDENCE",
    "MECHANICAL_REPAIR": "EVIDENCE",
}


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def blocked_plan(batch: dict[str, Any] | None, source: Path | None, errors: list[str]) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "repairPlanId": "repair-plan-blocked",
        "workflowId": (batch or {}).get("workflowId", "unknown"),
        "targetRevision": (batch or {}).get("targetRevision", "unknown"),
        "sourceBatch": str(source.resolve()) if source else "",
        "tasks": [],
        "status": "INCOMPLETE",
        "errors": errors,
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }


def build_plan(batch: dict[str, Any], source: Path) -> dict[str, Any]:
    if batch.get("batchType") != "CHANGE_SET_BATCH":
        return blocked_plan(batch, source, ["legacy repair batches are not accepted; compile a Change Set batch first"])
    status = batch.get("status")
    if status == "NO_CHANGES":
        return {
            "schemaVersion": 1,
            "repairPlanId": "repair-plan-no-changes",
            "workflowId": batch.get("workflowId", "unknown"),
            "targetRevision": batch.get("targetRevision", "unknown"),
            "sourceBatch": str(source.resolve()),
            "tasks": [],
            "status": "NO_REPAIR",
            "createdAt": datetime.now(timezone.utc).isoformat(),
        }
    if status != "READY_FOR_REPAIR":
        return blocked_plan(batch, source, [f"Change Set batch status {status!r} is not READY_FOR_REPAIR"])
    tasks: list[dict[str, Any]] = []
    for change_set in batch.get("changeSets", []):
        if change_set.get("status") != "PLANNED":
            return blocked_plan(batch, source, [f"Change Set {change_set.get('changeSetId')} is not PLANNED"])
        artifact_paths = [str(item["path"]) for item in change_set.get("affectedArtifacts", [])]
        verification_plan = change_set.get("verificationPlan", [])
        tasks.append({
            "taskId": "repair-" + str(change_set["changeSetId"]).lower(),
            "changeSetId": str(change_set["changeSetId"]),
            "rootCauseId": str(change_set["rootCauseId"]),
            "role": str(change_set["ownerRole"]),
            "repairClass": REPAIR_CLASS_BY_TRACK[str(change_set["repairTrack"])],
            "classification": str(change_set["classification"]),
            "businessRevisionRequired": bool(change_set["businessRevisionRequired"]),
            "ruleIds": [],
            "affectedArtifacts": artifact_paths,
            "closeConditions": list(change_set.get("closeConditions", [])),
            "verificationPlan": list(verification_plan),
            "regressionTests": [str(item["checkId"]) for item in verification_plan if item.get("required")],
            "budget": dict(change_set["budget"]),
            "dependencies": [],
            "status": "READY",
        })
    return {
        "schemaVersion": 1,
        "repairPlanId": "repair-plan-" + str(batch["batchId"]).lower(),
        "workflowId": batch["workflowId"],
        "targetRevision": batch["targetRevision"],
        "sourceBatch": str(source.resolve()),
        "tasks": tasks,
        "status": "READY" if tasks else "NO_REPAIR",
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--change-set-batch", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        batch = load(args.change_set_batch.resolve())
        result = build_plan(batch, args.change_set_batch.resolve())
    except Exception as exc:
        result = blocked_plan(None, args.change_set_batch, [str(exc)])
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": result["status"],
        "tasks": len(result["tasks"]),
        "repairPlanId": result["repairPlanId"],
        "plan": str(args.out.resolve()),
        "errors": result.get("errors", []),
    }, ensure_ascii=False, indent=2))
    return 0 if result["status"] in {"READY", "NO_REPAIR"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
