#!/usr/bin/env python3
"""Validate Decision Contract readiness and optional bound PRD revision."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from validate_json_schemas import load, validate


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--prd", type=Path)
    parser.add_argument("--workflow-id")
    parser.add_argument("--revision")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    contract = load(args.contract.resolve())
    errors: list[str] = []
    if contract.get("status") != "PASS":
        errors.append(f"contract status {contract.get('status')} != PASS")
    if contract.get("readiness") != "READY":
        errors.append(f"contract readiness {contract.get('readiness')} != READY")
    if int(contract.get("metrics", {}).get("openBlocking", 0)) != 0:
        errors.append("openBlocking decisions remain")
    uncovered = contract.get("traceability", {}).get("uncoveredP0P1ObjectIds", [])
    if uncovered:
        errors.append("uncovered FR/BR/AC objects remain: " + ", ".join(map(str, uncovered)))
    if not contract.get("semanticModelPath") or not contract.get("semanticModelSha256"):
        errors.append("semantic model is not bound")
    blocking = [item for item in contract.get("findings", []) if item.get("severity") == "BLOCKING"]
    if blocking:
        errors.append(f"blocking findings remain: {len(blocking)}")
    if args.prd and args.prd.is_file() and contract.get("prdSha256") != sha256(args.prd.resolve()):
        errors.append("PRD hash drift")
    if args.workflow_id and contract.get("workflowId") != args.workflow_id:
        errors.append("workflowId mismatch")
    if args.revision and contract.get("targetRevision") != args.revision:
        errors.append("revision mismatch")
    report = {"schemaVersion": 1, "status": "PASS" if not errors else "BLOCKED", "contractId": contract.get("contractId"), "errors": errors, "checkedAt": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
