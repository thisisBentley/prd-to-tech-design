#!/usr/bin/env python3
"""Classify a task into diagnosis, targeted revision, full delivery or escalation."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from trust_kernel import classify_task, load, save_json


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = classify_task(load(args.request.resolve()), load(args.policy.resolve()), args.policy.resolve())
    save_json(args.out, result)
    print(json.dumps({"mode": result["mode"], "status": result["status"], "reasons": result["reasons"], "out": str(args.out.resolve())}, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "CLASSIFIED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
