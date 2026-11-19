#!/usr/bin/env python3
"""Build a deterministic DOM/model change set between two Prototype revisions."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from prototype_changes import build_change_set, load, save, validate_schema_value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--previous-model", type=Path, required=True)
    parser.add_argument("--current-model", type=Path, required=True)
    parser.add_argument("--workflow-id")
    parser.add_argument("--from-revision")
    parser.add_argument("--to-revision")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    previous_path = args.previous_model.resolve()
    current_path = args.current_model.resolve()
    result = build_change_set(load(previous_path), load(current_path), previous_path, current_path, args.workflow_id, args.from_revision, args.to_revision)
    errors = validate_schema_value(result, "prototype-change-set.schema.json")
    if errors:
        print(json.dumps({"status": "FAIL", "errors": errors}, ensure_ascii=False, indent=2))
        return 1
    save(args.out, result)
    print(json.dumps({"status": "PASS", "out": str(args.out.resolve()), "primaryType": result["primaryType"], "metrics": result["metrics"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
