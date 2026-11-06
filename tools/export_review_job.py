#!/usr/bin/env python3
"""Export an immutable independent review job for a candidate bundle.

The generating session runs this command. It does not execute gates. The output
is the only contract a subagent/process worker should receive.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import secrets
from datetime import datetime, timezone
from pathlib import Path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path, help="01-delivery directory")
    parser.add_argument("--out", type=Path, required=True, help="review job JSON")
    args = parser.parse_args()

    root = args.bundle.resolve()
    dd = root / ".delivery"
    seal = json.loads((dd / "candidate-seal.json").read_text(encoding="utf-8"))
    revision = seal["revision"]
    frozen = seal["frozenCopy"]
    hashes = seal["artifactHashes"]
    errors = []
    cr = root / frozen
    for name, expected in hashes.items():
        p = cr / name
        if not p.exists():
            errors.append(f"missing frozen artifact: {p}")
            continue
        if sha256(p) != expected:
            errors.append(f"hash mismatch: {name}")
    for gate in ["R0", "G1", "O1", "U1", "U2", "QA", "Q1"]:
        p = dd / "gate-results" / revision / f"{gate}.json"
        if p.exists():
            errors.append(f"pre-existing formal gate result must be removed before export: {p}")
    if errors:
        print(json.dumps({"status": "FAIL", "errors": errors}, ensure_ascii=False, indent=2))
        return 1

    review_run_id = "review-" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S") + "-" + secrets.token_hex(4)
    job = {
        "schemaVersion": 2,
        "jobType": "delivery-independent-gates",
        "reviewRunId": review_run_id,
        "bundleId": seal["bundleId"],
        "revision": revision,
        "bundleRoot": str(root),
        "frozenCopy": str(cr),
        "candidateSeal": str(dd / "candidate-seal.json"),
        "artifactHashes": hashes,
        "gates": ["R0", "G1", "O1", "U1", "U2", "QA", "Q1"],
        "worker": {
            "kind": "subagent",
            "required": True,
            "forbidden": ["modify candidates", "edit formal gate JSON from generator session", "reuse previous PASS"],
            "outputs": {
                "gateResults": str(dd / "gate-results" / revision),
                "summary": str(dd / "gate-results" / revision / "summary.json"),
                "envelope": str(dd / "reviews" / review_run_id / "envelope.json"),
            },
        },
        "contract": {
            "gateResultSchema": "schemas/gate-result.schema.json",
            "summarySchema": "schemas/delivery-gate-summary.schema.json",
            "validator": "tools/gate_contract_validator.py",
            "bundleValidator": "tools/validate_delivery_bundle.py",
            "passPolicy": "PASS requires checks[], evidenceRefs[], hashes and blockingCount=0",
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(job, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "READY", "job": str(args.out), "reviewRunId": review_run_id}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
