#!/usr/bin/env python3
"""Build a deterministic Source Pack Registry from a catalog."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from source_pack import build_registry, load, save


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        registry = build_registry(load(args.catalog.resolve()), args.repo_root.resolve())
    except Exception as exc:
        print(json.dumps({"status": "BLOCKED", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    save(args.out.resolve(), registry)
    print(json.dumps({
        "status": registry["status"],
        "packId": registry["packId"],
        "sources": registry["metrics"]["sourceCount"],
        "locked": registry["metrics"]["lockedCount"],
        "trainingCandidates": registry["metrics"]["trainingCandidateCount"],
        "out": str(args.out.resolve()),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
