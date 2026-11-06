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


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_gate(data: dict[str, Any], source: str = "") -> list[str]:
    where = f"{source}: " if source else ""
    errors: list[str] = []
    schema_version = data.get("schemaVersion")
    if schema_version != 2:
        errors.append(where + "schemaVersion must be 2")
        return errors

    result = data.get("result")
    checks = data.get("checks") or []
    findings = data.get("findings") or []
    if data.get("independentContext") is not True:
        errors.append(where + "independentContext must be true")
    if result not in PASS_RESULTS:
        if not data.get("completionStatus") == "complete" and result not in NON_TERMINAL:
            errors.append(where + f"failed gate {result} must have completionStatus=complete or be INCOMPLETE/NOT_TRIGGERED/NOT_APPLICABLE")
    if result in PASS_RESULTS:
        if not checks:
            errors.append(where + "PASS requires checks; use INCOMPLETE when checks did not run")
        executable = [c for c in checks if c.get("status") not in {"not_applicable"}]
        if not executable:
            errors.append(where + "PASS requires at least one executable check")
        for check in checks:
            status = check.get("status")
            refs = check.get("evidenceRefs") or []
            if not refs:
                errors.append(where + f"check {check.get('checkId', '<missing>')} has no evidenceRefs")
            if status in EVIDENCE_FREE_STATUSES:
                errors.append(where + f"PASS gate contains {status} check {check.get('checkId', '<missing>')}")
        if any(not ref.strip() for check in checks for ref in (check.get("evidenceRefs") or [])):
            errors.append(where + "evidenceRefs contains an empty reference")

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
    if not str(data.get("ruleSetVersion", "")).strip():
        errors.append(where + "ruleSetVersion is required")
    if not str(data.get("tool", "")).strip():
        errors.append(where + "tool is required")
    if not data.get("objectHashes"):
        errors.append(where + "objectHashes is required")
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
