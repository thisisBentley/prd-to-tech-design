#!/usr/bin/env python3
"""Build and validate a Decision Impact Graph for every closed Decision Card.

A closed decision is only considered propagated when it declares the affected
authoritative objects, one expected invariant, zero unresolved conflicting
objects and at least one verification object. This tool is deterministic; it
does not infer business impact from prose.
"""
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
CLOSED_STATUSES = {"confirmed", "closed"}
PRD_OBJECT_TYPES = {"GOAL", "FR", "BR", "IR", "STATE", "AC"}
PRD_ID_RE = re.compile(r"\b(?:G|FR|BR|IR|STATE|AC)-[A-Z0-9_-]+\b")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def normalize_ref(value: dict[str, Any]) -> dict[str, Any]:
    """Keep only schema fields so upstream annotations do not leak into the graph."""
    result = {
        "objectId": str(value.get("objectId", "")).strip(),
        "objectType": str(value.get("objectType", "")).strip().upper(),
        "artifact": str(value.get("artifact", "")).strip(),
        "evidenceRefs": [str(item) for item in value.get("evidenceRefs", []) if str(item).strip()],
    }
    if value.get("location"):
        result["location"] = str(value["location"])
    return result


def resolve_artifact(value: str, artifact_root: Path) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (artifact_root / path).resolve()


