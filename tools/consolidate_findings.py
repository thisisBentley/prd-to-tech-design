#!/usr/bin/env python3
"""Consolidate independent review findings into one root-cause repair batch."""
from __future__ import annotations
import argparse, json, secrets
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def consolidate(paths: list[Path]) -> dict[str, Any]:
    reviews = [load(p) for p in paths]
    groups: OrderedDict[str, dict[str, Any]] = OrderedDict()
    workflow_ids = {r.get("workflowId") for r in reviews if r.get("workflowId")}
    revisions = {r.get("targetRevision") for r in reviews if r.get("targetRevision")}
    for review, path in zip(reviews, paths):
        for finding in review.get("findings") or []:
            root = finding.get("rootCauseId") or finding.get("stableKey") or finding.get("findingId") or f"inferred:{finding.get('title','unknown')}"
            group = groups.setdefault(root, {
                "rootCauseId": root,
                "findingIds": [],
                "repairClass": finding.get("repairClass") or "UNKNOWN",
                "owners": [],
                "evidenceRefs": [],
                "closeConditions": [],
                "expectedInvariants": [],
                "regressionTests": [],
            })
            fid = finding.get("findingId") or f"{path.name}:{root}"
            if fid not in group["findingIds"]: group["findingIds"].append(fid)
            owner = finding.get("owner") or "producer"
            if owner not in group["owners"]: group["owners"].append(owner)
            for key, target in [("evidenceRefs", "evidenceRefs"), ("closeCondition", "closeConditions"), ("expectedInvariant", "expectedInvariants"), ("regressionTests", "regressionTests"), ("closeEvidence", "evidenceRefs")]:
                value = finding.get(key)
                if isinstance(value, list): values = value
                elif value: values = [value]
                else: values = []
                for item in values:
                    if item not in group[target]: group[target].append(item)
            if finding.get("repairClass") and group["repairClass"] == "UNKNOWN": group["repairClass"] = finding["repairClass"]
    status = "READY_FOR_REPAIR" if groups else "NO_FINDINGS"
    blocking = sum(1 for review in reviews for finding in (review.get("findings") or []) if finding.get("severity") == "BLOCKING")
    if len(workflow_ids) > 1 or len(revisions) > 1:
        status = "INCOMPLETE"
    return {
        "schemaVersion": 1,
        "batchId": "repair-batch-" + secrets.token_hex(4),
        "workflowId": next(iter(workflow_ids), "unknown"),
        "targetRevision": next(iter(revisions), "unknown"),
        "sourceReviews": [str(p) for p in paths],
        "groups": list(groups.values()),
        "blockingCount": blocking,
        "status": status,
        "createdAt": now(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review", action="append", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = consolidate(args.review)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] != "INCOMPLETE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
