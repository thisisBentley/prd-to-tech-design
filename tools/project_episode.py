#!/usr/bin/env python3
"""Assemble one deterministic Project Episode from existing delivery evidence."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from semantic_convergence import canonical_hash
from trust_kernel import validate_schema_value


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


def source_ref(kind: str, layer: str, path: Path | None, revision: str | None = None) -> dict[str, Any] | None:
    if path is None or not path.is_file():
        return None
    return {"kind": kind, "layer": layer, "path": str(path.resolve()), "sha256": digest(path), "revision": revision}


def build(
    *,
    run_root: Path,
    workflow_id: str,
    requirement_id: str,
    artifact_profile: str,
    revision: str,
    procedure_path: Path,
    handoff_path: Path,
    finding_ledger_path: Path,
    repair_cycle_path: Path,
    cost_ledger_path: Path,
    final_gate_path: Path,
    consumer_report_paths: list[Path],
    decision_dir: Path,
) -> dict[str, Any]:
    errors: list[str] = []
    evidence_gaps: list[str] = []
    warnings: list[str] = []
    source_refs: list[dict[str, Any]] = []

    procedure = load(procedure_path, {}) or {}
    handoff = load(handoff_path, {}) or {}
    findings = load(finding_ledger_path, {}) or {}
    repair_cycle = load(repair_cycle_path, {}) or {}
    costs = load(cost_ledger_path, {}) or {}
    final_gate = load(final_gate_path, {}) or {}

    core = [
        ("DELIVERY_OPERATING_PROCEDURE", "DERIVED", procedure_path, procedure, procedure.get("revision")),
        ("DELIVERY_HANDOFF", "SOURCE_FACT", handoff_path, handoff, handoff.get("revision")),
        ("COST_REVISION_LEDGER", "MEASURED", cost_ledger_path, costs, costs.get("finalRevision")),
        ("FINAL_GATE", "MEASURED", final_gate_path, final_gate, final_gate.get("revision")),
    ]
    for kind, layer, path, data, source_revision in core:
        if not data or not path.is_file():
            errors.append(f"core source missing: {kind}")
            continue
        source_refs.append(source_ref(kind, layer, path, source_revision))
        if data.get("workflowId") not in {None, workflow_id}:
            errors.append(f"{kind} workflowId mismatch")
    if handoff and handoff.get("workflowId") != workflow_id:
        errors.append("DELIVERY_HANDOFF workflowId mismatch")
    if handoff and handoff.get("revision") != revision:
        errors.append("DELIVERY_HANDOFF revision does not match final episode revision")
    if costs and costs.get("workflowId") != workflow_id:
        errors.append("COST_REVISION_LEDGER workflowId mismatch")
    if costs and costs.get("finalRevision") != revision:
        errors.append("COST_REVISION_LEDGER finalRevision does not match episode revision")
    if procedure and procedure.get("workflowId") != workflow_id:
        errors.append("DELIVERY_OPERATING_PROCEDURE workflowId mismatch")
    if procedure and procedure.get("revision") != revision:
        warnings.append(f"Delivery Operating Procedure was created for {procedure.get('revision')} and remains the initial execution contract for {revision}.")
    if final_gate and final_gate.get("revision") not in {None, revision}:
        errors.append("FINAL_GATE revision does not match episode revision")

    optional_sources = [
        ("FINDING_LEDGER", "MEASURED", finding_ledger_path, findings, findings.get("currentRevision")),
        ("REPAIR_CYCLE", "MEASURED", repair_cycle_path, repair_cycle, repair_cycle.get("finalRevision")),
    ]
    for kind, layer, path, data, source_revision in optional_sources:
        if data and path.is_file():
            ref = source_ref(kind, layer, path, source_revision)
            if ref:
                source_refs.append(ref)
            if data.get("workflowId") not in {None, workflow_id}:
                errors.append(f"{kind} workflowId mismatch")
            if kind == "FINDING_LEDGER" and data.get("currentRevision") != revision:
                errors.append("FINDING_LEDGER currentRevision does not match episode revision")
            if kind == "REPAIR_CYCLE" and data.get("finalRevision") != revision:
                errors.append("REPAIR_CYCLE finalRevision does not match episode revision")
        else:
            evidence_gaps.append(f"optional source missing: {kind}")

    consumer_reports: list[dict[str, Any]] = []
    for path in consumer_report_paths:
        report = load(path, {}) or {}
        if not report:
            evidence_gaps.append(f"consumer report missing: {path}")
            continue
        if report.get("workflowId") != workflow_id:
            errors.append(f"CONSUMER_REPORT workflowId mismatch: {path.name}")
            continue
        if report.get("targetRevision") != revision:
            errors.append(f"CONSUMER_REPORT targetRevision mismatch: {path.name}")
            continue
        ref = source_ref("CONSUMER_ACCEPTANCE_REPORT", "MEASURED", path, report.get("targetRevision"))
        if ref:
            source_refs.append(ref)
        consumer_reports.append({**report, "__sourcePath": str(path.resolve())})
    if not consumer_reports:
        evidence_gaps.append("consumer acceptance reports: NONE")

    decision_refs: list[str] = []
    open_decisions = 0
    if decision_dir.is_dir():
        for path in sorted(decision_dir.glob("*.json")):
            data = load(path, {}) or {}
            decision_refs.append(str(path.resolve()))
            if data.get("status") not in {"confirmed", "closed"}:
                open_decisions += 1
            ref = source_ref("HUMAN_DECISION", "SOURCE_FACT", path, None)
            if ref:
                source_refs.append(ref)
    if decision_refs and open_decisions:
        adjudication_status = "PARTIAL"
    elif decision_refs:
        adjudication_status = "RECORDED"
    else:
        adjudication_status = "NOT_RECORDED"

    timeline: list[dict[str, Any]] = []
    for item in costs.get("revisions") or []:
        statuses = item.get("auditStatuses") or []
        timeline.append({
            "eventType": "REVISION",
            "revision": str(item.get("revision") or revision),
            "status": ",".join(str(value) for value in statuses) if statuses else "UNKNOWN",
            "sourceRefs": list(item.get("sourceRefs") or []),
        })
    for stage in costs.get("stages") or []:
        if stage.get("stageType") == "REPAIR":
            timeline.append({
                "eventType": "REPAIR",
                "revision": str(stage.get("revision") or revision),
                "nextRevision": stage.get("nextRevision"),
                "status": str(stage.get("status") or "UNKNOWN"),
                "sourceRefs": list(stage.get("sourceRefs") or []),
            })
    for report in consumer_reports:
        timeline.append({
            "eventType": "CONSUMER_ACCEPTANCE",
            "revision": str(report.get("targetRevision") or revision),
            "status": str(report.get("status") or "UNKNOWN"),
            "sourceRefs": [str(report.get("__sourcePath"))] if report.get("__sourcePath") else [],
        })
    final_result = str(final_gate.get("result") or final_gate.get("status") or "UNKNOWN")
    timeline.append({
        "eventType": "FINAL_GATE",
        "revision": revision,
        "status": final_result,
        "sourceRefs": [str(final_gate_path.resolve())] if final_gate_path.is_file() else [],
    })

    finding_entries = findings.get("entries") or []
    repair_rounds = int((repair_cycle.get("rounds") and len(repair_cycle.get("rounds"))) or 0)
    changed_artifacts: set[str] = set()
    for round_record in repair_cycle.get("rounds") or []:
        report_path = round_record.get("repairReport")
        if report_path:
            report = load(Path(str(report_path)), {}) or {}
            changed_artifacts.update(str(item) for item in report.get("changedArtifacts") or [])
    evidence_layers = {layer: [] for layer in ["SOURCE_FACT", "MEASURED", "DERIVED", "REFERENCE", "INFERENCE"]}
    for ref in source_refs:
        evidence_layers[ref["layer"]].append(ref["path"])
    for layer in evidence_layers:
        evidence_layers[layer] = sorted(set(evidence_layers[layer]))

    objective = str(
        (procedure.get("goalContract") or {}).get("objectiveText")
        or handoff.get("objective")
        or "UNAVAILABLE"
    )
    human_review_required = sum(1 for item in consumer_reports if item.get("humanConsumerReviewRequired") is True)
    status = "BLOCKED" if errors else ("PARTIAL" if evidence_gaps or adjudication_status != "RECORDED" else "COMPLETE")
    training_reasons = ["D14_EPISODE_TRAINING_DISABLED"]
    if adjudication_status != "RECORDED":
        training_reasons.append("HUMAN_ADJUDICATION_NOT_RECORDED")
    if any(item.get("caseClassification") == "REAL" for item in consumer_reports) is False:
        training_reasons.append("REAL_CONSUMER_EVIDENCE_NOT_PRESENT")
    payload_without_id = {
        "schemaVersion": 1,
        "workflowId": workflow_id,
        "requirementId": requirement_id,
        "artifactProfile": artifact_profile,
        "revision": revision,
        "status": status,
        "objective": objective,
        "revisionTimeline": timeline,
        "findings": {
            "status": "AVAILABLE" if findings else "UNAVAILABLE",
            "metrics": findings.get("metrics") or {},
            "openRootCauseIds": sorted({str(item.get("rootCauseId")) for item in finding_entries if item.get("status") not in {"resolved", "accepted_risk", "closed_by_decision"}}),
            "findingIds": sorted(str(item.get("findingId")) for item in finding_entries),
        },
        "repairs": {
            "status": "AVAILABLE" if repair_cycle else "UNAVAILABLE",
            "rounds": repair_rounds,
            "cycleStatus": repair_cycle.get("status") if repair_cycle else None,
            "changedArtifacts": sorted(changed_artifacts),
        },
        "costs": {
            "status": "AVAILABLE" if costs else "UNAVAILABLE",
            "metricsAvailability": costs.get("metricsAvailability", "UNAVAILABLE"),
            "metrics": costs.get("metrics") or {},
        },
        "consumerAcceptance": {
            "reportCount": len(consumer_reports),
            "realCount": sum(1 for item in consumer_reports if item.get("caseClassification") == "REAL"),
            "fixtureCount": sum(1 for item in consumer_reports if item.get("caseClassification") == "FIXTURE"),
            "statuses": [str(item.get("status") or "UNKNOWN") for item in consumer_reports],
            "humanReviewRequiredCount": human_review_required,
            "reportIds": [str(item.get("reportId") or "UNKNOWN") for item in consumer_reports],
        },
        "gates": {
            "finalResult": final_result,
            "finalBlockingCount": int(final_gate.get("blockingCount", 0) or 0),
            "finalStatus": "PASS" if final_result in {"PASS", "PASS_WITH_NONBLOCKING"} and int(final_gate.get("blockingCount", 0) or 0) == 0 else "BLOCKED_OR_INCOMPLETE",
        },
        "evidenceLayers": evidence_layers,
        "humanAdjudication": {
            "status": adjudication_status,
            "decisionRefs": decision_refs,
            "openDecisionCount": open_decisions,
        },
        "trainingEligibility": {
            "eligible": False,
            "status": "BLOCKED",
            "reasons": training_reasons,
        },
        "provenance": source_refs,
        "evidenceGaps": sorted(set(evidence_gaps)),
        "warnings": sorted(set(warnings)),
        "metrics": {
            "sourceCount": len(source_refs),
            "timelineEvents": len(timeline),
            "findingsTotal": len(finding_entries),
            "openBlockingFindings": int((findings.get("metrics") or {}).get("openBlocking", 0) or 0),
            "repairRounds": repair_rounds,
            "consumerReports": len(consumer_reports),
            "revisionCount": len(costs.get("revisions") or []),
            "evidenceGaps": len(set(evidence_gaps)),
            "warnings": len(set(warnings)),
        },
        "createdAt": now(),
    }
    payload = {"episodeId": "EP-" + canonical_hash(payload_without_id)[:16], **payload_without_id}
    issues = validate_schema_value(payload, "project-episode.schema.json")
    errors.extend(f"schema: {issue}" for issue in issues)
    if errors:
        payload["status"] = "BLOCKED"
        payload["warnings"] = sorted(set(payload["warnings"] + errors))
        raise ValueError("; ".join(errors))
    return payload
