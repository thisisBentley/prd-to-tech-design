#!/usr/bin/env python3
"""Aggregate independent Audit Track results and prove rule coverage."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from validate_json_schemas import load, validate

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_ROOT = ROOT / "schemas" if (ROOT / "schemas").exists() else ROOT / "references"
PASSING_CHECK = "passed"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def schema_errors(name: str, value: dict[str, Any]) -> list[str]:
    schema = load(SCHEMA_ROOT / name)
    return validate(value, schema, schema)


def result_files(results_dir: Path | None, explicit: list[Path]) -> list[Path]:
    paths = [path.resolve() for path in explicit]
    if results_dir:
        base = results_dir.resolve()
        paths.extend(path.resolve() for path in sorted(base.glob("*.json")))
    unique: dict[Path, None] = {}
    for path in paths:
        if path.name in {"audit-plan.json", "audit-summary.json"}:
            continue
        unique[path] = None
    return list(unique)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--results-dir", type=Path)
    parser.add_argument("--result", action="append", type=Path, default=[])
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    plan_path = args.plan.resolve()
    plan = load(plan_path)
    plan_sha = digest(plan_path)
    errors: list[str] = schema_errors("audit-plan.schema.json", plan)
    expected_jobs = {job["jobId"]: job for job in plan.get("jobs", [])}
    paths = result_files(args.results_dir, args.result)
    if not paths:
        errors.append("no audit result files were supplied")

    result_by_job: dict[str, tuple[dict[str, Any], Path]] = {}
    for path in paths:
        try:
            result = load(path)
        except Exception as exc:
            errors.append(f"{path.name}: cannot read JSON: {exc}")
            continue
        issues = schema_errors("audit-result.schema.json", result)
        if issues:
            errors.extend(f"{path.name}: {issue}" for issue in issues)
            continue
        job_id = str(result.get("jobId", ""))
        if job_id not in expected_jobs:
            errors.append(f"{path.name}: unknown audit jobId {job_id}")
            continue
        if job_id in result_by_job:
            errors.append(f"duplicate audit result for {job_id}")
            continue
        result_by_job[job_id] = (result, path)
        for field, expected in (
            ("auditPlanSha256", plan_sha),
            ("workflowId", plan.get("workflowId")),
            ("revision", plan.get("revision")),
            ("policyLockSha256", plan.get("policyLockSha256")),
            ("executorType", expected_jobs[job_id].get("executorType")),
        ):
            if result.get(field) != expected:
                errors.append(f"{job_id}: {field} does not match the frozen audit plan")
        if result.get("independentContext") is not True:
            errors.append(f"{job_id}: independentContext must be true")

    rule_jobs: dict[str, list[str]] = {
        rule_id: []
        for job in expected_jobs.values()
        for rule_id in job.get("sourcePolicyRuleIds", [])
    }
    for job_id, job in expected_jobs.items():
        for rule_id in job.get("sourcePolicyRuleIds", []):
            rule_jobs.setdefault(rule_id, []).append(job_id)

    successful_jobs: set[str] = set()
    failed_jobs: list[str] = []
    blocking_findings = 0
    for job_id, job in expected_jobs.items():
        pair = result_by_job.get(job_id)
        if pair is None:
            continue
        result, _path = pair
        if result.get("status") != "PASS":
            failed_jobs.append(job_id)
            errors.append(f"{job_id}: result status is {result.get('status')}")
            continue
        checks = result.get("checks", [])
        bad_checks = [check.get("checkId") for check in checks if check.get("status") != PASSING_CHECK]
        if bad_checks:
            failed_jobs.append(job_id)
            errors.append(f"{job_id}: non-passing checks: {', '.join(map(str, bad_checks))}")
            continue
        bound_rules = set(job.get("sourcePolicyRuleIds", []))
        observed_rules: set[str] = set()
        for check in checks:
            for rule_id in check.get("policyRuleIds", []):
                if bound_rules and rule_id not in bound_rules:
                    errors.append(f"{job_id}: check reports rule outside its job scope: {rule_id}")
                if rule_id in rule_jobs:
                    observed_rules.add(rule_id)
        missing_rules = sorted(bound_rules - observed_rules)
        if missing_rules:
            failed_jobs.append(job_id)
            errors.append(f"{job_id}: checks omit bound rules: {', '.join(missing_rules)}")
            continue
        findings = result.get("findings", [])
        blocking = sum(1 for finding in findings if finding.get("severity") == "BLOCKING")
        blocking_findings += blocking
        policy = plan.get("blockingFindingPolicy")
        blocking_total = blocking if policy == "BLOCK_BLOCKING" else len(findings)
        if blocking_total:
            failed_jobs.append(job_id)
            errors.append(f"{job_id}: contains {blocking_total} blocking audit findings")
            continue
        successful_jobs.add(job_id)

    missing_jobs = sorted(set(expected_jobs) - set(result_by_job))
    if missing_jobs:
        errors.append(f"missing audit jobs: {', '.join(missing_jobs)}")

    rule_coverage: list[dict[str, Any]] = []
    missing_rules: list[str] = []
    for rule_id in sorted(rule_jobs):
        expected_for_rule = rule_jobs[rule_id]
        covered = sorted(rule_id_job for rule_id_job in expected_for_rule if rule_id_job in successful_jobs)
        if not expected_for_rule:
            status = "MISSING"
            missing_rules.append(rule_id)
        elif len(covered) == len(expected_for_rule):
            status = "COVERED"
        else:
            status = "FAILED"
            missing_rules.append(rule_id)
        rule_coverage.append({
            "ruleId": rule_id,
            "executorTypes": sorted({expected_jobs[job_id].get("executorType") for job_id in expected_for_rule}),
            "jobIds": expected_for_rule,
            "status": status,
        })

    completed = len(result_by_job)
    passed = (
        plan.get("status") == "READY"
        and not errors
        and not missing_jobs
        and not failed_jobs
        and not missing_rules
        and completed == len(expected_jobs)
    )
    summary = {
        "schemaVersion": 1,
        "auditSummaryId": f"audit-summary-{plan.get('workflowId')}-{plan.get('revision')}",
        "auditPlanSha256": plan_sha,
        "workflowId": plan.get("workflowId"),
        "revision": plan.get("revision"),
        "policyLockSha256": plan.get("policyLockSha256"),
        "profileId": plan.get("profileId"),
        "status": "AUDIT_PASS" if passed else "AUDIT_BLOCKED",
        "expectedJobs": len(expected_jobs),
        "completedJobs": completed,
        "expectedRules": len(rule_jobs),
        "coveredRules": sum(1 for item in rule_coverage if item["status"] == "COVERED"),
        "missingJobs": missing_jobs,
        "missingRules": missing_rules,
        "failedJobs": sorted(set(failed_jobs)),
        "blockingFindingCount": blocking_findings,
        "jobs": [
            {
                "jobId": job_id,
                "status": result_by_job[job_id][0].get("status", "UNKNOWN") if job_id in result_by_job else "MISSING",
                "resultPath": str(result_by_job[job_id][1]) if job_id in result_by_job else "MISSING",
                "coveredRules": list(expected_jobs[job_id].get("sourcePolicyRuleIds", [])),
            }
            for job_id in sorted(expected_jobs)
        ],
        "ruleCoverage": rule_coverage,
        "errors": errors,
        "checkedAt": datetime.now(timezone.utc).isoformat(),
    }
    errors.extend(schema_errors("audit-summary.schema.json", summary))
    if errors:
        summary["status"] = "AUDIT_BLOCKED"
        summary["errors"] = errors
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": summary["status"],
        "jobs": f"{summary['completedJobs']}/{summary['expectedJobs']}",
        "rules": f"{summary['coveredRules']}/{summary['expectedRules']}",
        "blockingFindings": summary["blockingFindingCount"],
        "errors": len(errors),
        "out": str(args.out),
    }, ensure_ascii=False))
    return 0 if summary["status"] == "AUDIT_PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
