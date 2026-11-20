#!/usr/bin/env python3
"""Compile Decision Context, Semantic Model and optional Decision Impact Graph into a Decision Contract."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from validate_json_schemas import load, validate

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_ROOT = ROOT / "schemas" if (ROOT / "schemas").exists() else ROOT / "references"
CLOSED = {"confirmed", "closed"}
ID_PATTERN = re.compile(r"\b(?:G|FR|BR|IR|STATE|AC)-[A-Z0-9_-]+\b")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def decide_status(decision: dict[str, Any]) -> tuple[bool, str | None, list[str]]:
    issues: list[str] = []
    status = str(decision.get("status", "open"))
    selected = (
        (decision.get("confirmation") or {}).get("selectedOptionId")
        or (decision.get("recommendation") or {}).get("optionId")
    )
    if decision.get("blocking") and status not in CLOSED:
        issues.append("OPEN_BLOCKING_DECISION")
    if not decision.get("owner"):
        issues.append("DECISION_OWNER_MISSING")
    if status in CLOSED and not selected:
        issues.append("CLOSED_DECISION_HAS_NO_SELECTED_OPTION")
    return status in CLOSED, selected, issues


def collect_impact(decision: dict[str, Any], graph_by_id: dict[str, dict[str, Any]]) -> tuple[list[str], list[str], str | None, list[str]]:
    source = graph_by_id.get(str(decision.get("decisionId", ""))) or decision.get("decisionImpact") or {}
    affected = [str(item.get("objectId")) for item in source.get("affectedObjects", []) if isinstance(item, dict) and item.get("objectId")]
    verification = [str(item.get("objectId")) for item in source.get("verificationObjects", []) if isinstance(item, dict) and item.get("objectId")]
    expected = str(source.get("expectedInvariant", "")).strip() or None
    refs = [str(item) for item in source.get("evidenceRefs", []) if str(item).strip()]
    return sorted(dict.fromkeys(affected)), sorted(dict.fromkeys(verification)), expected, refs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prd", type=Path, required=True)
    parser.add_argument("--decision-context", type=Path, required=True)
    parser.add_argument("--semantic-model", type=Path)
    parser.add_argument("--decision-impact-graph", type=Path)
    parser.add_argument("--workflow-id", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    prd = args.prd.resolve()
    context_path = args.decision_context.resolve()
    if not prd.is_file() or not context_path.is_file():
        raise SystemExit("PRD or decision context missing")
    context = load(context_path)
    graph = load(args.decision_impact_graph.resolve()) if args.decision_impact_graph and args.decision_impact_graph.is_file() else {}
    graph_by_id = {str(item.get("decisionId")): item for item in graph.get("decisions", []) if isinstance(item, dict) and item.get("decisionId")}
    decisions: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    semantic_path = args.semantic_model.resolve() if args.semantic_model else None
    semantic: dict[str, Any] = {}
    semantic_error: str | None = None
    if semantic_path is None:
        semantic_error = "Semantic model is required for decision readiness."
    elif not semantic_path.is_file():
        semantic_error = f"Semantic model not found: {semantic_path}"
    else:
        semantic = load(semantic_path)
    semantic_units = [item for item in semantic.get("units", []) if isinstance(item, dict)]
    semantic_ids = {str(item.get("unitId")) for item in semantic_units}
    traceability_finding_index = 1
    if semantic_error:
        semantic_evidence = [str(context_path), str(prd)]
        if semantic_path is not None:
            semantic_evidence.append(str(semantic_path))
        findings.append({
            "findingId": f"DC-TRACEABILITY-{traceability_finding_index:03d}",
            "decisionId": "TRACEABILITY",
            "severity": "BLOCKING",
            "code": "SEMANTIC_MODEL_MISSING",
            "message": semantic_error,
            "evidenceRefs": semantic_evidence,
        })
        traceability_finding_index += 1
    decision_to_objects: dict[str, list[str]] = {}
    object_to_decisions: dict[str, list[str]] = {}
    for decision in context.get("decisions", []):
        decision_id = str(decision.get("decisionId", "UNKNOWN"))
        closed, selected, issues = decide_status(decision)
        affected, verification, expected, impact_refs = collect_impact(decision, graph_by_id)
        if closed and not affected:
            issues.append("CLOSED_DECISION_HAS_NO_AFFECTED_OBJECT")
        if closed and not verification:
            issues.append("CLOSED_DECISION_HAS_NO_VERIFICATION_OBJECT")
        if closed and not expected:
            issues.append("CLOSED_DECISION_HAS_NO_EXPECTED_INVARIANT")
        if semantic_ids:
            missing = sorted(item for item in affected if item not in semantic_ids)
            if missing:
                issues.append("DECISION_TARGET_NOT_IN_SEMANTIC_MODEL: " + ",".join(missing))
        source_refs = list(decision.get("researchRecordRefs") or [])
        source_refs.extend(impact_refs)
        source_refs = sorted(dict.fromkeys(str(item) for item in source_refs if str(item).strip()))
        decisions.append({
            "decisionId": decision_id,
            "title": str(decision.get("title", decision_id)),
            "category": str(decision.get("category", "product_decision")),
            "blocking": bool(decision.get("blocking")),
            "status": str(decision.get("status", "open")),
            "owner": str(decision.get("owner") or "UNASSIGNED"),
            "selectedOptionId": selected,
            "affectedObjectIds": affected,
            "verificationObjectIds": verification,
            "expectedInvariant": expected,
            "sourceRefs": source_refs,
            "issues": issues,
        })
        trace_objects = sorted(dict.fromkeys([*affected, *verification]))
        decision_to_objects[decision_id] = trace_objects
        for object_id in trace_objects:
            object_to_decisions.setdefault(object_id, []).append(decision_id)
        for index, issue in enumerate(issues, start=1):
            severity = "BLOCKING" if issue.startswith(("OPEN_", "CLOSED_", "DECISION_")) else "NON_BLOCKING"
            findings.append({
                "findingId": f"DC-{decision_id}-{index:03d}",
                "decisionId": decision_id,
                "severity": severity,
                "code": issue.split(":", 1)[0],
                "message": issue,
                "evidenceRefs": [str(context_path), str(prd), *source_refs],
            })

    # A decision contract is only ready when every semantic FR/BR/AC is
    # traceable. Priority-field filtering is unsafe here because AC units often
    # do not carry their own priority and would otherwise silently escape the
    # gate. The legacy field name is retained for contract compatibility.
    required_object_ids = {
        str(item.get("unitId")) for item in semantic_units
        if str(item.get("unitId", "")).startswith(("FR-", "BR-", "AC-"))
    }
    mapped_objects = set(object_to_decisions)
    uncovered = sorted(required_object_ids - mapped_objects)
    semantic_evidence = [str(context_path), str(prd)]
    if semantic_path is not None and semantic_path.is_file():
        semantic_evidence.append(str(semantic_path))
    for object_id in uncovered:
        findings.append({
            "findingId": f"DC-TRACEABILITY-{traceability_finding_index:03d}",
            "decisionId": "TRACEABILITY",
            "severity": "BLOCKING",
            "code": "UNDECIDED_P0_P1_OBJECT",
            "message": f"{object_id} has no decision source in the decision context.",
            "evidenceRefs": semantic_evidence,
        })
        traceability_finding_index += 1
    blocking_findings = [item for item in findings if item["severity"] == "BLOCKING"]
    status = "BLOCKED" if blocking_findings else "PASS"
    readiness = "BLOCKED" if blocking_findings else "READY"
    payload_without_id = {
        "schemaVersion": 1,
        "workflowId": args.workflow_id,
        "targetRevision": args.revision,
        "prdPath": str(prd),
        "prdSha256": digest(prd),
        "decisionContextPath": str(context_path),
        "decisionContextSha256": digest(context_path),
        **({"semanticModelPath": str(args.semantic_model.resolve()), "semanticModelSha256": digest(args.semantic_model.resolve())} if args.semantic_model and args.semantic_model.is_file() else {}),
        **({"decisionImpactGraphPath": str(args.decision_impact_graph.resolve()), "decisionImpactGraphSha256": digest(args.decision_impact_graph.resolve())} if args.decision_impact_graph and args.decision_impact_graph.is_file() else {}),
        "status": status,
        "readiness": readiness,
        "decisions": decisions,
        "traceability": {
            "decisionToObjects": decision_to_objects,
            "objectToDecisions": object_to_decisions,
            "uncoveredP0P1ObjectIds": uncovered,
        },
        "findings": findings,
        "metrics": {
            "decisions": len(decisions),
            "closed": sum(1 for item in decisions if item["status"] in CLOSED),
            "openBlocking": sum(1 for item in decisions if item["blocking"] and item["status"] not in CLOSED),
            "mappedObjects": len(mapped_objects),
            "traceableObjects": len(required_object_ids - set(uncovered)),
        },
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }
    contract_id = "DECISION-CONTRACT-" + hashlib.sha256((args.workflow_id + args.revision + digest(prd) + digest(context_path)).encode()).hexdigest()[:16]
    payload = {"contractId": contract_id, **payload_without_id}
    schema = load(SCHEMA_ROOT / "decision-contract.schema.json")
    errors = validate(payload, schema, schema)
    if errors:
        print(json.dumps({"status": "BLOCKED", "schemaErrors": errors[:20]}, ensure_ascii=False, indent=2))
        return 1
    save(args.out.resolve(), payload)
    print(json.dumps({"status": status, "readiness": readiness, "decisions": len(decisions), "openBlocking": payload["metrics"]["openBlocking"], "out": str(args.out.resolve())}, ensure_ascii=False, indent=2))
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
