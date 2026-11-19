#!/usr/bin/env python3
"""Validate Interaction Contract V2 structure, bindings and scenario closure."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from interaction_contracts import load, save, validate_contract


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--prd", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    contract = load(args.contract.resolve())
    report = validate_contract(contract, args.prd.resolve() if args.prd else None)
    if args.out:
        save(args.out, report)
    print(json.dumps(report, ensure_ascii=False, indent=2) if args.json else json.dumps({"status": report["status"], "errors": report["errors"], "metrics": report["metrics"]}, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
