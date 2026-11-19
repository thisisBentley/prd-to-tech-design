#!/usr/bin/env python3
"""Assess whether a Prototype is ready for Interaction Contract V2 migration."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from interaction_contracts import load, now, save, sha256_file


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prototype", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--prd", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    prototype = args.prototype.resolve()
    model = load(args.model.resolve())
    checks = []
    findings = []

    def check(check_id: str, ok: bool, observed: object, expected: str, code: str, blocking: bool = True) -> None:
        checks.append({"checkId": check_id, "status": "passed" if ok else "failed", "observed": observed, "expected": expected})
        if not ok:
            findings.append({"code": code, "severity": "BLOCKING" if blocking else "NON_BLOCKING", "message": expected, "observed": observed, "evidenceRefs": [str(prototype)]})

    metrics = model.get("metrics", {})
    check("MIGRATION.DATA_AI_IDS", metrics.get("dataAiIdNodes", 0) > 0, metrics.get("dataAiIdNodes", 0), "Prototype contains data-ai-id bindings", "DATA_AI_ID_MISSING")
    check("MIGRATION.INTERACTIVE_NODES", metrics.get("interactiveNodes", 0) > 0, metrics.get("interactiveNodes", 0), "Prototype contains interactive controls", "NO_INTERACTIVE_CONTROLS")
    check("MIGRATION.EVENT_BINDINGS", metrics.get("eventBindings", 0) > 0, metrics.get("eventBindings", 0), "Prototype exposes at least one event binding", "NO_EVENT_BINDINGS", blocking=False)
    manifest_ok = bool(args.manifest and args.manifest.is_file())
    check("MIGRATION.MANIFEST", manifest_ok, str(args.manifest.resolve()) if args.manifest else None, "Prototype Manifest exists", "MANIFEST_MISSING")
    prd_ok = bool(args.prd and args.prd.is_file())
    check("MIGRATION.PRD", prd_ok, str(args.prd.resolve()) if args.prd else None, "PRD is available for FR/AC closure", "PRD_MISSING")
    blocking = [item for item in findings if item["severity"] == "BLOCKING"]
    status = "READY_FOR_CONTRACT" if not blocking else "MIGRATION_BLOCKED"
    payload = {
        "schemaVersion": 1,
        "status": status,
        "prototypePath": str(prototype),
        "prototypeHash": sha256_file(prototype),
        **({"manifestPath": str(args.manifest.resolve()), "manifestHash": sha256_file(args.manifest.resolve())} if manifest_ok else {}),
        **({"prdPath": str(args.prd.resolve()), "prdHash": sha256_file(args.prd.resolve())} if prd_ok else {}),
        "metrics": metrics,
        "checks": checks,
        "findings": findings,
        "checkedAt": now(),
    }
    save(args.out, payload)
    print(json.dumps({"status": status, "out": str(args.out.resolve()), "metrics": metrics, "findings": [item["code"] for item in findings]}, ensure_ascii=False, indent=2))
    return 0 if status == "READY_FOR_CONTRACT" else 1


if __name__ == "__main__":
    raise SystemExit(main())
