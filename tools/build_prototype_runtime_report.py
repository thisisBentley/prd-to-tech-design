#!/usr/bin/env python3
"""Normalize verifier output into the Prototype Runtime Report contract."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from interaction_contracts import load, now, save, validate_schema_value


def normalize_status(value: str) -> str:
    if value in {"PASS", "FAIL", "INSUFFICIENT", "ENVIRONMENT_BLOCKED"}:
        return value
    return "FAIL"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    runtime = load(args.runtime.resolve())
    status = normalize_status(str(runtime.get("status", "FAIL")))
    report = {
        "schemaVersion": 1,
        "status": status,
        "workflowId": runtime.get("workflowId", "unknown"),
        "prototypeRevision": runtime.get("prototypeRevision", "unknown"),
        "prototypeHash": runtime.get("prototypeHash", "0" * 64),
        "contractId": runtime.get("contractId") or "unknown",
        "evidenceLevel": runtime.get("runtimeEvidenceLevel", "STATIC_CONTRACT"),
        "browserVersion": runtime.get("browserVersion"),
        "scenarioResults": runtime.get("scenarioResults", []) or [],
        "scenarioMetrics": runtime.get("scenarioMetrics") or {"total": 0, "passed": 0, "failed": 0, "skipped": 0, "coveredStateKinds": []},
        "consoleErrors": runtime.get("consoleErrors", []) or [],
        "pageErrors": runtime.get("pageErrors", []) or [],
        "requestFailures": runtime.get("requestFailures", []) or [],
        "checks": runtime.get("checks", []) or [],
        "screenshots": runtime.get("screenshots", []) or [],
        "domSnapshots": runtime.get("domSnapshots", []) or [],
        "traces": runtime.get("traces", []) or [],
        "checkedAt": runtime.get("checkedAt") or now(),
    }
    errors = validate_schema_value(report, "prototype-runtime-report.schema.json")
    if errors:
        print(json.dumps({"status": "FAIL", "errors": errors}, ensure_ascii=False, indent=2))
        return 1
    save(args.out, report)
    print(json.dumps({"status": status, "out": str(args.out.resolve()), "scenarioMetrics": report["scenarioMetrics"]}, ensure_ascii=False, indent=2))
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
