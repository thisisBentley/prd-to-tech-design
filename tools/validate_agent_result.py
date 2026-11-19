#!/usr/bin/env python3
"""Validate a structured Agent result against a released contract and Context Pack."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from agent_contracts import load, save, select_contract, validate_agent_result, validate_contract_release


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--context-pack", type=Path)
    parser.add_argument("--contract-id")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    release = load(args.release.resolve())
    release_errors = validate_contract_release(release)
    result = load(args.result.resolve())
    context = load(args.context_pack.resolve()) if args.context_pack else None
    if release_errors:
        report = {"schemaVersion": 1, "status": "FAIL", "checks": [], "errors": release_errors}
    else:
        contract_id = args.contract_id or result.get("contractId") if isinstance(result, dict) else args.contract_id
        try:
            contract = select_contract(release, contract_id=contract_id)
        except KeyError as exc:
            report = {"schemaVersion": 1, "status": "FAIL", "checks": [], "errors": [str(exc)]}
        else:
            report = validate_agent_result(result, contract, context)
    if args.out:
        save(args.out, report)
    print(json.dumps(report, ensure_ascii=False, indent=2) if args.json else json.dumps({"status": report["status"], "errors": report["errors"]}, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
