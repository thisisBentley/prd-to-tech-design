#!/usr/bin/env python3
"""Build a Semantic Ledger from the existing Delivery Semantic Model."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from semantic_convergence import build_semantic_ledger, save


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--semantic-model", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    ledger = build_semantic_ledger(args.semantic_model)
    save(args.out, ledger)
    print(json.dumps({"status": "PASS", "out": str(args.out.resolve()), "metrics": ledger["metrics"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
