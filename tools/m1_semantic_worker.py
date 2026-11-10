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
    "semantic-consistency-reviewer",
}
DECISION_ROLES = {"decision-readiness-agent"}
REVIEW_SEVERITIES = {"BLOCKING", "NON_BLOCKING", "INFO"}
CHECK_STATUSES = {"PASSED", "FAILED", "NOT_APPLICABLE", "UNVERIFIED", "NOT_EXECUTED", "PASS", "FAIL", "PASS_WITH_OBSERVATION"}
CHECK_STATUS_ALIASES = {
    "PASSED": "passed", "FAILED": "failed", "NOT_APPLICABLE": "not_applicable",
    "UNVERIFIED": "unverified", "NOT_EXECUTED": "not_executed",
    "PASS": "passed", "FAIL": "failed", "PASS_WITH_OBSERVATION": "passed",
    "PASS_OBSERVATION": "passed", "PASSED_WITH_OBSERVATION": "passed",
    "WARN": "passed", "WARNING": "passed", "OK": "passed",
}
REPAIR_CLASSES = {"SEMANTIC", "ARTIFACT_CONTRACT", "VISIBLE_INTERACTION", "RUNTIME", "EVIDENCE", "EVIDENCE-UPDATE"}
REPAIR_CLASS_ALIASES = {
    "SPECIFICATION-UPDATE": "SEMANTIC",
    "REQUIREMENT-UPDATE": "SEMANTIC",
    "PRD-UPDATE": "SEMANTIC",
    "CLARIFICATION": "SEMANTIC",
    "EVIDENCE-UPDATE": "EVIDENCE",
    "DOCUMENTATION-CLARIFICATION": "SEMANTIC",
    "DOCUMENTATION": "SEMANTIC",
    "CLARIFICATION": "SEMANTIC",
    "SPECIFICATION": "SEMANTIC",
    "PRD-CORRECTION": "SEMANTIC",
    "PRD-UPDATE": "SEMANTIC",
    "CONTENT-CORRECTION": "SEMANTIC",
    "CORRECTION": "SEMANTIC",
}


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
            "Return exactly one compact, strictly valid RFC-8259 JSON object with schemaVersion=1, status='SUCCEEDED', taskId=AI_NATIVE_TASK_ID, role=AI_NATIVE_ROLE, "
            "outputs=[{'path':'review-result','kind':'review-result'}], reviewResult=<review object>, and evidenceRefs=AI_NATIVE_INPUT_PATHS. "
            "Escape every quote and control character correctly; emit one JSON object only, with no trailing fields after the closing brace. "
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
            "outputs=[{'path':'decision-context','kind':'decision-context'}], readiness='READY' or 'NOT_READY', decision='HOLD' or 'PROCEED', "
            "blockingConditions=<array>, requiredDecisions=<array>, researchRecords=<array>, resolvedFacts=<array>, and evidenceRefs=AI_NATIVE_INPUT_PATHS. "
            "Apply Research-First before producing requiredDecisions: search the supplied frozen inputs and any permitted read-only Jira/MCP/Git evidence; "
            "if a fact can be uniquely determined, record it in resolvedFacts and do not ask the product; "
            "only a real business choice with no existing precedent may appear in requiredDecisions. "
            "Every requiredDecision must be backed by a researchRecords item with verdict='NEEDS_BUSINESS_DECISION', decisionRequired=true, sourcesChecked, evidenceRefs and decisionRationale. "
            "Do not use requiredDecisions for technical implementation details."
        )
    return "\n".join([
        "You are executing one bounded AI-Native Agile Product-Engineering M1 task.",
        instruction,
        required,
        "Read the supplied input paths directly. Return strict compact JSON only, without Markdown fences, commentary, or trailing text.",
        f"AI_NATIVE_TASK_ID={task.get('taskId', '')}",
        f"AI_NATIVE_ROLE={role}",
        "AI_NATIVE_INPUT_PATHS=" + ",".join(paths),
        f"AI_NATIVE_RESULT_PATH={result_path}",
        f"AI_NATIVE_REVIEW_PATH={review_path}",
        f"AI_NATIVE_ARTIFACT_PATH={artifact_path}",
    ])


def normalize_refs(value: Any) -> list[str] | Any:
    if isinstance(value, str) and value:
        return [value]
    return value


def normalize_review_shape(review: dict[str, Any], task: dict[str, Any]) -> dict[str, Any]:
    if review.get("reviewerRole") in {"AI_NATIVE_ROLE", "<role>", "role"}:
        review["reviewerRole"] = task.get("role")
    review["evidenceRefs"] = normalize_refs(review.get("evidenceRefs"))
    for check in review.get("checks", []) if isinstance(review.get("checks"), list) else []:
        if isinstance(check, dict):
            check["evidenceRefs"] = normalize_refs(check.get("evidenceRefs"))
    for finding in review.get("findings", []) if isinstance(review.get("findings"), list) else []:
        if isinstance(finding, dict):
            finding["evidenceRefs"] = normalize_refs(finding.get("evidenceRefs"))
            finding["regressionTests"] = normalize_refs(finding.get("regressionTests"))
    return review


