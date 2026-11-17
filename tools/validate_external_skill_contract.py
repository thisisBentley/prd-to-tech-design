#!/usr/bin/env python3
"""Validate artifacts against a source-locked external Skill contract profile."""
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


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def resolve_source(value: str, profile_path: Path, override: Path | None) -> Path:
    if override:
        return override.resolve()
    if value.startswith("skill://"):
        raise FileNotFoundError(f"source lock uses unresolved scheme: {value}")
    path = Path(value)
    return path.resolve() if path.is_absolute() else (profile_path.parent / path).resolve()


def json_key_exists(value: Any, dotted: str) -> bool:
    current = value
    for part in dotted.split("."):
        if not isinstance(current, dict) or part not in current:
            return False
        current = current[part]
    return True


def artifact_checks(path: Path, fmt: str, checks: list[dict[str, Any]], profile_schema: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    errors: list[str] = []
    results: list[dict[str, Any]] = []
    text = path.read_text(encoding="utf-8", errors="replace")
    parsed_json: Any = None
    if fmt == "JSON":
        try:
            parsed_json = json.loads(text)
        except json.JSONDecodeError as exc:
            errors.append(f"invalid JSON: {exc}")
    for check in checks:
        passed = False
        if fmt == "JSON" and parsed_json is None and check["kind"] == "JSON_KEY":
            passed = False
        elif check["kind"] == "REGEX":
            try:
                passed = bool(re.search(check["value"], text, re.MULTILINE))
            except re.error as exc:
                errors.append(f"{check['checkId']}: invalid regex: {exc}")
        elif check["kind"] == "TEXT":
            passed = check["value"] in text
        elif check["kind"] == "JSON_KEY":
            passed = json_key_exists(parsed_json, check["value"])
        results.append({
            "checkId": check["checkId"],
            "status": "PASS" if passed else "FAIL",
            "description": check["description"],
            "evidenceRef": str(path),
        })
        if not passed and not any(error.startswith(f"{check['checkId']}:") for error in errors):
            errors.append(f"{check['checkId']}: {check['description']}")
    return results, errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--workflow-id", required=True)
    parser.add_argument("--revision", default="r1")
    parser.add_argument("--artifact-profile", required=True, choices=["PRD_ONLY", "PRD_PLUS_PROTOTYPE", "EXISTING_PROTOTYPE_REVIEW", "EXTERNAL_UI_BOUNDARY"])
    parser.add_argument("--stage", choices=["PRE_FINAL_SEAL", "POST_CANDIDATE_SEAL"], default="PRE_FINAL_SEAL")
    parser.add_argument("--source", type=Path, help="Override the source lock path for a private or relocated Skill source.")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    profile_path = args.profile.resolve()
    bundle = args.bundle.resolve()
    profile = load(profile_path)
    profile_schema = load(SCHEMA_ROOT / "external-skill-contract-profile.schema.json")
    profile_errors = validate(profile, profile_schema, profile_schema)
    if profile_errors:
        print(json.dumps({"status": "BLOCKED", "errors": profile_errors[:20], "profile": str(profile_path)}, ensure_ascii=False))
        return 1
    source = profile["sourceLock"]
    source_errors: list[str] = []
    actual_sha = "0" * 64
    source_path: Path | None = None
    try:
        source_path = resolve_source(source["path"], profile_path, args.source)
        actual_sha = digest(source_path) if source_path.is_file() else actual_sha
        if not source_path.is_file():
            source_errors.append(f"source lock path does not exist: {source_path}")
        elif actual_sha != source["sha256"]:
            source_errors.append("source lock hash drift detected")
    except Exception as exc:
        source_errors.append(str(exc))
    if args.artifact_profile not in profile.get("appliesToProfiles", []):
        source_errors.append(f"profile does not apply to artifact profile {args.artifact_profile}")
    if args.stage == "PRE_FINAL_SEAL" and profile["reviewTiming"] == "AFTER_CANDIDATE_SEAL":
        source_errors.append("profile requires review after candidate seal, not before final seal")
    source_status = "PASS" if not source_errors else "BLOCKED"

    artifacts: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    total_checks = passed_checks = failed_checks = skipped = 0
    for contract in profile["artifacts"]:
        artifact_path = (bundle / contract["path"]).resolve()
        if args.artifact_profile not in contract["appliesToProfiles"]:
            skipped += 1
            artifacts.append({"artifactId": contract["artifactId"], "path": str(artifact_path), "status": "SKIPPED", "checks": [], "errors": []})
            continue
        if not artifact_path.is_file():
            error = f"required artifact is missing: {contract['path']}"
            if contract["required"]:
                artifacts.append({"artifactId": contract["artifactId"], "path": str(artifact_path), "status": "BLOCKED", "checks": [], "errors": [error]})
                findings.append({
                    "findingId": f"EXT-{len(findings) + 1:03d}",
                    "severity": "BLOCKING",
                    "code": "ARTIFACT_CONTRACT_VIOLATION",
                    "message": error,
                    "evidenceRefs": [str(artifact_path)],
                })
                failed_checks += 1
            else:
                skipped += 1
                artifacts.append({"artifactId": contract["artifactId"], "path": str(artifact_path), "status": "SKIPPED", "checks": [], "errors": []})
            continue
        check_results, errors = artifact_checks(artifact_path, contract["format"], contract["checks"], profile_schema)
        total_checks += len(check_results)
        passed_checks += sum(1 for item in check_results if item["status"] == "PASS")
        failed_checks += sum(1 for item in check_results if item["status"] == "FAIL")
        artifacts.append({
            "artifactId": contract["artifactId"],
            "path": str(artifact_path),
            "status": "BLOCKED" if errors else "PASS",
            "checks": check_results,
            "errors": errors,
        })
        for error in errors:
            findings.append({
                "findingId": f"EXT-{len(findings) + 1:03d}",
                "severity": "BLOCKING",
                "code": "ARTIFACT_CONTRACT_VIOLATION",
                "message": error,
                "evidenceRefs": [str(artifact_path)],
            })
    for error in source_errors:
        findings.append({
            "findingId": f"EXT-{len(findings) + 1:03d}",
            "severity": "BLOCKING",
            "code": "SOURCE_LOCK_DRIFT",
            "message": error,
            "evidenceRefs": [str(source_path or source["path"])],
        })
    status = "PASS" if not findings else "BLOCKED"
    payload = {
        "schemaVersion": 1,
        "workflowId": args.workflow_id,
        "targetRevision": args.revision,
        "artifactProfile": args.artifact_profile,
        "stage": args.stage,
        "profileId": profile["profileId"],
        "profileVersion": profile["version"],
        "reviewTiming": profile["reviewTiming"],
        "status": status,
        "sourceLock": {
            "skillId": source["skillId"],
            "version": source["version"],
            "path": str(source_path or source["path"]),
            "expectedSha256": source["sha256"],
            "actualSha256": actual_sha,
            "status": source_status,
        },
        "artifacts": artifacts,
        "findings": findings,
        "metrics": {
            "artifactsChecked": sum(1 for item in artifacts if item["status"] in {"PASS", "BLOCKED"}),
            "artifactsSkipped": skipped,
            "checks": total_checks,
            "passed": passed_checks,
            "failed": failed_checks,
        },
        "checkedAt": datetime.now(timezone.utc).isoformat(),
    }
    result_schema = load(SCHEMA_ROOT / "external-skill-contract-result.schema.json")
    schema_errors = validate(payload, result_schema, result_schema)
    if schema_errors:
        status = "BLOCKED"
        payload["status"] = status
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": status, "sourceLock": source_status, "failedChecks": failed_checks, "findings": len(findings), "schemaErrors": schema_errors[:10], "out": str(args.out)}, ensure_ascii=False))
    return 0 if status == "PASS" and not schema_errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
