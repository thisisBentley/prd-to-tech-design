#!/usr/bin/env python3
"""Final delivery gate combining Pair, consistency evidence and final review."""
from __future__ import annotations

import argparse
import hashlib
import json
import secrets
from datetime import datetime, timezone
from pathlib import Path

PASSING = {"PASS", "ACCEPTED", "ACCEPTED_WITH_ACTIONS"}


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pair", type=Path, required=True)
    parser.add_argument("--consistency", type=Path, required=True)
    parser.add_argument("--final-review", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    pair = load(args.pair); consistency = load(args.consistency); final_review = load(args.final_review)
    pair_ok = pair.get("pairStatus") == "SYNCED"
    consistency_ok = consistency.get("status") == "PASS" and int(consistency.get("blockingCount", 1)) == 0
    review_ok = final_review.get("verdict") in PASSING and int(final_review.get("blockingCount", 1)) == 0
    checks = [
        {"checkId": "FINAL.PAIR_SYNCED", "status": "passed" if pair_ok else "failed", "evidenceRefs": [str(args.pair.resolve())], "observed": f"pairStatus={pair.get('pairStatus')}", "expected": "SYNCED"},
        {"checkId": "FINAL.CONSISTENCY", "status": "passed" if consistency_ok else "failed", "evidenceRefs": [str(args.consistency.resolve())], "observed": f"status={consistency.get('status')} blockingCount={consistency.get('blockingCount')}", "expected": "PASS with zero blockers"},
        {"checkId": "FINAL.REVIEW", "status": "passed" if review_ok else "failed", "evidenceRefs": [str(args.final_review.resolve())], "observed": f"verdict={final_review.get('verdict')} blockingCount={final_review.get('blockingCount')}", "expected": "accepted with zero blockers"},
    ]
    findings = [item["checkId"] for item in checks if item["status"] != "passed"]
    result = "PASS" if not findings else "NEEDS_FIX"
    payload = {
        "schemaVersion": 2,
        "gate": "Q1",
        "revision": pair.get("prdRevision", "unknown"),
        "frozenCopy": str(args.pair.resolve()),
        "independentContext": True,
        "reviewRunId": final_review.get("reviewRunId", "final-" + secrets.token_hex(4)),
        "result": result,
        "ruleSetVersion": "delivery-final-v1",
        "objectHashes": {
            args.pair.name: digest(args.pair),
            args.consistency.name: digest(args.consistency),
            args.final_review.name: digest(args.final_review),
        },
        "checks": checks,
        "findings": findings,
        "blockingCount": len(findings),
        "completionStatus": "complete",
        "tool": "final_delivery_gate",
        "checkedAt": datetime.now(timezone.utc).isoformat(),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result, "blockingCount": len(findings), "out": str(args.out)}, ensure_ascii=False))
    return 0 if result == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
