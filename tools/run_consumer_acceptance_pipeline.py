#!/usr/bin/env python3
"""Run Consumer Acceptance from a request in one intake-to-report command."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from semantic_convergence import canonical_hash, load, save
from trust_kernel import now, validate_schema_value

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "scripts" if (ROOT / "scripts").exists() else ROOT / "tools"
BUILDER = TOOLS / "build_consumer_review_jobs.py"
RUNNER = TOOLS / "run_consumer_review_jobs.py"


def invoke(argv: list[str], cwd: Path) -> tuple[int, dict[str, Any], str]:
    process = subprocess.run(argv, cwd=cwd, text=True, capture_output=True, check=False)
    try:
        payload = json.loads(process.stdout) if process.stdout.strip() else {}
    except json.JSONDecodeError:
        payload = {}
    return process.returncode, payload, process.stderr or process.stdout


def execute(args: argparse.Namespace) -> dict[str, Any]:
    request = args.request.resolve()
    out_dir = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    jobs_dir = out_dir / "consumer-review-jobs"
    execution_dir = out_dir / "consumer-review-execution"
    jobs_manifest = jobs_dir / "manifest.json"
    execution_report = out_dir / "consumer-review-execution.json"
    consumer_report = execution_dir / "consumer-report.json"
    errors: list[str] = []

    build_code, build_result, build_error = invoke([
        sys.executable, str(BUILDER), "--request", str(request), "--out-dir", str(jobs_dir)
    ], out_dir)
    if build_code != 0 or not jobs_manifest.is_file():
        errors.append("Consumer Review Job Builder failed: " + build_error[-2000:])
        status = "FAILED"
    else:
        run_code, run_result, run_error = invoke([
            sys.executable, str(RUNNER),
            "--request", str(request),
            "--manifest", str(jobs_manifest),
            "--policy", str(args.policy.resolve()),
            "--out-dir", str(execution_dir),
            "--out", str(execution_report),
            "--worker", *args.worker,
        ], out_dir)
        if run_code != 0 and not execution_report.is_file():
            errors.append("Consumer Review Job Runner failed: " + run_error[-2000:])
            status = "FAILED"
        else:
            execution = load(execution_report) if execution_report.is_file() else {}
            status = execution.get("status", "FAILED")
            if run_code != 0 and status == "PASS":
                status = "FAILED"
                errors.append("Runner returned a non-zero exit code with PASS status")

    payload = {
        "schemaVersion": 1,
        "pipelineRunId": "CAP-" + canonical_hash({"request": str(request), "worker": args.worker})[:16],
        "request": str(request),
        "status": status if status in {"PASS", "NEEDS_REVIEW", "BLOCKED", "FAILED"} else "FAILED",
        "jobsManifest": str(jobs_manifest.resolve()),
        "executionReport": str(execution_report.resolve()),
        "consumerReport": str(consumer_report.resolve()),
        "m7ExitEvidenceEligible": False,
        "errors": errors,
        "createdAt": now(),
    }
    schema_errors = validate_schema_value(payload, "consumer-acceptance-pipeline-run.schema.json")
    if schema_errors:
        raise ValueError("invalid Consumer Acceptance Pipeline report: " + "; ".join(schema_errors))
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--worker", nargs=argparse.REMAINDER, required=True)
    args = parser.parse_args()
    if not args.worker:
        parser.error("--worker requires an executable command")
    try:
        payload = execute(args)
    except Exception as exc:
        print(json.dumps({"status": "FAILED", "errors": [str(exc)]}, ensure_ascii=False, indent=2))
        return 1
    save(args.out.resolve(), payload)
    print(json.dumps({
        "status": payload["status"],
        "pipelineRunId": payload["pipelineRunId"],
        "jobsManifest": payload["jobsManifest"],
        "executionReport": payload["executionReport"],
        "consumerReport": payload["consumerReport"],
        "out": str(args.out.resolve()),
    }, ensure_ascii=False, indent=2))
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
