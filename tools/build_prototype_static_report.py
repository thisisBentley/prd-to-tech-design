#!/usr/bin/env python3
"""Build the static layer of the Prototype three-layer gate."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from interaction_contracts import load, now, save, validate_contract, validate_schema_value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--prd", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    contract = load(args.contract.resolve())
    validation = validate_contract(contract, args.prd.resolve() if args.prd else None)
    findings = list(contract.get("findings", []) or [])
    for error in validation.get("errors", []):
        findings.append({"findingId": f"STATIC-{len(findings) + 1:04d}", "severity": "BLOCKING", "code": "STATIC_VALIDATION", "message": error, "evidenceRefs": [str(args.contract.resolve())]})
    status = "PASS" if validation["status"] == "PASS" and contract.get("status") == "PASS" and not findings else "FAIL"
    report = {
        "schemaVersion": 1,
        "reportId": "STATIC-" + hashlib.sha256(json.dumps([contract.get("contractId"), contract.get("source", {}).get("prototypeHash")], sort_keys=True).encode()).hexdigest()[:16],
        "workflowId": contract.get("workflowId", "unknown"),
        "prototypeRevision": contract.get("prototypeRevision", "unknown"),
        "prototypeHash": contract.get("source", {}).get("prototypeHash", "0" * 64),
        "contractId": contract.get("contractId", "unknown"),
        "status": status,
        "checks": validation.get("checks", []),
        "findings": findings,
        "metrics": contract.get("metrics", {}),
        "checkedAt": now(),
    }
    errors = validate_schema_value(report, "prototype-static-report.schema.json")
    if errors:
        print(json.dumps({"status": "FAIL", "errors": errors}, ensure_ascii=False, indent=2))
        return 1
    save(args.out, report)
    print(json.dumps({"status": status, "out": str(args.out.resolve()), "metrics": report["metrics"]}, ensure_ascii=False, indent=2))
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
