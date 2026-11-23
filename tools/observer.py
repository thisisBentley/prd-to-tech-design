#!/usr/bin/env python3
"""Build a read-only deterministic Observer report from delivery evidence."""
from __future__ import annotations
import hashlib
import json
from collections import defaultdict
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

def input_ref(kind: str, path: Path | None) -> tuple[dict[str, Any], str | None]:
    if path is None or not path.is_file():
        return {"kind": kind, "status": "MISSING", "path": None, "sha256": None}, f"{kind}:MISSING"
    return {"kind": kind, "status": "AVAILABLE", "path": str(path.resolve()), "sha256": digest(path)}, None

def build(*, episode_path: Path, finding_ledger_path: Path, repair_cycle_path: Path, cost_ledger_path: Path, corpus_path: Path, challenger_path: Path | None) -> dict[str, Any]:
    episode = load(episode_path, {}) or {}
    if not episode:
        raise ValueError("Project Episode is missing or unreadable")
    workflow_id = str(episode.get("workflowId") or "")
    revision = str(episode.get("revision") or "")
    if not workflow_id or not revision:
        raise ValueError("Project Episode lacks workflowId or revision")

    inputs = []
    gaps: list[str] = []
    for kind, path in [
        ("PROJECT_EPISODE", episode_path),
        ("FINDING_LEDGER", finding_ledger_path),
        ("REPAIR_CYCLE", repair_cycle_path),
        ("COST_LEDGER", cost_ledger_path),
        ("REHEARSAL_CORPUS", corpus_path),
        ("CHALLENGER_RUN", challenger_path),
    ]:
        ref, gap = input_ref(kind, path)
        inputs.append(ref)
        if gap:
            gaps.append(gap)

    findings = load(finding_ledger_path, {}) or {}
    repair = load(repair_cycle_path, {}) or {}
    cost = load(cost_ledger_path, {}) or {}
    challenger = load(challenger_path, {}) if challenger_path and challenger_path.is_file() else {}

    for name, data in [("Finding Ledger", findings), ("Repair Cycle", repair), ("Cost Ledger", cost), ("Challenger Run", challenger)]:
        if data and data.get("workflowId") not in {None, workflow_id}:
            raise ValueError(f"{name} workflowId mismatch")

    grouped: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "findingCount": 0, "openBlockingCount": 0, "repairAttempts": 0,
        "ruleIds": set(), "sourceRefs": set(),
    })
    finding_source = str(finding_ledger_path.resolve()) if finding_ledger_path.is_file() else ""
    for entry in findings.get("entries") or []:
        root = str(entry.get("rootCauseId") or entry.get("findingId") or "UNKNOWN")
        item = grouped[root]
        item["findingCount"] += 1
        if entry.get("severity") == "BLOCKING" and entry.get("status") not in {"resolved", "accepted_risk", "closed_by_decision"}:
            item["openBlockingCount"] += 1
        item["repairAttempts"] += int(entry.get("repairAttempts", 0) or 0)
        item["ruleIds"].update(str(x) for x in entry.get("ruleIds") or [])
        if finding_source:
            item["sourceRefs"].add(finding_source)
    root_causes = [
        {
            "rootCauseId": root,
            "findingCount": item["findingCount"],
            "openBlockingCount": item["openBlockingCount"],
            "repairAttempts": item["repairAttempts"],
            "ruleIds": sorted(item["ruleIds"]),
            "sourceRefs": sorted(item["sourceRefs"]),
        }
        for root, item in sorted(grouped.items())
    ]

    repair_rounds = len(repair.get("rounds") or [])
    changed_artifacts: set[str] = set()
    for round_record in repair.get("rounds") or []:
        report_path = round_record.get("repairReport")
        if report_path:
            report = load(Path(str(report_path)), {}) or {}
            changed_artifacts.update(str(x) for x in report.get("changedArtifacts") or [])
    before = int((findings.get("metrics") or {}).get("openBlocking", 0) or 0) if findings else None
    after = int((episode.get("findings") or {}).get("metrics", {}).get("openBlocking", 0) or 0)
    if repair:
        if before is not None and after < before:
            assessment = "IMPROVEMENT_OBSERVED"
        elif repair_rounds == 0:
            assessment = "INSUFFICIENT_DATA"
        else:
            assessment = "NO_IMPROVEMENT_OBSERVED"
        repair_effect = {
            "status": "AVAILABLE", "assessment": assessment, "rounds": repair_rounds,
            "changedArtifacts": sorted(changed_artifacts),
            "openBlockingBefore": before, "openBlockingAfter": after,
            "evidenceRefs": [str(repair_cycle_path.resolve())], "causalClaim": False,
        }
    else:
        gaps.append("REPAIR_CYCLE:MISSING")
        repair_effect = {
            "status": "MISSING", "assessment": "NOT_AVAILABLE", "rounds": 0,
            "changedArtifacts": [], "openBlockingBefore": before, "openBlockingAfter": after,
            "evidenceRefs": [], "causalClaim": False,
        }

    if challenger:
        results = challenger.get("scenarioResults") or []
        by_signal: dict[str, dict[str, int]] = defaultdict(lambda: {"detected": 0, "missed": 0, "incomplete": 0, "errors": 0})
        for item in results:
            signal = str((item.get("observedFailureSignal") or {}).get("kind") or "UNKNOWN")
            bucket = by_signal[signal]
            status = item.get("status")
            if status == "DETECTED":
                bucket["detected"] += 1
            elif status == "MISSED":
                bucket["missed"] += 1
            elif status == "INCOMPLETE":
                bucket["incomplete"] += 1
            else:
                bucket["errors"] += 1
        metrics = challenger.get("metrics") or {}
        challenger_patterns = {
            "status": "AVAILABLE",
            "outcome": str(challenger.get("outcome") or "UNKNOWN"),
            "scenarios": int(metrics.get("scenarios", len(results))),
            "detected": int(metrics.get("detected", 0)),
            "missed": int(metrics.get("missed", 0)),
            "incomplete": int(metrics.get("incomplete", 0)),
            "errors": int(metrics.get("errors", 0)),
            "bySignal": [{"signal": signal, **values} for signal, values in sorted(by_signal.items())],
            "evidenceRefs": [str(challenger_path.resolve())],
        }
    else:
        gaps.append("CHALLENGER_RUN:MISSING")
        challenger_patterns = {
            "status": "MISSING", "outcome": "NOT_RUN", "scenarios": 0, "detected": 0,
            "missed": 0, "incomplete": 0, "errors": 0, "bySignal": [], "evidenceRefs": [],
        }

    if cost:
        cost_quality = {
            "status": "AVAILABLE",
            "metrics": cost.get("metrics") or {},
            "interpretation": "Observed cost metrics are descriptive only; no causal relationship between cost and quality is inferred.",
            "causalClaim": False,
            "evidenceRefs": [str(cost_ledger_path.resolve())],
        }
    else:
        gaps.append("COST_LEDGER:MISSING")
        cost_quality = {
            "status": "MISSING", "metrics": {},
            "interpretation": "Cost data is unavailable; no quality/cost relationship can be assessed.",
            "causalClaim": False, "evidenceRefs": [],
        }

    episode_layers = episode.get("evidenceLayers") or {}
    analysis = {
        "rootCauses": root_causes,
        "repairEffect": repair_effect,
        "challengerPatterns": challenger_patterns,
        "costQuality": cost_quality,
        "evidenceLayers": {layer: len(episode_layers.get(layer, [])) for layer in ["SOURCE_FACT", "MEASURED", "DERIVED", "REFERENCE", "INFERENCE"]},
    }

    recommendations = []
    def rec(rec_id: str, priority: str, owner: str, action: str, reason: str, refs: list[str]) -> None:
        recommendations.append({
            "recommendationId": rec_id, "priority": priority, "owner": owner,
            "action": action, "reason": reason, "changeSetRequired": False,
            "sourceRefs": sorted(set(refs)),
        })

    open_roots = [item for item in root_causes if item["openBlockingCount"] > 0]
    if open_roots:
        rec("REVIEW_ROOT_CAUSE", "P0", "delivery-owner", "Review the highest-volume open root causes before proposing any Change Set.", f"openBlockingRootCauses={len(open_roots)}", [str(finding_ledger_path.resolve())])
    if not challenger:
        rec("RUN_REAL_CASE", "P1", "delivery-owner", "Run Challenger against a real or externally observed failure package.", "No Challenger Run is available for Observer analysis.", [str(corpus_path.resolve())])
    elif challenger_patterns["missed"] or challenger_patterns["incomplete"] or challenger_patterns["errors"]:
        rec("REVIEW_CHALLENGER_GAP", "P1", "review-owner", "Review Challenger missed or incomplete signals and bind them to a controlled Change Set.", "Challenger has gaps; Observer does not modify the candidate.", [str(challenger_path.resolve())])
    if gaps:
        rec("ADD_EVIDENCE", "P1", "evidence-owner", "Collect missing evidence sources and rerun Observer.", f"missingInputs={len(set(gaps))}", [str(episode_path.resolve())])
    if not cost or cost.get("metricsAvailability") != "COMPLETE":
        rec("IMPROVE_TELEMETRY", "P2", "runtime-owner", "Improve timing, token and context telemetry before comparing efficiency.", "Cost telemetry is missing or incomplete.", [str(cost_ledger_path.resolve())])
    if not recommendations:
        rec("NO_ACTION", "P2", "observer", "No deterministic Observer action is required for the current evidence.", "No open root cause, Challenger gap or missing input was observed.", [str(episode_path.resolve())])

    status = "BLOCKED" if episode.get("status") == "BLOCKED" else ("PARTIAL" if episode.get("status") != "COMPLETE" or gaps or not challenger else "READY")
    payload = {
        "schemaVersion": 1,
        "observerId": "OBS-" + canonical_hash({
            "workflowId": workflow_id,
            "revision": revision,
            "episode": digest(episode_path),
            "finding": digest(finding_ledger_path) if finding_ledger_path.is_file() else None,
            "challenger": digest(challenger_path) if challenger_path and challenger_path.is_file() else None,
        })[:16],
        "workflowId": workflow_id,
        "revision": revision,
        "status": status,
        "authority": {
            "readOnly": True, "resultAuthority": "NONE", "releaseEligible": False,
            "trainingEligible": False, "causalClaims": False,
        },
        "inputs": inputs,
        "analysis": analysis,
        "recommendations": recommendations,
        "evidenceGaps": sorted(set(gaps)),
        "warnings": [
            "Observer recommendations are advisory and require a separate controlled Change Set.",
            "Cost/quality analysis is descriptive; it does not establish causality.",
        ],
        "metrics": {
            "rootCauses": len(root_causes),
            "openBlockingRootCauses": len(open_roots),
            "repairRounds": repair_rounds,
            "challengerScenarios": challenger_patterns["scenarios"],
            "challengerMissed": challenger_patterns["missed"],
            "recommendations": len(recommendations),
            "evidenceGaps": len(set(gaps)),
        },
        "createdAt": now(),
    }
    errors = validate_schema_value(payload, "observer-report.schema.json")
    if errors:
        raise ValueError("; ".join(errors))
    return payload
