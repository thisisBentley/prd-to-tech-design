#!/usr/bin/env python3
"""Build a human adjudication queue from historical migration plans."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from semantic_convergence import canonical_hash, load, safe_id, save, sha256_file
from trust_kernel import now, validate_schema_value


def plan_content_hash(plan: dict[str, Any]) -> str:
    payload = {key: value for key, value in plan.items() if key not in {"planId", "contentSha256", "createdAt"}}
    return canonical_hash(payload)


def validate_plan(plan: dict[str, Any], path: Path) -> None:
    errors = validate_schema_value(plan, "historical-migration-plan.schema.json")
    if errors:
        raise ValueError(f"{path}: invalid migration plan: {'; '.join(errors)}")
    actual = plan_content_hash(plan)
    if plan.get("contentSha256") != actual:
        raise ValueError(f"{path}: migration plan content hash mismatch")


def item_id(case_id: str, kind: str, subject_id: str) -> str:
    digest = canonical_hash({"caseId": case_id, "kind": kind, "subjectId": subject_id})[:16].upper()
    return f"HMQ-{digest}-{safe_id(subject_id)}"


def queue_content_hash(queue: dict[str, Any]) -> str:
    payload = {key: value for key, value in queue.items() if key not in {"queueId", "contentSha256", "createdAt"}}
    payload["items"] = [{key: value for key, value in item.items() if key != "createdAt"} for item in payload.get("items", [])]
    return canonical_hash(payload)


def build_items(plan: dict[str, Any], plan_path: Path, plan_sha256: str) -> list[dict[str, Any]]:
    case_id = str(plan["caseId"])
    known_fr_ids = sorted(item["frId"] for item in plan.get("frObjects", []))
    links_by_ac: dict[str, list[dict[str, Any]]] = {}
    for link in plan.get("candidateLinks", []):
        links_by_ac.setdefault(link["acId"], []).append(link)

    items: list[dict[str, Any]] = []
    for ac in plan.get("acObjects", []):
        ac_id = str(ac["acId"])
        candidates = links_by_ac.get(ac_id, [])
        evidence_refs = list(ac.get("evidence", []))
        for link in candidates:
            evidence_refs.extend(link.get("evidence", []))
        evidence_refs.append(f"plan:{plan['planId']}")
        items.append({
            "itemId": item_id(case_id, "FR_AC_ASSOCIATION", ac_id),
            "caseId": case_id,
            "kind": "FR_AC_ASSOCIATION",
            "subjectId": ac_id,
            "status": "AWAITING_DECISION",
            "requiredAuthority": "PRODUCT_OWNER",
            "question": f"Decide the authoritative FR mapping for {ac_id}: {ac['text']}",
            "evidenceState": "CANDIDATE_AVAILABLE" if candidates else "NO_CANDIDATE",
            "knownFrIds": known_fr_ids,
            "candidateLinks": candidates,
            "evidenceRefs": list(dict.fromkeys(evidence_refs)),
            "sourcePlanId": plan["planId"],
            "sourcePlanPath": str(plan_path.resolve()),
            "sourcePlanSha256": plan_sha256,
            "createdAt": now(),
        })

    for topic in plan.get("prd", {}).get("missingTopics", []):
        items.append({
            "itemId": item_id(case_id, "REQUIRED_SECTION", topic),
            "caseId": case_id,
            "kind": "REQUIRED_SECTION",
            "subjectId": topic,
            "status": "AWAITING_DECISION",
            "requiredAuthority": "PRODUCT_OWNER",
            "question": f"Provide or explicitly defer the missing PRD section: {topic}.",
            "evidenceState": "ACTION_REQUIRED",
            "knownFrIds": known_fr_ids,
            "candidateLinks": [],
            "evidenceRefs": [f"plan:{plan['planId']}", f"missing-topic:{topic}"],
            "sourcePlanId": plan["planId"],
            "sourcePlanPath": str(plan_path.resolve()),
            "sourcePlanSha256": plan_sha256,
            "createdAt": now(),
        })

    prototype = plan.get("prototypeBindings", {})
    if int(prototype.get("legacyCount", 0)) > 0:
        markers = prototype.get("unmappedLegacyMarkers", [])
        items.append({
            "itemId": item_id(case_id, "PROTOTYPE_BINDING", "legacy-bindings"),
            "caseId": case_id,
            "kind": "PROTOTYPE_BINDING",
            "subjectId": "legacy-bindings",
            "status": "AWAITING_DECISION",
            "requiredAuthority": "PRODUCT_OWNER",
            "question": "Confirm the legacy Prototype binding migration evidence and resulting FR/AC coverage.",
            "evidenceState": "ACTION_REQUIRED",
            "knownFrIds": known_fr_ids,
            "candidateLinks": [],
            "evidenceRefs": [f"plan:{plan['planId']}", *[f"legacy-marker:{marker}" for marker in markers[:20]]],
            "sourcePlanId": plan["planId"],
            "sourcePlanPath": str(plan_path.resolve()),
            "sourcePlanSha256": plan_sha256,
            "createdAt": now(),
        })

    overview = plan.get("overviewMigration", {})
    if overview.get("sourceRefPresent") and not overview.get("sourceHashPresent"):
        items.append({
            "itemId": item_id(case_id, "OVERVIEW_SOURCE_HASH", "source-prd-sha256"),
            "caseId": case_id,
            "kind": "OVERVIEW_SOURCE_HASH",
            "subjectId": "source-prd-sha256",
            "status": "AWAITING_DECISION",
            "requiredAuthority": "PRODUCT_OWNER",
            "question": "Attach the frozen source-PRD SHA-256 metadata to the migrated Overview.",
            "evidenceState": "ACTION_REQUIRED",
            "knownFrIds": known_fr_ids,
            "candidateLinks": [],
            "evidenceRefs": [f"plan:{plan['planId']}", f"prd-sha256:{plan['prd']['sha256']}"],
            "sourcePlanId": plan["planId"],
            "sourcePlanPath": str(plan_path.resolve()),
            "sourcePlanSha256": plan_sha256,
            "createdAt": now(),
        })
    return items


def build_queue(plans_dir: Path) -> dict[str, Any]:
    plan_paths = sorted(path for path in plans_dir.glob("*.migration-plan.json") if path.is_file())
    if not plan_paths:
        raise ValueError(f"no migration plans found in {plans_dir}")

    all_items: list[dict[str, Any]] = []
    migration_plans: list[dict[str, Any]] = []
    cases: list[dict[str, Any]] = []
    for plan_path in plan_paths:
        plan = load(plan_path)
        validate_plan(plan, plan_path)
        plan_sha256 = sha256_file(plan_path)
        case_items = build_items(plan, plan_path, plan_sha256)
        all_items.extend(case_items)
        migration_plans.append({
            "caseId": plan["caseId"],
            "planId": plan["planId"],
            "path": str(plan_path.resolve()),
            "sha256": plan_sha256,
        })
        ac_items = [item for item in case_items if item["kind"] == "FR_AC_ASSOCIATION"]
        cases.append({
            "caseId": plan["caseId"],
            "planId": plan["planId"],
            "planSha256": plan_sha256,
            "status": plan["status"],
            "itemCount": len(case_items),
            "acItemCount": len(ac_items),
            "taskItemCount": len(case_items) - len(ac_items),
        })

    ac_items = [item for item in all_items if item["kind"] == "FR_AC_ASSOCIATION"]
    payload = {
        "schemaVersion": 1,
        "migrationPlans": migration_plans,
        "cases": cases,
        "summary": {
            "itemCount": len(all_items),
            "acItemCount": len(ac_items),
            "taskItemCount": len(all_items) - len(ac_items),
            "candidateBackedAcCount": sum(1 for item in ac_items if item["evidenceState"] == "CANDIDATE_AVAILABLE"),
            "unresolvedAcCount": sum(1 for item in ac_items if item["evidenceState"] == "NO_CANDIDATE"),
        },
        "items": all_items,
        "m7ExitEvidenceEligible": False,
        "trainingEligible": False,
        "createdAt": now(),
    }
    digest = queue_content_hash(payload)
    queue = {"queueId": "HMQ-QUEUE-" + digest[:16], **payload, "contentSha256": digest}
    errors = validate_schema_value(queue, "historical-migration-review-queue.schema.json")
    if errors:
        raise ValueError("invalid historical migration review queue: " + "; ".join(errors))
    return queue


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plans-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        queue = build_queue(args.plans_dir.resolve())
    except Exception as exc:
        print(json.dumps({"status": "BLOCKED", "error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2
    save(args.out.resolve(), queue)
    print(json.dumps({
        "status": "QUEUED",
        "queueId": queue["queueId"],
        "summary": queue["summary"],
        "out": str(args.out.resolve()),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
