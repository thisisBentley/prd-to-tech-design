#!/usr/bin/env python3
"""Validate Policy Pack, Audit Crosswalk and source Skill drift."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from validate_json_schemas import load, validate

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_ROOT = ROOT / "schemas" if (ROOT / "schemas").exists() else ROOT / "references"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def resolve_source(entry: dict[str, Any], source_root: Path) -> Path | None:
    base = ROOT if entry.get("pathKind") == "REPO" else source_root
    candidates = [entry.get("path", ""), *entry.get("alternatePaths", [])]
    for candidate in candidates:
        path = (base / candidate).resolve()
        if path.is_file():
            return path
    return None


def check(check_id: str, passed: bool, observed: Any, expected: str) -> dict[str, Any]:
    return {"checkId": check_id, "status": "passed" if passed else "failed", "observed": observed, "expected": expected}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy-pack", type=Path, required=True)
    parser.add_argument("--crosswalk", type=Path, required=True)
    parser.add_argument("--source-map", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, default=Path.home() / ".codex" / "skills")
    parser.add_argument("--lock", type=Path)
    parser.add_argument("--write-lock", action="store_true")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    policy_path = args.policy_pack.resolve()
    crosswalk_path = args.crosswalk.resolve()
    source_map_path = args.source_map.resolve()
    policy = load(policy_path)
    crosswalk = load(crosswalk_path)
    source_map = load(source_map_path)
    lock = load(args.lock.resolve()) if args.lock and args.lock.is_file() else {}
    errors: list[dict[str, Any]] = []
    drift: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []

    source_map_schema = load(SCHEMA_ROOT / "audit-source-map.schema.json")
    schema_issues = validate(source_map, source_map_schema, source_map_schema)
    checks.append(check("SOURCE_MAP.SCHEMA", not schema_issues, schema_issues, "source map matches its schema"))
    errors.extend({"code": "SOURCE_MAP_SCHEMA", "message": item} for item in schema_issues)

    policy_rules = {str(rule.get("ruleId")) for rule in policy.get("rules", [])}
    mapped_rules = {str(rule) for mapping in crosswalk.get("mappings", []) for rule in mapping.get("policyRuleIds", [])}
    unknown_rules = sorted(mapped_rules - policy_rules)
    missing_rules = sorted(policy_rules - mapped_rules)
    checks.append(check("CROSSWALK.KNOWN_RULES", not unknown_rules, unknown_rules, "every mapped rule exists in the Policy Pack"))
    checks.append(check("CROSSWALK.RULE_COVERAGE", not missing_rules, missing_rules, "every Policy Pack rule is mapped by the Crosswalk"))
    errors.extend({"code": "UNKNOWN_POLICY_RULE", "message": rule} for rule in unknown_rules)
    drift.extend({"code": "UNMAPPED_POLICY_RULE", "message": rule} for rule in missing_rules)

    declared_skills = {str(item.get("skillId")) for item in crosswalk.get("sourceSkills", [])}
    mapped_skills = {str(item.get("skillId")) for item in source_map.get("skills", [])}
    missing_skills = sorted(declared_skills - mapped_skills)
    checks.append(check("SOURCE_MAP.SKILLS", not missing_skills, missing_skills, "every Crosswalk source Skill has a source map entry"))
    errors.extend({"code": "MISSING_SOURCE_SKILL", "message": skill} for skill in missing_skills)

    sources: list[dict[str, Any]] = []
    for entry in source_map.get("skills", []):
        resolved = resolve_source(entry, args.source_root.resolve())
        source = {"skillId": entry.get("skillId"), "path": str(resolved) if resolved else entry.get("path"), "status": "resolved" if resolved else "missing", "sha256": digest(resolved) if resolved else None}
        sources.append(source)
        if not resolved:
            errors.append({"code": "SOURCE_SKILL_MISSING", "message": f"{entry.get('skillId')}: {entry.get('path')}"})
    checks.append(check("SOURCE.SKILL_FILES", all(item["status"] == "resolved" for item in sources), sources, "all mapped source Skills resolve to files"))

    hashes = {"policyPackSha256": digest(policy_path), "crosswalkSha256": digest(crosswalk_path), "sourceMapSha256": digest(source_map_path)}
    if lock:
        for key, current in hashes.items():
            if lock.get(key) and lock.get(key) != current:
                drift.append({"code": "INPUT_HASH_DRIFT", "field": key, "expected": lock.get(key), "observed": current})
        locked_sources = {item.get("skillId"): item.get("sha256") for item in lock.get("sources", [])}
        for source in sources:
            expected = locked_sources.get(source["skillId"])
            if expected and expected != source.get("sha256"):
                drift.append({"code": "SOURCE_HASH_DRIFT", "skillId": source["skillId"], "expected": expected, "observed": source.get("sha256")})
    elif args.lock:
        drift.append({"code": "SOURCE_LOCK_MISSING", "path": str(args.lock.resolve())})

    if args.write_lock and args.lock:
        lock_payload = {"schemaVersion": 1, **hashes, "sources": [{"skillId": item["skillId"], "sha256": item["sha256"]} for item in sources], "generatedAt": now()}
        args.lock.parent.mkdir(parents=True, exist_ok=True)
        args.lock.write_text(json.dumps(lock_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        drift = [item for item in drift if item.get("code") != "SOURCE_LOCK_MISSING"]

    status = "BLOCKED" if errors else ("DRIFT" if drift else "PASS")
    report = {
        "schemaVersion": 1,
        "reportId": f"crosswalk-drift-{crosswalk.get('crosswalkId')}-{crosswalk.get('version')}",
        "status": status,
        "policyPackPath": str(policy_path),
        "crosswalkPath": str(crosswalk_path),
        "sourceMapPath": str(source_map_path),
        "hashes": hashes,
        "sources": sources,
        "checks": checks,
        "drift": drift,
        "errors": errors,
        "checkedAt": now(),
    }
    schema = load(SCHEMA_ROOT / "audit-crosswalk-drift-report.schema.json")
    report_schema_errors = validate(report, schema, schema)
    if report_schema_errors:
        report["status"] = "BLOCKED"
        report["errors"].extend({"code": "REPORT_SCHEMA", "message": item} for item in report_schema_errors)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "drift": len(report["drift"]), "errors": len(report["errors"]), "out": str(args.out)}, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
