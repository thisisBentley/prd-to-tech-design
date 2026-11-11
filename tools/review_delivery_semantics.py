#!/usr/bin/env python3
"""Review semantic units through local, edge and global integration lenses."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from validate_json_schemas import load, validate

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_ROOT = ROOT / "schemas" if (ROOT / "schemas").exists() else ROOT / "references"


def check(check_id: str, layer: str, passed: bool | None, observed: Any, expected: str, evidence: list[str], owner: str, close_condition: str) -> dict[str, Any]:
    status = "passed" if passed is True else ("failed" if passed is False else "warning")
    return {
        "checkId": check_id,
        "layer": layer,
        "status": status,
        "observed": observed,
        "expected": expected,
        "evidenceRefs": evidence,
        "owner": owner,
        "closeCondition": close_condition,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    model_path = args.model.resolve()
    model = load(model_path)
    schema = load(SCHEMA_ROOT / "delivery-semantic-model.schema.json")
    schema_errors = validate(model, schema, schema)
    units = model.get("units", [])
    edges = model.get("edges", [])
    contracts = model.get("globalContracts", [])
    unit_by_id = {unit.get("unitId"): unit for unit in units}
    contract_ids = {item.get("contractId") for item in contracts}
    features = [unit for unit in units if unit.get("kind") == "FEATURE_SLICE"]
    acceptance = [unit for unit in units if unit.get("kind") == "ACCEPTANCE_CRITERION"]
    interactions = [unit for unit in units if unit.get("kind") == "INTERACTION_CONTRACT"]
    checks: list[dict[str, Any]] = []
    evidence = [str(model_path)]

    checks.append(check("SEMANTIC.MODEL.SCHEMA", "CONTRACT", not schema_errors, schema_errors, "semantic model satisfies its frozen schema", evidence, "delivery-producer", "Repair the semantic model contract."))

    duplicate_ids = sorted(item for item, count in Counter(unit.get("unitId") for unit in units).items() if count > 1)
    checks.append(check("SEMANTIC.UNITS.UNIQUE", "GLOBAL", not duplicate_ids, duplicate_ids, "every semantic unit ID is unique", evidence, "delivery-producer", "Remove duplicate unit IDs."))

    required_fr_sections = {"需求说明", "前置与触发", "产品逻辑", "业务规则", "数据", "异常"}
    incomplete_fr: dict[str, list[str]] = {}
    for unit in features:
        titles = set(unit.get("sections", {}))
        missing = sorted(required_fr_sections - titles)
        if missing:
            incomplete_fr[unit["unitId"]] = missing
    checks.append(check("LOCAL.FR.SECTIONS", "LOCAL", not incomplete_fr, incomplete_fr, "each feature slice contains the core closed-loop sections", [unit.get("sourceRef", "") for unit in features], "prd-producer", "Add the missing feature-slice sections and rebuild the semantic model."))

    required_ac_fields = {"关联功能", "前置条件", "WHEN", "THEN", "验收方式"}
    incomplete_ac: dict[str, list[str]] = {}
    for unit in acceptance:
        fields = set(unit.get("fields", {}))
        missing = sorted(required_ac_fields - fields)
        if missing:
            incomplete_ac[unit["unitId"]] = missing
    checks.append(check("LOCAL.AC.CLOSED", "LOCAL", not incomplete_ac, incomplete_ac, "every AC contains relation, precondition, trigger, result and verification", [unit.get("sourceRef", "") for unit in acceptance], "prd-producer", "Complete the AC fields and rebuild the semantic model."))

    outgoing = Counter(edge.get("fromUnitId") for edge in edges if edge.get("status") == "ACTIVE")
    incoming = Counter(edge.get("toUnitId") for edge in edges if edge.get("status") == "ACTIVE")
    fr_without_ac = sorted(unit["unitId"] for unit in features if not any(edge.get("fromUnitId") == unit["unitId"] and edge.get("relation") == "VERIFIED_BY" for edge in edges))
    checks.append(check("EDGE.FR_AC", "EDGE", not fr_without_ac, fr_without_ac, "every FR is verified by at least one AC", evidence, "prd-producer", "Add or bind an AC for every FR."))

    ac_without_fr = sorted(unit["unitId"] for unit in acceptance if not unit.get("frIds"))
    dangling_ac_fr = sorted({fr_id for unit in acceptance for fr_id in unit.get("frIds", []) if fr_id not in unit_by_id})
    ac_edge_ok = not ac_without_fr and not dangling_ac_fr
    checks.append(check("EDGE.AC_FR", "EDGE", ac_edge_ok, {"withoutFr": ac_without_fr, "danglingFr": dangling_ac_fr}, "every AC binds to existing FR units", evidence, "prd-producer", "Repair AC-to-FR bindings."))

    missing_ui_refs: list[dict[str, str]] = []
    for unit in interactions:
        for ref in unit.get("frIds", []) + unit.get("acIds", []):
            if ref not in unit_by_id:
                missing_ui_refs.append({"uiId": unit["unitId"], "missingRef": ref})
    checks.append(check("EDGE.UI_BINDINGS", "EDGE", not missing_ui_refs, missing_ui_refs, "every interaction contract binds to existing FR and AC units", [unit.get("sourceRef", "") for unit in interactions] or evidence, "prototype-producer", "Repair Prototype Manifest bindings."))

    ac_ui_bound = {edge.get("toUnitId") for edge in edges if edge.get("relation") == "BINDS_UI" and str(edge.get("toUnitId", "")).startswith("AC-")}
    unbound_acs = sorted(unit["unitId"] for unit in acceptance if unit["unitId"] not in ac_ui_bound)
    profile = model.get("artifactProfile")
    if profile in {"PRD_PLUS_PROTOTYPE", "EXISTING_PROTOTYPE_REVIEW"}:
        coverage_pass: bool | None = False if unbound_acs else True
        if not interactions:
            coverage_pass = None
    elif profile == "PRD_ONLY":
        coverage_pass = True
        unbound_acs = []
    else:
        coverage_pass = None
    checks.append(check("GLOBAL.AC_UI_COVERAGE", "GLOBAL", coverage_pass, {"unboundAcs": unbound_acs, "interactionContracts": len(interactions)}, "every AC has a prototype interaction binding or is explicitly non-UI", [unit.get("sourceRef", "") for unit in interactions] or evidence, "prototype-producer", "Bind each UI-visible AC to a Manifest element, or mark it explicitly NON_UI."))

    permission_features = [unit["unitId"] for unit in features if any(term in unit.get("content", "") for term in ("权限", "角色", "可见", "隐藏", "禁用", "无权限"))]
    missing_permission_dependency = sorted(
        unit_id for unit_id in permission_features
        if "GC-PERMISSIONS" not in unit_by_id[unit_id].get("dependencies", [])
    ) if "GC-PERMISSIONS" in contract_ids else []
    permission_pass: bool | None = False if missing_permission_dependency else (True if permission_features else None)
    checks.append(check("GLOBAL.PERMISSION_DEPENDENCY", "GLOBAL", permission_pass, {"features": permission_features, "missingDependency": missing_permission_dependency}, "features using permissions depend on the single permission contract", evidence, "prd-producer", "Reference GC-PERMISSIONS instead of repeating permission rules."))

    state_features = [unit["unitId"] for unit in features if any(term in unit.get("content", "") for term in ("状态", "空态", "失败", "加载", "处理中", "禁用"))]
    missing_state_dependency = sorted(
        unit_id for unit_id in state_features
        if "GC-STATE-MODEL" not in unit_by_id[unit_id].get("dependencies", [])
    ) if "GC-STATE-MODEL" in contract_ids else []
    state_pass: bool | None = False if missing_state_dependency else (True if state_features else None)
    checks.append(check("GLOBAL.STATE_DEPENDENCY", "GLOBAL", state_pass, {"features": state_features, "missingDependency": missing_state_dependency}, "features using states depend on the single state contract", evidence, "prd-producer", "Reference GC-STATE-MODEL instead of redefining state semantics."))

    governed_kinds = {"PERMISSION", "STATE", "ENUM", "TERMINOLOGY", "CAPABILITY"}
    orphan_contracts = sorted(
        item["contractId"] for item in contracts
        if item.get("kind") in governed_kinds and incoming[item["contractId"]] == 0
    )
    checks.append(check("GLOBAL.CONTRACT_REUSE", "GLOBAL", None if orphan_contracts else True, orphan_contracts, "governed global contracts are referenced by feature units", evidence, "prd-producer", "Reference or remove unused global contracts."))

    generation_path = model.get("generationContractPath")
    if generation_path and Path(generation_path).exists():
        generation = load(Path(generation_path))
        generation_status = generation.get("status")
        generation_pass: bool | None = True if generation_status == "READY" else (None if generation_status == "READY_WITH_ACTIONS" else False)
        checks.append(check("CONTRACT.GENERATION", "CONTRACT", generation_pass, {"status": generation_status, "metrics": generation.get("metrics")}, "generation contract is READY before production authoring", [generation_path], "delivery-producer", "Close generation-contract actions before production authoring."))
    else:
        checks.append(check("CONTRACT.GENERATION", "CONTRACT", None, "generation contract not supplied", "generation contract is linked to the semantic model", evidence, "delivery-producer", "Build and link the generation contract."))

    failed = [item for item in checks if item["status"] == "failed"]
    warnings = [item for item in checks if item["status"] == "warning"]
    findings: list[dict[str, Any]] = []
    for item in failed + warnings:
        severity = "BLOCKING" if item["status"] == "failed" else "NON_BLOCKING"
        findings.append({
            "findingId": f"SEM-{len(findings) + 1:03d}",
            "severity": severity,
            "checkId": item["checkId"],
            "title": item["checkId"],
            "owner": item.get("owner", "delivery-producer"),
            "closeCondition": item.get("closeCondition", "Resolve the semantic check."),
            "evidenceRefs": item.get("evidenceRefs", []),
        })

    status = "NEEDS_FIX" if failed else ("PASS_WITH_NONBLOCKING" if warnings else "PASS")
    payload = {
        "schemaVersion": 1,
        "workflowId": model.get("workflowId", "UNKNOWN"),
        "targetRevision": model.get("targetRevision", "r1"),
        "status": status,
        "blockingCount": len(failed),
        "checks": checks,
        "findings": findings,
        "metrics": {
            "checks": len(checks),
            "passed": sum(1 for item in checks if item["status"] == "passed"),
            "warnings": len(warnings),
            "failed": len(failed),
            "blockingCount": len(failed),
        },
        "checkedAt": datetime.now(timezone.utc).isoformat(),
    }
    review_schema = load(SCHEMA_ROOT / "semantic-integration-review.schema.json")
    review_errors = validate(payload, review_schema, review_schema)
    if review_errors:
        payload["status"] = "BLOCKED"
        payload["blockingCount"] = max(1, payload["blockingCount"])
        payload["findings"].append({
            "findingId": f"SEM-{len(payload['findings']) + 1:03d}",
            "severity": "BLOCKING",
            "checkId": "SEMANTIC.REVIEW.SCHEMA",
            "title": "Semantic integration review violates its schema",
            "owner": "delivery-producer",
            "closeCondition": "Repair the semantic review output contract.",
            "evidenceRefs": evidence,
        })
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "blockingCount": payload["blockingCount"], "warnings": len(warnings), "checks": len(checks), "out": str(args.out)}, ensure_ascii=False))
    return 0 if payload["status"] in {"PASS", "PASS_WITH_NONBLOCKING"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
