#!/usr/bin/env python3
"""Compile blocking findings into bounded, root-cause grouped Change Sets."""
from __future__ import annotations

import argparse
import json
import re
from collections import OrderedDict
from pathlib import Path
from typing import Any

from semantic_convergence import canonical_hash, load, save, sha256_file
from trust_kernel import now, validate_schema_value

CLASSIFICATIONS = {
    "DECISION_GAP", "SOURCE_CONFLICT", "SPEC_MISSING", "ARTIFACT_DRIFT",
    "IMPLEMENTATION_RISK", "TEST_GAP", "EDITORIAL", "MECHANICAL",
}
REPAIR_CLASS_TO_CHANGE_CLASS = {
    "SEMANTIC": "SPEC_MISSING",
    "ARTIFACT_CONTRACT": "ARTIFACT_DRIFT",
    "VISIBLE_INTERACTION": "ARTIFACT_DRIFT",
    "RUNTIME": "IMPLEMENTATION_RISK",
    "EVIDENCE": "MECHANICAL",
}
INFERENCE_RULES = [
    ("DECISION_GAP", ("decision", "open question", "undecided", "裁决", "决策", "未决")),
    ("SOURCE_CONFLICT", ("source conflict", "authority conflict", "来源冲突", "来源矛盾", "事实冲突")),
    ("SPEC_MISSING", ("missing spec", "missing rule", "undefined", "not specified", "缺失", "未定义", "未说明")),
    ("ARTIFACT_DRIFT", ("drift", "projection mismatch", "overview mismatch", "prototype mismatch", "不一致", "漂移", "投影不同步")),
    ("IMPLEMENTATION_RISK", ("runtime", "implementation", "performance", "concurrency", "实现风险", "运行态", "性能")),
    ("TEST_GAP", ("test gap", "test coverage", "missing test", "regression missing", "测试缺口", "缺少测试", "覆盖不足")),
    ("EDITORIAL", ("typo", "wording", "copy", "editorial", "文案", "措辞", "错别字")),
    ("MECHANICAL", ("hash", "path", "format", "schema", "机械", "哈希", "路径", "格式")),
]


def normalize_classification(value: str) -> str | None:
    normalized = re.sub(r"[^A-Z0-9]+", "_", value.strip().upper()).strip("_")
    aliases = {
        "DECISION": "DECISION_GAP",
        "DECISION_MISSING": "DECISION_GAP",
        "CONFLICT": "SOURCE_CONFLICT",
        "SOURCE": "SOURCE_CONFLICT",
        "SPEC": "SPEC_MISSING",
        "SPECIFICATION_MISSING": "SPEC_MISSING",
        "DRIFT": "ARTIFACT_DRIFT",
        "ARTIFACT_MISMATCH": "ARTIFACT_DRIFT",
        "IMPLEMENTATION": "IMPLEMENTATION_RISK",
        "RUNTIME": "IMPLEMENTATION_RISK",
        "TEST": "TEST_GAP",
        "COPY": "EDITORIAL",
        "FORMAT": "MECHANICAL",
        "PATH": "MECHANICAL",
    }
    normalized = aliases.get(normalized, normalized)
    return normalized if normalized in CLASSIFICATIONS else None


def classify_finding(finding: dict[str, Any]) -> tuple[str | None, str]:
    explicit = finding.get("classification") or finding.get("changeClassification") or finding.get("changeClass") or finding.get("findingType")
    if explicit:
        normalized = normalize_classification(str(explicit))
        if normalized:
            return normalized, "EXPLICIT"
    repair_class = str(finding.get("repairClass") or "").upper()
    if repair_class in REPAIR_CLASS_TO_CHANGE_CLASS:
        return REPAIR_CLASS_TO_CHANGE_CLASS[repair_class], "REPAIR_CLASS_MAPPING"
    text = " ".join(str(finding.get(key) or "") for key in ("title", "summary", "impact", "closeCondition", "expectedInvariant", "ruleId"))
    text += " " + " ".join(map(str, finding.get("ruleIds") or []))
    lowered = text.lower()
    hits = [classification for classification, terms in INFERENCE_RULES if any(term in lowered for term in terms)]
    unique = sorted(set(hits))
    if len(unique) == 1:
        return unique[0], "KEYWORD_INFERENCE"
    return None, "AMBIGUOUS_KEYWORD_INFERENCE" if unique else "UNCLASSIFIED"


