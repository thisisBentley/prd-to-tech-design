#!/usr/bin/env python3
"""Execute every frozen Audit Track job in an isolated worker process."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from build_audit_plan import artifact_snapshot, snapshot_sha256
from validate_json_schemas import load, validate

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_ROOT = ROOT / "schemas" if (ROOT / "schemas").exists() else ROOT / "references"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def schema_errors(name: str, value: dict[str, Any]) -> list[str]:
    schema = load(SCHEMA_ROOT / name)
    return validate(value, schema, schema)


def path_safe(value: str) -> bool:
    return bool(value) and "/" not in value and "\\" not in value and ".." not in value


def result_identity_errors(result: dict[str, Any], plan: dict[str, Any], plan_hash: str, job: dict[str, Any], context_id: str) -> list[str]:
    errors: list[str] = []
    for field, expected in (
        ("jobId", job["jobId"]),
        ("auditPlanSha256", plan_hash),
        ("workflowId", plan["workflowId"]),
        ("revision", plan["revision"]),
        ("policyLockSha256", plan["policyLockSha256"]),
        ("executorType", job["executorType"]),
        ("executorContextId", context_id),
        ("independentContext", True),
    ):
        if result.get(field) != expected:
            errors.append(f"{field} does not match the frozen job")
    bound_rules = set(job.get("sourcePolicyRuleIds", []))
    observed = {
        rule_id
        for check in result.get("checks", [])
        for rule_id in check.get("policyRuleIds", [])
    }
    missing = sorted(bound_rules - observed)
    unknown = sorted(observed - bound_rules)
    if missing:
        errors.append("checks omit bound rules: " + ", ".join(missing))
    if unknown:
        errors.append("checks report rules outside the job scope: " + ", ".join(unknown))
    return errors


def reject_result(path: Path, reason: str) -> None:
    if not path.exists():
        return
    target = path.with_name(path.name.replace(".result.json", ".rejected.json"))
    counter = 2
    while target.exists():
        target = path.with_name(f"{path.name.replace('.result.json', '')}.rejected-{counter}.json")
        counter += 1
    path.replace(target)
    transcript = path.with_name(path.name.replace(".result.json", ".rejection.txt"))
    transcript.write_text(reason.rstrip() + "\n", encoding="utf-8")


def write_job_envelope(path: Path, plan_path: Path, plan_hash: str, plan: dict[str, Any], job: dict[str, Any], context_id: str) -> dict[str, Any]:
    envelope = {
        "schemaVersion": 1,
        "auditRunId": "",
        "executorContextId": context_id,
        "workflowId": plan["workflowId"],
        "revision": plan["revision"],
        "auditPlanPath": str(plan_path),
        "auditPlanSha256": plan_hash,
        "artifactRoot": plan["artifactRoot"],
        "policyLockPath": plan["policyLockPath"],
        "policyLockSha256": plan["policyLockSha256"],
        "job": job,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(envelope, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return envelope


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--worker", nargs="+", required=True, help="Worker command; --job and --out are appended.")
    parser.add_argument("--out-dir", type=Path)
    parser.add_argument("--summary", type=Path, help="Aggregate all results into this Audit Summary after execution.")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--timeout", type=float, default=300)
    parser.add_argument("--resume", action="store_true", help="Reuse existing results bound to the same plan hash.")
    args = parser.parse_args()

    run_root = args.run_root.resolve()
    plan_path = args.plan.resolve()
    plan = load(plan_path)
    plan_hash = digest(plan_path)
    out_dir = args.out_dir.resolve() if args.out_dir else (run_root / ".agents" / "audit" / "results")
    jobs_dir = out_dir.parent / "job-inputs"
    transcripts_dir = out_dir.parent / "transcripts"
    report_path = args.report.resolve() if args.report else (out_dir.parent / "audit-runner-report.json")
    started_at = now()
    errors: list[str] = []
    errors.extend(schema_errors("audit-plan.schema.json", plan))
    if plan.get("status") != "READY":
        errors.append(f"audit plan status is {plan.get('status')}")
    state_path = run_root / ".agents" / "orchestration.json"
    if state_path.exists() and plan.get("workflowId") != load(state_path).get("workflowId"):
        errors.append("audit plan workflowId does not match orchestration state")
    artifact_root_value = str(plan.get("artifactRoot", ""))
    artifact_root = Path(artifact_root_value).resolve() if artifact_root_value else None
    expected_snapshot = plan.get("artifactHashes") or {}
    current_snapshot = artifact_snapshot(artifact_root) if artifact_root and artifact_root.is_dir() else {}
    before_hash = snapshot_sha256(current_snapshot)
    expected_hash = snapshot_sha256(expected_snapshot)
    if current_snapshot != expected_snapshot:
        errors.append("artifact snapshot changed after the audit plan was frozen")

    jobs = plan.get("jobs", [])
    seen_ids: set[str] = set()
    for job in jobs:
        job_id = str(job.get("jobId", ""))
        if not path_safe(job_id):
            errors.append(f"unsafe audit jobId: {job_id}")
        if job_id in seen_ids:
            errors.append(f"duplicate audit jobId: {job_id}")
        seen_ids.add(job_id)

    job_reports: list[dict[str, Any]] = []
    if errors:
        for job in jobs:
            job_reports.append({
                "jobId": job.get("jobId", "UNKNOWN"),
                "executorType": job.get("executorType", "SEMANTIC"),
                "executorContextId": "not-started",
                "status": "FAILED",
                "resultPath": "NOT_CREATED",
                "transcriptPath": "NOT_CREATED",
                "artifactStable": current_snapshot == expected_snapshot,
                "artifactSnapshotSha256Before": before_hash,
                "artifactSnapshotSha256After": before_hash,
                "error": "; ".join(errors),
                "startedAt": started_at,
                "finishedAt": now(),
            })
        run_status = "BLOCKED"
        audit_status = "AUDIT_BLOCKED"
    else:
        out_dir.mkdir(parents=True, exist_ok=True)
        jobs_dir.mkdir(parents=True, exist_ok=True)
        transcripts_dir.mkdir(parents=True, exist_ok=True)
        existing = [path for path in out_dir.glob("*.result.json")]
        if existing and not args.resume:
            errors.append("audit results already exist; use --resume to continue or choose a new output directory")
            for job in jobs:
                job_reports.append({
                    "jobId": job["jobId"],
                    "executorType": job["executorType"],
                    "executorContextId": "not-started",
                    "status": "FAILED",
                    "resultPath": str(out_dir / f"{job['jobId']}.result.json"),
                    "transcriptPath": str(transcripts_dir / f"{job['jobId']}.log"),
                    "artifactStable": True,
                    "artifactSnapshotSha256Before": before_hash,
                    "artifactSnapshotSha256After": before_hash,
                    "error": errors[-1],
                    "startedAt": started_at,
                    "finishedAt": now(),
                })
        for job in jobs:
            if errors:
                break
            job_id = job["jobId"]
            result_path = out_dir / f"{job_id}.result.json"
            transcript_path = transcripts_dir / f"{job_id}.log"
            job_input_path = jobs_dir / f"{job_id}.job.json"
            context_id = f"{plan['workflowId']}:{plan['revision']}:{job_id}:{secrets.token_hex(8)}"
            started = now()
            before = artifact_snapshot(Path(plan["artifactRoot"]))
            before_digest = snapshot_sha256(before)
            record: dict[str, Any] = {
                "jobId": job_id,
                "executorType": job["executorType"],
                "executorContextId": context_id,
                "status": "FAILED",
                "resultPath": str(result_path),
                "transcriptPath": str(transcript_path),
                "artifactStable": False,
                "artifactSnapshotSha256Before": before_digest,
                "artifactSnapshotSha256After": before_digest,
                "startedAt": started,
                "finishedAt": started,
            }
            if before != expected_snapshot:
                record["error"] = "artifact snapshot changed before job execution"
                record["finishedAt"] = now()
                job_reports.append(record)
                errors.append(f"{job_id}: {record['error']}")
                break
            if args.resume and result_path.exists():
                try:
                    result = load(result_path)
                    issues = schema_errors("audit-result.schema.json", result)
                    issues.extend(result_identity_errors(result, plan, plan_hash, job, result.get("executorContextId", "")))
                except Exception as exc:
                    issues = [f"invalid existing result: {exc}"]
                if issues:
                    errors.append(f"{job_id}: existing result cannot be resumed: {'; '.join(issues)}")
                else:
                    record.update({
                        "executorContextId": result["executorContextId"],
                        "status": "RESUMED",
                        "resultStatus": result["status"],
                        "artifactStable": True,
                        "artifactSnapshotSha256After": snapshot_sha256(artifact_snapshot(Path(plan["artifactRoot"]))),
                        "finishedAt": now(),
                    })
                    job_reports.append(record)
                    continue
            envelope = write_job_envelope(job_input_path, plan_path, plan_hash, plan, job, context_id)
            envelope["auditRunId"] = f"audit-run-{plan['workflowId']}-{plan['revision']}"
            job_input_path.write_text(json.dumps(envelope, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            env = os.environ.copy()
            env.update({
                "AI_NATIVE_AUDIT_PLAN": str(plan_path),
                "AI_NATIVE_AUDIT_PLAN_SHA256": plan_hash,
                "AI_NATIVE_AUDIT_JOB": str(job_input_path),
                "AI_NATIVE_AUDIT_JOB_ID": job_id,
                "AI_NATIVE_AUDIT_RESULT_PATH": str(result_path),
                "AI_NATIVE_AUDIT_TRANSCRIPT_PATH": str(transcript_path),
                "AI_NATIVE_AUDIT_CONTEXT_ID": context_id,
                "AI_NATIVE_RUN_ROOT": str(run_root),
                "AI_NATIVE_ARTIFACT_ROOT": plan["artifactRoot"],
                "AI_NATIVE_POLICY_LOCK": plan["policyLockPath"],
                "AI_NATIVE_WORKFLOW_ID": plan["workflowId"],
                "AI_NATIVE_REVISION": plan["revision"],
            })
            argv = [*args.worker, "--job", str(job_input_path), "--out", str(result_path)]
            completed = None
            try:
                completed = subprocess.run(
                    argv, cwd=run_root, env=env, text=True, capture_output=True,
                    timeout=args.timeout, check=False,
                )
                transcript_path.write_text((completed.stdout or "") + (completed.stderr or ""), encoding="utf-8")
                record["exitCode"] = completed.returncode
            except subprocess.TimeoutExpired as exc:
                stdout = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
                stderr = exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or "")
                transcript_path.write_text(stdout + stderr, encoding="utf-8")
                record["error"] = f"worker timed out after {args.timeout}s"
            except Exception as exc:
                transcript_path.write_text(str(exc) + "\n", encoding="utf-8")
                record["error"] = f"worker launch failed: {exc}"
            after = artifact_snapshot(Path(plan["artifactRoot"]))
            after_digest = snapshot_sha256(after)
            record["artifactSnapshotSha256After"] = after_digest
            record["artifactStable"] = after == before
            if not record["artifactStable"]:
                record["error"] = "worker changed the frozen artifact snapshot"
                reject_result(result_path, record["error"])
            if completed is not None and completed.returncode != 0 and "error" not in record:
                record["error"] = f"worker exited with code {completed.returncode}"
            issues: list[str] = []
            if result_path.exists():
                try:
                    result = load(result_path)
                    issues.extend(schema_errors("audit-result.schema.json", result))
                    issues.extend(result_identity_errors(result, plan, plan_hash, job, context_id))
                    if result.get("status") == "PASS":
                        if any(check.get("status") != "passed" for check in result.get("checks", [])):
                            issues.append("PASS result contains non-passing checks")
                        if any(finding.get("severity") == "BLOCKING" for finding in result.get("findings", [])):
                            issues.append("PASS result contains a blocking finding")
                    record["resultStatus"] = result.get("status")
                except Exception as exc:
                    issues.append(f"invalid audit result: {exc}")
            elif "error" not in record:
                issues.append("worker did not create the required audit result")
            if issues:
                record["error"] = "; ".join(filter(None, [record.get("error"), *issues]))
            if record.get("error"):
                reject_result(result_path, record["error"])
                errors.append(f"{job_id}: {record['error']}")
            else:
                record["status"] = "EXECUTED"
            record["finishedAt"] = now()
            job_reports.append(record)
        after_hash = snapshot_sha256(artifact_snapshot(Path(plan["artifactRoot"])))
        if after_hash != expected_hash:
            errors.append("artifact snapshot changed during audit execution")
        run_status = "BLOCKED" if errors else "COMPLETE"
        audit_status = "NOT_AGGREGATED"
        if args.summary and not errors:
            summary_path = args.summary.resolve()
            aggregate = subprocess.run(
                [sys.executable, str(ROOT / ("scripts" if ROOT.name == "ai-native-delivery" else "tools") / "validate_audit_results.py"),
                 "--plan", str(plan_path), "--results-dir", str(out_dir), "--out", str(summary_path)],
                cwd=run_root, text=True, capture_output=True, check=False,
            )
            if aggregate.returncode == 0:
                audit_status = "AUDIT_PASS"
            else:
                audit_status = "AUDIT_BLOCKED"
                errors.append("audit aggregation blocked: " + (aggregate.stdout + aggregate.stderr).strip())
        if errors:
            run_status = "BLOCKED"
            audit_status = "AUDIT_BLOCKED"

    finished_at = now()
    report = {
        "schemaVersion": 1,
        "auditRunId": f"audit-run-{plan.get('workflowId')}-{plan.get('revision')}-{secrets.token_hex(4)}",
        "auditPlanSha256": plan_hash,
        "workflowId": plan.get("workflowId"),
        "revision": plan.get("revision"),
        "policyLockSha256": plan.get("policyLockSha256"),
        "artifactRoot": artifact_root_value,
        "artifactSnapshotSha256Before": before_hash,
        "artifactSnapshotSha256After": snapshot_sha256(artifact_snapshot(artifact_root)) if artifact_root and artifact_root.is_dir() else before_hash,
        "worker": args.worker,
        "status": run_status,
        "auditStatus": audit_status if "audit_status" in locals() else "AUDIT_BLOCKED",
        "jobs": job_reports,
        "startedAt": started_at,
        "finishedAt": finished_at,
    }
    issues = schema_errors("audit-run-report.schema.json", report)
    if issues:
        errors.extend(f"runner report: {issue}" for issue in issues)
        report["status"] = "BLOCKED"
        report["auditStatus"] = "AUDIT_BLOCKED"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "auditStatus": report["auditStatus"],
        "jobs": f"{sum(1 for item in job_reports if item['status'] in {'EXECUTED', 'RESUMED'})}/{len(jobs)}",
        "errors": len(errors),
        "report": str(report_path),
    }, ensure_ascii=False))
    return 0 if report["status"] == "COMPLETE" and report["auditStatus"] in {"AUDIT_PASS", "NOT_AGGREGATED"} and not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
