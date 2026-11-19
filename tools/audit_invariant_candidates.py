#!/usr/bin/env python3
"""Run a deterministic source-grounding review over candidate invariants."""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from semantic_convergence import load, now, save, sha256_file, validate_schema_value


def norm(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--review-out", type=Path, required=True)
    parser.add_argument("--audit-out", type=Path, required=True)
    parser.add_argument("--reviewer-role", default="independent-source-checker")
    args = parser.parse_args()
    registry_path = args.registry.resolve()
    ledger_path = args.ledger.resolve()
    registry = load(registry_path)
    ledger = load(ledger_path)
    prd_path = Path(str((ledger.get("source") or {}).get("prdPath", ""))).resolve()
    if not prd_path.is_file():
        raise SystemExit(f"PRD not found: {prd_path}")
    prd_text = norm(prd_path.read_text(encoding="utf-8", errors="replace"))
    decisions = []
    audit_rows = []
    for invariant in registry.get("invariants", []) or []:
        lines = [norm(line.lstrip("-* ")) for line in str(invariant.get("statement", "")).splitlines()]
        evidence_lines = [line for line in lines if len(line) >= 4]
        missing = [line for line in evidence_lines if line not in prd_text]
        invariant_id = str(invariant.get("invariantId", ""))
        if evidence_lines and not missing:
            decision = "ACCEPT"
            target = "ACTIVE"
            rationale = "Every substantive invariant line is grounded in the bound PRD source."
        else:
            decision = "DEFER"
            target = "CANDIDATE"
            rationale = "The invariant aggregates content that is not wholly locatable in the bound PRD source; narrower review is required."
        decisions.append({
            "invariantId": invariant_id,
            "decision": decision,
            "targetStatus": target,
            "rationale": rationale,
            "evidenceRefs": sorted(set([*(invariant.get("sourceRefs") or []), str(prd_path)])),
        })
        audit_rows.append({
            "invariantId": invariant_id,
            "decision": decision,
            "lineCount": len(evidence_lines),
            "missingLineCount": len(missing),
            "missingSamples": missing[:3],
        })
    review = {
        "schemaVersion": 1,
        "reviewId": "INV-REVIEW-" + sha256_file(registry_path)[:16],
        "workflowId": str(registry.get("workflowId", "unknown")),
        "targetRevision": str(registry.get("targetRevision", "unknown")),
        "registryPath": str(registry_path),
        "registryHash": sha256_file(registry_path),
        "reviewerRole": args.reviewer_role,
        "independentContext": True,
        "decisions": decisions,
        "reviewedAt": now(),
    }
    errors = validate_schema_value(review, "invariant-review-result.schema.json")
    if errors:
        raise SystemExit("; ".join(errors))
    save(args.review_out, review)
    audit = {
        "schemaVersion": 1,
        "status": "PASS",
        "reviewPath": str(args.review_out.resolve()),
        "reviewHash": sha256_file(args.review_out.resolve()),
        "accepted": sum(1 for item in decisions if item["decision"] == "ACCEPT"),
        "deferred": sum(1 for item in decisions if item["decision"] == "DEFER"),
        "rows": audit_rows,
        "checkedAt": now(),
    }
    save(args.audit_out, audit)
    print(json.dumps({k: audit[k] for k in ("status", "accepted", "deferred", "reviewPath", "reviewHash")}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
