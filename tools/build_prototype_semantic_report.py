#!/usr/bin/env python3
"""Project a semantic review aggregate into the Prototype Semantic Report contract."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from interaction_contracts import load, now, save, validate_schema_value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--aggregate", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    aggregate_path = args.aggregate.resolve()
    aggregate = load(aggregate_path)
    contract = load(args.contract.resolve())
    findings = list(aggregate.get("findings", []) or [])
    blocking = int(aggregate.get("blockingCount", 0) or 0)
    status = aggregate.get("status", "BLOCKED")
    if status not in {"PASS", "PASS_WITH_NONBLOCKING", "NEEDS_FIX", "BLOCKED"}:
        status = "BLOCKED"
    checks = aggregate.get("checks", []) or []
    report = {
        "schemaVersion": 1,
        "reportId": "SEMANTIC-" + hashlib.sha256(aggregate_path.read_bytes()).hexdigest()[:16],
        "workflowId": aggregate.get("workflowId") or contract.get("workflowId", "unknown"),
        "prototypeRevision": aggregate.get("targetRevision") or contract.get("prototypeRevision", "unknown"),
        "prototypeHash": contract.get("source", {}).get("prototypeHash", "0" * 64),
        "contractId": contract.get("contractId", "unknown"),
        "status": status,
        "blockingCount": blocking,
        "findings": findings,
        "checks": checks,
        "sourceAggregatePath": str(aggregate_path),
        "sourceAggregateHash": hashlib.sha256(aggregate_path.read_bytes()).hexdigest(),
        "checkedAt": aggregate.get("generatedAt") or now(),
    }
    errors = validate_schema_value(report, "prototype-semantic-report.schema.json")
    if errors:
        print(json.dumps({"status": "FAIL", "errors": errors}, ensure_ascii=False, indent=2))
        return 1
    save(args.out, report)
    print(json.dumps({"status": status, "out": str(args.out.resolve()), "blockingCount": blocking}, ensure_ascii=False, indent=2))
    return 0 if status in {"PASS", "PASS_WITH_NONBLOCKING"} and blocking == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
