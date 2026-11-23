#!/usr/bin/env python3
"""Validate Observer authority, source hashes and non-causal boundaries."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from observer import digest, load
from trust_kernel import validate_schema_value

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--verify-source-hashes", action="store_true")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    report = load(args.report.resolve(), {})
    errors = validate_schema_value(report, "observer-report.schema.json")
    authority = report.get("authority") or {}
    if authority.get("readOnly") is not True or authority.get("resultAuthority") != "NONE":
        errors.append("Observer must be read-only with resultAuthority NONE")
    if authority.get("releaseEligible") is not False or authority.get("trainingEligible") is not False:
        errors.append("Observer cannot grant release or training eligibility")
    if authority.get("causalClaims") is not False:
        errors.append("Observer v0 cannot make causal claims")
    if (report.get("analysis", {}).get("repairEffect") or {}).get("causalClaim") is not False:
        errors.append("repair effect cannot claim causality")
    if (report.get("analysis", {}).get("costQuality") or {}).get("causalClaim") is not False:
        errors.append("cost/quality analysis cannot claim causality")
    for rec in report.get("recommendations") or []:
        if rec.get("changeSetRequired") is not False:
            errors.append(f"recommendation requests an unapproved Change Set: {rec.get('recommendationId')}")
    if args.verify_source_hashes:
        for item in report.get("inputs") or []:
            if item.get("status") != "AVAILABLE":
                continue
            path = Path(str(item.get("path")))
            if not path.is_file():
                errors.append(f"source missing: {path}")
            elif digest(path) != item.get("sha256"):
                errors.append(f"source hash drift: {path}")
    result = {
        "schemaVersion": 1,
        "observerId": report.get("observerId"),
        "status": "PASS" if not errors else "BLOCKED",
        "reportStatus": report.get("status"),
        "errors": errors,
        "metrics": report.get("metrics", {}),
    }
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not errors else 1

if __name__ == "__main__":
    raise SystemExit(main())
