#!/usr/bin/env python3
"""Build an independent Audit Track plan from a frozen policy lock and rule crosswalk."""
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
GATES = ["R0", "G1", "O1", "U1", "U2", "QA", "Q1"]
PASS_CONDITION = "all bound policy rules have independent PASS evidence and no blocking finding remains"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def schema_errors(name: str, value: dict[str, Any]) -> list[str]:
    schema = load(SCHEMA_ROOT / name)
    return validate(value, schema, schema)


def stable_token(value: str) -> str:
    return "".join(char if char.isalnum() else "-" for char in value.upper()).strip("-")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy-lock", type=Path, required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--crosswalk", type=Path, required=True)
    parser.add_argument("--workflow-id", required=True)
    parser.add_argument("--revision", default="r1")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    policy_path = args.policy_lock.resolve()
    profile_path = args.profile.resolve()
    crosswalk_path = args.crosswalk.resolve()
    policy = load(policy_path)
    profile = load(profile_path)
    crosswalk = load(crosswalk_path)
    errors: list[str] = []
    errors.extend(schema_errors("audit-profile.schema.json", profile))
    errors.extend(schema_errors("toolbox-rule-crosswalk.schema.json", crosswalk))

    required_gates = set(profile.get("requiredGates") or [])
    allowed_executors = set(profile.get("executorTypes") or [])
    minimum_executors = int(profile.get("minimumExecutorsPerRule") or 1)
    expected_rules = sorted(
        rule_id
        for gate in GATES
        if gate in required_gates
        for rule_id in (policy.get("applicableRules") or {}).get(gate, [])
    )
    focus_rules = set(profile.get("focusRuleIds") or [])
    missing_focus_rules = sorted(focus_rules - set(expected_rules))
    if missing_focus_rules:
        errors.append(f"profile focus rules are not active in the policy lock: {', '.join(missing_focus_rules)}")

    source_skills = {item.get("skillId") for item in crosswalk.get("sourceSkills", [])}
    mapping_ids: set[str] = set()
    jobs: list[dict[str, Any]] = []
    rule_executors: dict[str, set[str]] = {rule_id: set() for rule_id in expected_rules}

    for mapping in sorted(crosswalk.get("mappings", []), key=lambda item: item.get("mappingId", "")):
        mapping_id = str(mapping.get("mappingId", ""))
        if mapping_id in mapping_ids:
            errors.append(f"duplicate mappingId: {mapping_id}")
        mapping_ids.add(mapping_id)
        if profile.get("profileId") not in mapping.get("appliesToProfiles", []):
            continue
        skill_id = str(mapping.get("skillId", ""))
        if skill_id not in source_skills:
            errors.append(f"{mapping_id}: unknown source skill {skill_id}")
        bound_rules = sorted(set(mapping.get("policyRuleIds", [])) & set(expected_rules))
        if not bound_rules:
            continue
        mapping_executors = sorted(set(mapping.get("executorTypes", [])) & allowed_executors)
        if not mapping_executors:
            errors.append(f"{mapping_id}: no executor type is enabled by profile {profile.get('profileId')}")
            continue
        for executor in mapping_executors:
            job_id = f"AUD-{stable_token(str(profile.get('profileId', '')))}-{stable_token(mapping_id)}-{executor}"
            jobs.append({
                "jobId": job_id,
                "jobType": "RULE_AUDIT",
                "sourcePolicyRuleIds": bound_rules,
                "sourceSkillId": skill_id,
                "sourceSkillCheckIds": list(mapping.get("skillCheckIds", [])),
                "executorType": executor,
                "owner": mapping.get("owner"),
                "requiredEvidence": list(mapping.get("requiredEvidence", [])),
                "passCondition": PASS_CONDITION,
            })
            for rule_id in bound_rules:
                rule_executors[rule_id].add(executor)

    required_global_types: list[str] = []
    if profile.get("requireEdgeReview"):
        required_global_types.append("EDGE_REVIEW")
    if profile.get("requireGlobalIntegrationReview"):
        required_global_types.append("GLOBAL_INTEGRATION_REVIEW")
    present_global_types: set[str] = set()
    for audit in sorted(crosswalk.get("globalAudits", []), key=lambda item: item.get("auditId", "")):
        audit_type = str(audit.get("auditType", ""))
        if profile.get("profileId") not in audit.get("appliesToProfiles", []):
            continue
        if audit_type not in required_global_types:
            continue
        executor = str(audit.get("executorType", ""))
        if executor not in allowed_executors:
            errors.append(f"{audit.get('auditId')}: global audit executor {executor} is not enabled by profile")
            continue
        skill_id = str(audit.get("skillId", ""))
        if skill_id not in source_skills:
            errors.append(f"{audit.get('auditId')}: unknown source skill {skill_id}")
        present_global_types.add(audit_type)
        jobs.append({
            "jobId": f"AUD-{stable_token(str(profile.get('profileId', '')))}-{stable_token(str(audit.get('auditId', '')))}-{executor}",
            "jobType": audit_type,
            "sourcePolicyRuleIds": [],
            "sourceSkillId": skill_id,
            "sourceSkillCheckIds": list(audit.get("skillCheckIds", [])),
            "executorType": executor,
            "owner": audit.get("owner"),
            "requiredEvidence": list(audit.get("requiredEvidence", [])),
            "passCondition": PASS_CONDITION,
        })
    for required_type in required_global_types:
        if required_type not in present_global_types:
            errors.append(f"profile requires {required_type} but the crosswalk supplies no enabled audit")

    job_ids: set[str] = set()
    for job in jobs:
        if job["jobId"] in job_ids:
            errors.append(f"duplicate audit jobId: {job['jobId']}")
        job_ids.add(job["jobId"])

    uncovered = [rule_id for rule_id, executors in rule_executors.items() if not executors]
    under_covered = [rule_id for rule_id, executors in rule_executors.items() if len(executors) < minimum_executors]
    if uncovered:
        errors.append(f"uncovered policy rules: {', '.join(uncovered)}")
    if under_covered:
        errors.append(f"rules below minimum executor coverage ({minimum_executors}): {', '.join(under_covered)}")

    plan = {
        "schemaVersion": 1,
        "auditPlanId": f"audit-{args.workflow_id}-{args.revision}-{profile.get('profileId')}",
        "workflowId": args.workflow_id,
        "revision": args.revision,
        "policyLockPath": str(policy_path),
        "policyLockSha256": digest(policy_path),
        "profileId": profile.get("profileId"),
        "profileVersion": profile.get("version"),
        "crosswalkId": crosswalk.get("crosswalkId"),
        "crosswalkVersion": crosswalk.get("version"),
        "crosswalkSha256": digest(crosswalk_path),
        "blockingFindingPolicy": profile.get("blockingFindingPolicy"),
        "jobs": jobs,
        "coverage": {
            "expectedRules": len(expected_rules),
            "mappedRules": len(expected_rules) - len(uncovered),
            "minimumExecutorsPerRule": minimum_executors,
            "uncoveredRules": uncovered,
            "underCoveredRules": under_covered,
            "requiredGlobalAudits": required_global_types,
        },
        "status": "READY" if not errors else "BLOCKED",
        "errors": errors,
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }
    errors.extend(schema_errors("audit-plan.schema.json", plan))
    if errors:
        plan["status"] = "BLOCKED"
        plan["errors"] = errors
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": plan["status"],
        "jobs": len(jobs),
        "expectedRules": len(expected_rules),
        "mappedRules": plan["coverage"]["mappedRules"],
        "errors": len(errors),
        "out": str(args.out),
    }, ensure_ascii=False))
    return 0 if plan["status"] == "READY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
