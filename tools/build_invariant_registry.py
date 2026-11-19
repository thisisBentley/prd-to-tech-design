#!/usr/bin/env python3
"""Build a candidate Invariant Registry from explicit semantic sources."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from semantic_convergence import build_invariant_registry, save


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--decision-impact-graph", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    registry = build_invariant_registry(args.ledger, args.decision_impact_graph)
    save(args.out, registry)
    print(json.dumps({"status": "PASS", "out": str(args.out.resolve()), "metrics": registry["metrics"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
