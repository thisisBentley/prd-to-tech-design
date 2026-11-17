#!/usr/bin/env python3
"""Build an independent Audit Track plan from a frozen policy lock and rule crosswalk."""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from validate_json_schemas import load, validate

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_ROOT = ROOT / "schemas" if (ROOT / "schemas").exists() else ROOT / "references"
GATES = ["R0", "G1", "O1", "U1", "U2", "QA", "Q1"]
PASS_CONDITION = "all bound policy rules have independent PASS evidence and no blocking finding remains"
DEFAULT_INPUT_SCOPES = ROOT / "config" / "audit-input-scopes.json"
AUDIT_OUTPUT_DIRS = {
    ".delivery/audit-results",
    ".delivery/audit-job-inputs",
    ".delivery/audit-transcripts",
}
AUDIT_OUTPUT_FILES = {
    ".delivery/audit-plan.json",
    ".delivery/audit-summary.json",
    ".delivery/audit-runner-report.json",
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def artifact_snapshot(root: Path) -> dict[str, str]:
    root = root.resolve()
    snapshot: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name == ".DS_Store":
            continue
        relative = path.relative_to(root).as_posix()
        if relative in AUDIT_OUTPUT_FILES or any(relative == item or relative.startswith(item + "/") for item in AUDIT_OUTPUT_DIRS):
            continue
        snapshot[relative] = digest(path)
    return snapshot


def snapshot_sha256(snapshot: dict[str, str]) -> str:
    payload = json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def schema_errors(name: str, value: dict[str, Any]) -> list[str]:
    schema = load(SCHEMA_ROOT / name)
    return validate(value, schema, schema)


def stable_token(value: str) -> str:
    return "".join(char if char.isalnum() else "-" for char in value.upper()).strip("-")


def select_job_inputs(job: dict[str, Any], artifact_files: list[str], scopes: dict[str, Any]) -> tuple[list[str], list[str], str]:
    evidence_text = " ".join(str(item) for item in job.get("requiredEvidence", [])).casefold()
    global_phrases = [str(item).casefold() for item in scopes.get("globalEvidencePhrases", [])]
    if job.get("jobType") in {"EDGE_REVIEW", "GLOBAL_INTEGRATION_REVIEW"} or any(phrase in evidence_text for phrase in global_phrases):
        return list(artifact_files), ["GLOBAL_SCOPE"], "GLOBAL_ALL"
    selected: set[str] = set()
    basis: list[str] = []
    for relative in scopes.get("always", []):
        if relative in artifact_files:
            selected.add(relative)
            basis.append(f"ALWAYS:{relative}")
    for path in artifact_files:
        for pattern in scopes.get("alwaysPatterns", []):
            if fnmatch.fnmatch(path, pattern):
                selected.add(path)
                basis.append(f"ALWAYS_PATTERN:{pattern}")
                break
    for selector in scopes.get("selectors", []):
        if not any(str(phrase).casefold() in evidence_text for phrase in selector.get("phrases", [])):
            continue
        matched: list[str] = []
        for path in artifact_files:
            if any(fnmatch.fnmatch(path, pattern) for pattern in selector.get("patterns", [])):
                matched.append(path)
        if matched:
            selected.update(matched)
            basis.append(f"SELECTOR:{selector.get('selectorId')}")
    if not selected:
        if len(artifact_files) <= 20:
            return list(artifact_files), ["FALLBACK:SMALL_ARTIFACT_SET"], "FALLBACK_ALL"
        return [], ["FALLBACK:NO_MATCH"], "JOB_ALLOWLIST"
    return sorted(selected), basis, "JOB_ALLOWLIST"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy-lock", type=Path, required=True)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--crosswalk", type=Path, required=True)
    parser.add_argument("--input-scopes", type=Path, default=DEFAULT_INPUT_SCOPES)
    parser.add_argument("--workflow-id", required=True)
    parser.add_argument("--revision", default="r1")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    policy_path = args.policy_lock.resolve()
    artifact_root = args.artifact_root.resolve()
    profile_path = args.profile.resolve()
    crosswalk_path = args.crosswalk.resolve()
    policy = load(policy_path)
    profile = load(profile_path)
    crosswalk = load(crosswalk_path)
    input_scopes = load(args.input_scopes.resolve()) if args.input_scopes and args.input_scopes.is_file() else {"always": [], "selectors": [], "globalEvidencePhrases": []}
    errors: list[str] = []
    if not artifact_root.is_dir():
        errors.append(f"artifact root does not exist: {artifact_root}")
        artifact_hashes: dict[str, str] = {}
    else:
        artifact_hashes = artifact_snapshot(artifact_root)
        if not artifact_hashes:
            errors.append(f"artifact root has no auditable files: {artifact_root}")
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
    scope_modes: set[str] = set()
    unit_report_path: Path | None = None
    unit_targets_by_rule: dict[str, list[str]] = {}
    all_unit_ids: set[str] = set()
    prd_candidates = [path for path in sorted(artifact_root.rglob("*.md")) if "PRD" in path.name.upper() or path.name == "PRD_DELIVERY.md"]
    if prd_candidates:
        unit_report_path = args.out.parent / "unit-applicability.json"
        unit_cmd = [
            sys.executable, str(Path(__file__).resolve().parent / "resolve_unit_applicability.py"),
            "--policy-lock", str(policy_path), "--prd", str(prd_candidates[0]),
            "--workflow-id", args.workflow_id, "--revision", args.revision, "--out", str(unit_report_path),
        ]
        manifest_path = artifact_root / "prototype-manifest.json"
        if manifest_path.is_file():
            unit_cmd.extend(["--manifest", str(manifest_path)])
        unit_run = subprocess.run(unit_cmd, text=True, capture_output=True, check=False)
        if unit_run.returncode != 0:
            errors.append("unit applicability resolution failed: " + (unit_run.stdout + unit_run.stderr).strip())
        elif unit_report_path.is_file():
            unit_report = load(unit_report_path)
            unit_targets_by_rule = {item["ruleId"]: list(item.get("targetUnitIds") or []) for item in unit_report.get("rules", [])}
            all_unit_ids = {str(item.get("unitId")) for item in unit_report.get("units", [])}
    for job in jobs:
        if job["jobId"] in job_ids:
            errors.append(f"duplicate audit jobId: {job['jobId']}")
        job_ids.add(job["jobId"])
        input_files, selection_basis, scope_mode = select_job_inputs(job, sorted(artifact_hashes), input_scopes)
        job["inputFiles"] = input_files
        job["inputSelectionBasis"] = selection_basis
        scope_modes.add(scope_mode)
        if unit_targets_by_rule:
            if job.get("sourcePolicyRuleIds"):
                job["unitTargets"] = sorted({unit for rule in job["sourcePolicyRuleIds"] for unit in unit_targets_by_rule.get(rule, [])})
            else:
                job["unitTargets"] = sorted(all_unit_ids)

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
        "artifactRoot": str(artifact_root),
        "artifactHashes": artifact_hashes,
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
            "inputScopeMode": next(iter(scope_modes)) if len(scope_modes) == 1 else "MIXED",
            **({"unitApplicabilityPath": str(unit_report_path), "unitTargetCount": len(all_unit_ids)} if unit_report_path else {}),
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
        "artifacts": len(artifact_hashes),
        "errors": len(errors),
        "out": str(args.out),
    }, ensure_ascii=False))
    return 0 if plan["status"] == "READY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
