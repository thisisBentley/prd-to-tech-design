#!/usr/bin/env python3
"""Audit whether evaluation tasks can be answered within their declared evidence scope."""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def save(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ref_matches(ref: str, patterns: list[str]) -> bool:
    return any(re.search(pattern, ref) for pattern in patterns)


def rule_matches(rule: dict[str, Any], task: dict[str, Any]) -> bool:
    task_types = rule.get("taskTypes") or []
    if task_types and task.get("taskType") not in task_types:
        return False
    prompt = str(task.get("prompt", ""))
    all_terms = [str(item) for item in rule.get("promptAll", []) or []]
    any_terms = [str(item) for item in rule.get("promptAny", []) or []]
    if all_terms and not all(term in prompt for term in all_terms):
        return False
    if any_terms and not any(term in prompt for term in any_terms):
        return False
    return bool(all_terms or any_terms)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", type=Path, action="append", required=True)
    parser.add_argument("--issue-root", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    policy = load(args.policy.resolve())
    artifact_types = policy.get("artifactTypes") or {}
    scope_rules = policy.get("scopeRules") or []
    issue_root = args.issue_root.resolve()
    results: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for path in args.tasks:
        for task in load_jsonl(path.resolve()):
            task_id = str(task.get("goldenTaskId", ""))
            version = str(task.get("taskVersion", "v1"))
            identity = (task_id, version)
            errors: list[str] = []
            if identity in seen:
                errors.append("DUPLICATE_TASK_VERSION")
            seen.add(identity)

            sample_id = str(task.get("sampleId", ""))
            issue_dir = issue_root / sample_id
            refs = [str(item) for item in (task.get("rubric") or {}).get("evidenceRefs", []) or []]
            missing_refs = [ref for ref in refs if not (issue_dir / ref).is_file()]
            if missing_refs:
                errors.append("EVIDENCE_REF_MISSING")

            required_types = [str(item) for item in task.get("requiredArtifactTypes", []) or []]
            matched_rules: list[str] = []
            for rule in scope_rules:
                if not rule_matches(rule, task):
                    continue
                matched_rules.append(str(rule.get("ruleId", "SCOPE_RULE")))
                required_types.extend(str(item) for item in rule.get("requiredArtifactTypes", []) or [])
            required_types = sorted(set(required_types))

            missing_types: list[str] = []
            for artifact_type in required_types:
                spec = artifact_types.get(artifact_type) or {}
                patterns = [str(item) for item in spec.get("pathPatterns", []) or []]
                if not patterns or not any(ref_matches(ref, patterns) for ref in refs):
                    missing_types.append(artifact_type)
            if missing_types:
                errors.append("REQUIRED_ARTIFACT_NOT_IN_EVIDENCE_SCOPE")

            results.append({
                "goldenTaskId": task_id,
                "taskVersion": version,
                "sampleId": sample_id,
                "taskType": str(task.get("taskType", "UNKNOWN")),
                "capabilityMode": str(task.get("capabilityMode", "UNKNOWN")),
                "status": "VALID" if not errors else "INVALID",
                "matchedScopeRules": matched_rules,
                "requiredArtifactTypes": required_types,
                "missingArtifactTypes": missing_types,
                "missingEvidenceRefs": missing_refs,
                "errors": errors,
            })

    invalid = [item for item in results if item["status"] == "INVALID"]
    report = {
        "schemaVersion": 1,
        "reportId": "evaluation-integrity-" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S"),
        "status": "PASS" if not invalid else "BLOCKED",
        "mode": "STATIC_TASK_EVIDENCE_AUDIT",
        "taskSets": [str(path.resolve()) for path in args.tasks],
        "policyPath": str(args.policy.resolve()),
        "counts": {
            "tasks": len(results),
            "valid": len(results) - len(invalid),
            "invalid": len(invalid),
        },
        "invalidTaskIds": [item["goldenTaskId"] for item in invalid],
        "tasks": results,
        "checkedAt": now(),
    }
    save(args.out, report)
    print(json.dumps({
        "status": report["status"],
        "counts": report["counts"],
        "invalidTaskIds": report["invalidTaskIds"],
        "out": str(args.out.resolve()),
    }, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" or not args.strict else 1


if __name__ == "__main__":
    raise SystemExit(main())
