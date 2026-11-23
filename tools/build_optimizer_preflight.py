#!/usr/bin/env python3
"""Build conditional Bounded Optimizer preflight."""
from __future__ import annotations
import argparse, json
from pathlib import Path
from optimizer_preflight import build, save

def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--episode", type=Path, required=True)
    parser.add_argument("--observer", type=Path, required=True)
    parser.add_argument("--decision-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args=parser.parse_args()
    try:
        result=build(args.episode.resolve(), args.observer.resolve(), args.decision_dir.resolve())
    except Exception as exc:
        print(json.dumps({"status":"BLOCKED","error":str(exc)},ensure_ascii=False,indent=2))
        return 1
    save(args.out.resolve(), result)
    print(json.dumps({"status":result["status"],"preflightId":result["preflightId"],"proposals":len(result["proposals"]),"out":str(args.out.resolve())},ensure_ascii=False,indent=2))
    return 0
if __name__ == "__main__":
    raise SystemExit(main())
