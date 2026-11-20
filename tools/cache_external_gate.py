#!/usr/bin/env python3
"""Cache a normalized QA/G1 verdict under a deterministic evidence key."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from external_gate_cache import cache_verdict
from trust_kernel import load


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verdict", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = cache_verdict(load(args.verdict.resolve()), args.cache_dir.resolve(), str(args.verdict.resolve()))
    except Exception as exc:
        print(json.dumps({"status": "BLOCKED", "errors": [str(exc)]}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps({
        "status": result["status"],
        "cacheKey": result["cacheKey"],
        "evidenceKey": result["evidenceKey"],
        "path": result["path"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
