#!/usr/bin/env python3
"""Plan owner-specific repairs from a PRD-Prototype consistency result."""
from __future__ import annotations

import argparse
import json
import secrets
from datetime import datetime, timezone
from pathlib import Path


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--consistency", type=Path, required=True)
    parser.add_argument("--pair", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    consistency = load(args.consistency); pair = load(args.pair)
    tasks = []
    for index, finding in enumerate(consistency.get("findings", []), start=1):
        owner = finding.get("owner", "delivery-main-agent")
        tasks.append({
            "taskId": f"artifact-repair-{index:02d}",
            "owner": owner,
            "findingType": finding.get("type", "CONSISTENCY_FINDING"),
            "uiElementId": finding.get("uiElementId"),
            "frIds": finding.get("frIds", []),
            "acIds": finding.get("acIds", []),
            "closeCondition": finding.get("closeCondition", "Resolve the consistency finding."),
            "regressionTests": finding.get("regressionTests", ["rerun artifact consistency gate"]),
            "status": "PENDING",
        })
    status = "NO_REPAIR" if not tasks else ("READY" if consistency.get("blockingCount", 0) > 0 else "INCOMPLETE")
    result = {
        "schemaVersion": 1,
        "repairGroupId": "artifact-repair-group-" + secrets.token_hex(4),
        "workflowId": pair.get("workflowId", consistency.get("workflowId", "unknown")),
        "pairId": pair.get("pairId", consistency.get("pairId", "unknown")),
        "sourceConsistencyResult": str(args.consistency.resolve()),
        "tasks": tasks,
        "status": status,
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": status, "tasks": len(tasks), "out": str(args.out)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
