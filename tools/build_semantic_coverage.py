#!/usr/bin/env python3
"""Prove that semantic evidence covers every PRD ID, UI element and known capability."""
from __future__ import annotations

import argparse
import html
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

FR_RE = re.compile(r"\bFR-[0-9]{3}\b")
AC_RE = re.compile(r"\bAC-[0-9]{3}\b")
BR_RE = re.compile(r"\bBR-[0-9]{3}\b")
ATTR_RE = re.compile(r'data-ai-([a-z-]+)="([^"]*)"', re.IGNORECASE)


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def check(check_id: str, passed: bool, observed: Any, expected: Any, evidence: list[str]) -> dict[str, Any]:
    return {
        "checkId": check_id,
        "status": "passed" if passed else "failed",
        "observed": observed,
        "expected": expected,
        "evidenceRefs": evidence,
    }


def parse_elements(prototype: str) -> list[dict[str, Any]]:
    elements: list[dict[str, Any]] = []
    for match in re.finditer(r"<[^>]*data-ai-id=\"([^\"]+)\"[^>]*>", prototype, re.IGNORECASE):
        attrs = {name.lower(): html.unescape(value) for name, value in ATTR_RE.findall(match.group(0))}
        attributes = {name: [item for item in value.split(",") if item] for name, value in attrs.items() if name in {"fr", "ac", "state", "permission", "permission-edge"}}
        elements.append({"elementId": html.unescape(match.group(1)), **attributes})
    return elements


def evaluate(data: dict[str, Any], prd_path: Path, prototype_path: Path | None, capability_path: Path | None, manifest_path: Path | None) -> dict[str, Any]:
    prd = prd_path.read_text(encoding="utf-8")
    fr_ids = set(FR_RE.findall(prd))
    ac_ids = set(AC_RE.findall(prd))
    br_ids = set(BR_RE.findall(prd))
    checks: list[dict[str, Any]] = []
    missing: list[str] = []
    assertions = data.get("businessAssertions", [])
    covered_ids = {item for assertion in assertions for item in assertion.get("coveredIds", [])}
    for name, required_ids in (("FR", fr_ids), ("AC", ac_ids), ("BR", br_ids)):
        uncovered = sorted(required_ids - covered_ids)
        missing.extend(f"{name}:{item}" for item in uncovered)
        checks.append(check(
            f"COVERAGE.{name}", not uncovered,
            {"required": len(required_ids), "covered": len(required_ids & covered_ids), "missing": uncovered},
            "every identifier is represented in businessAssertions.coveredIds",
            [str(prd_path.resolve())],
        ))

    prototype_elements: list[dict[str, Any]] = []
    if prototype_path and prototype_path.exists():
        prototype_elements = parse_elements(prototype_path.read_text(encoding="utf-8"))
        ledger_elements = {item.get("elementId"): item for item in data.get("interactionElements", [])}
        missing_elements = sorted(item["elementId"] for item in prototype_elements if item["elementId"] not in ledger_elements)
        missing.extend(f"UI:{item}" for item in missing_elements)
        checks.append(check(
            "COVERAGE.INTERACTION_ELEMENTS", not missing_elements,
            {"prototype": [item["elementId"] for item in prototype_elements], "missing": missing_elements},
            "every visible data-ai-id is represented in interactionElements",
            [str(prototype_path.resolve())],
        ))
        binding_errors: list[str] = []
        for element in prototype_elements:
            item = ledger_elements.get(element["elementId"], {})
            for key, valid in (("fr", fr_ids), ("ac", ac_ids)):
                unknown = sorted(set(element.get(key, [])) - valid)
                if unknown:
                    binding_errors.append(f"{element['elementId']}.{key}={unknown}")
                declared = set(item.get({"fr": "frIds", "ac": "acIds"}[key], []))
                if declared != set(element.get(key, [])):
                    binding_errors.append(f"{element['elementId']}.{key} ledger/prototype mismatch={sorted(declared)}/{element.get(key, [])}")
        missing.extend(f"BINDING:{item}" for item in binding_errors)
        checks.append(check(
            "COVERAGE.INTERACTION_BINDING", not binding_errors, binding_errors,
            "UI FR/AC bindings are valid and match the frozen ledger",
            [str(prototype_path.resolve()), str(prd_path.resolve())],
        ))
        manifest_states: set[str] = set()
        if manifest_path and manifest_path.exists():
            manifest = load(manifest_path)
            for item in manifest.get("elements", []):
                manifest_states.update(str(state) for state in item.get("states", []))
        ledger_states = {item.get("stateId") for item in data.get("stateAssumptions", [])}
        missing_states = sorted(manifest_states - ledger_states)
        missing.extend(f"STATE:{item}" for item in missing_states)
        checks.append(check(
            "COVERAGE.STATES", not missing_states,
            {"manifest": sorted(manifest_states), "missing": missing_states},
            "every declared UI state is represented in stateAssumptions",
            [str((manifest_path or prototype_path).resolve())],
        ))
    else:
        checks.append(check("COVERAGE.INTERACTION_ELEMENTS", True, "not applicable", "no local Prototype", [str(prd_path.resolve())]))
        checks.append(check("COVERAGE.INTERACTION_BINDING", True, "not applicable", "no local Prototype", [str(prd_path.resolve())]))
        checks.append(check("COVERAGE.STATES", True, "not applicable", "no local Prototype", [str(prd_path.resolve())]))

    if capability_path and capability_path.exists():
        capability = load(capability_path)
        names = [capability.get("canonicalName", "")] + list(capability.get("knownAliases", []) or [])
        used = [name for name in names if name and (name in prd or (prototype_path and prototype_path.exists() and name in prototype_path.read_text(encoding="utf-8")))]
        claims = {item.get("capabilityId"): item for item in data.get("capabilityClaims", [])}
        claim = claims.get(capability.get("capabilityId"))
        capability_ok = not used or bool(claim and claim.get("sourceRefs") and claim.get("verificationEvidenceRefs"))
        if not capability_ok:
            missing.append(f"CAPABILITY:{capability.get('capabilityId')}")
        checks.append(check(
            "COVERAGE.CAPABILITY", capability_ok,
            {"usedNames": used, "claimPresent": bool(claim)},
            "every referenced known capability has a sourced capability claim",
            [str(capability_path.resolve()), str(prd_path.resolve())],
        ))
    else:
        checks.append(check("COVERAGE.CAPABILITY", True, "not applicable", "no Capability Context", [str(prd_path.resolve())]))

    failed = [item for item in checks if item["status"] == "failed"]
    status = "FAIL" if failed else "PASS"
    return {
        "schemaVersion": 1,
        "status": status,
        "workflowId": data.get("workflowId", "UNKNOWN"),
        "checks": checks,
        "missing": sorted(set(missing)),
        "blockingCount": len(missing),
        "checkedAt": datetime.now(timezone.utc).isoformat(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--semantic-input", type=Path, required=True)
    parser.add_argument("--prd", type=Path, required=True)
    parser.add_argument("--prototype", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--capability-context", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = evaluate(load(args.semantic_input), args.prd, args.prototype, args.capability_context, args.manifest)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "missing": len(result["missing"]), "out": str(args.out)}, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
