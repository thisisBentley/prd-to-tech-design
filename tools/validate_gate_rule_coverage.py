#!/usr/bin/env python3
"""Prove that each gate executed every rule required by the frozen policy lock."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

GATES = ["R0", "G1", "O1", "U1", "U2", "QA", "Q1"]
PASSING = {"PASS", "PASS_WITH_NONBLOCKING"}


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy-lock", type=Path, required=True)
    parser.add_argument("--gate-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    lock_path = args.policy_lock.resolve()
    lock = load(lock_path)
    lock_hash = digest(lock_path)
    gate_dir = args.gate_dir.resolve()
    errors: list[str] = []
    gate_summaries: dict[str, dict[str, Any]] = {}
    total_expected = total_executed = total_missing = 0
    for gate in GATES:
        expected = list((lock.get("applicableRules") or {}).get(gate) or [])
        total_expected += len(expected)
        path = gate_dir / f"{gate}.json"
        if not path.exists():
            if expected:
                errors.append(f"{gate}: gate result missing, expected {len(expected)} rules")
                total_missing += len(expected)
            gate_summaries[gate] = {"expected": expected, "executed": [], "missing": expected, "status": "MISSING"}
            continue
        result = load(path)
        executed: list[str] = []
        bad_status: list[dict[str, str]] = []
        unknown: list[str] = []
        duplicates: list[str] = []
        for item in result.get("checks", []):
            rule_id = str(item.get("ruleId", "")).strip()
            if not rule_id:
                continue
            if rule_id in executed:
                duplicates.append(rule_id)
            if rule_id not in expected:
                unknown.append(rule_id)
            else:
                executed.append(rule_id)
                if item.get("status") != "passed":
                    bad_status.append({"ruleId": rule_id, "status": str(item.get("status"))})
                for ref in item.get("evidenceRefs") or []:
                    if not str(ref).strip():
                        bad_status.append({"ruleId": rule_id, "status": "empty-evidence"})
        missing = sorted(set(expected) - set(executed))
        total_executed += len(set(executed))
        total_missing += len(missing)
        if missing:
            errors.append(f"{gate}: missing applicable rules: {', '.join(missing)}")
        if bad_status:
            errors.append(f"{gate}: applicable rule did not pass: {bad_status}")
        if unknown:
            errors.append(f"{gate}: unknown/unlocked ruleIds: {', '.join(sorted(set(unknown)))}")
        if duplicates:
            errors.append(f"{gate}: duplicate rule results: {', '.join(sorted(set(duplicates)))}")
        if expected and result.get("policyLockSha256") != lock_hash:
            errors.append(f"{gate}: policyLockSha256 does not match frozen policy lock")
        if expected and result.get("ruleSetVersion") != lock.get("ruleSetVersion"):
            errors.append(f"{gate}: ruleSetVersion does not match policy lock")
        if expected and result.get("result") not in PASSING and not missing:
            errors.append(f"{gate}: gate did not pass despite complete rule coverage")
        gate_summaries[gate] = {
            "expected": expected,
            "executed": sorted(set(executed)),
            "missing": missing,
            "badStatus": bad_status,
            "unknown": sorted(set(unknown)),
            "duplicates": sorted(set(duplicates)),
            "status": "PROVEN_COVERED" if not missing and not bad_status and not unknown and not duplicates else "NOT_PROVEN",
        }
    payload = {
        "schemaVersion": 1,
        "status": "PASS" if not errors else "FAIL",
        "policyPackId": lock.get("policyPackId"),
        "policyPackVersion": lock.get("policyPackVersion"),
        "policyLockSha256": lock_hash,
        "expectedRules": total_expected,
        "executedRules": total_executed,
        "missingRules": total_missing,
        "gates": gate_summaries,
        "errors": errors,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "expected": total_expected, "executed": total_executed, "missing": total_missing, "out": str(args.out)}, ensure_ascii=False))
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
