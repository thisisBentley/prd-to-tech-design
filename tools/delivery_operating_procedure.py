#!/usr/bin/env python3
"""Build one deterministic Delivery Operating Procedure from existing control-plane artifacts."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from source_pack import validate_tool_sources
from trust_kernel import validate_schema_value

STOP_CONDITIONS = [
    "SOURCE_DRIFT_OR_STALE_LOCK",
    "OPEN_BLOCKING_DECISION",
    "NEW_BLOCKING_FINDING",
    "NO_MEASURABLE_IMPROVEMENT",
    "REGRESSION",
    "MAX_REPAIR_ROUNDS_REACHED",
    "RUN_BUDGET_EXCEEDED",
    "INDEPENDENT_REVIEW_UNAVAILABLE",
]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load(path: Path | None, default: Any = None) -> Any:
    if path is None or not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def save(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def objective_from_requirement(path: Path) -> tuple[str, str]:
    if not path.is_file():
        return "UNAVAILABLE", "UNAVAILABLE"
    text = path.read_text(encoding="utf-8", errors="replace")
    heading = re.search(r"^\s*#\s+(.+?)\s*$", text, re.MULTILINE)
    if heading:
        return heading.group(1).strip(), "REQUIREMENT_TITLE"
    for line in text.splitlines():
        value = line.strip().lstrip("-*").strip()
        if value:
            return value, "REQUIREMENT_TITLE"
    return "UNAVAILABLE", "UNAVAILABLE"


def build(
    *,
    workflow_id: str,
    requirement_id: str,
    artifact_profile: str,
    revision: str,
    requirement_path: Path,
    objective: str | None,
    generation_contract_path: Path,
    policy_lock_path: Path,
    obligations_path: Path,
    plan_path: Path,
    tool_policy_path: Path,
    budget_path: Path,
    repair_policy_path: Path,
    source_pack_path: Path,
    task_domain: str = "PRODUCT_ENGINEERING",
) -> dict[str, Any]:
    errors: list[str] = []
    generation = load(generation_contract_path, {})
    policy_lock = load(policy_lock_path, {})
    obligations = load(obligations_path, {})
    plan = load(plan_path, {})
    tool_policy = load(tool_policy_path, {})
    budget = load(budget_path, {})
    repair_policy = load(repair_policy_path, {})
    source_pack = load(source_pack_path, {})

    for name, data in (
        ("policy lock", policy_lock),
        ("delivery plan", plan),
        ("tool policy", tool_policy),
        ("run budget", budget),
        ("repair policy", repair_policy),
    ):
        if not data:
            errors.append(f"{name} is missing or unreadable")

    if generation and generation.get("workflowId") != workflow_id:
        errors.append("generation contract workflowId does not match procedure")
    if generation and generation.get("artifactProfile") != artifact_profile:
        errors.append("generation contract artifactProfile does not match procedure")
    if policy_lock and (policy_lock.get("scope") or {}).get("artifactProfile") != artifact_profile:
        errors.append("policy lock artifactProfile does not match procedure")
    if obligations and obligations.get("workflowId") != workflow_id:
        errors.append("generation obligations workflowId does not match procedure")
    if obligations and policy_lock_path.is_file() and obligations.get("policyLockSha256") != digest(policy_lock_path):
        errors.append("generation obligations policyLockSha256 does not match policy lock")
    if plan and plan.get("workflowId") != workflow_id:
        errors.append("delivery plan workflowId does not match procedure")
    if plan and plan.get("artifactProfile") != artifact_profile:
        errors.append("delivery plan artifactProfile does not match procedure")
    if not plan.get("tasks"):
        errors.append("delivery plan has no tasks")

    routes = []
    for route in tool_policy.get("routes") or []:
        tool = route.get("tool") or {}
        missing = [key for key in ("toolDomain", "allowedTaskDomains", "allowedOperations", "writeAuthority", "sourcePackRefs") if key not in tool]
        if missing:
            errors.append(f"{route.get('routeId')}: missing tool authority fields {missing}")
            continue
        if task_domain not in tool.get("allowedTaskDomains", []):
            errors.append(f"{route.get('routeId')}: does not allow task domain {task_domain}")
        source_errors = validate_tool_sources(tool, source_pack) if source_pack else ["source pack is unavailable"]
        if source_errors:
            errors.append(f"{route.get('routeId')}: " + "; ".join(source_errors))
        routes.append({
            "routeId": route.get("routeId"),
            "executionModes": route.get("executionModes", []),
            "intents": route.get("intents", []),
            "toolId": tool.get("toolId"),
            "toolDomain": tool.get("toolDomain"),
            "allowedTaskDomains": tool.get("allowedTaskDomains", []),
            "allowedOperations": tool.get("allowedOperations", []),
            "writeAuthority": tool.get("writeAuthority", []),
            "sourcePackRefs": tool.get("sourcePackRefs", []),
            "requiresHumanApproval": bool(tool.get("requiresHumanApproval", False)),
        })
    if not routes:
        errors.append("tool policy exposes no valid routes")

    budget_rounds = int(budget.get("maxRepairRounds", 0) or 0)
    repair_rounds = int(repair_policy.get("maxRounds", 0) or 0)
    if budget_rounds and repair_rounds and budget_rounds != repair_rounds:
        errors.append("run budget maxRepairRounds does not match repair policy maxRounds")

    if objective:
        objective_text, objective_source = objective.strip(), "EXPLICIT"
    else:
        objective_text, objective_source = objective_from_requirement(requirement_path)
    if not objective_text or objective_text == "UNAVAILABLE":
        errors.append("objective text is unavailable")

    tasks = plan.get("tasks") or []
    subgoals = [{
        "subgoalId": str(task.get("taskId")),
        "ownerRole": str(task.get("role")),
        "kind": str(task.get("kind")),
        "dependencies": list(task.get("dependencies") or []),
        "expectedOutputs": list(task.get("expectedOutputs") or []),
        "required": bool(task.get("required", True)),
        "status": str(task.get("status") or "PENDING"),
    } for task in tasks]
    read_scope_count = sum(len(task.get("readScope") or []) for task in tasks)
    applicable_rules = policy_lock.get("applicableRules") or {}
    guardrail_rules = sum(len(value) for value in applicable_rules.values() if isinstance(value, list))
    obligation_metrics = obligations.get("metrics") or {}
    source_pack_status = source_pack.get("status", "SKIPPED")
    generation_status = generation.get("status", "SKIPPED")
    requirements = list(generation.get("requirementTypes") or [])
    requirement_path = requirement_path.resolve()
    if not requirement_path.is_file():
        errors.append("requirement source is missing")

    status = "BLOCKED" if errors else ("READY_WITH_ACTIONS" if generation_status in {"READY_WITH_ACTIONS", "BLOCKED", "SKIPPED"} else "READY")
    provenance_paths = [
        ("REQUIREMENT", requirement_path),
        ("GENERATION_CONTRACT", generation_contract_path),
        ("POLICY_LOCK", policy_lock_path),
        ("GENERATION_OBLIGATIONS", obligations_path),
        ("DELIVERY_PLAN", plan_path),
        ("TOOL_POLICY", tool_policy_path),
        ("RUN_BUDGET", budget_path),
        ("REPAIR_POLICY", repair_policy_path),
        ("SOURCE_PACK", source_pack_path),
    ]
    provenance = [
        {"kind": kind, "path": str(path.resolve()), "sha256": digest(path)}
        for kind, path in provenance_paths if path.is_file()
    ]
    payload: dict[str, Any] = {
        "schemaVersion": 1,
        "procedureId": "DOP-" + hashlib.sha256(json.dumps({
            "workflowId": workflow_id,
            "requirementId": requirement_id,
            "artifactProfile": artifact_profile,
            "revision": revision,
            "provenance": provenance,
        }, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:16],
        "workflowId": workflow_id,
        "requirementId": requirement_id,
        "artifactProfile": artifact_profile,
        "revision": revision,
        "status": status,
        "goalContract": {
            "objectiveText": objective_text or "UNAVAILABLE",
            "objectiveSource": objective_source,
            "requirementTypes": requirements,
            "generationContractStatus": generation_status,
            "generationContractPath": str(generation_contract_path.resolve()) if generation_contract_path.is_file() else None,
            "generationContractSha256": digest(generation_contract_path) if generation_contract_path.is_file() else None,
            "sourcePath": str(requirement_path),
            "sourceSha256": digest(requirement_path) if requirement_path.is_file() else "0" * 64,
        },
        "subgoals": subgoals,
        "guardrails": {
            "policyLockPath": str(policy_lock_path.resolve()),
            "policyLockSha256": digest(policy_lock_path) if policy_lock_path.is_file() else "0" * 64,
            "applicableRules": applicable_rules,
            "excludedRules": list(policy_lock.get("excludedRules") or []),
            "obligationsPath": str(obligations_path.resolve()) if obligations_path.is_file() else None,
            "obligationsSha256": digest(obligations_path) if obligations_path.is_file() else None,
            "obligationsTotal": int(obligation_metrics.get("total", 0)),
            "obligationsOpen": int(obligation_metrics.get("open", 0)),
            "sourcePackStatus": source_pack_status,
        },
        "toolAuthority": {
            "policyPath": str(tool_policy_path.resolve()),
            "policySha256": digest(tool_policy_path) if tool_policy_path.is_file() else "0" * 64,
            "defaultTaskDomain": task_domain,
            "routes": routes,
        },
        "contextPolicy": {
            "maxContextFiles": int(budget.get("maxContextFiles", 1) or 1),
            "allowedSourceClasses": ["NORMATIVE", "SOURCE_FACT", "MEASURED", "DERIVED", "REFERENCE", "INFERENCE"],
            "sourcePackPath": str(source_pack_path.resolve()) if source_pack_path.is_file() else None,
            "sourcePackSha256": digest(source_pack_path) if source_pack_path.is_file() else None,
            "readScopeCount": read_scope_count,
        },
        "stateContract": {
            "planPath": str(plan_path.resolve()),
            "planSha256": digest(plan_path) if plan_path.is_file() else "0" * 64,
            "planTaskCount": len(tasks),
            "candidateSealRequired": True,
            "reviewSeparationRequired": True,
            "handoffRequired": True,
        },
        "stopPolicy": {
            "maxTotalSeconds": float(budget.get("maxTotalSeconds", 1) or 1),
            "maxJobSeconds": float(budget.get("maxJobSeconds", 1) or 1),
            "maxContextFiles": int(budget.get("maxContextFiles", 1) or 1),
            "maxTranscriptBytes": int(budget.get("maxTranscriptBytes", 1) or 1),
            "maxRepairRounds": budget_rounds or repair_rounds,
            "conditions": STOP_CONDITIONS,
        },
        "revisionPolicy": {
            "initialRevision": revision,
            "nextRevisionPattern": "r<number+1>",
            "repairRequiresDerivedRebuild": True,
            "packageRebindsFinalSeal": True,
            "staleEvidenceForbidden": True,
        },
        "exitCriteria": [
            {"criterionId": "EXIT.GENERATION_OBLIGATIONS", "condition": "all required generation obligations are declared with resolvable evidence", "required": True, "sourceRef": str(obligations_path.resolve())},
            {"criterionId": "EXIT.ARTIFACT_QUALITY", "condition": "artifact quality result is PASS", "required": True, "sourceRef": "artifact-quality.json"},
            {"criterionId": "EXIT.FINAL_GATE", "condition": "final package gate result is PASS with zero blockers", "required": True, "sourceRef": "final-package-gate.json"},
            {"criterionId": "EXIT.READINESS", "condition": "readiness reaches DESIGN_READY when readiness gate is enabled", "required": True, "sourceRef": "delivery-readiness.json"},
            {"criterionId": "EXIT.COST_LEDGER", "condition": "Cost / Revision Ledger is present and not INSUFFICIENT", "required": True, "sourceRef": "cost-revision-ledger.json"},
        ],
        "provenance": provenance,
        "metrics": {
            "subgoals": len(subgoals),
            "requiredSubgoals": sum(1 for task in tasks if bool(task.get("required", True))),
            "guardrailRules": guardrail_rules,
            "toolRoutes": len(routes),
            "readScopeCount": read_scope_count,
            "exitCriteria": 5,
        },
        "createdAt": now(),
    }
    issues = validate_schema_value(payload, "delivery-operating-procedure.schema.json")
    errors.extend(f"schema: {issue}" for issue in issues)
    if errors:
        payload["status"] = "BLOCKED"
        raise ValueError("; ".join(errors))
    return payload
