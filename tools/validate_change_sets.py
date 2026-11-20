#!/usr/bin/env python3
"""Independently validate Change Set coverage, routing, budgets and repair readiness."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from semantic_convergence import load
from trust_kernel import now, validate_schema_value


def collect_blocking(reviews: list[Path]) -> tuple[set[str], list[str]]:
    ids: set[str] = set()
    errors: list[str] = []
    workflow_ids: set[str] = set()
    revisions: set[str] = set()
    for path in reviews:
        data = load(path.resolve())
        if data.get("workflowId"):
            workflow_ids.add(str(data["workflowId"]))
        if data.get("targetRevision"):
            revisions.add(str(data["targetRevision"]))
        for finding in data.get("findings") or []:
            if not isinstance(finding, dict):
                errors.append(f"{path}: finding is not an object")
                continue
            if str(finding.get("severity") or "BLOCKING").upper() != "BLOCKING":
                continue
            finding_id = str(finding.get("findingId") or "").strip()
            if not finding_id:
                errors.append(f"{path}: blocking finding has no findingId")
            elif finding_id in ids:
                errors.append(f"duplicate blocking findingId: {finding_id}")
            else:
                ids.add(finding_id)
    if len(workflow_ids) != 1:
        errors.append("finding sources do not share one workflowId")
    if len(revisions) != 1:
        errors.append("finding sources do not share one targetRevision")
    return ids, errors


def validate_batch(batch: dict[str, Any], policy: dict[str, Any], reviews: list[Path]) -> list[str]:
    errors: list[str] = []
    errors.extend("batch: " + item for item in validate_schema_value(batch, "change-set-batch.schema.json"))
    if errors:
        return errors
    blocking_ids, source_errors = collect_blocking(reviews)
    errors.extend(source_errors)
    if batch.get("workflowId") != (load(reviews[0].resolve()).get("workflowId") if reviews else None):
        errors.append("batch workflowId does not match finding sources")
    if batch.get("targetRevision") != (load(reviews[0].resolve()).get("targetRevision") if reviews else None):
        errors.append("batch targetRevision does not match finding sources")
    if batch.get("status") == "NO_CHANGES":
        if blocking_ids:
            errors.append("NO_CHANGES batch contains blocking findings")
        if batch.get("changeSets"):
            errors.append("NO_CHANGES batch must not contain Change Sets")
        return errors
    if batch.get("status") != "READY_FOR_REPAIR":
        errors.append(f"batch status {batch.get('status')} is not READY_FOR_REPAIR")
    if batch.get("findings"):
        errors.append("batch-level blocking findings remain")
    route_by_class = {item["classification"]: item for item in policy.get("routes", [])}
    covered: list[str] = []
    for change_set in batch.get("changeSets", []):
        change_set_id = change_set.get("changeSetId", "<missing>")
        if change_set.get("status") != "PLANNED":
            errors.append(f"{change_set_id}: status is not PLANNED")
        classification = change_set.get("classification")
        route = route_by_class.get(classification)
        if route is None:
            errors.append(f"{change_set_id}: classification has no policy route")
        else:
            for key in ("repairTrack", "businessRevisionRequired", "ownerRole"):
                expected = route.get(key)
                if change_set.get(key) != expected:
                    errors.append(f"{change_set_id}: {key} does not match policy")
            budget = change_set.get("budget") or {}
            if budget != route.get("budget"):
                errors.append(f"{change_set_id}: budget does not match policy")
            if len(change_set.get("affectedArtifacts", [])) > int(budget.get("maxAffectedArtifacts", 0)):
                errors.append(f"{change_set_id}: affected artifact budget exceeded")
            if len(change_set.get("findingIds", [])) > int(budget.get("maxFindings", 0)):
                errors.append(f"{change_set_id}: finding budget exceeded")
        covered.extend(change_set.get("findingIds", []))
    duplicates = sorted({item for item in covered if covered.count(item) > 1})
    if duplicates:
        errors.append("findings appear in multiple Change Sets: " + ", ".join(duplicates))
    covered_set = set(covered)
    missing = sorted(blocking_ids - covered_set)
    extra = sorted(covered_set - blocking_ids)
    if missing:
        errors.append("blocking findings not covered: " + ", ".join(missing))
    if extra:
        errors.append("Change Sets contain non-blocking or unknown findings: " + ", ".join(extra))
    metrics = batch.get("metrics") or {}
    if int(metrics.get("blockingFindings", -1)) != len(blocking_ids):
        errors.append("blockingFindings metric does not match finding sources")
    if int(metrics.get("coveredBlockingFindings", -1)) != len(covered_set):
        errors.append("coveredBlockingFindings metric does not match Change Sets")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--review", action="append", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    errors = validate_batch(load(args.batch.resolve()), load(args.policy.resolve()), args.review)
    report = {
        "schemaVersion": 1,
        "status": "PASS" if not errors else "BLOCKED",
        "errors": errors,
        "checkedAt": now(),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
