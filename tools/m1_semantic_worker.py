#!/usr/bin/env python3
"""Execute one semantic M1 task with a Codex subprocess and materialize its contract.

The adapter intentionally remains narrow: it accepts a frozen Agent Task manifest,
runs one bounded Codex call, validates the returned structured envelope, and writes
either a PRD artifact or a canonical Review Result.  It never approves a task by
itself and never bypasses the deterministic final gatekeeper.
"""
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

REVIEW_VERDICTS = {"ACCEPTED", "ACCEPTED_WITH_ACTIONS", "RETURNED", "BLOCKED", "INCOMPLETE"}
REVIEWER_ROLES = {
    "delivery-reviewer",
    "qa-red-team",
    "tech-prd-diagnostician",
    "final-package-reviewer",
}
REVIEW_SEVERITIES = {"BLOCKING", "NON_BLOCKING", "INFO"}
CHECK_STATUSES = {"passed", "failed", "not_applicable", "unverified", "not_executed"}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def absolute_input(root: Path, value: str) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def input_paths(root: Path, task: dict[str, Any]) -> list[str]:
    return [str(absolute_input(root, item["path"])) for item in task.get("inputs", [])]


def slug(value: str) -> str:
    cleaned = "".join(char.lower() if char.isalnum() else "-" for char in value)
    return "-".join(part for part in cleaned.split("-") if part) or "root-cause"


def build_prompt(task: dict[str, Any], paths: list[str], result_path: Path, review_path: Path, artifact_path: Path) -> str:
    role = task.get("role", "")
    if role in {"prd-producer", "prd-repair-agent"}:
        instruction = (
            "Produce one complete Markdown PRD in the field prdMarkdown. Use only facts in the supplied input paths. "
            "The PRD must contain Requirement Summary, Functional Requirements with stable FR ids, Acceptance Criteria with stable AC ids, "
            "Non-Goals, Permissions, States, Exceptions and Recovery. Preserve all supplied business facts and do not invent new ones."
        )
        required = (
            "Return exactly one compact JSON object with schemaVersion=1, status='SUCCEEDED', taskId=AI_NATIVE_TASK_ID, role=AI_NATIVE_ROLE, "
            "outputs=[{'path':'PRD_DELIVERY.md','kind':'PRD'}], prdArtifactPath=AI_NATIVE_ARTIFACT_PATH, prdMarkdown=<complete markdown>, "
            "and evidenceRefs=AI_NATIVE_INPUT_PATHS."
        )
    elif role in REVIEWER_ROLES:
        instruction = (
            "Independently review the frozen PRD and all supplied evidence. Check factual coverage, traceability, permissions, states, "
            "acceptance criteria, non-goals, technical feasibility, and internal consistency. Do not modify frozen inputs."
        )
        required = (
            "Return exactly one compact JSON object with schemaVersion=1, status='SUCCEEDED', taskId=AI_NATIVE_TASK_ID, role=AI_NATIVE_ROLE, "
            "outputs=[{'path':'review-result','kind':'review-result'}], reviewResult=<review object>, and evidenceRefs=AI_NATIVE_INPUT_PATHS. "
            "The review object must contain schemaVersion=1, reviewerRole=AI_NATIVE_ROLE, verdict ('ACCEPTED' or 'RETURNED'), completionStatus='complete', "
            "blockingCount equal to the number of BLOCKING findings, evidenceRefs, checks, and findings. "
            "Each check requires checkId, status, evidenceRefs, observed and expected. "
            "Each finding requires findingId, severity ('BLOCKING','NON_BLOCKING','INFO'), title, evidenceRefs, impact, closeCondition, owner, "
            "rootCauseId, repairClass, expectedInvariant and regressionTests. Return findings=[] and blockingCount=0 only when evidence supports ACCEPTED."
        )
    else:
        instruction = "Execute the bounded task analytically without commands or file writes."
        required = (
            "Return exactly one compact JSON object with schemaVersion=1, status='SUCCEEDED', taskId=AI_NATIVE_TASK_ID, role=AI_NATIVE_ROLE, "
            "outputs covering every expected output, and evidenceRefs=AI_NATIVE_INPUT_PATHS."
        )
    return "\n".join([
        "You are executing one bounded AI-Native Agile Product-Engineering M1 task.",
        instruction,
        required,
        "Read the supplied input paths directly. Return compact JSON only, without Markdown fences or commentary.",
        f"AI_NATIVE_TASK_ID={task.get('taskId', '')}",
        f"AI_NATIVE_ROLE={role}",
        "AI_NATIVE_INPUT_PATHS=" + ",".join(paths),
        f"AI_NATIVE_RESULT_PATH={result_path}",
        f"AI_NATIVE_REVIEW_PATH={review_path}",
        f"AI_NATIVE_ARTIFACT_PATH={artifact_path}",
    ])


