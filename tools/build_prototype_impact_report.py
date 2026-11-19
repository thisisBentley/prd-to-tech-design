#!/usr/bin/env python3
"""Compute affected elements, rules, consumers and reruns from a change set."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from prototype_changes import build_impact_report, load, save, validate_schema_value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--change-set", type=Path, required=True)
    parser.add_argument("--current-model", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    impact = build_impact_report(load(args.change_set.resolve()), load(args.current_model.resolve()), load(args.manifest.resolve()) if args.manifest else None)
    errors = validate_schema_value(impact, "prototype-impact-report.schema.json")
    if errors:
        print(json.dumps({"status": "FAIL", "errors": errors}, ensure_ascii=False, indent=2))
        return 1
    save(args.out, impact)
    print(json.dumps({"status": impact["status"], "out": str(args.out.resolve()), "riskLevel": impact["riskLevel"], "affected": impact["affected"], "requiredReruns": impact["requiredReruns"]}, ensure_ascii=False, indent=2))
    return 0 if impact["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
