#!/usr/bin/env python3
"""Build a deterministic Roadmap state snapshot across all state sources."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from roadmap_state import build_state, save


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--roadmap", type=Path, required=True)
    parser.add_argument("--changelog", type=Path, required=True)
    parser.add_argument("--version-manifest", type=Path, required=True)
    parser.add_argument("--dataset-status", type=Path, required=True)
    parser.add_argument("--expected-milestone", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    state = build_state(args.roadmap, args.changelog, args.version_manifest, args.dataset_status, args.expected_milestone)
    save(args.out, state)
    print(json.dumps({"status": state["status"], "canonical": state["canonical"], "drift": state["drift"], "out": str(args.out.resolve())}, ensure_ascii=False, indent=2))
    return 0 if state["status"] == "PASS" or not args.strict else 1


if __name__ == "__main__":
    raise SystemExit(main())
