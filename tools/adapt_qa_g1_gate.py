#!/usr/bin/env python3
"""Adapt a raw QA/G1 report observation into a normalized external-gate verdict."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from trust_kernel import load, normalize_external_gate, save_json, validate_schema_value


def adapt(report: dict, target_binding: dict) -> dict:
    errors = validate_schema_value(report, "external-gate-report.schema.json")
    if errors:
        raise ValueError("invalid QA/G1 report: " + "; ".join(errors))
    source = report["report"]
    canonical = {
        "schemaVersion": 1,
        "workflowId": report["workflowId"],
        "candidateRevision": report["candidateRevision"],
        "jiraKey": report["jiraKey"],
        "gateType": report["gateType"],
        "rawResult": source["statusText"],
        "findings": report["findings"],
        "tool": report["tool"],
        "candidateArtifacts": report["candidateArtifacts"],
        "evidenceRefs": [source["reportId"], *source["evidenceRefs"]],
        "checkedAt": source["checkedAt"],
    }
    return normalize_external_gate(canonical, target_binding)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--target-binding", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        verdict = adapt(load(args.report.resolve()), load(args.target_binding.resolve()))
    except Exception as exc:
        print(json.dumps({"status": "BLOCKED", "errors": [str(exc)]}, ensure_ascii=False, indent=2))
        return 1
    save_json(args.out, verdict)
    print(json.dumps({
        "status": "NORMALIZED",
        "gateType": verdict["gateType"],
        "verdict": verdict["verdict"],
        "releaseState": verdict["releaseState"],
        "closureEligible": verdict["closureEligible"],
        "out": str(args.out.resolve()),
    }, ensure_ascii=False, indent=2))
    return 0 if verdict["closureEligible"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
