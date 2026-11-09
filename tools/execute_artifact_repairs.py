#!/usr/bin/env python3
"""Execute bounded owner-specific Artifact Repair Groups and reseal evidence."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def save(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repair-group", type=Path, required=True)
    parser.add_argument("--delta", type=Path, required=True)
    parser.add_argument("--prd", type=Path, required=True)
    parser.add_argument("--reconciliation", type=Path, required=True)
    parser.add_argument("--from-prd-revision", required=True)
    parser.add_argument("--to-prd-revision", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    group = load(args.repair_group)
    delta = load(args.delta)
    tasks = group.get("tasks", [])
    executed: list[dict[str, Any]] = []
    unsupported: list[dict[str, Any]] = []
    prd_owners = {"prd-agent", "prd-producer", "prd-repair-agent", "delivery-main-agent"}
    deleted_ui_ids = {
        str(change.get("uiElementId"))
        for change in delta.get("changes", [])
        if change.get("action") in {"DELETE", "MOVE"} and change.get("uiElementId")
    }
    repairable_types = {
        "UNRECONCILED_PROTOTYPE_DELTA",
        "DELETED_UI_ELEMENT_STILL_PRESENT_IN_PRD",
        "MISSING_UI_ELEMENT",
        "STALE_ARTIFACT_PAIR",
    }

    for task in tasks:
        owner = str(task.get("owner", "delivery-main-agent"))
        finding_type = str(task.get("findingType", "CONSISTENCY_FINDING"))
        paired_delete_repair = finding_type == "MISSING_UI_ELEMENT" and str(task.get("uiElementId")) in deleted_ui_ids
        if (owner in prd_owners or paired_delete_repair) and finding_type in repairable_types:
            executed.append({
                "taskId": task.get("taskId"),
                "owner": owner,
                "status": "EXECUTED",
                "action": "PAIRED_PRD_RECONCILIATION_APPLY" if paired_delete_repair else "PRD_RECONCILIATION_APPLY",
                "findingType": finding_type,
                "deltaId": delta.get("deltaId"),
            })
        else:
            unsupported.append({
                "taskId": task.get("taskId"),
                "owner": owner,
                "status": "BLOCKED",
                "findingType": finding_type,
                "reason": "No bounded automatic repair adapter is registered for this owner/finding type.",
            })

    if unsupported:
        result = {
            **group,
            "status": "BLOCKED",
            "executionStatus": "BLOCKED",
            "execution": executed + unsupported,
            "updatedAt": datetime.now(timezone.utc).isoformat(),
        }
        save(args.out, result)
        print(json.dumps({"status": "BLOCKED", "out": str(args.out), "blockedTasks": len(unsupported)}, ensure_ascii=False))
        return 1

    if executed:
        script = Path(__file__).resolve().parent / "reconcile_prototype_delta.py"
        command = [
            sys.executable, str(script),
            "--delta", str(args.delta),
            "--prd", str(args.prd),
            "--from-prd-revision", args.from_prd_revision,
            "--to-prd-revision", args.to_prd_revision,
            "--status", "SYNCED",
            "--apply",
            "--out", str(args.reconciliation),
        ]
        process = subprocess.run(command, text=True, capture_output=True, check=False)
        if process.returncode != 0:
            result = {
                **group,
                "status": "BLOCKED",
                "executionStatus": "FAILED",
                "execution": executed,
                "error": process.stderr or process.stdout,
                "updatedAt": datetime.now(timezone.utc).isoformat(),
            }
            save(args.out, result)
            print(json.dumps({"status": "FAILED", "out": str(args.out)}, ensure_ascii=False))
            return 1

    result = {
        **group,
        "status": "CLOSED",
        "executionStatus": "SUCCEEDED",
        "execution": executed,
        "reconciliationPath": str(args.reconciliation.resolve()) if executed else None,
        "updatedAt": datetime.now(timezone.utc).isoformat(),
    }
    save(args.out, result)
    print(json.dumps({"status": "CLOSED", "out": str(args.out), "executedTasks": len(executed)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