def review_errors(review: Any, task: dict[str, Any]) -> list[str]:
    if not isinstance(review, dict):
        return ["reviewResult must be a JSON object"]
    errors: list[str] = []
    if review.get("schemaVersion") != 1:
        errors.append("reviewResult.schemaVersion must equal 1")
    expected_role = task.get("role")
    if expected_role in REVIEWER_ROLES and review.get("reviewerRole") != expected_role:
        errors.append("reviewResult.reviewerRole must match the task role")
    if review.get("verdict") not in REVIEW_VERDICTS:
        errors.append("reviewResult.verdict is invalid")
    if review.get("completionStatus") != "complete":
        errors.append("reviewResult.completionStatus must be complete")
    findings = review.get("findings")
    if not isinstance(findings, list):
        errors.append("reviewResult.findings must be an array")
        findings = []
    blocking = sum(1 for item in findings if isinstance(item, dict) and item.get("severity") == "BLOCKING")
    if review.get("blockingCount") != blocking:
        errors.append("reviewResult.blockingCount must equal BLOCKING findings")
    if review.get("verdict") in {"ACCEPTED"} and blocking:
        errors.append("ACCEPTED review must not contain BLOCKING findings")
    if review.get("verdict") in {"RETURNED", "BLOCKED"} and not blocking:
        errors.append(f"{review.get('verdict')} review requires at least one BLOCKING finding")
    checks = review.get("checks")
    if not isinstance(checks, list) or not checks:
        errors.append("reviewResult.checks must be a non-empty array")
    else:
        for index, check in enumerate(checks):
            if not isinstance(check, dict) or not check.get("checkId") or check.get("status") not in CHECK_STATUSES:
                errors.append(f"checks[{index}] requires checkId and a valid status")
            if not isinstance(check.get("evidenceRefs"), list) or not check["evidenceRefs"]:
                errors.append(f"checks[{index}] requires evidenceRefs")
            if not isinstance(check.get("observed"), str) or not check["observed"]:
                errors.append(f"checks[{index}] requires observed")
            if not isinstance(check.get("expected"), str) or not check["expected"]:
                errors.append(f"checks[{index}] requires expected")
    required_finding = [
        "findingId", "severity", "title", "evidenceRefs", "impact", "closeCondition", "owner",
        "rootCauseId", "repairClass", "expectedInvariant", "regressionTests",
    ]
    for index, finding in enumerate(findings):
        if not isinstance(finding, dict):
            errors.append(f"findings[{index}] must be an object")
            continue
        for key in required_finding:
            value = finding.get(key)
            if key == "regressionTests" and (not isinstance(value, list) or not value):
                errors.append(f"findings[{index}].regressionTests must be non-empty")
            elif key == "evidenceRefs" and (not isinstance(value, list) or not value):
                errors.append(f"findings[{index}].evidenceRefs must be non-empty")
            elif key != "regressionTests" and key != "evidenceRefs" and (not isinstance(value, str) or not value):
                errors.append(f"findings[{index}] requires {key}")
        if finding.get("severity") not in REVIEW_SEVERITIES:
            errors.append(f"findings[{index}].severity is invalid")
        if finding.get("repairClass") not in {"SEMANTIC", "ARTIFACT_CONTRACT", "VISIBLE_INTERACTION", "RUNTIME", "EVIDENCE"}:
            errors.append(f"findings[{index}].repairClass is invalid")
    return errors


