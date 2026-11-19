#!/usr/bin/env python3
"""Compare two Finding snapshots and enforce semantic convergence."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from semantic_convergence import evaluate_convergence, load, save


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--invariant-registry", type=Path, required=True)
    parser.add_argument("--history", type=Path, action="append", default=[], help="Prior Finding snapshot; repeat for chronological history")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    history = [load(path.resolve()) for path in args.history]
    report = evaluate_convergence(
        load(args.baseline.resolve()),
        load(args.current.resolve()),
        load(args.policy.resolve()),
        load(args.invariant_registry.resolve()),
        history=history,
    )
    save(args.out, report)
    print(json.dumps(report, ensure_ascii=False, indent=2) if args.json else json.dumps({"status": report["status"], "metrics": report["metrics"], "blockingReasons": report["blockingReasons"], "out": str(args.out.resolve())}, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
