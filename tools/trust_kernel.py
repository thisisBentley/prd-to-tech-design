#!/usr/bin/env python3
"""Deterministic M7.6 trust-kernel helpers."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from source_pack import validate_tool_sources
from urllib.parse import urlsplit

from semantic_convergence import canonical_hash, load, save, sha256_file, validate_schema_value


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def classify_task(request: dict[str, Any], policy: dict[str, Any], policy_path: Path) -> dict[str, Any]:
    errors = validate_schema_value(request, "execution-task-request.schema.json")
    if errors:
        raise ValueError("; ".join(errors))
    reasons: list[str] = []
    mode = "ESCALATE"
    status = "ESCALATE"
    rules = policy.get("rules") or {}
    structural = request["structuralChanges"]
    structural_hits = [
        key for key in policy.get("fullDeliveryStructuralSignals", [])
        if structural.get(key) is True
    ]

    if not request["changeRequested"] and rules.get("diagnosisWhenNoChange", True):
        mode = "DIAGNOSIS_ONLY"
        status = "CLASSIFIED"
        reasons.append("No change is requested; the task is read-only diagnosis.")
    elif request["unknownSignals"] and rules.get("unknownSignalForcesEscalation", True):
        reasons.append("Unknown task signals require human triage before execution.")
    elif int(request["openBlockingDecisions"]) > 0 and rules.get("openBlockingDecisionForcesEscalation", True):
        reasons.append("Open blocking business decisions prevent autonomous execution.")
    elif structural_hits and rules.get("structuralChangeForcesFullDelivery", True):
        mode = "FULL_DELIVERY"
        status = "CLASSIFIED"
        reasons.append("Structural changes require full delivery: " + ", ".join(structural_hits))
    elif not request["existingArtifactAvailable"]:
        mode = "FULL_DELIVERY"
        status = "CLASSIFIED"
        reasons.append("No reusable artifact exists; full delivery is required.")
    else:
        scopes = set(request["localChangeScopes"])
        allowed = set(policy.get("targetedRevisionScopes", []))
        invalid_scopes = sorted(scopes - allowed)
        requires_findings = rules.get("targetedRequiresExternalFindings", True)
        has_findings = bool(request["externalFindings"])
        if invalid_scopes:
            reasons.append("Change scopes are outside the targeted-revision policy: " + ", ".join(invalid_scopes))
        elif requires_findings and not has_findings:
            reasons.append("Targeted revision requires at least one explicit external finding.")
        elif not scopes:
            reasons.append("No local change scope is declared.")
        else:
            mode = "TARGETED_REVISION"
            status = "CLASSIFIED"
            reasons.append("An existing artifact and explicit external findings are limited to local revision scopes.")

    payload_without_id = {
        "schemaVersion": 1,
        "workflowId": request["workflowId"],
        "taskId": request["taskId"],
        "mode": mode,
        "status": status,
        "reasons": reasons,
        "signals": {
            "changeRequested": request["changeRequested"],
            "existingArtifactAvailable": request["existingArtifactAvailable"],
            "externalFindingCount": len(request["externalFindings"]),
            "localChangeScopes": request["localChangeScopes"],
            "structuralHits": structural_hits,
            "openBlockingDecisions": request["openBlockingDecisions"],
            "unknownSignals": request["unknownSignals"],
        },
        "policyPath": str(policy_path.resolve()),
        "policyHash": sha256_file(policy_path),
        "createdAt": now(),
    }
    result = {"decisionId": "EXEC-MODE-" + canonical_hash(payload_without_id)[:16], **payload_without_id}
    errors = validate_schema_value(result, "execution-mode-decision.schema.json")
    if errors:
        raise ValueError("; ".join(errors))
    return result


def _meta_value(text: str, label: str) -> str | None:
    pattern = rf"^\s*[-*]?\s*{re.escape(label)}\s*:\s*(.+?)\s*$"
    match = re.search(pattern, text, re.MULTILINE | re.IGNORECASE)
    if match:
        return match.group(1).strip().strip("`\"")
    table_pattern = rf"^\s*\|\s*{re.escape(label)}\s*\|\s*([^|\n]+?)\s*\|"
    match = re.search(table_pattern, text, re.MULTILINE | re.IGNORECASE)
    if not match:
        return None
    return match.group(1).strip().strip("`\"")


def _overview_meta(text: str, name: str) -> str | None:
    match = re.search(rf'<meta\s+name=["\']{re.escape(name)}["\']\s+content=["\']([^"\']+)["\']', text, re.IGNORECASE)
    if not match:
        match = re.search(rf'<meta\s+content=["\']([^"\']+)["\']\s+name=["\']{re.escape(name)}["\']', text, re.IGNORECASE)
    return match.group(1).strip() if match else None


def parse_artifact(path: Path, artifact_type: str) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    if artifact_type == "PRD":
        issue_key = _meta_value(text, "Issue Key") or _meta_value(text, "Requirement ID")
        source_baseline = _meta_value(text, "Source baseline")
        return {
            "issueKey": issue_key,
            "issueUrl": _meta_value(text, "Issue URL"),
            "owner": _meta_value(text, "需求 Owner") or _meta_value(text, "Owner"),
            "version": _meta_value(text, "当前 PRD 版本") or _meta_value(text, "Current PRD Version"),
            "sourceBaseline": source_baseline,
            "sourcePrdSha256": None,
        }
    return {
        "issueKey": _overview_meta(text, "issue-key"),
        "issueUrl": _overview_meta(text, "issue-url"),
        "owner": _overview_meta(text, "owner"),
        "version": _overview_meta(text, "source-prd-version"),
        "sourceBaseline": None,
        "sourcePrdSha256": _overview_meta(text, "source-prd-sha256"),
    }


def normalize_url(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlsplit(value.strip())
    if not parsed.scheme or not parsed.netloc:
        return value.strip().rstrip("/")
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}{parsed.path.rstrip('/')}"


def validate_target_binding(request: dict[str, Any]) -> dict[str, Any]:
    errors = validate_schema_value(request, "target-binding-request.schema.json")
    if errors:
        raise ValueError("; ".join(errors))
    target = request["target"]
    checks: list[dict[str, Any]] = []
    artifacts: list[dict[str, Any]] = []
    allowed_lineage = set(request.get("allowedLineageIssueKeys", []))
    prd_artifact: dict[str, Any] | None = None

    def check(check_id: str, observed: Any, expected: Any) -> None:
        checks.append({
            "checkId": check_id,
            "status": "passed" if observed == expected else "failed",
            "observed": observed,
            "expected": expected,
        })

    for item in request["artifacts"]:
        path = Path(item["path"]).resolve()
        if not path.is_file():
            checks.append({"checkId": f"TARGET.ARTIFACT.{item['type']}.PRESENT", "status": "failed", "observed": str(path), "expected": "existing file"})
            continue
        parsed = parse_artifact(path, item["type"])
        artifact = {
            "type": item["type"],
            "path": str(path),
            "sha256": sha256_file(path),
            "issueKey": parsed.get("issueKey"),
            "issueUrl": parsed.get("issueUrl"),
            "owner": parsed.get("owner"),
            "version": parsed.get("version"),
            "sourcePrdSha256": parsed.get("sourcePrdSha256"),
        }
        artifacts.append(artifact)
        if item["type"] == "PRD":
            prd_artifact = artifact
        prefix = f"TARGET.{item['type']}"
        if parsed["issueKey"] is not None or item["type"] == "PRD":
            check(f"{prefix}.ISSUE_KEY", parsed["issueKey"], target["jiraKey"])
        if parsed["issueKey"] and parsed["issueKey"] != target["jiraKey"]:
            check(f"{prefix}.LINEAGE_NOT_CURRENT", parsed["issueKey"] in allowed_lineage, False)
        if parsed["issueUrl"] is not None:
            check(f"{prefix}.ISSUE_URL", normalize_url(parsed["issueUrl"]), normalize_url(target["jiraUrl"]))
        if item["type"] == "PRD":
            source_baseline = parsed.get("sourceBaseline") or ""
            check(f"{prefix}.SOURCE_REFERENCE", target["jiraKey"] in source_baseline, True)
        if parsed["owner"] is not None or item["type"] == "PRD":
            check(f"{prefix}.OWNER", parsed["owner"], target["owner"])
        if item.get("expectedVersion") is not None:
            check(f"{prefix}.VERSION", parsed["version"], item["expectedVersion"])
        if item["type"] == "OVERVIEW" and prd_artifact is not None:
            source_hash = parsed.get("sourcePrdSha256")
            if source_hash:
                check(f"{prefix}.SOURCE_PRD_HASH", source_hash, prd_artifact["sha256"])
            if parsed.get("issueKey") is None:
                check(f"{prefix}.SOURCE_PRD_VERSION", parsed.get("version"), prd_artifact.get("version"))

    payload = {
        "schemaVersion": 1,
        "reportId": "TARGET-BINDING-" + canonical_hash({"workflowId": request["workflowId"], "target": target, "artifacts": artifacts})[:16],
        "workflowId": request["workflowId"],
        "target": target,
        "status": "PASS" if checks and all(item["status"] == "passed" for item in checks) else "BLOCKED",
        "checks": checks,
        "artifacts": artifacts,
        "createdAt": now(),
    }
    errors = validate_schema_value(payload, "target-binding-report.schema.json")
    if errors:
        raise ValueError("; ".join(errors))
    return payload


def map_external_result(raw: str, findings: list[dict[str, Any]]) -> str:
    value = raw.strip().lower()
    if any(token in value for token in ("environment_blocked", "environment blocked", "环境阻断", "环境不可用")):
        return "ENVIRONMENT_BLOCKED"
    if any(token in value for token in ("unknown", "unverified", "无法判断", "未知")):
        return "UNKNOWN"
    if any(token in value for token in ("rejected", "fail", "不通过", "不合格")):
        return "REJECTED"
    if any(token in value for token in ("needs_fix", "needs fix", "退回", "需修改", "待修改")):
        return "NEEDS_FIX"
    if any(token in value for token in ("pass", "passed", "通过", "合格")):
        if any(item.get("severity") == "BLOCKING" for item in findings):
            return "NEEDS_FIX"
        return "PASS"
    return "UNKNOWN"


def normalize_external_gate(data: dict[str, Any], target_binding: dict[str, Any]) -> dict[str, Any]:
    errors = validate_schema_value(data, "external-gate-input.schema.json")
    if errors:
        raise ValueError("; ".join(errors))
    candidate_artifacts = []
    hash_mismatch = False
    for item in data["candidateArtifacts"]:
        path = Path(item["path"]).resolve()
        actual = sha256_file(path) if path.is_file() else None
        candidate_artifacts.append({"path": str(path), "declaredSha256": item["sha256"], "actualSha256": actual})
        if actual != item["sha256"]:
            hash_mismatch = True
    verdict = map_external_result(data["rawResult"], data["findings"])
    binding_ok = (
        target_binding.get("status") == "PASS"
        and target_binding.get("workflowId") == data["workflowId"]
        and (target_binding.get("target") or {}).get("jiraKey") == data["jiraKey"]
    )
    if verdict == "ENVIRONMENT_BLOCKED":
        release_state = "ENVIRONMENT_BLOCKED"
    elif hash_mismatch or not binding_ok:
        release_state = "BLOCKED"
    elif verdict == "PASS":
        release_state = "CLOSED"
    elif verdict in {"NEEDS_FIX", "REJECTED"}:
        release_state = "EXTERNAL_GATE_FAILED"
    else:
        release_state = "EXTERNAL_GATE_PENDING"
    payload_without_id = {
        "schemaVersion": 1,
        "workflowId": data["workflowId"],
        "candidateRevision": data["candidateRevision"],
        "jiraKey": data["jiraKey"],
        "gateType": data["gateType"],
        "verdict": verdict,
        "releaseState": release_state,
        "closureEligible": release_state == "CLOSED",
        "findings": data["findings"],
        "tool": data["tool"],
        "candidateArtifacts": candidate_artifacts,
        "targetBinding": {
            "status": target_binding.get("status"),
            "reportId": target_binding.get("reportId"),
            "jiraKey": (target_binding.get("target") or {}).get("jiraKey"),
            "hashMismatch": hash_mismatch,
        },
        "evidenceRefs": data["evidenceRefs"],
        "checkedAt": data["checkedAt"],
    }
    payload = {"verdictId": "EXT-GATE-" + canonical_hash(payload_without_id)[:16], **payload_without_id}
    errors = validate_schema_value(payload, "external-gate-verdict.schema.json")
    if errors:
        raise ValueError("; ".join(errors))
    return payload


def route_specialist_tool(
    workflow_id: str,
    execution_mode: str,
    intent: str,
    policy: dict[str, Any],
    policy_path: Path,
    task_domain: str = "PRODUCT_ENGINEERING",
    operation: str = "SELECT",
    source_pack: dict[str, Any] | None = None,
) -> dict[str, Any]:
    selected = None
    rejected: list[str] = []
    for route in policy.get("routes", []):
        if execution_mode not in route.get("executionModes", []) or intent not in route.get("intents", []):
            continue
        tool = route.get("tool") or {}
        allowed_domains = tool.get("allowedTaskDomains")
        allowed_operations = tool.get("allowedOperations")
        if allowed_domains and task_domain not in allowed_domains:
            rejected.append(f"{route.get('routeId')}: task domain {task_domain} is not allowed")
            continue
        if allowed_operations and operation not in allowed_operations:
            rejected.append(f"{route.get('routeId')}: operation {operation} is not allowed")
            continue
        if source_pack is not None:
            source_errors = validate_tool_sources(tool, source_pack)
            if source_errors:
                rejected.append(f"{route.get('routeId')}: " + "; ".join(source_errors))
                continue
        selected = route
        break

    if selected:
        applicability = {
            "status": "VERIFIED" if source_pack is not None else "UNVERIFIED",
            "taskDomain": task_domain,
            "operation": operation,
            "sourcePackStatus": "VERIFIED" if source_pack is not None else "UNAVAILABLE",
            "reason": "Route domain, operation and source pack are compatible." if source_pack is not None else "Domain and operation matched; source pack was not supplied.",
        }
        reason = "Matched a declared specialist-tool route."
    else:
        applicability = {
            "status": "BLOCKED" if rejected else "UNVERIFIED",
            "taskDomain": task_domain,
            "operation": operation,
            "sourcePackStatus": "BLOCKED" if any("sourcePackRef" in item or "source pack" in item for item in rejected) else "UNAVAILABLE",
            "reason": "; ".join(rejected) if rejected else "No route matched the execution mode and intent.",
        }
        reason = applicability["reason"]
    base = {
        "schemaVersion": 1,
        "workflowId": workflow_id,
        "executionMode": execution_mode,
        "intent": intent,
        "status": "ROUTED" if selected else "ESCALATE",
        "reason": reason,
        "applicability": applicability,
        "policyPath": str(policy_path.resolve()),
        "policyHash": sha256_file(policy_path),
        "createdAt": now(),
    }
    if selected:
        base["routeId"] = str(selected["routeId"])
        base["selectedTool"] = selected["tool"]
    else:
        base["routeId"] = "TOOL-ROUTE-ESCALATE"
    errors = validate_schema_value(base, "specialist-tool-route.schema.json")
    if errors:
        raise ValueError("; ".join(errors))
    return base


def save_json(path: Path, value: Any) -> None:
    save(path.resolve(), value)