def canonical_review(task: dict[str, Any], review: dict[str, Any], paths: list[str], context_id: str, transcript_path: Path, revision: str) -> dict[str, Any]:
    result = {
        "schemaVersion": 1,
        "reviewRunId": "REV-" + hashlib.sha256((task.get("taskId", "") + context_id + transcript_path.read_text(encoding="utf-8")[-1000:]).encode()).hexdigest()[:16],
        "reviewPlanId": "RP-" + task.get("workflowId", "WF"),
        "workflowId": task.get("workflowId", ""),
        "producerRole": "prd-producer",
        "reviewerRole": task.get("role", ""),
        "reviewType": "independent",
        "targetHandoffId": "HO-" + task.get("workflowId", "WF") + "-" + task.get("taskId", "TASK"),
        "targetRevision": revision,
        "independentContext": True,
        "verdict": review.get("verdict"),
        "completionStatus": "complete",
        "checks": review.get("checks", []),
        "findings": review.get("findings", []),
        "blockingCount": int(review.get("blockingCount", 0)),
        "evidenceRefs": review.get("evidenceRefs") or paths,
        "reviewerContextId": context_id,
        "reviewerTranscript": str(transcript_path),
        "checkedAt": datetime.now(timezone.utc).isoformat(),
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex", default=shutil.which("codex") or "codex")
    parser.add_argument("--model")
    parser.add_argument("--timeout", type=float, default=float(os.environ.get("AI_NATIVE_TIMEOUT", "300")))
    args = parser.parse_args()

    manifest_path = Path(os.environ["AI_NATIVE_TASK_MANIFEST"]).resolve()
    task = load_json(manifest_path)
    root = Path(os.environ["AI_NATIVE_RUN_ROOT"]).resolve()
    result_path = Path(os.environ["AI_NATIVE_RESULT_PATH"]).resolve()
    artifact_path = Path(os.environ["AI_NATIVE_ARTIFACT_PATH"]).resolve()
    review_path = Path(os.environ["AI_NATIVE_REVIEW_PATH"]).resolve()
    transcript_path = Path(os.environ["AI_NATIVE_TRANSCRIPT_PATH"]).resolve()
    context_id = os.environ["AI_NATIVE_CONTEXT_ID"]
    revision = os.environ.get("AI_NATIVE_TARGET_REVISION", "r1")
    paths = input_paths(root, task)

    result_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    review_path.parent.mkdir(parents=True, exist_ok=True)
    transcript_path.parent.mkdir(parents=True, exist_ok=True)

    prompt = build_prompt(task, paths, result_path, review_path, artifact_path)
    role = task.get("role", "")
    sandbox = "workspace-write" if role in {"prd-producer", "prd-repair-agent"} else "read-only"
    argv = [
        args.codex, "exec", "--ephemeral", "--skip-git-repo-check", "--ignore-rules",
        "--sandbox", sandbox, "--output-last-message", str(result_path), "-C", str(root),
    ]
    if args.model:
        argv.extend(["--model", args.model])
    argv.append(prompt)
    try:
        completed = subprocess.run(argv, cwd=root, text=True, capture_output=True, timeout=args.timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        transcript_path.write_text(str(exc.stdout or "") + str(exc.stderr or ""), encoding="utf-8")
        print(f"codex timeout after {args.timeout}s", file=sys.stderr)
        return 124
    transcript_path.write_text(completed.stdout + completed.stderr, encoding="utf-8")
    if completed.returncode != 0:
        print(f"codex exited with code {completed.returncode}", file=sys.stderr)
        return completed.returncode
    try:
        result = load_json(result_path)
    except Exception as exc:
        print(f"invalid codex result JSON: {exc}", file=sys.stderr)
        return 2
    if not isinstance(result, dict) or result.get("schemaVersion") != 1 or result.get("status") != "SUCCEEDED" or not isinstance(result.get("outputs"), list) or not result["outputs"]:
        print("codex result violates the structured envelope", file=sys.stderr)
        return 3

    if role in {"prd-producer", "prd-repair-agent"}:
        markdown = result.get("prdMarkdown")
        if not isinstance(markdown, str) or not markdown.strip():
            print("producer result lacks non-empty prdMarkdown", file=sys.stderr)
            return 4
        artifact_path.write_text(markdown.rstrip() + "\n", encoding="utf-8")
        result["prdArtifactPath"] = str(artifact_path)
        result["prdArtifactSha256"] = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
        result["outputs"] = [{"path": "PRD_DELIVERY.md", "kind": "PRD"}]
        result["evidenceRefs"] = paths
    elif role in REVIEWER_ROLES:
        errors = review_errors(result.get("reviewResult"), task)
        if errors:
            print("invalid semantic review result: " + "; ".join(errors), file=sys.stderr)
            return 4
        review = canonical_review(task, result["reviewResult"], paths, context_id, transcript_path, revision)
        review_path.write_text(json.dumps(review, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        result["reviewResultPath"] = str(review_path)
        result["reviewResultSha256"] = hashlib.sha256(review_path.read_bytes()).hexdigest()
        result["verdict"] = review["verdict"]
        result["outputs"] = [{"path": str(review_path), "kind": "review-result"}]
        result["evidenceRefs"] = paths
    else:
        print(f"unsupported semantic role: {role}", file=sys.stderr)
        return 5

    result_path.write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
