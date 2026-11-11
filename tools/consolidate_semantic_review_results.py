#!/usr/bin/env python3
"""Consolidate independent semantic slice reviews into one integration result."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--results-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    manifest = load(args.manifest.resolve())
    results_dir = args.results_dir.resolve()
    findings: list[dict[str, Any]] = []
    missing: list[str] = []
    verdicts: Counter[str] = Counter()
    blocking = 0
    reviewed = 0
    for job in manifest.get("jobs", []):
        job_id = job["jobId"]
        result_path = results_dir / f"{job_id}.review.json"
        if not result_path.exists():
            missing.append(job_id)
            blocking += 1
            findings.append({
                "findingId": f"SEM-{len(findings) + 1:03d}",
                "severity": "BLOCKING",
                "checkId": job_id,
                "title": f"Missing independent review for {job_id}",
                "owner": "delivery-producer",
                "closeCondition": f"Run the isolated review job {job_id} and provide a review result.",
                "evidenceRefs": [job.get("path", "")],
            })
            continue
        try:
            result = load(result_path)
        except Exception as exc:
            missing.append(job_id)
            blocking += 1
            findings.append({
                "findingId": f"SEM-{len(findings) + 1:03d}",
                "severity": "BLOCKING",
                "checkId": job_id,
                "title": f"Invalid review result for {job_id}: {exc}",
                "owner": "delivery-producer",
                "closeCondition": "Repair the semantic review result contract.",
                "evidenceRefs": [str(result_path)],
            })
            continue
        reviewed += 1
        verdict = str(result.get("verdict", "INCOMPLETE"))
        verdicts[verdict] += 1
        job_blocking = int(result.get("blockingCount", 0))
        if verdict in {"RETURNED", "BLOCKED", "INCOMPLETE"} and job_blocking == 0:
            job_blocking = 1
        if job_blocking:
            blocking += job_blocking
        for finding in result.get("findings", []):
            if not isinstance(finding, dict):
                continue
            item = dict(finding)
            item.setdefault("findingId", f"SEM-{len(findings) + 1:03d}")
            item.setdefault("checkId", job_id)
            item.setdefault("owner", "delivery-producer")
            item.setdefault("closeCondition", "Resolve the semantic finding.")
            item.setdefault("evidenceRefs", [str(result_path)])
            if str(item.get("severity", "")).upper() == "INFO":
                item["severity"] = "NON_BLOCKING"
            findings.append(item)

    if missing or any(verdict in {"RETURNED", "BLOCKED", "INCOMPLETE"} for verdict in verdicts) or any(str(item.get("severity", "")).upper() == "BLOCKING" for item in findings):
        status = "BLOCKED"
    elif blocking:
        status = "NEEDS_FIX"
    elif findings or verdicts.get("ACCEPTED_WITH_ACTIONS", 0):
        status = "PASS_WITH_NONBLOCKING"
    else:
        status = "PASS"
    payload = {
        "schemaVersion": 1,
        "workflowId": manifest.get("workflowId", "UNKNOWN"),
        "targetRevision": manifest.get("targetRevision", "r1"),
        "status": status,
        "blockingCount": blocking,
        "jobsTotal": len(manifest.get("jobs", [])),
        "jobsReviewed": reviewed,
        "missingJobs": missing,
        "verdicts": dict(sorted(verdicts.items())),
        "findings": findings,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": status, "blockingCount": blocking, "reviewed": reviewed, "total": payload["jobsTotal"], "out": str(args.out)}, ensure_ascii=False))
    return 0 if status in {"PASS", "PASS_WITH_NONBLOCKING"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
