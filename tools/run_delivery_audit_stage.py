#!/usr/bin/env python3
"""Run the pre-finalization Delivery Audit Track against a sealed candidate."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from validate_json_schemas import load as load_schema, validate as validate_schema

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / ("scripts" if (ROOT / "scripts").exists() else "tools")
SCHEMA_ROOT = ROOT / "schemas" if (ROOT / "schemas").exists() else ROOT / "references"
DEFAULT_PROFILE = ROOT / "config" / "audit-profiles" / "prd-prototype.json"
DEFAULT_CROSSWALK = ROOT / "config" / "audit-crosswalk" / "delivery-toolbox-v2.json"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def save(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def validate_stage(value: dict[str, Any]) -> list[str]:
    schema = load_schema(SCHEMA_ROOT / "audit-stage-report.schema.json")
    return validate_schema(value, schema, schema)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(argv: list[str], cwd: Path) -> dict[str, Any]:
    process = subprocess.run(argv, cwd=cwd, text=True, capture_output=True, check=False)
    try:
        payload = json.loads(process.stdout) if process.stdout.strip() else {}
    except json.JSONDecodeError:
        payload = {}
    return {
        "returnCode": process.returncode,
        "stdout": process.stdout,
        "stderr": process.stderr,
        "result": payload,
    }


def validate_candidate(bundle: Path, revision: str) -> tuple[dict[str, Any], Path, list[str]]:
    errors: list[str] = []
    seal_path = bundle / ".delivery" / "candidate-seal.json"
    final_path = bundle / ".delivery" / "final-seal.json"
    if final_path.exists():
        errors.append("final-seal.json already exists; Audit Track must run before finalization")
    if not seal_path.is_file():
        errors.append("candidate-seal.json is required before audit")
        return {}, Path(), errors
    seal = load(seal_path)
    if seal.get("revision") != revision:
        errors.append(f"candidate revision {seal.get('revision')!r} does not match {revision!r}")
    frozen_value = str(seal.get("frozenCopy") or "")
    if not frozen_value:
        errors.append("candidate-seal.frozenCopy is required")
        return seal, Path(), errors
    frozen = Path(frozen_value)
    if not frozen.is_absolute():
        frozen = bundle / frozen
    frozen = frozen.resolve()
    if not frozen.is_dir():
        errors.append(f"candidate frozen copy does not exist: {frozen}")
        return seal, frozen, errors
    hashes = seal.get("artifactHashes") or {}
    if not hashes:
        errors.append("candidate-seal.artifactHashes is empty")
    for name, expected in sorted(hashes.items()):
        path = frozen / name
        if not path.is_file():
            errors.append(f"candidate artifact is missing from frozen copy: {name}")
        elif digest(path) != expected:
            errors.append(f"candidate artifact hash mismatch: {name}")
    return seal, frozen, errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--workflow-id", required=True)
    parser.add_argument("--revision", default="r1")
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument("--crosswalk", type=Path, default=DEFAULT_CROSSWALK)
    parser.add_argument("--worker", nargs="+", default=[sys.executable, str(SCRIPTS / "audit_worker.py")])
    parser.add_argument("--timeout", type=float, default=300)
    parser.add_argument("--out", type=Path, help="Stage result path; defaults to .agents/audit/delivery-audit-stage.json")
    args = parser.parse_args()

    run_root = args.run_root.resolve()
    bundle = args.bundle.resolve()
    dd = bundle / ".delivery"
    out_path = args.out.resolve() if args.out else (run_root / ".agents" / "audit" / "delivery-audit-stage.json")
    started_at = now()
    seal, frozen, errors = validate_candidate(bundle, args.revision)
    stage: dict[str, Any] = {
        "schemaVersion": 1,
        "workflowId": args.workflow_id,
        "revision": args.revision,
        "status": "AUDIT_BLOCKED",
        "orderChecked": True,
        "candidateSealPath": str(dd / "candidate-seal.json"),
        "candidateSealSha256": digest(dd / "candidate-seal.json") if (dd / "candidate-seal.json").is_file() else None,
        "artifactRoot": str(frozen) if frozen else None,
        "auditPlanPath": str(dd / "audit-plan.json"),
        "auditSummaryPath": str(dd / "audit-summary.json"),
        "auditRunnerReportPath": str(dd / "audit-runner-report.json"),
        "plan": None,
        "runner": None,
        "errors": errors,
        "startedAt": started_at,
        "finishedAt": started_at,
    }
    if errors:
        if any("already exists" in item for item in errors):
            stage["status"] = "AUDIT_ORDER_VIOLATION"
        stage["finishedAt"] = now()
        issues = validate_stage(stage)
        if issues:
            stage["errors"].extend(f"stage report: {issue}" for issue in issues)
        save(out_path, stage)
        print(json.dumps({"status": stage["status"], "errors": stage["errors"], "out": str(out_path)}, ensure_ascii=False))
        return 1

    audit_run_dir = dd / "audit-runs" / args.revision
    audit_run_dir.mkdir(parents=True, exist_ok=True)
    plan_path = audit_run_dir / "audit-plan.json"
    plan_run = run([
        sys.executable, str(SCRIPTS / "build_audit_plan.py"),
        "--policy-lock", str(dd / "policy-lock.json"),
        "--artifact-root", str(frozen),
        "--profile", str(args.profile.resolve()),
        "--crosswalk", str(args.crosswalk.resolve()),
        "--workflow-id", args.workflow_id,
        "--revision", args.revision,
        "--out", str(plan_path),
    ], run_root)
    stage["plan"] = plan_run
    if plan_run["returnCode"] != 0 or plan_run.get("result", {}).get("status") != "READY":
        stage["errors"].append("audit plan construction blocked")
        stage["finishedAt"] = now()
        stage["errors"].extend(f"stage report: {issue}" for issue in validate_stage(stage))
        save(out_path, stage)
        print(json.dumps({"status": stage["status"], "errors": stage["errors"], "out": str(out_path)}, ensure_ascii=False))
        return 1

    results_dir = audit_run_dir / "results"
    summary_path = audit_run_dir / "audit-summary.json"
    report_path = audit_run_dir / "audit-runner-report.json"
    runner_run = run([
        sys.executable, str(SCRIPTS / "run_audit_jobs.py"),
        "--run-root", str(run_root),
        "--plan", str(plan_path),
        "--worker", *args.worker,
        "--out-dir", str(results_dir),
        "--summary", str(summary_path),
        "--report", str(report_path),
        "--timeout", str(args.timeout),
    ], run_root)
    stage["runner"] = runner_run
    runner_status = runner_run.get("result", {}).get("auditStatus")
    for source, published in (
        (plan_path, dd / "audit-plan.json"),
        (summary_path, dd / "audit-summary.json"),
        (report_path, dd / "audit-runner-report.json"),
    ):
        if source.exists():
            shutil.copyfile(source, published)
    if runner_run["returnCode"] == 0 and runner_status == "AUDIT_PASS":
        stage["status"] = "AUDIT_PASS"
    else:
        stage["errors"].append(f"audit execution blocked: {runner_run.get('stderr') or runner_run.get('stdout')}")
    stage["finishedAt"] = now()
    stage["errors"].extend(f"stage report: {issue}" for issue in validate_stage(stage))
    if stage["errors"] and stage["status"] == "AUDIT_PASS":
        stage["status"] = "AUDIT_BLOCKED"
    save(out_path, stage)
    print(json.dumps({
        "status": stage["status"],
        "plan": str(plan_path),
        "summary": str(summary_path),
        "runnerReport": str(report_path),
        "stageReport": str(out_path),
        "errors": len(stage["errors"]),
    }, ensure_ascii=False))
    return 0 if stage["status"] == "AUDIT_PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
