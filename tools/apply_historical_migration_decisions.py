#!/usr/bin/env python3
"""Apply explicit product-owner adjudications to a historical migration queue."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from semantic_convergence import canonical_hash, load, save
from trust_kernel import now, validate_schema_value


def queue_content_hash(queue: dict[str, Any]) -> str:
    payload = {key: value for key, value in queue.items() if key not in {"queueId", "contentSha256", "createdAt"}}
    payload["items"] = [{key: value for key, value in item.items() if key != "createdAt"} for item in payload.get("items", [])]
    return canonical_hash(payload)


def validate_inputs(queue: dict[str, Any], decision: dict[str, Any]) -> None:
    errors = validate_schema_value(queue, "historical-migration-review-queue.schema.json")
    if errors:
        raise ValueError("invalid historical migration review queue: " + "; ".join(errors))
    if queue.get("contentSha256") != queue_content_hash(queue):
        raise ValueError("historical migration review queue content hash mismatch")
    errors = validate_schema_value(decision, "historical-migration-decision.schema.json")
    if errors:
        raise ValueError("invalid historical migration decision record: " + "; ".join(errors))
    if decision["queueId"] != queue["queueId"]:
        raise ValueError("decision queueId does not match the review queue")
    if decision["queueSha256"] != queue["contentSha256"]:
        raise ValueError("decision queueSha256 does not match the review queue content")

    item_by_id = {item["itemId"]: item for item in queue["items"]}
    seen: set[str] = set()
    for entry in decision["decisions"]:
        item_id = entry["itemId"]
        if item_id in seen:
            raise ValueError(f"duplicate decision for item: {item_id}")
        seen.add(item_id)
        item = item_by_id.get(item_id)
        if item is None:
            raise ValueError(f"decision references unknown item: {item_id}")
        action = entry["decision"]
        evidence_refs = entry.get("evidenceRefs", [])
        if not str(entry.get("reason", "")).strip() or not evidence_refs:
            raise ValueError(f"{item_id}: reason and evidenceRefs are required")
        if action == "APPROVE_MAPPING":
            if item["kind"] != "FR_AC_ASSOCIATION":
                raise ValueError(f"{item_id}: APPROVE_MAPPING is only valid for FR_AC_ASSOCIATION")
            approved = entry.get("approvedFrIds") or []
            known = set(item.get("knownFrIds", []))
            if not approved:
                raise ValueError(f"{item_id}: APPROVE_MAPPING requires non-empty approvedFrIds")
            unknown = sorted(set(approved) - known)
            if unknown:
                raise ValueError(f"{item_id}: approvedFrIds are not in the source plan: {', '.join(unknown)}")
        elif action == "REJECT_MAPPING":
            if item["kind"] != "FR_AC_ASSOCIATION":
                raise ValueError(f"{item_id}: REJECT_MAPPING is only valid for FR_AC_ASSOCIATION")
            if entry.get("approvedFrIds"):
                raise ValueError(f"{item_id}: REJECT_MAPPING must not contain approvedFrIds")
        elif action == "MARK_COMPLETED":
            if item["kind"] == "FR_AC_ASSOCIATION":
                raise ValueError(f"{item_id}: MARK_COMPLETED is only valid for migration tasks")
            if entry.get("approvedFrIds"):
                raise ValueError(f"{item_id}: MARK_COMPLETED must not contain approvedFrIds")
        elif action == "DEFER":
            if entry.get("approvedFrIds"):
                raise ValueError(f"{item_id}: DEFER must not contain approvedFrIds")
        else:
            raise ValueError(f"{item_id}: unsupported decision {action}")


def apply_decisions(queue: dict[str, Any], decision: dict[str, Any], queue_sha256: str) -> dict[str, Any]:
    entries = {entry["itemId"]: entry for entry in decision["decisions"]}
    item_results: list[dict[str, Any]] = []
    approved_mappings: list[dict[str, Any]] = []
    counts = {"total": len(queue["items"]), "pending": 0, "approvedMappings": 0, "rejectedMappings": 0, "completedTasks": 0, "deferredItems": 0}

    for item in queue["items"]:
        entry = entries.get(item["itemId"])
        if entry is None:
            outcome = "PENDING"
            action = "PENDING"
            reason = None
            evidence_refs: list[str] = []
            approved_fr_ids: list[str] = []
        else:
            action = entry["decision"]
            reason = entry["reason"]
            evidence_refs = entry["evidenceRefs"]
            approved_fr_ids = entry.get("approvedFrIds", [])
            if action == "APPROVE_MAPPING":
                outcome = "APPROVED_MAPPING"
                counts["approvedMappings"] += 1
                approved_mappings.append({
                    "caseId": item["caseId"],
                    "acId": item["subjectId"],
                    "frIds": approved_fr_ids,
                    "evidenceRefs": evidence_refs,
                    "decisionItemId": item["itemId"],
                })
            elif action == "REJECT_MAPPING":
                outcome = "REJECTED_MAPPING"
                counts["rejectedMappings"] += 1
            elif action == "MARK_COMPLETED":
                outcome = "COMPLETED"
                counts["completedTasks"] += 1
            else:
                outcome = "DEFERRED"
                counts["deferredItems"] += 1
        if outcome == "PENDING":
            counts["pending"] += 1
        item_results.append({
            "itemId": item["itemId"],
            "caseId": item["caseId"],
            "kind": item["kind"],
            "subjectId": item["subjectId"],
            "decision": action,
            "outcome": outcome,
            "reason": reason,
            "evidenceRefs": evidence_refs,
            "approvedFrIds": approved_fr_ids,
        })

    required_ac_items = sum(1 for item in queue["items"] if item["kind"] == "FR_AC_ASSOCIATION")
    required_task_items = len(queue["items"]) - required_ac_items
    ready = counts["approvedMappings"] == required_ac_items and counts["completedTasks"] == required_task_items
    if ready:
        status = "COMPLETE"
    elif counts["pending"] == counts["total"]:
        status = "PENDING"
    else:
        status = "PARTIAL"

    payload = {
        "schemaVersion": 1,
        "queueId": queue["queueId"],
        "queueSha256": queue_sha256,
        "reviewer": decision["reviewer"],
        "status": status,
        "itemResults": item_results,
        "approvedMappings": approved_mappings,
        "counts": counts,
        "migrationReadyForPackaging": ready,
        "m7ExitEvidenceEligible": False,
        "trainingEligible": False,
        "createdAt": now(),
    }
    digest = canonical_hash(payload)
    result = {"adjudicationId": "HMA-" + digest[:16], **payload, "contentSha256": digest}
    errors = validate_schema_value(result, "historical-migration-adjudication.schema.json")
    if errors:
        raise ValueError("invalid historical migration adjudication: " + "; ".join(errors))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--decisions", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    queue_path = args.queue.resolve()
    try:
        queue = load(queue_path)
        decisions = load(args.decisions.resolve())
        validate_inputs(queue, decisions)
        result = apply_decisions(queue, decisions, queue["contentSha256"])
    except Exception as exc:
        print(json.dumps({"status": "BLOCKED", "error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2
    save(args.out.resolve(), result)
    print(json.dumps({
        "status": result["status"],
        "adjudicationId": result["adjudicationId"],
        "counts": result["counts"],
        "migrationReadyForPackaging": result["migrationReadyForPackaging"],
        "out": str(args.out.resolve()),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
