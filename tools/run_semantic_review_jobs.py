#!/usr/bin/env python3
"""Run isolated semantic review jobs through a worker command and consolidate results."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from validate_json_schemas import load, validate

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_ROOT = ROOT / "schemas" if (ROOT / "schemas").exists() else ROOT / "references"


def save(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--worker-command", nargs="+", required=True)
    parser.add_argument("--results-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--retries", type=int, default=0)
    parser.add_argument("--jobs", nargs="*", help="Optional job IDs. Omit to run every job.")
    args = parser.parse_args()
    manifest = load(args.manifest.resolve())
    selected = set(args.jobs or [])
    jobs = [job for job in manifest.get("jobs", []) if not selected or job.get("jobId") in selected]
    results_dir = args.results_dir.resolve()
    results_dir.mkdir(parents=True, exist_ok=True)
    review_schema = load(SCHEMA_ROOT / "review-result.schema.json")
    attempts: list[dict[str, Any]] = []
    for job in jobs:
        job_path = Path(job["path"]).resolve()
        job_payload = load(job_path)
        output: dict[str, Any] | None = None
        error = None
        for attempt in range(1, args.retries + 2):
            process = subprocess.run(
                args.worker_command,
                input=json.dumps(job_payload, ensure_ascii=False),
                text=True,
                capture_output=True,
                timeout=args.timeout,
                check=False,
            )
            if process.returncode != 0:
                error = f"worker exit {process.returncode}: {process.stderr[-2000:]}"
            else:
                try:
                    output = json.loads(process.stdout) if process.stdout.strip() else None
                except json.JSONDecodeError as exc:
                    error = f"invalid worker JSON: {exc}"
                if output is not None:
                    errors = validate(output, review_schema, review_schema)
                    if errors:
                        error = "invalid review result: " + "; ".join(errors[:8])
                        output = None
            attempts.append({"jobId": job["jobId"], "attempt": attempt, "status": "SUCCESS" if output is not None else "ERROR", "error": error})
            if output is not None:
                break
        if output is None:
            continue
        save(results_dir / f"{job['jobId']}.review.json", output)
    consolidate = Path(__file__).resolve().parent / "consolidate_semantic_review_results.py"
    process = subprocess.run([
        sys.executable, str(consolidate), "--manifest", str(args.manifest.resolve()),
        "--results-dir", str(results_dir), "--out", str(args.out.resolve()),
    ], text=True, capture_output=True, check=False)
    aggregate = load(args.out.resolve()) if args.out.exists() else {}
    status = aggregate.get("status", "BLOCKED")
    print(json.dumps({
        "schemaVersion": 1,
        "status": status,
        "jobsRequested": len(jobs),
        "jobsCompleted": sum(1 for item in attempts if item["status"] == "SUCCESS"),
        "attempts": attempts,
        "aggregate": str(args.out),
        "consolidation": {"returnCode": process.returncode, "stdout": process.stdout, "stderr": process.stderr},
        "generatedAt": datetime.now(timezone.utc).isoformat(),
    }, ensure_ascii=False))
    return 0 if status in {"PASS", "PASS_WITH_NONBLOCKING"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
