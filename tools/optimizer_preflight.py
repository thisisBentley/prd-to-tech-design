#!/usr/bin/env python3
"""Check whether the bounded optimizer may prepare a human-reviewed Change Set."""
from __future__ import annotations
import json
from pathlib import Path
from semantic_convergence import canonical_hash
from trust_kernel import validate_schema_value
from datetime import datetime, timezone

def now() -> str:
    return datetime.now(timezone.utc).isoformat()

def load(path: Path | None, default=None):
    if path is None or not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8"))

def save(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

def build(episode_path: Path, observer_path: Path, decision_dir: Path) -> dict:
    episode = load(episode_path, {}) or {}
    observer = load(observer_path, {}) or {}
    prerequisites = []
    gaps = []
    workflow_id = str(episode.get("workflowId") or observer.get("workflowId") or "UNKNOWN")
    requirement_id = str(episode.get("requirementId") or "UNKNOWN")
    revision = str(episode.get("revision") or observer.get("revision") or "r1")

    def add(pid, status, observed, expected, refs):
        prerequisites.append({"prerequisiteId": pid, "status": status, "observed": observed, "expected": expected, "sourceRefs": refs})

    consumer = episode.get("consumerAcceptance") or {}
    repairs = episode.get("repairs") or {}
    gates = episode.get("gates") or {}
    real_count = int(consumer.get("realCount", 0) or 0)
    repair_rounds = int(repairs.get("rounds", 0) or 0)
    real_loop = episode.get("status") == "COMPLETE" and real_count >= 1 and repair_rounds >= 1 and gates.get("finalStatus") == "PASS"
    add("REAL_CLOSED_LOOP", "PASS" if real_loop else "FAIL", f"episode={episode.get('status')} realConsumers={real_count} repairRounds={repair_rounds} finalStatus={gates.get('finalStatus')}", "COMPLETE + at least one REAL consumer + at least one Repair round + Final Gate PASS", [str(episode_path)])
    if not real_loop:
        gaps.append("REAL_CLOSED_LOOP:REQUIRED")

    observer_status = observer.get("status")
    observer_gaps = observer.get("evidenceGaps") or []
    observer_ok = observer_status == "READY" and not observer_gaps
    add("OBSERVER_COMPLETE", "PASS" if observer_ok else "FAIL", f"status={observer_status} gaps={len(observer_gaps)}", "Observer READY with no evidence gaps", [str(observer_path)])
    if not observer_ok:
        gaps.append("OBSERVER_COMPLETE:REQUIRED")

    decisions = []
    if decision_dir.is_dir():
        for path in sorted(decision_dir.glob("*.json")):
            data = load(path, {}) or {}
            decisions.append(data)
    confirmed = sum(1 for item in decisions if item.get("status") in {"confirmed", "closed"})
    human_ok = bool(decisions) and confirmed == len(decisions)
    add("HUMAN_ADJUDICATION", "PASS" if human_ok else "MISSING", f"decisions={len(decisions)} confirmed={confirmed}", "at least one confirmed/closed human decision and no open decision", [str(decision_dir)])
    if not human_ok:
        gaps.append("HUMAN_ADJUDICATION:REQUIRED")

    recommendations = [item for item in observer.get("recommendations") or [] if item.get("recommendationId") != "NO_ACTION"]
    recommendation_ok = bool(recommendations)
    add("OBSERVER_RECOMMENDATION", "PASS" if recommendation_ok else "MISSING", f"recommendations={len(recommendations)}", "at least one actionable Observer recommendation", [str(observer_path)])
    if not recommendation_ok:
        gaps.append("OBSERVER_RECOMMENDATION:REQUIRED")

    revision_ok = episode.get("revision") == observer.get("revision")
    add("REVISION_BINDING", "PASS" if revision_ok else "FAIL", f"episode={episode.get('revision')} observer={observer.get('revision')}", "Episode and Observer target the same revision", [str(episode_path), str(observer_path)])
    if not revision_ok:
        gaps.append("REVISION_BINDING:REQUIRED")

    proposals = []
    if not gaps:
        for item in recommendations:
            proposal_seed = {"workflowId": workflow_id, "revision": revision, "recommendationId": item.get("recommendationId"), "action": item.get("action")}
            proposals.append({
                "proposalId": "OP-" + canonical_hash(proposal_seed)[:16],
                "recommendationId": str(item.get("recommendationId")),
                "priority": str(item.get("priority")),
                "owner": str(item.get("owner")),
                "action": str(item.get("action")),
                "sourceRefs": list(item.get("sourceRefs") or []) + [str(observer_path.resolve())],
                "applyStatus": "REQUIRES_HUMAN_CHANGE_SET",
            })
    status = "READY_FOR_HUMAN_CHANGE_SET" if not gaps else "BLOCKED"
    payload = {
        "schemaVersion": 1,
        "preflightId": "OP-" + canonical_hash({"workflowId": workflow_id, "requirementId": requirement_id, "revision": revision, "prerequisites": prerequisites})[:16],
        "workflowId": workflow_id,
        "requirementId": requirement_id,
        "revision": revision,
        "status": status,
        "authority": {"readOnly": True, "mayApply": False, "releaseEligible": False, "trainingEligible": False, "resultAuthority": "NONE"},
        "prerequisites": prerequisites,
        "proposals": proposals,
        "evidenceGaps": sorted(set(gaps)),
        "warnings": ["Optimizer v0 only prepares human-reviewed Change Set proposals; it never applies changes."],
        "createdAt": now(),
    }
    errors = validate_schema_value(payload, "optimizer-preflight.schema.json")
    if errors:
        raise ValueError("; ".join(errors))
    return payload
