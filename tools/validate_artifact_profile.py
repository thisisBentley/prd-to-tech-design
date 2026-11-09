#!/usr/bin/env python3
"""Validate portable artifact-profile and prototype-contract boundaries.

This validator is intentionally independent of Jira or any external gate. It
checks whether a requirement selected a coherent artifact route and whether a
prototype preflight is evidence-complete for that route.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

PROFILES = {"PRD_ONLY", "PRD_PLUS_PROTOTYPE", "EXISTING_PROTOTYPE_REVIEW", "EXTERNAL_UI_BOUNDARY", "UNKNOWN"}
PROTOTYPE_STATUSES = {"TRIGGERED", "NOT_TRIGGERED", "UNKNOWN"}
OWNERS = {"LOCAL", "EXTERNAL", "NONE", "UNKNOWN"}
REQUIRED_PROTOTYPE_PROFILES = {"PRD_PLUS_PROTOTYPE", "EXISTING_PROTOTYPE_REVIEW"}
NO_PROTOTYPE_PROFILES = {"PRD_ONLY", "EXTERNAL_UI_BOUNDARY"}


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_profile(data: dict[str, Any], where: str = "profile") -> list[str]:
    errors: list[str] = []
    required = ["schemaVersion", "artifactProfile", "prototypeStatus", "uiOwnership"]
    for key in required:
        if key not in data:
            errors.append(f"{where}: missing {key}")
    if data.get("schemaVersion") != 1:
        errors.append(f"{where}: schemaVersion must be 1")
    profile = data.get("artifactProfile")
    status = data.get("prototypeStatus")
    owner = data.get("uiOwnership")
    if profile not in PROFILES:
        errors.append(f"{where}: invalid artifactProfile={profile}")
    if status not in PROTOTYPE_STATUSES:
        errors.append(f"{where}: invalid prototypeStatus={status}")
    if owner not in OWNERS:
        errors.append(f"{where}: invalid uiOwnership={owner}")
    if profile in REQUIRED_PROTOTYPE_PROFILES and status != "TRIGGERED":
        errors.append(f"{where}: {profile} requires prototypeStatus=TRIGGERED")
    if profile in NO_PROTOTYPE_PROFILES and status != "NOT_TRIGGERED":
        errors.append(f"{where}: {profile} requires prototypeStatus=NOT_TRIGGERED")
    if profile == "EXTERNAL_UI_BOUNDARY" and owner != "EXTERNAL":
        errors.append(f"{where}: EXTERNAL_UI_BOUNDARY requires uiOwnership=EXTERNAL")
    if profile == "PRD_ONLY" and owner not in {"NONE", "UNKNOWN"}:
        errors.append(f"{where}: PRD_ONLY requires uiOwnership=NONE or UNKNOWN")
    return errors


def validate_prototype_contract(data: dict[str, Any], where: str = "prototype-contract") -> list[str]:
    errors: list[str] = []
    for key in ["schemaVersion", "requirementId", "artifactProfile", "prototypeStatus", "status", "checks", "consoleErrors"]:
        if key not in data:
            errors.append(f"{where}: missing {key}")
    if data.get("schemaVersion") != 1:
        errors.append(f"{where}: schemaVersion must be 1")
    profile = data.get("artifactProfile")
    status = data.get("prototypeStatus")
    checks = data.get("checks") or []
    if profile not in PROFILES:
        errors.append(f"{where}: invalid artifactProfile={profile}")
    if status not in PROTOTYPE_STATUSES:
        errors.append(f"{where}: invalid prototypeStatus={status}")
    if not isinstance(data.get("consoleErrors"), int) or data.get("consoleErrors", 0) < 0:
        errors.append(f"{where}: consoleErrors must be a non-negative integer")
    if status == "NOT_TRIGGERED":
        if data.get("status") != "NOT_APPLICABLE":
            errors.append(f"{where}: NOT_TRIGGERED requires status=NOT_APPLICABLE")
        return errors
    if status != "TRIGGERED":
        errors.append(f"{where}: prototypeStatus must be TRIGGERED or NOT_TRIGGERED")
        return errors
    if not checks:
        errors.append(f"{where}: triggered prototype requires checks")
    for i, check in enumerate(checks):
        for key in ["checkId", "status", "evidenceRefs", "observed", "expected"]:
            if key not in check:
                errors.append(f"{where}/checks[{i}]: missing {key}")
        if check.get("status") in {"unverified", "not_executed"}:
            errors.append(f"{where}/checks[{i}]: triggered prototype cannot contain {check.get('status')}")
        if not check.get("evidenceRefs"):
            errors.append(f"{where}/checks[{i}]: evidenceRefs must not be empty")
        vi = check.get("visibleInteraction")
        if vi:
            for key in ["ruleId", "visibleLabel", "triggerArea", "targetView", "preserveContext", "expectedEvidence"]:
                if key not in vi:
                    errors.append(f"{where}/checks[{i}]/visibleInteraction: missing {key}")
            ev = vi.get("expectedEvidence") or {}
            if ev.get("domText") != vi.get("visibleLabel"):
                errors.append(f"{where}/checks[{i}]: visible interaction domText must equal visibleLabel")
            if ev.get("clickable") is not True:
                errors.append(f"{where}/checks[{i}]: visible interaction must be clickable")
            if ev.get("targetView") != vi.get("targetView"):
                errors.append(f"{where}/checks[{i}]: visible interaction target mismatch")
            if ev.get("contextPreserved") is not True:
                errors.append(f"{where}/checks[{i}]: visible interaction context must be preserved")
            if ev.get("consoleErrors") != 0:
                errors.append(f"{where}/checks[{i}]: visible interaction consoleErrors must be 0")
    if data.get("consoleErrors") != 0:
        errors.append(f"{where}: triggered prototype requires consoleErrors=0")
    if data.get("status") == "PASS" and any(c.get("status") != "passed" for c in checks):
        errors.append(f"{where}: PASS requires every executed check to be passed")
    if data.get("status") == "PASS" and data.get("consoleErrors") != 0:
        errors.append(f"{where}: PASS requires consoleErrors=0")
    return errors


def validate_runtime_result(data: dict[str, Any], where: str = "runtime-result") -> list[str]:
    errors: list[str] = []
    status = data.get("status")
    diagnostics = data.get("consoleDiagnostics") or data.get("consoleErrors") or []
    page_errors = data.get("pageErrors") or []
    if status not in {"PASS", "NEEDS_FIX", "INCOMPLETE", "NOT_APPLICABLE"}:
        errors.append(f"{where}: invalid status={status}")
    if status == "PASS":
        if diagnostics:
            errors.append(f"{where}: PASS cannot contain console diagnostics/errors")
        if page_errors:
            errors.append(f"{where}: PASS cannot contain pageErrors")
        if data.get("runtimeVerified") is False:
            errors.append(f"{where}: PASS requires runtimeVerified=true when provided")
        if data.get("requestFailures"):
            errors.append(f"{where}: PASS cannot contain requestFailures")
    return errors

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", type=Path)
    parser.add_argument("--prototype-contract", type=Path)
    parser.add_argument("--runtime-result", type=Path)
    args = parser.parse_args()
    errors = validate_profile(load(args.profile), str(args.profile))
    if args.prototype_contract:
        errors.extend(validate_prototype_contract(load(args.prototype_contract), str(args.prototype_contract)))
    if args.runtime_result:
        errors.extend(validate_runtime_result(load(args.runtime_result), str(args.runtime_result)))
    result = {"status": "PASS" if not errors else "FAIL", "errors": errors}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
