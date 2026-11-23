#!/usr/bin/env python3
"""Create a read-only collaboration view from a Project Episode."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from semantic_convergence import canonical_hash
from trust_kernel import validate_schema_value

REVIEW_REQUIRED = {"reviewRunId", "workflowId", "targetRevision", "reviewerRole", "verdict", "blockingCount", "findings"}
TERMINAL_FINDING = {"resolved", "accepted_risk", "closed_by_decision"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load(path: Path | None, default: Any = None) -> Any:
    if path is None or not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def save(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def add_risk(items: list[dict[str, Any]], risk_id: str, severity: str, title: str, detail: str, refs: list[str]) -> None:
    items.append({
        "riskId": risk_id,
        "severity": severity,
        "title": title,
        "detail": detail,
        "sourceRefs": sorted(set(refs)),
    })


def build(
    *,
    episode_path: Path,
    review_dir: Path,
    decision_dir: Path,
) -> dict[str, Any]:
    episode = load(episode_path, {}) or {}
    if not episode:
        raise ValueError("Project Episode is missing or unreadable")
    workflow_id = str(episode.get("workflowId") or "")
    revision = str(episode.get("revision") or "")
    requirement_id = str(episode.get("requirementId") or "")
    artifact_profile = str(episode.get("artifactProfile") or "")
    if not workflow_id or not revision or not requirement_id:
        raise ValueError("Project Episode lacks workflowId, requirementId or revision")

    errors: list[str] = []
    warnings: list[str] = list(episode.get("warnings") or [])
    evidence_gaps: list[str] = list(episode.get("evidenceGaps") or [])
    source_refs: list[dict[str, Any]] = [{
        "kind": "PROJECT_EPISODE",
        "path": str(episode_path.resolve()),
        "sha256": digest(episode_path),
    }]

    # Change digest.
    change_items: list[dict[str, Any]] = []
    for event in episode.get("revisionTimeline") or []:
        if event.get("eventType") not in {"REVISION", "REPAIR"}:
            continue
        changed = list((episode.get("repairs") or {}).get("changedArtifacts") or []) if event.get("eventType") == "REPAIR" else []
        change_items.append({
            "revision": str(event.get("revision") or revision),
            "nextRevision": event.get("nextRevision"),
            "status": str(event.get("status") or "UNKNOWN"),
            "changedArtifacts": sorted(set(changed)),
            "sourceRefs": list(event.get("sourceRefs") or []),
        })
    unique_artifacts = sorted({
        artifact
        for item in change_items
        for artifact in item["changedArtifacts"]
    })
    change_status = "AVAILABLE" if change_items else "UNAVAILABLE"
    change_summary = (
        f"{len(change_items)} revision/repair events, {len(unique_artifacts)} changed artifacts."
        if change_items else "No revision or repair changes are recorded in the Episode."
    )

    # Review digest.
    review_items: list[dict[str, Any]] = []
    if review_dir.is_dir():
        for path in sorted(review_dir.glob("*.json")):
            data = load(path, {}) or {}
            if not REVIEW_REQUIRED.issubset(data):
                continue
            if data.get("workflowId") != workflow_id:
                warnings.append(f"ignored review from another workflow: {path.name}")
                continue
            if data.get("targetRevision") != revision:
                warnings.append(f"ignored review for another revision: {path.name} ({data.get('targetRevision')})")
                continue
            review_items.append({
                "reviewId": str(data.get("reviewRunId")),
                "reviewerRole": str(data.get("reviewerRole")),
                "reviewType": str(data.get("reviewType") or "UNKNOWN"),
                "revision": str(data.get("targetRevision")),
                "verdict": str(data.get("verdict")),
                "blockingCount": int(data.get("blockingCount", 0) or 0),
                "findingCount": len(data.get("findings") or []),
                "sourcePath": str(path.resolve()),
            })
            source_refs.append({"kind": "REVIEW_RESULT", "path": str(path.resolve()), "sha256": digest(path)})
    accepted = sum(1 for item in review_items if item["verdict"] in {"ACCEPTED", "ACCEPTED_WITH_ACTIONS"})
    returned = sum(1 for item in review_items if item["verdict"] == "RETURNED")
    blocked = sum(1 for item in review_items if item["verdict"] in {"BLOCKED", "INCOMPLETE"})
    consumer = episode.get("consumerAcceptance") or {}

    # Decision digest.
    decision_items: list[dict[str, Any]] = []
    decision_refs = list((episode.get("humanAdjudication") or {}).get("decisionRefs") or [])
    for value in decision_refs:
        path = Path(str(value))
        data = load(path, {}) or {}
        if not data:
            evidence_gaps.append(f"decision source missing: {value}")
            continue
        decision_items.append({
            "decisionId": str(data.get("decisionId") or path.stem),
            "status": str(data.get("status") or "open"),
            "owner": str(data.get("owner") or "UNKNOWN"),
            "ambiguity": str(data.get("ambiguity") or "UNSPECIFIED"),
            "selectedOptionId": data.get("selectedOptionId"),
            "sourcePath": str(path.resolve()),
        })
        source_refs.append({"kind": "HUMAN_DECISION", "path": str(path.resolve()), "sha256": digest(path)})
    if not decision_items and decision_dir.is_dir():
        evidence_gaps.append("human decisions: NONE")

    # Risks.
    risks: list[dict[str, Any]] = []
    if episode.get("status") == "BLOCKED":
        add_risk(risks, "RISK-EPISODE-BLOCKED", "BLOCKING", "Episode is blocked", "The Project Episode cannot be used as a valid collaboration source.", [str(episode_path.resolve())])
    gates = episode.get("gates") or {}
    if int(gates.get("finalBlockingCount", 0) or 0) > 0 or gates.get("finalStatus") != "PASS":
        add_risk(risks, "RISK-FINAL-GATE", "BLOCKING", "Final gate is not clean", f"result={gates.get('finalResult')} blocking={gates.get('finalBlockingCount')} status={gates.get('finalStatus')}", [str(episode_path.resolve())])
    open_findings = int((episode.get("findings") or {}).get("metrics", {}).get("openBlocking", 0) or 0)
    if open_findings:
        add_risk(risks, "RISK-OPEN-FINDINGS", "BLOCKING", "Open blocking findings remain", f"openBlocking={open_findings}", [str(episode_path.resolve())])
    open_decisions = sum(1 for item in decision_items if item["status"] not in {"confirmed", "closed"})
    if open_decisions:
        add_risk(risks, "RISK-OPEN-DECISIONS", "BLOCKING", "Human decisions remain open", f"openDecisions={open_decisions}", [item["sourcePath"] for item in decision_items])
    if evidence_gaps:
        add_risk(risks, "RISK-EVIDENCE-GAPS", "NON_BLOCKING", "Evidence gaps remain", f"gaps={len(set(evidence_gaps))}", [str(episode_path.resolve())])
    if not review_items:
        add_risk(risks, "RISK-NO-REVIEWS", "NON_BLOCKING", "No matching independent reviews found", "The surface has no review records for the current workflow/revision.", [str(review_dir.resolve())])
    if int(consumer.get("realCount", 0) or 0) == 0:
        add_risk(risks, "RISK-NO-REAL-CONSUMER", "NON_BLOCKING", "No real consumer report", "Only fixture or no consumer evidence is available.", [str(episode_path.resolve())])
    if (episode.get("costs") or {}).get("metricsAvailability") != "COMPLETE":
        add_risk(risks, "RISK-COST-INCOMPLETE", "NON_BLOCKING", "Cost metrics are incomplete", f"availability={(episode.get('costs') or {}).get('metricsAvailability')}", [str(episode_path.resolve())])
    if (episode.get("trainingEligibility") or {}).get("eligible") is not False:
        errors.append("Episode trainingEligibility must remain false")

    # Next actions.
    actions: list[dict[str, Any]] = []
    def action(action_id: str, priority: str, owner: str, text: str, reason: str, refs: list[str]) -> None:
        actions.append({"actionId": action_id, "priority": priority, "owner": owner, "action": text, "reason": reason, "sourceRefs": sorted(set(refs))})
    if episode.get("status") == "BLOCKED":
        action("RESOLVE_EPISODE_BLOCKERS", "P0", "delivery-owner", "Resolve Episode blockers and rebuild the Episode.", "Episode status is BLOCKED.", [str(episode_path.resolve())])
    if gates.get("finalStatus") != "PASS":
        action("RESOLVE_FINAL_GATE_BLOCKERS", "P0", "delivery-owner", "Resolve final gate blockers and rerun the gate.", "Final gate is not PASS.", [str(episode_path.resolve())])
    if open_decisions:
        action("OBTAIN_HUMAN_DECISION", "P0", "product-owner", "Confirm the open Human Decision Card(s).", f"openDecisions={open_decisions}", [item["sourcePath"] for item in decision_items])
    if open_findings:
        action("RUN_BOUNDED_REPAIR", "P0", "repair-owner", "Run bounded repair for open blocking findings.", f"openBlocking={open_findings}", [str(episode_path.resolve())])
    if int(consumer.get("reportCount", 0) or 0) == 0:
        action("RUN_CONSUMER_ACCEPTANCE", "P1", "consumer-review-owner", "Run PM and Architect consumer acceptance and attach the reports.", "No consumer acceptance report is available.", [str(episode_path.resolve())])
    if not review_items:
        action("RUN_INDEPENDENT_REVIEW", "P1", "review-owner", "Run an independent review for the current revision.", "No matching review was found.", [str(review_dir.resolve())])
    if evidence_gaps:
        action("COLLECT_MISSING_EVIDENCE", "P1", "evidence-owner", "Collect or explicitly classify the missing evidence.", f"evidenceGaps={len(set(evidence_gaps))}", [str(episode_path.resolve())])
    if (episode.get("costs") or {}).get("metricsAvailability") != "COMPLETE":
        action("IMPROVE_COST_TELEMETRY", "P2", "runtime-owner", "Add missing timing and context telemetry.", "Cost metrics are PARTIAL or UNAVAILABLE.", [str(episode_path.resolve())])
    if not actions:
        action("REVIEW_DELIVERY_PACKAGE", "P1", "human-reviewer", "Review the delivery package and decide the next human action.", "No deterministic blocking action remains.", [str(episode_path.resolve())])

    blocking_count = sum(1 for item in risks if item["severity"] == "BLOCKING")
    nonblocking_count = sum(1 for item in risks if item["severity"] == "NON_BLOCKING")
    info_count = sum(1 for item in risks if item["severity"] == "INFO")
    remediation_actions = [item for item in actions if item["actionId"] != "REVIEW_DELIVERY_PACKAGE"]
    if episode.get("status") == "BLOCKED" or blocking_count:
        surface_status = "BLOCKED" if episode.get("status") == "BLOCKED" else "ACTION_REQUIRED"
        next_status = "BLOCKED" if episode.get("status") == "BLOCKED" else "ACTION_REQUIRED"
        risk_status = "BLOCKED" if episode.get("status") == "BLOCKED" else "ATTENTION"
    elif remediation_actions:
        surface_status = "ACTION_REQUIRED"
        next_status = "ACTION_REQUIRED"
        risk_status = "ATTENTION" if risks else "CLEAR"
    else:
        surface_status = "READY"
        next_status = "CLEAR"
        risk_status = "CLEAR"

    layers = {layer: len((episode.get("evidenceLayers") or {}).get(layer, [])) for layer in ["SOURCE_FACT", "MEASURED", "DERIVED", "REFERENCE", "INFERENCE"]}
    payload_without_id = {
        "schemaVersion": 1,
        "workflowId": workflow_id,
        "requirementId": requirement_id,
        "artifactProfile": artifact_profile,
        "revision": revision,
        "status": surface_status,
        "objective": str(episode.get("objective") or "UNAVAILABLE"),
        "authority": {"readOnly": True, "factSource": "PROJECT_EPISODE", "gateAuthority": "UNCHANGED", "trainingAuthority": "NONE"},
        "changeDigest": {"status": change_status, "summary": change_summary, "items": change_items},
        "reviewDigest": {
            "status": "AVAILABLE" if review_items else "UNAVAILABLE",
            "totalReviews": len(review_items), "accepted": accepted, "returned": returned, "blocked": blocked,
            "items": review_items,
            "consumer": {
                "reportCount": int(consumer.get("reportCount", 0) or 0),
                "realCount": int(consumer.get("realCount", 0) or 0),
                "fixtureCount": int(consumer.get("fixtureCount", 0) or 0),
                "statuses": list(consumer.get("statuses") or []),
            },
        },
        "decisionDigest": {
            "status": "AVAILABLE" if decision_items else "UNAVAILABLE",
            "total": len(decision_items),
            "open": open_decisions,
            "confirmed": sum(1 for item in decision_items if item["status"] in {"confirmed", "closed"}),
            "items": decision_items,
        },
        "riskDigest": {"status": risk_status, "blocking": blocking_count, "nonBlocking": nonblocking_count, "info": info_count, "items": risks},
        "evidenceDigest": {
            "status": "BLOCKED" if episode.get("status") == "BLOCKED" else ("PARTIAL" if evidence_gaps else "COMPLETE"),
            "sourceCount": len(source_refs),
            "layers": layers,
            "provenance": [{"kind": item["kind"], "layer": item["layer"], "path": item["path"], "sha256": item["sha256"]} for item in (episode.get("provenance") or [])],
            "gaps": sorted(set(evidence_gaps)),
            "warnings": sorted(set(warnings)),
        },
        "nextAction": {"status": next_status, "actions": actions},
        "sourceRefs": sorted(source_refs, key=lambda item: (item["kind"], item["path"])),
        "evidenceGaps": sorted(set(evidence_gaps)),
        "warnings": sorted(set(warnings)),
        "metrics": {"changes": len(change_items), "reviews": len(review_items), "decisions": len(decision_items), "risks": len(risks), "sources": len(source_refs), "nextActions": len(actions)},
        "createdAt": now(),
    }
    payload = {"surfaceId": "CS-" + canonical_hash(payload_without_id)[:16], **payload_without_id}
    issues = validate_schema_value(payload, "collaboration-surface.schema.json")
    errors.extend(f"schema: {issue}" for issue in issues)
    if errors:
        raise ValueError("; ".join(errors))
    return payload


def render_markdown(surface: dict[str, Any]) -> str:
    lines = [
        f"# Collaboration Surface — {surface['workflowId']}",
        "",
        f"- Requirement: `{surface['requirementId']}`",
        f"- Artifact profile: `{surface['artifactProfile']}`",
        f"- Revision: `{surface['revision']}`",
        f"- Status: `{surface['status']}`",
        f"- Objective: {surface['objective']}",
        "",
        "> Read-only derived view. Final Gate, release eligibility and training approval remain unchanged.",
        "",
        "## Change Digest",
        "",
        f"**{surface['changeDigest']['status']}** — {surface['changeDigest']['summary']}",
        "",
    ]
    if surface["changeDigest"]["items"]:
        for item in surface["changeDigest"]["items"]:
            next_revision = f" → {item['nextRevision']}" if item.get("nextRevision") else ""
            artifacts = ", ".join(item["changedArtifacts"]) or "no artifact list"
            lines.append(f"- `{item['revision']}{next_revision}`: {item['status']} — {artifacts}")
    else:
        lines.append("- No change event recorded.")
    lines += ["", "## Review Digest", ""]
    review = surface["reviewDigest"]
    lines.append(f"**{review['status']}** — {review['totalReviews']} reviews / {review['accepted']} accepted / {review['returned']} returned / {review['blocked']} blocked.")
    for item in review["items"]:
        lines.append(f"- `{item['reviewerRole']}` at `{item['revision']}`: {item['verdict']} (blocking={item['blockingCount']}, findings={item['findingCount']})")
    consumer = review["consumer"]
    lines.append(f"- Consumer reports: {consumer['reportCount']} total / {consumer['realCount']} real / {consumer['fixtureCount']} fixture; statuses={', '.join(consumer['statuses']) or 'none'}.")
    lines += ["", "## Decision Digest", ""]
    decision = surface["decisionDigest"]
    lines.append(f"**{decision['status']}** — {decision['total']} decisions / {decision['open']} open / {decision['confirmed']} confirmed.")
    for item in decision["items"]:
        selected = item.get("selectedOptionId") or "not selected"
        lines.append(f"- `{item['decisionId']}`: {item['status']}, owner={item['owner']}, selected={selected}")
    lines += ["", "## Risk Digest", ""]
    risk = surface["riskDigest"]
    lines.append(f"**{risk['status']}** — blocking={risk['blocking']}, nonBlocking={risk['nonBlocking']}, info={risk['info']}.")
    for item in risk["items"]:
        lines.append(f"- **{item['severity']}** `{item['riskId']}`: {item['title']} — {item['detail']}")
    lines += ["", "## Evidence Digest", ""]
    evidence = surface["evidenceDigest"]
    layers = ", ".join(f"{key}={value}" for key, value in evidence["layers"].items())
    lines.append(f"**{evidence['status']}** — sources={evidence['sourceCount']}; {layers}.")
    if evidence["gaps"]:
        lines.append("")
        lines.append("Evidence gaps:")
        lines.extend(f"- {gap}" for gap in evidence["gaps"])
    if evidence["warnings"]:
        lines.append("")
        lines.append("Warnings:")
        lines.extend(f"- {warning}" for warning in evidence["warnings"])
    lines += ["", "## Next Action", ""]
    next_action = surface["nextAction"]
    lines.append(f"**{next_action['status']}**")
    for item in next_action["actions"]:
        lines.append(f"- **{item['priority']}** `{item['actionId']}` → {item['owner']}: {item['action']} ({item['reason']})")
    lines += ["", "## Authority", ""]
    lines.append("This surface is read-only. It does not approve release, modify facts, or grant training eligibility.")
    lines.append("")
    return "\n".join(lines)