def validate_ref(ref: dict[str, Any], artifact_root: Path, prd_text: str, prd_path: Path) -> list[str]:
    errors: list[str] = []
    object_id = ref.get("objectId", "")
    object_type = ref.get("objectType", "")
    artifact_value = ref.get("artifact", "")
    if not object_id:
        errors.append("objectId is required")
    if not object_type:
        errors.append(f"{object_id or '<unknown>'}: objectType is required")
    if object_type and object_type not in {
        "GOAL", "FR", "BR", "IR", "STATE", "AC", "OVERVIEW", "DIAGRAM",
        "PROTOTYPE", "TEST_PLAN", "XMIND", "JIRA", "EVIDENCE", "OTHER",
    }:
        errors.append(f"{object_id or '<unknown>'}: unsupported objectType {object_type}")
    if not artifact_value:
        errors.append(f"{object_id or '<unknown>'}: artifact is required")
        return errors
    artifact = resolve_artifact(artifact_value, artifact_root)
    if not artifact.is_file():
        errors.append(f"{object_id or '<unknown>'}: artifact does not exist: {artifact_value}")
        return errors
    if not ref.get("evidenceRefs"):
        errors.append(f"{object_id or '<unknown>'}: evidenceRefs is required")
    text = artifact.read_text(encoding="utf-8", errors="replace")
    if object_type in PRD_OBJECT_TYPES:
        if artifact.resolve() != prd_path.resolve():
            errors.append(f"{object_id}: PRD objectType must cite PRD_DELIVERY.md, got {artifact_value}")
        if object_id not in prd_text:
            errors.append(f"{object_id}: object is not present in PRD")
    elif object_id not in text and object_type not in {"OVERVIEW", "DIAGRAM", "PROTOTYPE", "TEST_PLAN", "XMIND", "JIRA", "EVIDENCE"}:
        errors.append(f"{object_id}: object is not present in {artifact_value}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prd", type=Path, required=True)
    parser.add_argument("--workflow-id", required=True)
    parser.add_argument("--revision", default="r1")
    parser.add_argument("--decision-context", type=Path)
    parser.add_argument("--impact-input", type=Path, help="Optional sidecar graph input with a decisions array.")
    parser.add_argument("--artifact-root", type=Path, help="Root used to resolve relative artifact paths. Defaults to the PRD directory.")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    prd_path = args.prd.resolve()
    if not prd_path.is_file():
        print(json.dumps({"status": "BLOCKED", "error": f"PRD not found: {prd_path}"}, ensure_ascii=False))
        return 1
    artifact_root = args.artifact_root.resolve() if args.artifact_root else prd_path.parent
    prd_text = prd_path.read_text(encoding="utf-8", errors="replace")
    context = load(args.decision_context.resolve()) if args.decision_context and args.decision_context.is_file() else {}
    input_doc = load(args.impact_input.resolve()) if args.impact_input and args.impact_input.is_file() else {}
    input_by_id = {
        str(item.get("decisionId", "")): item
        for item in input_doc.get("decisions", [])
        if isinstance(item, dict) and item.get("decisionId")
    }
    decisions: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    for decision in context.get("decisions", []):
        if decision.get("status") not in CLOSED_STATUSES:
            continue
        decision_id = str(decision.get("decisionId", ""))
        selected = str(
            (decision.get("confirmation") or {}).get("selectedOptionId")
            or (decision.get("recommendation") or {}).get("optionId")
            or ""
        )
        source = input_by_id.get(decision_id) or decision.get("decisionImpact") or {}
        affected = [normalize_ref(item) for item in source.get("affectedObjects", []) if isinstance(item, dict)]
        conflicting = [normalize_ref(item) for item in source.get("conflictingObjects", []) if isinstance(item, dict)]
        verification = [normalize_ref(item) for item in source.get("verificationObjects", []) if isinstance(item, dict)]
        expected_invariant = str(source.get("expectedInvariant", "")).strip() or "UNRESOLVED"
        evidence_refs = [str(item) for item in source.get("evidenceRefs", []) if str(item).strip()]
        errors: list[str] = []
        if not selected:
            errors.append("closed decision has no selected option")
        if not source:
            errors.append("closed decision has no decisionImpact declaration")
        if not affected:
            errors.append("affectedObjects must contain at least one object")
        if not expected_invariant:
            errors.append("expectedInvariant is required")
        if conflicting:
            errors.append("conflictingObjects must be empty before CONTENT_READY")
        if not verification:
            errors.append("verificationObjects must contain at least one object")
        if not evidence_refs:
            errors.append("decision-level evidenceRefs is required")
        if affected and not any(ref.get("objectType") in PRD_OBJECT_TYPES for ref in affected):
            errors.append("at least one affected object must be an authoritative PRD object")
        verification_types = {ref.get("objectType") for ref in verification}
        if verification and not verification_types.intersection({"AC", "TEST_PLAN", "PROTOTYPE", "EVIDENCE"}):
            errors.append("verificationObjects must include an AC, test plan, prototype or evidence object")
        affected_ids = {ref.get("objectId") for ref in affected if ref.get("objectId")}
        conflicting_ids = {ref.get("objectId") for ref in conflicting if ref.get("objectId")}
        overlap = sorted(affected_ids & conflicting_ids)
        if overlap:
            errors.append("objects cannot be both affected and conflicting: " + ", ".join(overlap))
        for label, refs in (("affectedObjects", affected), ("conflictingObjects", conflicting), ("verificationObjects", verification)):
            for ref in refs:
                for error in validate_ref(ref, artifact_root, prd_text, prd_path):
                    errors.append(f"{label}: {error}")
        for ref in evidence_refs:
            path = resolve_artifact(ref.split("#", 1)[0], artifact_root)
            if not path.exists():
                errors.append(f"evidenceRef does not exist: {ref}")
        status = "BLOCKED" if errors else "PASS"
        decisions.append({
            "decisionId": decision_id,
            "selectedOptionId": selected or "UNRESOLVED",
            "status": status,
            "affectedObjects": affected,
            "expectedInvariant": expected_invariant,
            "conflictingObjects": conflicting,
            "verificationObjects": verification,
            "evidenceRefs": evidence_refs,
            "errors": errors,
        })
        for index, message in enumerate(errors, start=1):
            findings.append({
                "findingId": f"DI-{decision_id}-{index:03d}",
                "decisionId": decision_id,
                "severity": "BLOCKING",
                "code": "DECISION_IMPACT_GAP",
                "message": message,
                "evidenceRefs": [str(prd_path), *([str(args.decision_context.resolve())] if args.decision_context and args.decision_context.exists() else [])],
            })
    graph_id = "DIG-" + hashlib.sha256((args.workflow_id + args.revision + digest(prd_path)).encode()).hexdigest()[:16]
    status = "BLOCKED" if findings else "PASS"
    payload = {
        "schemaVersion": 1,
        "graphId": graph_id,
        "workflowId": args.workflow_id,
        "targetRevision": args.revision,
        "prdPath": str(prd_path),
        "prdSha256": digest(prd_path),
        "status": status,
        "decisions": decisions,
        "findings": findings,
        "metrics": {
            "closedDecisions": len(decisions),
            "passed": sum(1 for item in decisions if item["status"] == "PASS"),
            "blocked": sum(1 for item in decisions if item["status"] == "BLOCKED"),
            "affectedObjects": sum(len(item["affectedObjects"]) for item in decisions),
            "verificationObjects": sum(len(item["verificationObjects"]) for item in decisions),
        },
        "generatedAt": datetime.now(timezone.utc).isoformat(),
    }
    schema = load(SCHEMA_ROOT / "decision-impact-graph.schema.json")
    schema_errors = validate(payload, schema, schema)
    if schema_errors:
        status = "BLOCKED"
        payload["status"] = status
    save(args.out, payload)
    print(json.dumps({
        "status": status,
        "closedDecisions": len(decisions),
        "blocked": sum(1 for item in decisions if item["status"] == "BLOCKED"),
        "schemaErrors": schema_errors[:10],
        "out": str(args.out),
    }, ensure_ascii=False))
    return 0 if status == "PASS" and not schema_errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
