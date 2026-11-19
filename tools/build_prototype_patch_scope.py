#!/usr/bin/env python3
"""Derive the executable write scope for a Prototype change set."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from prototype_changes import build_patch_scope, load, save, validate_schema_value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--change-set", type=Path, required=True)
    parser.add_argument("--impact-report", type=Path, required=True)
    parser.add_argument("--current-model", type=Path, required=True)
    parser.add_argument("--prototype", type=Path, required=True)
    parser.add_argument("--max-changed-characters", type=int, default=20000)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    impact = load(args.impact_report.resolve())
    if impact.get("status") != "PASS":
        print(json.dumps({"status": "BLOCKED", "errors": ["impact report is not PASS; patch scope cannot be derived"], "impactReportId": impact.get("impactReportId"), "rationale": impact.get("rationale", [])}, ensure_ascii=False, indent=2))
        return 1
    scope = build_patch_scope(
        load(args.change_set.resolve()),
        impact,
        load(args.current_model.resolve()),
        args.prototype,
        args.max_changed_characters,
    )
    errors = validate_schema_value(scope, "prototype-patch-scope.schema.json")
    if errors:
        print(json.dumps({"status": "FAIL", "errors": errors}, ensure_ascii=False, indent=2))
        return 1
    save(args.out, scope)
    print(json.dumps({"status": "PASS", "out": str(args.out.resolve()), "scopeId": scope["scopeId"], "allowedUIElementIds": scope["allowedUIElementIds"], "allowedNodeIds": scope["allowedNodeIds"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