def artifacts_for(finding: dict[str, Any]) -> list[dict[str, str]]:
    raw: list[Any] = []
    if finding.get("affectedArtifacts"):
        value = finding["affectedArtifacts"]
        raw.extend(value if isinstance(value, list) else [value])
    if finding.get("artifact"):
        raw.append(finding["artifact"])
    if isinstance(finding.get("artifacts"), list):
        raw.extend(finding["artifacts"])
    result: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in raw:
        if isinstance(item, str):
            path = item.strip()
            artifact_type = "UNKNOWN"
            reason = "Referenced by the finding."
        elif isinstance(item, dict):
            path = str(item.get("path") or "").strip()
            artifact_type = str(item.get("artifactType") or item.get("type") or "UNKNOWN")
            reason = str(item.get("reason") or "Referenced by the finding.")
        else:
            continue
        if not path:
            continue
        key = (path, artifact_type)
        if key in seen:
            continue
        seen.add(key)
        result.append({"path": path, "artifactType": artifact_type, "reason": reason})
    return sorted(result, key=lambda item: (item["path"], item["artifactType"]))


def verification_for(finding: dict[str, Any], route: dict[str, Any]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    raw = finding.get("verificationPlan")
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict) and item.get("checkId"):
                checks.append({
                    "checkId": str(item["checkId"]),
                    "kind": str(item.get("kind") or "CUSTOM"),
                    "description": str(item.get("description") or item["checkId"]),
                    "required": bool(item.get("required", True)),
                })
            elif isinstance(item, str) and item.strip():
                checks.append({"checkId": "CUSTOM-" + canonical_hash(item)[:8], "kind": "CUSTOM", "description": item, "required": True})
    for item in finding.get("regressionTests") or []:
        if isinstance(item, str) and item.strip():
            checks.append({"checkId": "REGRESSION-" + canonical_hash(item)[:8], "kind": "REGRESSION", "description": item, "required": True})
    default_checks = []
    for item in route.get("verificationChecks") or []:
        if isinstance(item, dict):
            default_checks.append({
                "checkId": str(item["checkId"]),
                "kind": str(item["kind"]),
                "description": str(item["description"]),
                "required": bool(item.get("required", True)),
            })
    unique: OrderedDict[str, dict[str, Any]] = OrderedDict()
    for item in [*default_checks, *checks]:
        unique.setdefault(item["checkId"], item)
    return list(unique.values())


def batch_finding(code: str, message: str, evidence_refs: list[str], root_cause_id: str | None = None) -> dict[str, Any]:
    payload = {"code": code, "message": message, "evidenceRefs": evidence_refs, "rootCauseId": root_cause_id}
    return {"findingId": "CHANGE-SET-" + code + "-" + canonical_hash(payload)[:12], **payload}


