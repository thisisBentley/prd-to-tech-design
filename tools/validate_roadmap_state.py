#!/usr/bin/env python3
"""Validate a Roadmap state snapshot against its current source files."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from roadmap_state import build_state, load, validate_state


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--roadmap", type=Path, required=True)
    parser.add_argument("--changelog", type=Path, required=True)
    parser.add_argument("--version-manifest", type=Path, required=True)
    parser.add_argument("--dataset-status", type=Path, required=True)
    parser.add_argument("--expected-milestone", required=True)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    snapshot = load(args.snapshot.resolve())
    rebuilt = build_state(args.roadmap, args.changelog, args.version_manifest, args.dataset_status, args.expected_milestone)
    errors = validate_state(snapshot, rebuilt)
    result = {"schemaVersion": 1, "status": "PASS" if not errors else "FAIL", "errors": errors, "canonical": rebuilt["canonical"]}
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
