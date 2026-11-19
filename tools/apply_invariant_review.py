#!/usr/bin/env python3
"""Apply an independent invariant review and promote/deprecate candidates."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from semantic_convergence import load, now, save, sha256_file, validate_schema_value


DECISION_TARGETS = {
    "ACCEPT": {"ACTIVE", "LOCKED"},
    "DEFER": {"CANDIDATE"},
    "REJECT": {"DEPRECATED"},
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    registry_path = args.registry.resolve()
    review_path = args.review.resolve()
    registry = load(registry_path)
    review = load(review_path)
    review_errors = validate_schema_value(review, "invariant-review-result.schema.json")
    if review_errors:
        print(json.dumps({"status": "FAIL", "errors": review_errors}, ensure_ascii=False, indent=2))
        return 1
    errors: list[str] = []
    if review.get("workflowId") != registry.get("workflowId"):
        errors.append("review workflowId does not match registry")
    if review.get("targetRevision") != registry.get("targetRevision"):
        errors.append("review targetRevision does not match registry")
    if review.get("registryHash") != sha256_file(registry_path):
        errors.append("review registryHash does not match current registry")
    by_id = {str(item.get("invariantId")): item for item in registry.get("invariants", []) or []}
    seen: set[str] = set()
    for decision in review.get("decisions", []) or []:
        invariant_id = str(decision.get("invariantId", ""))
        if invariant_id in seen:
            errors.append(f"duplicate review decision: {invariant_id}")
            continue
        seen.add(invariant_id)
        invariant = by_id.get(invariant_id)
        if not invariant:
            errors.append(f"unknown invariant: {invariant_id}")
            continue
        if invariant.get("status") == "DEPRECATED" and decision.get("decision") == "ACCEPT":
            errors.append(f"deprecated invariant cannot be accepted: {invariant_id}")
        allowed_targets = DECISION_TARGETS.get(str(decision.get("decision")), set())
        if decision.get("targetStatus") not in allowed_targets:
            errors.append(
                f"{decision.get('decision')} invariant must target one of "
                f"{sorted(allowed_targets)}: {invariant_id}"
            )
    if errors:
        print(json.dumps({"status": "FAIL", "errors": errors}, ensure_ascii=False, indent=2))
        return 1
    for decision in review.get("decisions", []):
        invariant = by_id[str(decision["invariantId"])]
        if decision.get("decision") == "DEFER":
            invariant["owner"] = str(review["reviewerRole"])
            invariant["reviewResultRef"] = str(review_path)
            continue
        invariant["status"] = str(decision["targetStatus"])
        invariant["owner"] = str(review["reviewerRole"])
        invariant["reviewResultRef"] = str(review_path)
        if decision["targetStatus"] == "LOCKED":
            invariant["lockedBy"] = str(review["reviewerRole"])
            invariant["lockedAt"] = str(review["reviewedAt"])
    statuses = ("CANDIDATE", "ACTIVE", "LOCKED", "DEPRECATED")
    registry["metrics"] = {
        "invariants": len(registry.get("invariants", [])),
        **{status.lower(): sum(1 for item in registry.get("invariants", []) if item.get("status") == status) for status in statuses},
    }
    registry["source"]["lastReviewResultPath"] = str(review_path)
    registry["source"]["lastReviewResultHash"] = sha256_file(review_path)
    registry_errors = validate_schema_value(registry, "invariant-registry.schema.json")
    if registry_errors:
        print(json.dumps({"status": "FAIL", "errors": registry_errors}, ensure_ascii=False, indent=2))
        return 1
    save(args.out, registry)
    print(json.dumps({"status": "PASS", "out": str(args.out.resolve()), "metrics": registry["metrics"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
