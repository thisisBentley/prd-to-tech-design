#!/usr/bin/env python3
"""Build a deterministic, read-only Observer report."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from observer import build, save

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--episode", type=Path, required=True)
    parser.add_argument("--finding-ledger", type=Path, required=True)
    parser.add_argument("--repair-cycle", type=Path, required=True)
    parser.add_argument("--cost-ledger", type=Path, required=True)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--challenger-run", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = build(
            episode_path=args.episode.resolve(),
            finding_ledger_path=args.finding_ledger.resolve(),
            repair_cycle_path=args.repair_cycle.resolve(),
            cost_ledger_path=args.cost_ledger.resolve(),
            corpus_path=args.corpus.resolve(),
            challenger_path=args.challenger_run.resolve() if args.challenger_run else None,
        )
    except Exception as exc:
        print(json.dumps({"status": "BLOCKED", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    save(args.out.resolve(), report)
    print(json.dumps({
        "status": report["status"],
        "observerId": report["observerId"],
        "rootCauses": report["metrics"]["rootCauses"],
        "recommendations": report["metrics"]["recommendations"],
        "out": str(args.out.resolve()),
    }, ensure_ascii=False, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
