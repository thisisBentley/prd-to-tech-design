#!/usr/bin/env python3
"""Validate agent task, handoff, review plan/result, decision, and escalation files."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

HEX64 = re.compile(r"^[a-f0-9]{64}$")
ACCEPTED = {"ACCEPTED", "ACCEPTED_WITH_ACTIONS"}


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _required(data: dict[str, Any], keys: list[str], where: str) -> list[str]:
    return [f"{where}: missing {key}" for key in keys if key not in data]


def validate_handoff(data: dict[str, Any], where: str = "handoff") -> list[str]:
    errors = _required(data, ["schemaVersion", "handoffId", "workflowId", "fromAgent", "toAgents", "phase", "revision", "producerContextId", "artifacts", "decisions", "openFindings", "unknowns", "requestedReviews", "createdAt"], where)
    if data.get("schemaVersion") != 1:
        errors.append(f"{where}: schemaVersion must be 1")
    if not data.get("toAgents"):
        errors.append(f"{where}: toAgents must not be empty")
    arts = data.get("artifacts") or []
    if not arts:
        errors.append(f"{where}: artifacts must not be empty")
    for i, art in enumerate(arts):
        if not art.get("path"):
            errors.append(f"{where}/artifact[{i}]: path is required")
        if not HEX64.fullmatch(str(art.get("sha256", ""))):
            errors.append(f"{where}/artifact[{i}]: sha256 is required")
    return errors


def validate_review_plan(data: dict[str, Any], where: str = "review-plan") -> list[str]:
    errors = _required(data, ["schemaVersion", "reviewPlanId", "reviewRunId", "workflowId", "reviewerRole", "targetHandoffId", "targetRevision", "questions", "evidenceTargets", "counterexamples", "selectedChecks", "createdAt"], where)
    if not data.get("questions"):
        errors.append(f"{where}: questions must not be empty")
    if not data.get("evidenceTargets"):
        errors.append(f"{where}: evidenceTargets must not be empty")
    if not data.get("selectedChecks"):
        errors.append(f"{where}: selectedChecks must not be empty")
    return errors


def validate_review_result(data: dict[str, Any], where: str = "review-result") -> list[str]:
    errors = _required(data, ["schemaVersion", "reviewRunId", "reviewPlanId", "workflowId", "producerRole", "reviewerRole", "reviewType", "targetHandoffId", "targetRevision", "independentContext", "reviewerContextId", "reviewerTranscript", "verdict", "completionStatus", "checks", "findings", "blockingCount", "evidenceRefs", "checkedAt"], where)
    if data.get("independentContext") is not True:
        errors.append(f"{where}: independentContext must be true")
    if data.get("producerRole") == data.get("reviewerRole"):
        errors.append(f"{where}: producerRole and reviewerRole must differ")
    checks = data.get("checks") or []
    verdict = data.get("verdict")
    completion = data.get("completionStatus")
    if verdict in ACCEPTED:
        if not checks:
            errors.append(f"{where}: accepted review requires checks")
        if completion != "complete":
            errors.append(f"{where}: accepted review requires completionStatus=complete")
        if int(data.get("blockingCount", 0)) != 0:
            errors.append(f"{where}: accepted review requires blockingCount=0")
        for check in checks:
            if check.get("status") in {"unverified", "not_executed"}:
                errors.append(f"{where}: accepted review contains {check.get('status')} check {check.get('checkId')}")
            if not check.get("evidenceRefs"):
                errors.append(f"{where}: check {check.get('checkId')} has no evidenceRefs")
        if not data.get("evidenceRefs"):
            errors.append(f"{where}: accepted review requires top-level evidenceRefs")
    if verdict in {"RETURNED", "BLOCKED"} and int(data.get("blockingCount", 0)) <= 0:
        errors.append(f"{where}: {verdict} requires at least one blocking finding")
    if verdict == "ACCEPTED_WITH_ACTIONS" and not data.get("findings"):
        errors.append(f"{where}: ACCEPTED_WITH_ACTIONS requires at least one recorded non-blocking finding")
    if verdict == "INCOMPLETE" and completion == "complete":
        errors.append(f"{where}: INCOMPLETE cannot have completionStatus=complete")
    for finding in data.get("findings") or []:
        if not finding.get("evidenceRefs"):
            errors.append(f"{where}: finding {finding.get('findingId')} has no evidenceRefs")
        if not finding.get("closeCondition"):
            errors.append(f"{where}: finding {finding.get('findingId')} has no closeCondition")
    return errors


def validate_decision(data: dict[str, Any], where: str = "decision-card") -> list[str]:
    errors = _required(data, ["schemaVersion", "decisionId", "workflowId", "reviewerRole", "businessScenario", "currentFacts", "ambiguity", "options", "recommendation", "defaultAndRisk", "owner", "closeCondition", "createdAt"], where)
    if len(data.get("options") or []) < 2:
        errors.append(f"{where}: at least two options are required")
    if data.get("status") == "confirmed" and not data.get("selectedOptionId"):
        errors.append(f"{where}: confirmed decision requires selectedOptionId")
    return errors


def validate_escalation(data: dict[str, Any], where: str = "escalation") -> list[str]:
    errors = _required(data, ["schemaVersion", "escalationId", "workflowId", "fromRoles", "issue", "evidenceRefs", "attemptedRounds", "requestedDecision", "status", "createdAt"], where)
    if len(data.get("fromRoles") or []) < 2:
        errors.append(f"{where}: at least two roles are required")
    if int(data.get("attemptedRounds", 0)) < 2:
        errors.append(f"{where}: attemptedRounds must be at least 2")
    if not data.get("evidenceRefs"):
        errors.append(f"{where}: evidenceRefs must not be empty")
    return errors


def kind(data: dict[str, Any]) -> str:
    if "handoffId" in data: return "handoff"
    if "reviewRunId" in data and "verdict" in data: return "review-result"
    if "reviewPlanId" in data: return "review-plan"
    if "decisionId" in data: return "decision-card"
    if "escalationId" in data: return "escalation"
    if "taskId" in data: return "agent-task"
    return "unknown"


def validate_file(path: Path) -> list[str]:
    try:
        data = load(path)
    except Exception as exc:
        return [f"{path}: invalid JSON: {exc}"]
    k = kind(data)
    if k == "handoff": return validate_handoff(data, str(path))
    if k == "review-plan": return validate_review_plan(data, str(path))
    if k == "review-result": return validate_review_result(data, str(path))
    if k == "decision-card": return validate_decision(data, str(path))
    if k == "escalation": return validate_escalation(data, str(path))
    if k == "agent-task":
        errors = _required(data, ["schemaVersion", "taskId", "workflowId", "stage", "role", "objective", "inputs", "constraints", "expectedOutputs"], str(path))
        if not data.get("inputs"):
            errors.append(f"{path}: inputs must not be empty")
        for i, item in enumerate(data.get("inputs") or []):
            if not HEX64.fullmatch(str(item.get("sha256", ""))):
                errors.append(f"{path}/inputs[{i}]: sha256 is required")
        if not data.get("constraints"):
            errors.append(f"{path}: constraints must not be empty")
        return errors
    return [f"{path}: unknown agent contract type"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    errors = [error for raw in args.files for error in validate_file(Path(raw))]
    result = {"status": "PASS" if not errors else "FAIL", "files": len(args.files), "errors": errors}
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"status: {result['status']}")
        for error in errors:
            print(f"- {error}")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
