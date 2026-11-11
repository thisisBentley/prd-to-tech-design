#!/usr/bin/env python3
"""Resolve the applicable delivery gate rules and emit a frozen policy lock."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from validate_json_schemas import load as load_json, validate as validate_schema

GATES = ["R0", "G1", "O1", "U1", "U2", "QA", "Q1"]
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY_PACK = ROOT / "references" / "gate-policy-current.json"
if not DEFAULT_POLICY_PACK.exists():
    DEFAULT_POLICY_PACK = ROOT / "core" / "gate-policy-current.json"


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def matches(values: list[str] | None, actual: str | list[str]) -> bool:
    if not values or "*" in values:
        return True
    if isinstance(actual, list):
        return not actual or bool(set(values) & set(actual))
    return actual in values


def resolve_rule(rule: dict[str, Any], profile: str, requirement_types: list[str], prototype_status: str, ui_ownership: str) -> tuple[bool, list[str]]:
    conditions = rule.get("appliesWhen") or {}
    reasons: list[str] = []
    if not matches(conditions.get("artifactProfiles"), profile):
        reasons.append(f"artifactProfile={profile} not in {conditions.get('artifactProfiles')}")
    if not matches(conditions.get("requirementTypes"), requirement_types):
        reasons.append(f"requirementTypes={requirement_types} do not match {conditions.get('requirementTypes')}")
    if not matches(conditions.get("prototypeStatuses"), prototype_status):
        reasons.append(f"prototypeStatus={prototype_status} not in {conditions.get('prototypeStatuses')}")
    if not matches(conditions.get("uiOwnerships"), ui_ownership):
        reasons.append(f"uiOwnership={ui_ownership} not in {conditions.get('uiOwnerships')}")
    return not reasons, reasons


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy-pack", type=Path, default=DEFAULT_POLICY_PACK)
    parser.add_argument("--artifact-profile", required=True, choices=["PRD_ONLY", "PRD_PLUS_PROTOTYPE", "EXISTING_PROTOTYPE_REVIEW", "EXTERNAL_UI_BOUNDARY"])
    parser.add_argument("--requirement-types", default="", help="Comma-separated requirement types")
    parser.add_argument("--prototype-status", default="UNKNOWN", choices=["TRIGGERED", "NOT_TRIGGERED", "UNKNOWN"])
    parser.add_argument("--ui-ownership", default="UNKNOWN", choices=["LOCAL", "EXTERNAL", "NONE", "UNKNOWN"])
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    pack_path = args.policy_pack.resolve()
    pack = load(pack_path)
    schema_root = ROOT / "schemas" if (ROOT / "schemas").exists() else ROOT / "references"
    pack_schema = load_json(schema_root / "gate-policy-pack.schema.json")
    pack_errors = validate_schema(pack, pack_schema, pack_schema)
    if pack_errors:
        print(json.dumps({"status": "BLOCKED", "errors": pack_errors[:20], "policyPack": str(pack_path)}, ensure_ascii=False))
        return 1
    requirement_types = [item.strip() for item in args.requirement_types.split(",") if item.strip()]
    applicable = {gate: [] for gate in GATES}
    excluded: list[dict[str, str]] = []
    pack_rules = {item["ruleId"]: item for item in pack.get("rules", [])}
    for rule in pack.get("rules", []):
        ok, reasons = resolve_rule(rule, args.artifact_profile, requirement_types, args.prototype_status, args.ui_ownership)
        if ok:
            applicable.setdefault(rule["gate"], []).append(rule["ruleId"])
        else:
            excluded.append({"ruleId": rule["ruleId"], "reason": "; ".join(reasons)})
    # Fail closed on dangling gate references.
    for gate in GATES:
        applicable.setdefault(gate, [])
        for rule_id in applicable[gate]:
            if pack_rules[rule_id]["gate"] != gate:
                raise SystemExit(f"policy pack inconsistency: {rule_id} listed under {gate}")
    payload = {
        "schemaVersion": 1,
        "policyPackId": pack["policyPackId"],
        "policyPackVersion": pack["policyPackVersion"],
        "ruleSetVersion": pack["ruleSetVersion"],
        "policyPackSha256": sha256(pack_path),
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "scope": {
            "artifactProfile": args.artifact_profile,
            "requirementTypes": requirement_types,
            "prototypeStatus": args.prototype_status,
            "uiOwnership": args.ui_ownership,
        },
        "applicableRules": applicable,
        "excludedRules": excluded,
    }
    lock_schema = load_json(schema_root / "policy-lock.schema.json")
    lock_errors = validate_schema(payload, lock_schema, lock_schema)
    if lock_errors:
        print(json.dumps({"status": "BLOCKED", "errors": lock_errors[:20], "policyLock": str(args.out)}, ensure_ascii=False))
        return 1
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "rules": sum(len(v) for v in applicable.values()), "excluded": len(excluded), "policyLock": str(args.out)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
