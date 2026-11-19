#!/usr/bin/env python3
"""Build Interaction Contract V2 from a Prototype Model and Manifest."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from interaction_contracts import build_contract, save, validate_schema_value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prototype", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--overlay", type=Path)
    parser.add_argument("--prd", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    contract = build_contract(args.prototype, args.model, args.manifest, args.overlay, args.prd)
    errors = validate_schema_value(contract, "interaction-contract.schema.json")
    if errors:
        print(json.dumps({"status": "FAIL", "errors": errors}, ensure_ascii=False, indent=2))
        return 1
    save(args.out, contract)
    print(json.dumps({"status": contract["status"], "out": str(args.out.resolve()), "metrics": contract["metrics"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
