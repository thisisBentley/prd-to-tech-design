#!/usr/bin/env python3
"""Close the static, runtime and semantic Prototype layers into one gate."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from interaction_contracts import load, now, save, validate_schema_value


def report_hash(path: Path | None) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path and path.is_file() else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--static", type=Path)
    parser.add_argument("--runtime", type=Path)
    parser.add_argument("--semantic", type=Path)
    parser.add_argument("--require-real-browser", action="store_true")
    parser.add_argument("--required-state-kind", action="append", default=[])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    paths = {"static": args.static.resolve() if args.static else None, "runtime": args.runtime.resolve() if args.runtime else None, "semantic": args.semantic.resolve() if args.semantic else None}
    reports = {layer: load(path) if path and path.is_file() else None for layer, path in paths.items()}
    blocking: list[str] = []
    layers = {
        "static": reports["static"].get("status", "MISSING") if reports["static"] else "MISSING",
        "runtime": reports["runtime"].get("status", "MISSING") if reports["runtime"] else "MISSING",
        "semantic": reports["semantic"].get("status", "MISSING") if reports["semantic"] else "MISSING",
    }
    missing = [layer for layer, value in layers.items() if value == "MISSING"]
    if missing:
        blocking.append("missing layers: " + ", ".join(missing))
    available = [report for report in reports.values() if report]
    expected_hashes = {str(report.get("prototypeHash", "")) for report in available}
    expected_contracts = {str(report.get("contractId", "")) for report in available}
    expected_workflows = {str(report.get("workflowId", "")) for report in available}
    if len(expected_hashes) > 1:
        blocking.append("prototypeHash mismatch across layers: " + ", ".join(sorted(expected_hashes)))
    if len(expected_contracts) > 1:
        blocking.append("contractId mismatch across layers: " + ", ".join(sorted(expected_contracts)))
    if len(expected_workflows) > 1:
        blocking.append("workflowId mismatch across layers: " + ", ".join(sorted(expected_workflows)))
    if layers["static"] != "MISSING" and layers["static"] != "PASS":
        blocking.append(f"static layer is {layers['static']}")
    if layers["runtime"] != "MISSING" and layers["runtime"] != "PASS":
        blocking.append(f"runtime layer is {layers['runtime']}")
    if layers["semantic"] not in {"MISSING", "PASS", "PASS_WITH_NONBLOCKING"}:
        blocking.append(f"semantic layer is {layers['semantic']}")
    if reports["semantic"] and int(reports["semantic"].get("blockingCount", 0) or 0) > 0:
        blocking.append(f"semantic blockingCount is {reports['semantic'].get('blockingCount')}")
    evidence_level = reports["runtime"].get("evidenceLevel", "MISSING") if reports["runtime"] else "MISSING"
    if args.require_real_browser and evidence_level != "REAL_BROWSER":
        blocking.append(f"runtime evidence level is {evidence_level}; REAL_BROWSER required")
    if reports["runtime"]:
        metrics = reports["runtime"].get("scenarioMetrics") or {}
        if int(metrics.get("total", 0) or 0) <= 0:
            blocking.append("runtime has no executed scenarios")
        if int(metrics.get("failed", 0) or 0) > 0:
            blocking.append(f"runtime has {metrics.get('failed')} failed scenarios")
        covered = set(str(item) for item in metrics.get("coveredStateKinds", []) or [])
        missing_states = [kind for kind in args.required_state_kind if kind not in covered]
        if missing_states:
            blocking.append("missing runtime state coverage: " + ", ".join(missing_states))
    if missing:
        status = "INCOMPLETE"
    else:
        status = "PASS" if not blocking else "BLOCKED"
    evidence_refs = [str(path) for path in paths.values() if path]
    sample = available[0] if available else {}
    report = {
        "schemaVersion": 1,
        "gateId": "THREE-LAYER-" + hashlib.sha256(json.dumps({"layers": layers, "hashes": sorted(expected_hashes), "contracts": sorted(expected_contracts)}, sort_keys=True).encode()).hexdigest()[:16],
        "workflowId": sample.get("workflowId", "unknown"),
        "prototypeRevision": sample.get("prototypeRevision", "unknown"),
        "prototypeHash": sample.get("prototypeHash", "0" * 64),
        "contractId": sample.get("contractId", "unknown"),
        "status": status,
        "layers": layers,
        "runtimeEvidenceLevel": evidence_level,
        "evidenceRefs": evidence_refs or ["NO-EVIDENCE"],
        "blockingReasons": blocking,
        "requiresFullGate": True,
        "checkedAt": now(),
    }
    errors = validate_schema_value(report, "prototype-three-layer-gate.schema.json")
    if errors:
        print(json.dumps({"status": "FAIL", "errors": errors}, ensure_ascii=False, indent=2))
        return 1
    save(args.out, report)
    print(json.dumps(report, ensure_ascii=False, indent=2) if args.json else json.dumps({"status": status, "layers": layers, "runtimeEvidenceLevel": evidence_level, "blockingReasons": blocking, "out": str(args.out.resolve())}, ensure_ascii=False))
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
