#!/usr/bin/env python3
"""Codex adapter for one isolated Audit Track job."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from validate_json_schemas import load, validate

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_ROOT = ROOT / "schemas" if (ROOT / "schemas").exists() else ROOT / "references"


def schema_errors(name: str, value: dict[str, Any]) -> list[str]:
    schema = load(SCHEMA_ROOT / name)
    return validate(value, schema, schema)


def result_errors(result: dict[str, Any], envelope: dict[str, Any]) -> list[str]:
    errors = schema_errors("audit-result.schema.json", result)
    job = envelope["job"]
    for field, expected in (
        ("jobId", job["jobId"]),
        ("auditRunId", envelope["auditRunId"]),
        ("auditPlanSha256", envelope["auditPlanSha256"]),
        ("workflowId", envelope["workflowId"]),
        ("revision", envelope["revision"]),
        ("policyLockSha256", envelope["policyLockSha256"]),
        ("executorType", job["executorType"]),
        ("executorContextId", envelope["executorContextId"]),
        ("independentContext", True),
    ):
        if result.get(field) != expected:
            errors.append(f"{field} does not match the frozen audit job")
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
    if result.get("status") == "PASS":
        if any(check.get("status") != "passed" for check in result.get("checks", [])):
            errors.append("PASS result contains non-passing checks")
        if any(finding.get("severity") == "BLOCKING" for finding in result.get("findings", [])):
            errors.append("PASS result contains a blocking finding")
    return errors


def build_prompt(envelope: dict[str, Any], result_path: Path) -> str:
    job = envelope["job"]
    rules = ", ".join(job.get("sourcePolicyRuleIds", [])) or "(global cross-rule review)"
    evidence = "; ".join(job.get("requiredEvidence", []))
    checks = ", ".join(job.get("sourceSkillCheckIds", []))
    return "\n".join([
        "You are an independent Audit Executor. Execute exactly one frozen Audit Track job.",
        "Read only the frozen artifact root, policy lock, audit plan and this job. Do not use any Producer or generation transcript.",
        "Do not modify any artifact, policy, gate result, seal or report. This task is read-only.",
        "Use the named source Skill and check IDs as the audit rule source when available. Do not broaden the job.",
        "Return exactly one compact JSON object matching audit-result.schema.json, without Markdown fences or commentary.",
        "For every bound policyRuleId, return at least one check with non-empty artifact evidenceRefs and status passed|failed|unverified|not_executed|not_applicable.",
        "For every check, include unitIds drawn from the job unitTargets and claim only units actually inspected.",
        "Evidence refs should identify a real relative artifact path or deterministic observation; do not repeat the rule text as evidence.",
        "If any required evidence is missing, unreadable or unexecuted, return status INCOMPLETE, never PASS.",
        "PASS is allowed only when every check passed, every bound rule is covered, and no blocking finding remains.",
        "For EDGE_REVIEW and GLOBAL_INTEGRATION_REVIEW, reports may use an empty policyRuleIds list in checks, but must provide a substantive transcript and evidence.",
        f"AI_NATIVE_AUDIT_PLAN={envelope['auditPlanPath']}",
        f"AI_NATIVE_AUDIT_PLAN_SHA256={envelope['auditPlanSha256']}",
        f"AI_NATIVE_ARTIFACT_ROOT={envelope['artifactRoot']}",
        f"AI_NATIVE_POLICY_LOCK={envelope['policyLockPath']}",
        f"AI_NATIVE_WORKFLOW_ID={envelope['workflowId']}",
        f"AI_NATIVE_REVISION={envelope['revision']}",
        f"AI_NATIVE_JOB_ID={job['jobId']}",
        f"AI_NATIVE_JOB_TYPE={job['jobType']}",
        f"AI_NATIVE_EXECUTOR_TYPE={job['executorType']}",
        f"AI_NATIVE_EXECUTOR_CONTEXT_ID={envelope['executorContextId']}",
        f"AI_NATIVE_SOURCE_SKILL={job['sourceSkillId']}",
        f"AI_NATIVE_SOURCE_CHECKS={checks}",
        f"AI_NATIVE_BOUND_RULES={rules}",
        f"AI_NATIVE_REQUIRED_EVIDENCE={evidence}",
        f"AI_NATIVE_PASS_CONDITION={job['passCondition']}",
        f"AI_NATIVE_RESULT_PATH={result_path}",
    ])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--codex", default=shutil.which("codex") or "codex")
    parser.add_argument("--model")
    parser.add_argument("--timeout", type=float, default=float(os.environ.get("AI_NATIVE_TIMEOUT", "300")))
    parser.add_argument("--allow-human-simulation", action="store_true", help="Test-only: permit an LLM to produce a HUMAN executor result.")
    args = parser.parse_args()

    job_path = args.job.resolve()
    envelope = load(job_path)
    if envelope.get("job", {}).get("executorType") == "HUMAN" and not args.allow_human_simulation:
        print("HUMAN audit jobs require a real human result; an LLM cannot simulate them", file=sys.stderr)
        return 6
    result_path = args.out.resolve()
    result_path.parent.mkdir(parents=True, exist_ok=True)
    transcript_path = Path(os.environ.get("AI_NATIVE_AUDIT_TRANSCRIPT_PATH", result_path.with_suffix(".log"))).resolve()
    transcript_path.parent.mkdir(parents=True, exist_ok=True)
    run_root = Path(os.environ["AI_NATIVE_RUN_ROOT"]).resolve()
    job_artifact_root = Path(envelope.get("artifactRoot") or run_root).resolve()
    prompt = build_prompt(envelope, result_path)
    argv = [
        args.codex, "exec", "--ephemeral", "--skip-git-repo-check", "--ignore-rules",
        "--sandbox", "read-only", "--output-last-message", str(result_path), "-C", str(job_artifact_root),
    ]
    if args.model:
        argv += ["--model", args.model]
    argv.append(prompt)
    completed = subprocess.run(argv, text=True, capture_output=True, timeout=args.timeout, check=False)
    transcript_path.write_text((completed.stdout or "") + (completed.stderr or ""), encoding="utf-8")
    if completed.returncode != 0:
        print(f"codex exited with code {completed.returncode}", file=sys.stderr)
        return completed.returncode
    try:
        result = json.loads(result_path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"invalid audit result JSON: {exc}", file=sys.stderr)
        return 2
    errors = result_errors(result, envelope)
    if errors:
        print(json.dumps({"status": "INVALID", "errors": errors}, ensure_ascii=False), file=sys.stderr)
        return 3
    result["executorId"] = result.get("executorId") or "codex-audit-executor"
    result["checkedAt"] = result.get("checkedAt") or datetime.now(timezone.utc).isoformat()
    result["executorTranscript"] = result.get("executorTranscript") or str(transcript_path)
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "jobId": result["jobId"], "out": str(result_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
