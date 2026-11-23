#!/usr/bin/env python3
"""Validate conditional Optimizer preflight boundaries."""
from __future__ import annotations
import argparse, json
from pathlib import Path
from trust_kernel import validate_schema_value
from optimizer_preflight import load

def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    args=parser.parse_args()
    data=load(args.preflight.resolve(), {})
    errors=validate_schema_value(data,"optimizer-preflight.schema.json")
    authority=data.get("authority") or {}
    if authority.get("readOnly") is not True or authority.get("mayApply") is not False:
        errors.append("Optimizer preflight must be read-only and mayApply=false")
    if authority.get("releaseEligible") is not False or authority.get("trainingEligible") is not False:
        errors.append("Optimizer preflight cannot grant release or training eligibility")
    for proposal in data.get("proposals") or []:
        if proposal.get("applyStatus") != "REQUIRES_HUMAN_CHANGE_SET":
            errors.append("proposal does not require human Change Set")
    report={"schemaVersion":1,"preflightId":data.get("preflightId"),"status":"PASS" if not errors else "BLOCKED","preflightStatus":data.get("status"),"errors":errors,"proposalCount":len(data.get("proposals") or [])}
    if args.out:
        args.out.parent.mkdir(parents=True,exist_ok=True)
        args.out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return 0 if not errors else 1
if __name__ == "__main__":
    raise SystemExit(main())
