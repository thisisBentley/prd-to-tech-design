#!/usr/bin/env python3
"""Validate that PRD and Overview artifacts are bound to the current Jira target."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from trust_kernel import load, save_json, validate_target_binding


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = validate_target_binding(load(args.request.resolve()))
    save_json(args.out, result)
    print(json.dumps({"status": result["status"], "failedChecks": [item for item in result["checks"] if item["status"] == "failed"], "out": str(args.out.resolve())}, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
