#!/usr/bin/env python3
"""Validate completeness and integrity of producer obligation declarations."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from validate_json_schemas import load, validate

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_ROOT = ROOT / "schemas" if (ROOT / "schemas").exists() else ROOT / "references"


def validate_declarations(obligations_doc: dict[str, Any], declarations_doc: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    obligations = {item["obligationId"]: item for item in obligations_doc.get("obligations", [])}
    declarations = declarations_doc.get("declarations", [])
    by_id: dict[str, dict[str, Any]] = {}
    for declaration in declarations:
        obligation_id = str(declaration.get("obligationId", ""))
        if obligation_id in by_id:
            errors.append(f"duplicate declaration for {obligation_id}")
            continue
        by_id[obligation_id] = declaration
    if declarations_doc.get("policyLockSha256") != obligations_doc.get("policyLockSha256"):
        errors.append("declaration policyLockSha256 does not match generation obligations")
    if declarations_doc.get("workflowId") != obligations_doc.get("workflowId"):
        errors.append("declaration workflowId does not match generation obligations")
    if declarations_doc.get("targetRevision") != obligations_doc.get("targetRevision"):
        errors.append("declaration targetRevision does not match generation obligations")
    for obligation_id, obligation in obligations.items():
        if not obligation.get("declarationRequired"):
            continue
        declaration = by_id.get(obligation_id)
        if declaration is None:
            errors.append(f"missing declaration for {obligation_id} ({obligation.get('ruleId')})")
            continue
        if declaration.get("ruleId") != obligation.get("ruleId"):
            errors.append(f"{obligation_id}: ruleId mismatch")
        if declaration.get("producerRole") != obligation.get("ownerRole"):
            errors.append(f"{obligation_id}: producerRole mismatch")
        if declaration.get("status") != "DECLARED":
            errors.append(f"{obligation_id}: declarationRequired obligation must be DECLARED, got {declaration.get('status')}")
        if not str(declaration.get("artifact", "")).strip():
            errors.append(f"{obligation_id}: artifact is required")
        if not str(declaration.get("location", "")).strip():
            errors.append(f"{obligation_id}: location is required")
        if not declaration.get("evidenceRefs"):
            errors.append(f"{obligation_id}: evidenceRefs is required")
    for obligation_id, declaration in by_id.items():
        if obligation_id not in obligations:
            errors.append(f"unknown declaration obligationId: {obligation_id}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--obligations", type=Path, required=True)
    parser.add_argument("--declarations", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    obligations = load(args.obligations.resolve())
    declarations = load(args.declarations.resolve())
    schema = load(SCHEMA_ROOT / "obligation-declarations.schema.json")
    errors = validate(declarations, schema, schema)
    errors.extend(validate_declarations(obligations, declarations))
    required = [item for item in obligations.get("obligations", []) if item.get("declarationRequired")]
    declared_ids = {item.get("obligationId") for item in declarations.get("declarations", []) if item.get("status") == "DECLARED"}
    payload = {
        "schemaVersion": 1,
        "status": "PASS" if not errors else "FAIL",
        "workflowId": obligations.get("workflowId"),
        "targetRevision": obligations.get("targetRevision"),
        "policyLockSha256": obligations.get("policyLockSha256"),
        "requiredDeclarations": len(required),
        "declaredRequired": sum(1 for item in required if item.get("obligationId") in declared_ids),
        "errors": errors,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "required": len(required), "declared": payload["declaredRequired"], "errors": len(errors), "out": str(args.out)}, ensure_ascii=False))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
