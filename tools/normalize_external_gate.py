#!/usr/bin/env python3
"""Normalize an external QA/G1 result and bind it to candidate hashes and target identity."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from trust_kernel import load, normalize_external_gate, save_json


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--target-binding", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = normalize_external_gate(load(args.input.resolve()), load(args.target_binding.resolve()))
    save_json(args.out, result)
    print(json.dumps({"verdict": result["verdict"], "releaseState": result["releaseState"], "closureEligible": result["closureEligible"], "out": str(args.out.resolve())}, ensure_ascii=False, indent=2))
    return 0 if result["closureEligible"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