def compile_change_sets(reviews: list[tuple[Path, dict[str, Any]]], policy: dict[str, Any], policy_path: Path) -> dict[str, Any]:
    if not reviews:
        raise ValueError("at least one finding source is required")
    policy_errors = validate_schema_value(policy, "change-set-policy.schema.json")
    if policy_errors:
        raise ValueError("invalid change-set policy: " + "; ".join(policy_errors))
    workflow_ids = {str(data.get("workflowId")) for _, data in reviews if data.get("workflowId")}
    revisions = {str(data.get("targetRevision")) for _, data in reviews if data.get("targetRevision")}
    findings: list[tuple[Path, dict[str, Any]]] = []
    for path, data in reviews:
        for item in data.get("findings") or []:
            if isinstance(item, dict):
                findings.append((path, item))
    blocking_findings = [(path, item) for path, item in findings if str(item.get("severity") or "BLOCKING").upper() == "BLOCKING"]
    batch_findings: list[dict[str, Any]] = []
    if len(workflow_ids) != 1 or len(revisions) != 1:
        batch_findings.append(batch_finding(
            "SOURCE_IDENTITY_INCONSISTENT",
            "All finding sources must share one workflowId and targetRevision.",
            [str(path) for path, _ in reviews],
        ))
        return {
            "schemaVersion": 1,
            "batchType": "CHANGE_SET_BATCH",
            "batchId": "CHANGE-SET-BATCH-" + canonical_hash({"reviews": [str(path) for path, _ in reviews]})[:16],
            "workflowId": next(iter(workflow_ids), "unknown"),
            "targetRevision": next(iter(revisions), "unknown"),
            "sourceFindings": [str(path.resolve()) for path, _ in reviews],
            "policy": {"path": str(policy_path.resolve()), "policyId": policy.get("policyId"), "policySha256": sha256_file(policy_path)},
            "changeSets": [],
            "metrics": {"blockingFindings": len(blocking_findings), "coveredBlockingFindings": 0, "changeSets": 0, "plannedChangeSets": 0, "blockedChangeSets": 0, "businessRevisionChangeSets": 0, "mechanicalChangeSets": 0},
            "status": "BLOCKED",
            "findings": batch_findings,
            "createdAt": now(),
        }

    route_by_class = {item["classification"]: item for item in policy["routes"]}
    groups: OrderedDict[str, list[tuple[Path, dict[str, Any]]]] = OrderedDict()
    orphan_findings: list[tuple[Path, dict[str, Any]]] = []
    for path, finding in blocking_findings:
        root = str(finding.get("rootCauseId") or finding.get("stableKey") or finding.get("dedupeKey") or "").strip()
        if not root:
            orphan_findings.append((path, finding))
            batch_findings.append(batch_finding(
                "ROOT_CAUSE_MISSING",
                f"Blocking finding {finding.get('findingId', '<missing>')} has no rootCauseId/stableKey.",
                [str(path.resolve())],
            ))
            continue
        groups.setdefault(root, []).append((path, finding))

    change_sets: list[dict[str, Any]] = []
    covered_finding_ids: set[str] = set()
    for root_cause_id, root_findings in groups.items():
        group_sources = sorted({str(path.resolve()) for path, _ in root_findings})
        classifications: dict[str, list[str]] = {}
        artifacts: list[dict[str, str]] = []
        checks: list[dict[str, Any]] = []
        close_conditions: list[str] = []
        invariants: list[str] = []
        finding_ids: list[str] = []
        issues: list[dict[str, Any]] = []
        for path, finding in root_findings:
            finding_id = str(finding.get("findingId") or "").strip()
            if not finding_id:
                issues.append(batch_finding("FINDING_ID_MISSING", f"Blocking finding under {root_cause_id} has no findingId.", [str(path.resolve())], root_cause_id))
                continue
            if finding_id in covered_finding_ids:
                issues.append(batch_finding("FINDING_DUPLICATED", f"Finding {finding_id} appears in multiple Change Set inputs.", [str(path.resolve())], root_cause_id))
                continue
            classification, source = classify_finding(finding)
            if classification is None:
                issues.append(batch_finding("CLASSIFICATION_UNRESOLVED", f"Finding {finding_id} cannot be safely classified ({source}).", [str(path.resolve())], root_cause_id))
            else:
                classifications.setdefault(classification, []).append(finding_id)
            artifact_items = artifacts_for(finding)
            if not artifact_items:
                issues.append(batch_finding("AFFECTED_ARTIFACT_MISSING", f"Finding {finding_id} declares no affected artifact.", [str(path.resolve())], root_cause_id))
            artifacts.extend(artifact_items)
            finding_ids.append(finding_id)
            covered_finding_ids.add(finding_id)
            if finding.get("closeCondition"):
                close_conditions.append(str(finding["closeCondition"]))
            elif finding.get("closeConditions"):
                close_conditions.extend(map(str, finding["closeConditions"]))
            if finding.get("expectedInvariant"):
                invariants.append(str(finding["expectedInvariant"]))
            elif finding.get("expectedInvariants"):
                invariants.extend(map(str, finding["expectedInvariants"]))

        classification_names = sorted(classifications)
        if len(classification_names) > 1:
            issues.append(batch_finding(
                "ROOT_CAUSE_CLASSIFICATION_CONFLICT",
                f"Root cause {root_cause_id} contains conflicting classes: {', '.join(classification_names)}.",
                group_sources,
                root_cause_id,
            ))
        if not classification_names:
            issues.extend(item for item in batch_findings if False)
            batch_findings.extend(issues)
            continue
        classification = classification_names[0]
        route = route_by_class[classification]
        unique_artifacts = list({(item["path"], item["artifactType"]): item for item in artifacts}.values())
        unique_artifacts.sort(key=lambda item: (item["path"], item["artifactType"]))
        merged_checks: OrderedDict[str, dict[str, Any]] = OrderedDict()
        for finding in (item for _, item in root_findings):
            for item in verification_for(finding, route):
                merged_checks.setdefault(item["checkId"], item)
        budget = dict(route["budget"])
        if len(unique_artifacts) > budget["maxAffectedArtifacts"]:
            issues.append(batch_finding("BUDGET_AFFECTED_ARTIFACTS_EXCEEDED", f"Root cause {root_cause_id} affects {len(unique_artifacts)} artifacts, over budget {budget['maxAffectedArtifacts']}.", group_sources, root_cause_id))
        if len(finding_ids) > budget["maxFindings"]:
            issues.append(batch_finding("BUDGET_FINDINGS_EXCEEDED", f"Root cause {root_cause_id} contains {len(finding_ids)} findings, over budget {budget['maxFindings']}.", group_sources, root_cause_id))
        if issues:
            batch_findings.extend(issues)
            continue
        change_set_identity = {
            "rootCauseId": root_cause_id,
            "findingIds": sorted(finding_ids),
            "classification": classification,
            "affectedArtifacts": unique_artifacts,
            "targetRevision": next(iter(revisions)),
        }
        change_sets.append({
            "changeSetId": "CHANGE-SET-" + canonical_hash(change_set_identity)[:16],
            "rootCauseId": root_cause_id,
            "findingIds": sorted(finding_ids),
            "classification": classification,
            "repairTrack": route["repairTrack"],
            "businessRevisionRequired": bool(route["businessRevisionRequired"]),
            "ownerRole": route["ownerRole"],
            "affectedArtifacts": unique_artifacts,
            "verificationPlan": list(merged_checks.values()),
            "budget": budget,
            "closeConditions": sorted(set(close_conditions)) or [f"Close all findings under root cause {root_cause_id}."],
            "expectedInvariants": sorted(set(invariants)),
            "sourceRefs": group_sources,
            "status": "PLANNED",
        })

    if not blocking_findings and not batch_findings:
        status = "NO_CHANGES"
    elif batch_findings or orphan_findings or covered_finding_ids != {str(item.get("findingId")) for _, item in blocking_findings if item.get("findingId")}:
        status = "BLOCKED"
    else:
        status = "READY_FOR_REPAIR"
    unique_batch_findings: OrderedDict[str, dict[str, Any]] = OrderedDict()
    for item in batch_findings:
        unique_batch_findings.setdefault(str(item["findingId"]), item)
    batch_findings = list(unique_batch_findings.values())
    metrics = {
        "blockingFindings": len(blocking_findings),
        "coveredBlockingFindings": len(covered_finding_ids),
        "changeSets": len(change_sets),
        "plannedChangeSets": sum(1 for item in change_sets if item["status"] == "PLANNED"),
        "blockedChangeSets": sum(1 for item in change_sets if item["status"] == "BLOCKED"),
        "businessRevisionChangeSets": sum(1 for item in change_sets if item["repairTrack"] == "BUSINESS_REVISION"),
        "mechanicalChangeSets": sum(1 for item in change_sets if item["repairTrack"] == "MECHANICAL_REPAIR"),
    }
    source_paths = [str(path.resolve()) for path, _ in reviews]
    policy_ref = {"path": str(policy_path.resolve()), "policyId": policy.get("policyId"), "policySha256": sha256_file(policy_path)}
    batch_without_id = {
        "schemaVersion": 1,
        "batchType": "CHANGE_SET_BATCH",
        "workflowId": next(iter(workflow_ids)),
        "targetRevision": next(iter(revisions)),
        "sourceFindings": source_paths,
        "policy": policy_ref,
        "changeSets": change_sets,
        "metrics": metrics,
        "status": status,
        "findings": batch_findings,
    }
    batch = {
        "batchId": "CHANGE-SET-BATCH-" + canonical_hash(batch_without_id)[:16],
        **batch_without_id,
        "createdAt": now(),
    }
    errors = validate_schema_value(batch, "change-set-batch.schema.json")
    if errors:
        raise ValueError("invalid change-set batch: " + "; ".join(errors))
    return batch


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review", action="append", type=Path, required=True, help="Review or finding collection JSON. Repeatable.")
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        reviews = [(path.resolve(), load(path.resolve())) for path in args.review]
        batch = compile_change_sets(reviews, load(args.policy.resolve()), args.policy.resolve())
    except Exception as exc:
        print(json.dumps({"status": "BLOCKED", "errors": [str(exc)]}, ensure_ascii=False, indent=2))
        return 1
    save(args.out.resolve(), batch)
    print(json.dumps({
        "status": batch["status"],
        "changeSets": len(batch["changeSets"]),
        "blockingFindings": batch["metrics"]["blockingFindings"],
        "coveredBlockingFindings": batch["metrics"]["coveredBlockingFindings"],
        "batchId": batch["batchId"],
        "out": str(args.out.resolve()),
    }, ensure_ascii=False, indent=2))
    return 0 if batch["status"] in {"READY_FOR_REPAIR", "NO_CHANGES"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
