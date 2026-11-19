#!/usr/bin/env python3
"""Verify that a baseline evaluation run is complete and bound to a valid task set."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def save(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--integrity", type=Path, required=True)
    parser.add_argument("--tasks", type=Path, action="append", required=True)
    parser.add_argument("--predictions-dir", type=Path, required=True)
    parser.add_argument("--baseline", action="append", default=[])
    parser.add_argument("--runtime-blocker", action="append", default=[])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    integrity = load(args.integrity.resolve())
    task_rows: list[dict[str, Any]] = []
    for path in args.tasks:
        task_rows.extend(load_jsonl(path.resolve()))
    expected_by_split: dict[str, set[str]] = {}
    for task in task_rows:
        expected_by_split.setdefault(str(task["split"]), set()).add(str(task["goldenTaskId"]))
    baselines = args.baseline or ["b0", "b1", "b2"]
    blockers = list(args.runtime_blocker)
    if integrity.get("status") != "PASS":
        blockers.append("TASK_INTEGRITY_NOT_PASS")

    runs: list[dict[str, Any]] = []
    for baseline in baselines:
        for split, expected in sorted(expected_by_split.items()):
            path = args.predictions_dir / f"{baseline}-{split}.jsonl"
            if not path.is_file():
                runs.append({
                    "baseline": baseline,
                    "split": split,
                    "status": "BLOCKED" if blockers else "INCOMPLETE",
                    "expected": len(expected),
                    "records": 0,
                    "missingTaskIds": sorted(expected),
                    "extraTaskIds": [],
                    "predictionPath": str(path.resolve()),
                    "predictionHash": None,
                })
                continue
            rows = load_jsonl(path)
            ids = [str(row.get("goldenTaskId", "")) for row in rows]
            missing = sorted(expected - set(ids))
            extra = sorted(set(ids) - expected)
            duplicate_count = len(ids) - len(set(ids))
            status = "COMPLETE" if not missing and not extra and not duplicate_count and len(rows) == len(expected) else "INCOMPLETE"
            runs.append({
                "baseline": baseline,
                "split": split,
                "status": status,
                "expected": len(expected),
                "records": len(rows),
                "missingTaskIds": missing,
                "extraTaskIds": extra,
                "duplicateTaskIds": duplicate_count,
                "predictionPath": str(path.resolve()),
                "predictionHash": digest(path),
            })
    complete = all(item["status"] == "COMPLETE" for item in runs)
    status = "BLOCKED" if blockers else ("PASS" if complete else "INCOMPLETE")
    report = {
        "schemaVersion": 1,
        "reportId": "evaluation-run-" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S"),
        "status": status,
        "closureEligible": status == "PASS",
        "taskSetHashes": {str(path.resolve()): digest(path.resolve()) for path in args.tasks},
        "integrityReportPath": str(args.integrity.resolve()),
        "integrityReportHash": digest(args.integrity.resolve()),
        "integrityStatus": integrity.get("status"),
        "runtimeBlockers": blockers,
        "runs": runs,
        "checkedAt": datetime.now(timezone.utc).isoformat(),
    }
    save(args.out, report)
    print(json.dumps({
        "status": report["status"],
        "closureEligible": report["closureEligible"],
        "runtimeBlockers": report["runtimeBlockers"],
        "incompleteRuns": sum(item["status"] != "COMPLETE" for item in runs),
        "out": str(args.out.resolve()),
    }, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" or not args.strict else 1


if __name__ == "__main__":
    raise SystemExit(main())
