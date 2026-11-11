#!/usr/bin/env python3
"""Collect producer obligation declarations from task results and package inputs."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from validate_json_schemas import load, validate

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_ROOT = ROOT / "schemas" if (ROOT / "schemas").exists() else ROOT / "references"


def declarations_from(path: Path) -> list[dict[str, Any]]:
    data = load(path)
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        values = data.get("declarations")
        if isinstance(values, list):
            return [item for item in values if isinstance(item, dict)]
        values = data.get("obligationDeclarations")
        if isinstance(values, list):
            return [item for item in values if isinstance(item, dict)]
    raise ValueError("declaration input must be a list or contain declarations/obligationDeclarations")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--obligations", type=Path, required=True)
    parser.add_argument("--declarations-dir", type=Path)
    parser.add_argument("--input", action="append", type=Path, default=[])
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    obligations_doc = load(args.obligations.resolve())
    obligations = {item["obligationId"]: item for item in obligations_doc.get("obligations", [])}
    inputs: list[Path] = []
    if args.declarations_dir and args.declarations_dir.is_dir():
        inputs.extend(sorted(args.declarations_dir.glob("*.json")))
    inputs.extend(args.input)
    merged: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    for path in inputs:
        try:
            declarations = declarations_from(path.resolve())
        except Exception as exc:
            errors.append(f"{path}: {exc}")
            continue
        for declaration in declarations:
            obligation_id = str(declaration.get("obligationId", ""))
            rule_id = str(declaration.get("ruleId", ""))
            obligation = obligations.get(obligation_id)
            if obligation is None:
                errors.append(f"{path}: unknown obligationId {obligation_id}")
                continue
            if rule_id != obligation.get("ruleId"):
                errors.append(f"{path}: {obligation_id} ruleId {rule_id} != {obligation.get('ruleId')}")
                continue
            if declaration.get("producerRole") != obligation.get("ownerRole"):
                errors.append(f"{path}: {obligation_id} producerRole {declaration.get('producerRole')} != {obligation.get('ownerRole')}")
                continue
            if obligation_id in merged and merged[obligation_id] != declaration:
                errors.append(f"{path}: conflicting duplicate declaration for {obligation_id}")
                continue
            merged[obligation_id] = declaration
    payload = {
        "schemaVersion": 1,
        "workflowId": obligations_doc["workflowId"],
        "targetRevision": obligations_doc["targetRevision"],
        "policyLockSha256": obligations_doc["policyLockSha256"],
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "declarations": list(merged.values()),
    }
    schema = load(SCHEMA_ROOT / "obligation-declarations.schema.json")
    schema_errors = validate(payload, schema, schema)
    if schema_errors:
        errors.extend(schema_errors)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    required_ids = {item["obligationId"] for item in obligations.values() if item.get("declarationRequired")}
    declared_ids = {item["obligationId"] for item in merged.values() if item.get("status") == "DECLARED"}
    status = "BLOCKED" if errors else ("COMPLETE" if required_ids <= declared_ids else "PARTIAL")
    print(json.dumps({"status": status, "required": len(required_ids), "declared": len(declared_ids & required_ids), "inputs": len(inputs), "errors": errors, "out": str(args.out)}, ensure_ascii=False))
    return 0 if status != "BLOCKED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
