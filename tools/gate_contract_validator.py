#!/usr/bin/env python3
"""Validate v2 gate results without permitting evidence-free PASS.

A passing gate must prove that:
- it read the exact frozen revision;
- every check has at least one evidence reference;
- no passing result contains unexecuted/unverified checks;
- a passing result contains at least one executable check;
- blockers are counted consistently.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

PASS_RESULTS = {"PASS", "PASS_WITH_NONBLOCKING"}
EVIDENCE_FREE_STATUSES = {"unverified", "not_executed"}
NON_TERMINAL = {"INCOMPLETE", "NOT_TRIGGERED", "NOT_APPLICABLE"}
VALID_GATES = {"R0", "G1", "O1", "U1", "U2", "QA", "Q1"}
VALID_CHECK_STATUSES = {"passed", "failed", "not_applicable", "unverified", "not_executed"}
MIN_PASS_CHECKS = {"R0": 1, "G1": 2, "O1": 2, "U1": 2, "U2": 2, "QA": 2, "Q1": 2}
SUSPICIOUS_WORKER_MARKERS = ("legacy", "old-workflow", "producer", "generator")
RULESET_ALLOWLIST_CANDIDATES = [
    Path(__file__).resolve().parents[1] / "references" / "approved-ruleset-versions.json",
    Path(__file__).resolve().parents[1] / "core" / "approved-ruleset-versions.json",
]


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def approved_rulesets() -> set[str]:
    allowlist = next((path for path in RULESET_ALLOWLIST_CANDIDATES if path.exists()), None)
    if allowlist is None:
        return set()
    data = load(allowlist)
    return {str(item) for item in data.get("approved", []) if str(item).strip()}


def validate_gate(data: dict[str, Any], source: str = "") -> list[str]:
    where = f"{source}: " if source else ""
    errors: list[str] = []
    schema_version = data.get("schemaVersion")
    if schema_version != 2:
        errors.append(where + "schemaVersion must be 2")
        return errors

    result = data.get("result")
    gate = data.get("gate")
    checks = data.get("checks") or []
    findings = data.get("findings") or []
    if gate not in VALID_GATES:
        errors.append(where + f"invalid gate {gate!r}")
    if data.get("independentContext") is not True:
        errors.append(where + "independentContext must be true")
    if not str(data.get("frozenCopy", "")).strip():
        errors.append(where + "frozenCopy is required")
    if result not in PASS_RESULTS:
        if not data.get("completionStatus") == "complete" and result not in NON_TERMINAL:
            errors.append(where + f"failed gate {result} must have completionStatus=complete or be INCOMPLETE/NOT_TRIGGERED/NOT_APPLICABLE")
    if result in PASS_RESULTS:
        if not checks:
            errors.append(where + "PASS requires checks; use INCOMPLETE when checks did not run")
        executable = [c for c in checks if c.get("status") not in {"not_applicable"}]
        minimum = MIN_PASS_CHECKS.get(gate, 1)
        if len(executable) < minimum:
            errors.append(where + f"PASS requires at least {minimum} executable checks for {gate}; use INCOMPLETE when coverage is insufficient")
        if data.get("completionStatus") != "complete":
            errors.append(where + "PASS requires completionStatus=complete")
        for check in checks:
            status = check.get("status")
            refs = check.get("evidenceRefs") or []
            if status not in VALID_CHECK_STATUSES:
                errors.append(where + f"check {check.get('checkId', '<missing>')} has invalid status {status!r}")
            if not refs:
                errors.append(where + f"check {check.get('checkId', '<missing>')} has no evidenceRefs")
            if status in EVIDENCE_FREE_STATUSES:
                errors.append(where + f"PASS gate contains {status} check {check.get('checkId', '<missing>')}")
            if status == "failed":
                errors.append(where + f"PASS gate contains failed check {check.get('checkId', '<missing>')}")
        if any(not ref.strip() for check in checks for ref in (check.get("evidenceRefs") or [])):
            errors.append(where + "evidenceRefs contains an empty reference")
        if result == "PASS" and findings:
            errors.append(where + "PASS cannot hide findings; use PASS_WITH_NONBLOCKING or NEEDS_FIX")
        if result == "PASS_WITH_NONBLOCKING" and not findings:
            errors.append(where + "PASS_WITH_NONBLOCKING requires at least one finding")

    blocking = [f for f in findings if str(f).strip()]
    try:
        declared = int(data.get("blockingCount", -1))
    except (TypeError, ValueError):
        declared = -1
        errors.append(where + "blockingCount must be an integer")
    # findings are stable IDs in v2; blocking semantics are declared by the gate worker.
    if declared < 0:
        errors.append(where + "blockingCount is required")
    if result == "PASS" and declared != 0:
        errors.append(where + "PASS requires blockingCount=0")
    if result == "PASS_WITH_NONBLOCKING" and declared != 0:
        errors.append(where + "PASS_WITH_NONBLOCKING requires blockingCount=0")
    if result == "NEEDS_FIX" and declared <= 0:
        errors.append(where + "NEEDS_FIX requires blockingCount>0")
    if not str(data.get("reviewRunId", "")).strip():
        errors.append(where + "reviewRunId is required")
    ruleset = str(data.get("ruleSetVersion", "")).strip()
    if not ruleset:
        errors.append(where + "ruleSetVersion is required")
    elif ruleset not in approved_rulesets():
        errors.append(where + f"ruleSetVersion {ruleset!r} is not approved for formal PASS")
    tool = str(data.get("tool", "")).strip()
    if not tool:
        errors.append(where + "tool is required")
    elif any(marker in tool.lower() for marker in SUSPICIOUS_WORKER_MARKERS):
        errors.append(where + f"tool {tool!r} is not an independent review worker")
    object_hashes = data.get("objectHashes") or {}
    if not object_hashes:
        errors.append(where + "objectHashes is required")
    elif any(not str(value).strip() for value in object_hashes.values()):
        errors.append(where + "objectHashes contains an empty hash")
    return errors


def validate_summary(data: dict[str, Any], source: str = "") -> list[str]:
    where = f"{source}: " if source else ""
    errors: list[str] = []
    if data.get("schemaVersion") != 2:
        errors.append(where + "schemaVersion must be 2")
        return errors
    results = data.get("results") or {}
    required = ["R0", "G1", "O1", "U1", "U2", "QA", "Q1"]
    missing = [gate for gate in required if gate not in results]
    if missing:
        errors.append(where + "missing gates: " + ", ".join(missing))
    for gate in required:
        if results.get(gate) == "INCOMPLETE" and data.get("finalizable") is True:
            errors.append(where + f"finalizable cannot be true while {gate}=INCOMPLETE")
    if data.get("openBlockingFindings") != 0 and data.get("finalizable") is True:
        errors.append(where + "finalizable cannot be true with open blocking findings")
    if data.get("hashStable") is not True:
        errors.append(where + "hashStable must be true")
    if data.get("independentContext") is not True:
        errors.append(where + "independentContext must be true")
    if data.get("finalizable") is True:
        non_passing = [gate for gate in required if results.get(gate) not in PASS_RESULTS]
        if non_passing:
            errors.append(where + "finalizable requires all gates PASS/PASS_WITH_NONBLOCKING: " + ", ".join(non_passing))
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+", help="Gate Result v2 or Delivery Gate Summary v2 JSON files")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    errors: list[str] = []
    summaries: list[str] = []
    for raw in args.files:
        path = Path(raw)
        try:
            data = load(path)
        except Exception as exc:
            errors.append(f"{path}: invalid JSON: {exc}")
            continue
        gate = data.get("gate")
        if gate:
            errors.extend(validate_gate(data, str(path)))
        elif "results" in data:
            summaries.append(str(path))
            errors.extend(validate_summary(data, str(path)))
        else:
            errors.append(f"{path}: not a Gate Result or Delivery Gate Summary")

    result = {"status": "PASS" if not errors else "FAIL", "files": len(args.files), "errors": errors}
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"status: {result['status']}")
        for error in errors:
            print(f"- {error}")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
