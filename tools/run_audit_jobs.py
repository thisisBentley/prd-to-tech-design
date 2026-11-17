#!/usr/bin/env python3
"""Execute every frozen Audit Track job in an isolated worker process."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from build_audit_plan import artifact_snapshot, snapshot_sha256
from validate_json_schemas import load, validate

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_ROOT = ROOT / "schemas" if (ROOT / "schemas").exists() else ROOT / "references"
DEFAULT_BUDGET = ROOT / "config" / "run-budgets" / "default.json"


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
    allowed_units = set(job.get("unitTargets") or [])
    if allowed_units:
        for check in result.get("checks", []):
            unit_ids = set(check.get("unitIds") or [])
            if not unit_ids:
                errors.append(f"{check.get('checkId')}: unitIds are required by the job unit scope")
            unknown_units = sorted(unit_ids - allowed_units)
            if unknown_units:
                errors.append(f"{check.get('checkId')}: unitIds outside job scope: {', '.join(unknown_units)}")
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


def write_budget_escalation(path: Path, plan: dict[str, Any], code: str, message: str, metric: str, limit: float, observed: float, job_id: str | None, evidence_refs: list[str]) -> dict[str, Any]:
    payload = {
        "schemaVersion": 1,
        "escalationId": f"budget-{plan.get('workflowId')}-{plan.get('revision')}-{secrets.token_hex(4)}",
        "workflowId": plan.get("workflowId"),
        "revision": plan.get("revision"),
        "status": "OPEN",
        "code": code,
        "message": message,
        "metric": metric,
        "limit": limit,
        "observed": observed,
        **({"jobId": job_id} if job_id else {}),
        "evidenceRefs": evidence_refs or ["audit-plan"],
        "createdAt": now(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def write_job_envelope(path: Path, plan_path: Path, plan_hash: str, plan: dict[str, Any], job: dict[str, Any], context_id: str, artifact_root: Path, policy_lock_path: Path, source_artifact_root: Path) -> dict[str, Any]:
    envelope = {
        "schemaVersion": 1,
        "auditRunId": "",
        "executorContextId": context_id,
        "workflowId": plan["workflowId"],
        "revision": plan["revision"],
        "auditPlanPath": str(plan_path),
        "auditPlanSha256": plan_hash,
        "artifactRoot": str(artifact_root),
        "sourceArtifactRoot": str(source_artifact_root),
        "policyLockPath": str(policy_lock_path),
        "policyLockSha256": plan["policyLockSha256"],
        "job": job,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(envelope, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return envelope


def prepare_job_view(view_root: Path, source_root: Path, plan_path: Path, plan: dict[str, Any], job: dict[str, Any]) -> tuple[Path, Path, Path, Path]:
    if view_root.exists():
        shutil.rmtree(view_root)
    artifacts_dir = view_root / "artifacts"
    context_dir = view_root / ".audit-context"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    context_dir.mkdir(parents=True, exist_ok=True)
    selected = list(job.get("inputFiles") or sorted(plan.get("artifactHashes", {})))
    copied: list[dict[str, Any]] = []
    source_resolved = source_root.resolve()
    for relative in selected:
        candidate = (source_resolved / relative).resolve()
        try:
            candidate.relative_to(source_resolved)
        except ValueError:
            raise ValueError(f"job input path escapes artifact root: {relative}")
        if not candidate.is_file():
            raise FileNotFoundError(f"job input file missing: {relative}")
        destination = artifacts_dir / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(candidate, destination)
        copied.append({"path": relative, "sha256": digest(destination)})
    policy_source = Path(plan["policyLockPath"]).resolve()
    if not policy_source.is_file():
        raise FileNotFoundError(f"policy lock missing: {policy_source}")
    policy_target = context_dir / "policy-lock.json"
    shutil.copy2(policy_source, policy_target)
    minimal_plan = {
        key: plan.get(key) for key in (
            "schemaVersion", "auditPlanId", "workflowId", "revision", "artifactRoot", "artifactHashes",
            "policyLockPath", "policyLockSha256", "profileId", "profileVersion", "crosswalkId", "crosswalkVersion",
            "crosswalkSha256", "blockingFindingPolicy", "status", "errors", "createdAt"
        )
    }
    minimal_plan["jobs"] = [job]
    minimal_plan["coverage"] = plan.get("coverage")
    minimal_plan_path = context_dir / "audit-plan.json"
    minimal_plan_path.write_text(json.dumps(minimal_plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest = {
        "schemaVersion": 1,
        "jobId": job["jobId"],
        "sourceArtifactRoot": str(source_root),
        "sourcePlanPath": str(plan_path),
        "sourcePlanSha256": digest(plan_path),
        "inputSelectionBasis": list(job.get("inputSelectionBasis") or []),
        "files": copied,
    }
    manifest_path = context_dir / "input-manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return artifacts_dir, context_dir / "policy-lock.json", minimal_plan_path, manifest_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--worker", nargs="+", required=True, help="Worker command; --job and --out are appended.")
    parser.add_argument("--out-dir", type=Path)
    parser.add_argument("--summary", type=Path, help="Aggregate all results into this Audit Summary after execution.")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--timeout", type=float)
    parser.add_argument("--resume", action="store_true", help="Reuse existing results bound to the same plan hash.")
    parser.add_argument("--budget", type=Path, default=DEFAULT_BUDGET)
    parser.add_argument("--max-total-seconds", type=float)
    parser.add_argument("--max-context-files", type=int)
    parser.add_argument("--max-transcript-bytes", type=int)
    parser.add_argument("--telemetry", type=Path)
    parser.add_argument("--escalation-out", type=Path)
    args = parser.parse_args()

    run_root = args.run_root.resolve()
    plan_path = args.plan.resolve()
    plan = load(plan_path)
    plan_hash = digest(plan_path)
    budget_doc = load(args.budget.resolve()) if args.budget and args.budget.is_file() else {}
    budget = {
        "budgetName": str(budget_doc.get("budgetName") or "CLI_DEFAULT"),
        "maxTotalSeconds": float(args.max_total_seconds if args.max_total_seconds is not None else budget_doc.get("maxTotalSeconds", 3600)),
        "maxJobSeconds": float(args.timeout if args.timeout is not None else budget_doc.get("maxJobSeconds", 300)),
        "maxContextFiles": int(args.max_context_files if args.max_context_files is not None else budget_doc.get("maxContextFiles", 200)),
        "maxTranscriptBytes": int(args.max_transcript_bytes if args.max_transcript_bytes is not None else budget_doc.get("maxTranscriptBytes", 10_000_000)),
        "maxRepairRounds": int(budget_doc.get("maxRepairRounds", 2)),
    }
    out_dir = args.out_dir.resolve() if args.out_dir else (run_root / ".agents" / "audit" / "results")
    jobs_dir = out_dir.parent / "job-inputs"
    transcripts_dir = out_dir.parent / "transcripts"
    report_path = args.report.resolve() if args.report else (out_dir.parent / "audit-runner-report.json")
    telemetry_path = args.telemetry.resolve() if args.telemetry else (out_dir.parent / "run-cost-telemetry.json")
    escalation_path = args.escalation_out.resolve() if args.escalation_out else (out_dir.parent / "run-budget-escalation.json")
    started_at = now()
    started_monotonic = time.monotonic()
    errors: list[str] = []
    telemetry_jobs: list[dict[str, Any]] = []
    escalation: dict[str, Any] | None = None
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
            job_view_root = jobs_dir / job_id
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
            try:
                job_artifact_root, job_policy_lock, job_plan_path, input_manifest_path = prepare_job_view(
                    job_view_root, Path(plan["artifactRoot"]), plan_path, plan, job,
                )
                job_view_before = artifact_snapshot(job_artifact_root)
                job_view_before_hash = snapshot_sha256(job_view_before)
                record.update({
                    "inputManifestPath": str(input_manifest_path),
                    "inputManifestSha256": digest(input_manifest_path),
                    "inputFileCount": len(job.get("inputFiles") or plan.get("artifactHashes", {})),
                    "jobViewSha256Before": job_view_before_hash,
                    "jobViewSha256After": job_view_before_hash,
                })
                if record["inputFileCount"] > budget["maxContextFiles"]:
                    observed = record["inputFileCount"]
                    limit = budget["maxContextFiles"]
                    record["error"] = f"context file budget exceeded: {observed} > {limit}"
                    record["finishedAt"] = now()
                    telemetry_jobs.append({
                        "jobId": job_id, "status": "BUDGET_BLOCKED", "durationMs": 0,
                        "inputFileCount": observed, "transcriptBytes": 0, "estimatedTokens": 0,
                        "budgetExceeded": "maxContextFiles",
                    })
                    escalation = write_budget_escalation(escalation_path, plan, "BUDGET_EXCEEDED", record["error"], "maxContextFiles", limit, observed, job_id, [str(input_manifest_path)])
                    job_reports.append(record)
                    errors.append(f"{job_id}: {record['error']}")
                    break
            except Exception as exc:
                record["error"] = f"job input view could not be prepared: {exc}"
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
                    telemetry_jobs.append({
                        "jobId": job_id, "status": "RESUMED", "durationMs": 0,
                        "inputFileCount": record.get("inputFileCount", 0), "transcriptBytes": 0, "estimatedTokens": 0,
                    })
                    job_reports.append(record)
                    continue
            envelope = write_job_envelope(job_input_path, job_plan_path, plan_hash, plan, job, context_id, job_artifact_root, job_policy_lock, Path(plan["artifactRoot"]))
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
                "AI_NATIVE_ARTIFACT_ROOT": str(job_artifact_root),
                "AI_NATIVE_POLICY_LOCK": str(job_policy_lock),
                "AI_NATIVE_WORKFLOW_ID": plan["workflowId"],
                "AI_NATIVE_REVISION": plan["revision"],
            })
            argv = [*args.worker, "--job", str(job_input_path), "--out", str(result_path)]
            completed = None
            job_started_monotonic = time.monotonic()
            try:
                completed = subprocess.run(
                    argv, cwd=run_root, env=env, text=True, capture_output=True,
                    timeout=budget["maxJobSeconds"], check=False,
                )
                transcript_path.write_text((completed.stdout or "") + (completed.stderr or ""), encoding="utf-8")
                record["exitCode"] = completed.returncode
            except subprocess.TimeoutExpired as exc:
                stdout = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
                stderr = exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or "")
                transcript_path.write_text(stdout + stderr, encoding="utf-8")
                record["error"] = f"worker timed out after {budget['maxJobSeconds']}s"
                escalation = write_budget_escalation(escalation_path, plan, "JOB_TIMEOUT", record["error"], "maxJobSeconds", budget["maxJobSeconds"], budget["maxJobSeconds"], job_id, [str(job_input_path)])
            except Exception as exc:
                transcript_path.write_text(str(exc) + "\n", encoding="utf-8")
                record["error"] = f"worker launch failed: {exc}"
            after = artifact_snapshot(Path(plan["artifactRoot"]))
            after_digest = snapshot_sha256(after)
            job_view_after = artifact_snapshot(job_artifact_root)
            job_view_after_hash = snapshot_sha256(job_view_after)
            record["artifactSnapshotSha256After"] = after_digest
            record["jobViewSha256After"] = job_view_after_hash
            record["artifactStable"] = after == before and job_view_after == job_view_before
            if not record["artifactStable"]:
                record["error"] = "worker changed the frozen artifact snapshot or its job input view"
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
            transcript_bytes = transcript_path.stat().st_size if transcript_path.is_file() else 0
            duration_ms = round((time.monotonic() - job_started_monotonic) * 1000, 2)
            telemetry_jobs.append({
                "jobId": job_id,
                "status": "BUDGET_BLOCKED" if escalation else record["status"],
                "durationMs": duration_ms,
                "inputFileCount": record.get("inputFileCount", 0),
                "transcriptBytes": transcript_bytes,
                "estimatedTokens": (transcript_bytes + 3) // 4,
                **({"budgetExceeded": escalation["metric"]} if escalation else {}),
            })
            elapsed_seconds = time.monotonic() - started_monotonic
            total_transcript_bytes = sum(item["transcriptBytes"] for item in telemetry_jobs)
            if not escalation and elapsed_seconds > budget["maxTotalSeconds"]:
                escalation = write_budget_escalation(escalation_path, plan, "BUDGET_EXCEEDED", f"total runtime budget exceeded: {elapsed_seconds:.2f}s > {budget['maxTotalSeconds']}s", "maxTotalSeconds", budget["maxTotalSeconds"], elapsed_seconds, job_id, [str(report_path)])
                errors.append(escalation["message"])
            if not escalation and total_transcript_bytes > budget["maxTranscriptBytes"]:
                escalation = write_budget_escalation(escalation_path, plan, "BUDGET_EXCEEDED", f"transcript budget exceeded: {total_transcript_bytes} > {budget['maxTranscriptBytes']}", "maxTranscriptBytes", budget["maxTranscriptBytes"], total_transcript_bytes, job_id, [str(transcripts_dir)])
                errors.append(escalation["message"])
            if escalation:
                break
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
        "telemetryPath": str(telemetry_path),
        **({"escalationPath": str(escalation_path)} if escalation_path.is_file() else {}),
    }
    issues = schema_errors("audit-run-report.schema.json", report)
    if issues:
        errors.extend(f"runner report: {issue}" for issue in issues)
        report["status"] = "BLOCKED"
        report["auditStatus"] = "AUDIT_BLOCKED"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    elapsed_ms = round((time.monotonic() - started_monotonic) * 1000, 2)
    total_transcript = sum(int(item.get("transcriptBytes", 0)) for item in telemetry_jobs)
    telemetry = {
        "schemaVersion": 1,
        "runId": report["auditRunId"],
        "workflowId": plan.get("workflowId"),
        "revision": plan.get("revision"),
        "status": "PASS" if report["status"] == "COMPLETE" and not escalation else "BLOCKED",
        "budget": budget,
        "metrics": {
            "elapsedMs": elapsed_ms,
            "jobs": len(telemetry_jobs),
            "inputFiles": sum(int(item.get("inputFileCount", 0)) for item in telemetry_jobs),
            "transcriptBytes": total_transcript,
            "estimatedTokens": sum(int(item.get("estimatedTokens", 0)) for item in telemetry_jobs),
        },
        "jobs": telemetry_jobs,
        "startedAt": started_at,
        "finishedAt": finished_at,
    }
    telemetry_issues = schema_errors("run-cost-telemetry.schema.json", telemetry)
    if telemetry_issues:
        errors.extend(f"telemetry report: {issue}" for issue in telemetry_issues)
        telemetry["status"] = "BLOCKED"
    telemetry_path.parent.mkdir(parents=True, exist_ok=True)
    telemetry_path.write_text(json.dumps(telemetry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
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
