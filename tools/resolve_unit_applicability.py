#!/usr/bin/env python3
"""Resolve active policy rules to FR, UI, permission or package-level units."""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from validate_json_schemas import load, validate

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_ROOT = ROOT / "schemas" if (ROOT / "schemas").exists() else ROOT / "references"
FR_RE = re.compile(r"\bFR-\d{3}\b")
AC_RE = re.compile(r"\bAC-\d{3}\b")
GATES = ["R0", "G1", "O1", "U1", "U2", "QA", "Q1"]

MARKERS = {
    "ROLES_PERMISSIONS": r"角色|权限|role|permission",
    "FLOW_BRANCH": r"流程|分支|flow|branch|条件",
    "FIELDS_DATA": r"字段|数据|field|data|table|参数",
    "STATES_EXCEPTIONS": r"状态|异常|失败|空态|state|exception|error",
    "BOUNDARY_RECOVERY": r"边界|恢复|超时|重试|回滚|recover|timeout|fallback",
    "ACCEPTANCE_METADATA": r"\bAC-\d{3}\b|验收|acceptance",
    "AI_LLM": r"AI|LLM|模型|prompt|token",
    "MIGRATION": r"迁移|migration|兼容|compat",
    "ASYNC": r"异步|队列|async|queue|回调|callback",
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_fr_units(prd_path: Path) -> list[dict[str, Any]]:
    lines = prd_path.read_text(encoding="utf-8").splitlines()
    starts = [(index, FR_RE.search(line).group(0)) for index, line in enumerate(lines) if FR_RE.search(line)]
    units: list[dict[str, Any]] = []
    for position, (start, fr_id) in enumerate(starts):
        end = starts[position + 1][0] if position + 1 < len(starts) else len(lines)
        text = "\n".join(lines[start:end])
        units.append({"unitId": fr_id, "unitType": "FR", "frIds": [fr_id], "text": text, "evidenceRefs": [f"{prd_path.name}#{fr_id}"], "line": start + 1, "acIds": sorted(set(AC_RE.findall(text)))})
    return units


def targets_for_rule(rule_id: str, gate: str, fr_units: list[dict[str, Any]], ui_units: list[dict[str, Any]], prd_text: str, prd_name: str) -> tuple[list[str], str, list[str]]:
    suffix = rule_id.rsplit(".", 1)[-1]
    if gate == "R0" or suffix in {"DECISION_READINESS", "DECISION_IMPACT_CLOSURE"} or rule_id.startswith("Q1."):
        unit = "PACKAGE" if gate != "G1" else "DECISION"
        return [unit], f"gate={gate}; package-level rule", [prd_name]
    if gate == "O1":
        return ["OVERVIEW"], "Overview projection rule", [prd_name]
    if gate in {"U1", "U2"}:
        if ui_units:
            return [item["unitId"] for item in ui_units], "Prototype UI bindings", [prd_name]
        return [item["unitId"] for item in fr_units], "no UI manifest binding; fall back to bound FR units", [prd_name]
    if suffix == "BACKGROUND_GOAL_SCOPE":
        return ["PACKAGE"], "goal/scope applies to the whole requirement", [prd_name]
    if suffix in {"ROLES_PERMISSIONS"} and re.search(MARKERS[suffix], prd_text, re.IGNORECASE):
        return ["PERMISSIONS"], "PRD declares roles or permissions", [prd_name]
    if gate == "QA" and suffix == "AC_COVERAGE":
        targeted = [item["unitId"] for item in fr_units if item["acIds"]]
        return targeted or [item["unitId"] for item in fr_units], "acceptance criteria coverage by FR", [prd_name]
    marker = MARKERS.get(suffix)
    if marker:
        targeted = [item["unitId"] for item in fr_units if re.search(marker, item["text"], re.IGNORECASE)]
        if targeted:
            return targeted, f"FR content matches marker {marker}", [prd_name]
        return [item["unitId"] for item in fr_units], "condition active in policy lock; apply to all FR units", [prd_name]
    return [item["unitId"] for item in fr_units] or ["PACKAGE"], "generic rule applies to requirement units", [prd_name]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy-lock", type=Path, required=True)
    parser.add_argument("--prd", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--workflow-id")
    parser.add_argument("--revision")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    lock = load(args.policy_lock.resolve())
    prd_path = args.prd.resolve()
    prd_text = prd_path.read_text(encoding="utf-8")
    fr_units = parse_fr_units(prd_path)
    ui_units: list[dict[str, Any]] = []
    if args.manifest and args.manifest.is_file():
        manifest = load(args.manifest.resolve())
        for item in manifest.get("elements", []):
            ui_units.append({"unitId": str(item.get("uiElementId")), "unitType": "UI", "frIds": list(item.get("frIds") or []), "evidenceRefs": [args.manifest.name + "#" + str(item.get("uiElementId"))]})
    public_fr_units = [{"unitId": item["unitId"], "unitType": "FR", "frIds": item["frIds"], "evidenceRefs": item["evidenceRefs"]} for item in fr_units]
    units = [
        {"unitId": "PACKAGE", "unitType": "PACKAGE", "evidenceRefs": [prd_path.name]},
        {"unitId": "OVERVIEW", "unitType": "OVERVIEW", "evidenceRefs": [prd_path.name]},
        {"unitId": "DECISION", "unitType": "DECISION", "evidenceRefs": [prd_path.name]},
        *([{"unitId": "PERMISSIONS", "unitType": "PERMISSIONS", "evidenceRefs": [prd_path.name]}] if re.search(MARKERS["ROLES_PERMISSIONS"], prd_text, re.IGNORECASE) else []),
        *public_fr_units,
        *ui_units,
    ]
    rules: list[dict[str, Any]] = []
    findings: list[str] = []
    active_ids = {rule_id for gate in GATES for rule_id in (lock.get("applicableRules") or {}).get(gate, [])}
    for gate in GATES:
        for rule_id in (lock.get("applicableRules") or {}).get(gate, []):
            target_ids, basis, evidence_refs = targets_for_rule(rule_id, gate, fr_units, ui_units, prd_text, prd_path.name)
            known = {item["unitId"] for item in units}
            target_ids = sorted(set(target_ids) & known)
            if not target_ids:
                findings.append(f"{rule_id}: no applicable unit target")
            rules.append({"ruleId": rule_id, "gate": gate, "applicability": "ACTIVE", "targetUnitIds": target_ids, "basis": basis, "evidenceRefs": evidence_refs})
    status = "PASS" if not findings else "FAIL"
    report = {
        "schemaVersion": 1,
        "reportId": f"unit-applicability-{args.workflow_id or lock.get('policyPackId')}-{args.revision or 'r1'}",
        "workflowId": args.workflow_id or lock.get("policyPackId"),
        "revision": args.revision or "r1",
        "status": status,
        "units": units,
        "rules": rules,
        "metrics": {
            "rules": len(rules),
            "activeRules": len(active_ids),
            "units": len(units),
            "frUnits": len(fr_units),
            "uiUnits": len(ui_units),
        },
        "checkedAt": now(),
    }
    schema = load(SCHEMA_ROOT / "unit-applicability-report.schema.json")
    schema_errors = validate(report, schema, schema)
    if schema_errors:
        report["status"] = "FAIL"
        findings.extend(schema_errors)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "rules": len(rules), "units": len(units), "findings": len(findings), "out": str(args.out)}, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