def review_errors(review: Any, task: dict[str, Any]) -> list[str]:
    if not isinstance(review, dict):
        return ["reviewResult must be a JSON object"]
    normalize_review_shape(review, task)
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
    if findings is None:
        review["findings"] = findings = []
    elif not isinstance(findings, list):
        errors.append("reviewResult.findings must be an array")
        findings = []
    if review.get("blockingCount") is None:
        review["blockingCount"] = sum(1 for item in findings if isinstance(item, dict) and item.get("severity") == "BLOCKING")
    blocking = sum(1 for item in findings if isinstance(item, dict) and item.get("severity") == "BLOCKING")
    if review.get("blockingCount") != blocking:
        errors.append("reviewResult.blockingCount must equal BLOCKING findings")
    if review.get("verdict") in {"ACCEPTED"} and blocking:
        errors.append("ACCEPTED review must not contain BLOCKING findings")
    if review.get("verdict") in {"RETURNED", "BLOCKED"} and not blocking:
        errors.append(f"{review.get('verdict')} review requires at least one BLOCKING finding")
    checks = review.get("checks")
    if isinstance(checks, list):
        for check in checks:
            if isinstance(check, dict):
                status = str(check.get("status", "")).upper()
                check["status"] = CHECK_STATUS_ALIASES.get(status, status)
    if not isinstance(checks, list) or not checks:
        errors.append("reviewResult.checks must be a non-empty array")
    else:
        for index, check in enumerate(checks):
            status = str(check.get("status", "")).upper() if isinstance(check, dict) else ""
            if not isinstance(check, dict) or not check.get("checkId") or status not in CHECK_STATUSES:
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
        raw_repair_class = str(finding.get("repairClass", "")).upper().replace(" ", "-").replace("_", "-")
        repair_class = REPAIR_CLASS_ALIASES.get(raw_repair_class)
        if repair_class is None and "EVIDENCE" in raw_repair_class:
            repair_class = "EVIDENCE"
        elif repair_class is None:
            # M1 findings are analytical PRD corrections unless explicitly runtime,
            # visible-interaction, or artifact-contract evidence is supplied.
            repair_class = "SEMANTIC"
        finding["repairClass"] = repair_class
        if repair_class not in REPAIR_CLASSES:
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
    parser.add_argument(
        "--bypass-inner-sandbox",
        action="store_true",
        help="smoke-only escape hatch when codex is nested inside an external sandbox whose Seatbelt cannot be initialized",
    )
    parser.add_argument("--timeout", type=float, default=float(os.environ.get("AI_NATIVE_TIMEOUT", "300")))
    args = parser.parse_args()
    if os.environ.get("AI_NATIVE_SEMANTIC_BYPASS_INNER_SANDBOX") == "1":
        args.bypass_inner_sandbox = True

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
        "--output-last-message", str(result_path), "-C", str(root),
    ]
    if args.bypass_inner_sandbox:
        # Required only for nested smoke runs inside an external host sandbox.
        # Normal production execution keeps the semantic codex sandbox enabled.
        argv.append("--dangerously-bypass-approvals-and-sandbox")
    else:
        argv.extend(["--sandbox", sandbox])
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
        raw_result = result_path.read_text(encoding="utf-8")
        stripped = raw_result.lstrip()
        result, end = json.JSONDecoder().raw_decode(stripped)
        if end != len(stripped.rstrip()):
            raise ValueError("codex result contains trailing data")
        if not isinstance(result, dict):
            raise ValueError("codex result must be a JSON object")
    except Exception as exc:
        malformed = root / ".agents" / "results" / f"{task.get('taskId', 'UNKNOWN')}.malformed.json"
        malformed.write_text(raw_result, encoding="utf-8")
        print(f"invalid codex result JSON: {exc}; saved={malformed}", file=sys.stderr)
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
    elif role in DECISION_ROLES:
        evidence = normalize_refs(result.get("evidenceRefs"))
        result["evidenceRefs"] = evidence
        readiness = result.get("readiness")
        decision = result.get("decision")
        required_decisions = result.get("requiredDecisions") or []
        research_records = result.get("researchRecords") or []
        if readiness not in {"READY", "NOT_READY"} or decision not in {"PROCEED", "HOLD"}:
            print("decision result requires readiness READY/NOT_READY and decision PROCEED/HOLD", file=sys.stderr)
            return 4
        if not (isinstance(evidence, list) and evidence and all(isinstance(item, str) and item for item in evidence)):
            print("decision result requires non-empty evidenceRefs", file=sys.stderr)
            return 4
        if not isinstance(required_decisions, list) or not isinstance(research_records, list):
            print("decision result requires requiredDecisions and researchRecords arrays", file=sys.stderr)
            return 4
        unresolved_records = [
            record for record in research_records
            if isinstance(record, dict) and (record.get("decisionRequired") is True or record.get("verdict") in {"NEEDS_BUSINESS_DECISION", "FACT_CONFLICT", "NO_EVIDENCE"})
        ]
        if required_decisions:
            backed = [record for record in unresolved_records if record.get("verdict") == "NEEDS_BUSINESS_DECISION" and record.get("evidenceRefs") and record.get("sourcesChecked") and record.get("decisionRationale")]
            if not backed:
                print("requiredDecisions require Research-First evidence; factual gaps must be resolved before asking the product", file=sys.stderr)
                return 4
            if readiness == "READY" or decision == "PROCEED":
                print("requiredDecisions cannot coexist with READY/PROCEED", file=sys.stderr)
                return 4
        if unresolved_records and (readiness == "READY" or decision == "PROCEED"):
            print("unresolved research records block READY/PROCEED", file=sys.stderr)
            return 4
        result["researchRecords"] = research_records
        result["resolvedFacts"] = result.get("resolvedFacts") or []
        result["outputs"] = [{"path": "decision-context", "kind": "decision-context"}]
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
