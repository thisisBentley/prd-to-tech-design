#!/usr/bin/env python3
"""Semantic ledger, invariant registry and convergence gate helpers."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from validate_json_schemas import load as schema_load, validate as schema_validate

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "schemas" if (ROOT / "schemas").exists() else ROOT / "references"
OBJECT_TYPE_BY_CONTRACT = {
    "PERMISSION": "PERMISSION",
    "STATE": "STATE",
}
OBJECT_TYPE_BY_UNIT = {
    "FEATURE_SLICE": "FEATURE_SLICE",
    "ACCEPTANCE_CRITERION": "AC",
    "INTERACTION_CONTRACT": "INTERACTION_CONTRACT",
    "JOURNEY": "JOURNEY",
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def save(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def validate_schema_value(value: Any, schema_name: str) -> list[str]:
    schema = schema_load(SCHEMA_DIR / schema_name)
    return schema_validate(value, schema, schema)


def safe_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "-", value).strip("-").upper()


def build_semantic_ledger(model_path: Path) -> dict[str, Any]:
    model_path = model_path.resolve()
    model = load(model_path)
    prd_path = Path(str((model.get("source") or {}).get("prdPath", ""))).resolve()
    if not prd_path.is_file():
        raise ValueError(f"semantic model PRD does not exist: {prd_path}")
    objects: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add_object(item: dict[str, Any]) -> None:
        object_id = str(item["objectId"])
        if object_id in seen:
            raise ValueError(f"duplicate semantic object: {object_id}")
        seen.add(object_id)
        objects.append(item)

    for contract in model.get("globalContracts", []) or []:
        contract_id = str(contract.get("contractId", ""))
        kind = str(contract.get("kind", "OTHER"))
        statement = str(contract.get("statement", ""))
        source_ref = str(contract.get("sourceRef", f"{prd_path}#{contract_id}"))
        add_object({
            "objectId": contract_id,
            "objectType": OBJECT_TYPE_BY_CONTRACT.get(kind, "GLOBAL_CONTRACT"),
            "title": str(contract.get("title", contract_id)),
            "statement": statement,
            "sourceRef": source_ref,
            "authority": str(contract.get("authority", "PRD")),
            "status": "DEPRECATED" if contract.get("status") == "CONFLICT" else "ACTIVE",
            "frIds": [],
            "acIds": [],
            "dependencies": [],
            "sections": {"statement": statement},
            "fields": {"kind": kind},
            "evidenceRefs": [source_ref],
            "contentHash": canonical_hash({"title": contract.get("title"), "statement": statement, "kind": kind}),
        })

    for unit in model.get("units", []) or []:
        unit_id = str(unit.get("unitId", ""))
        kind = str(unit.get("kind", ""))
        object_type = OBJECT_TYPE_BY_UNIT.get(kind)
        if not object_type:
            continue
        source_ref = str(unit.get("sourceRef", f"{prd_path}#{unit_id}"))
        add_object({
            "objectId": unit_id,
            "objectType": object_type,
            "title": str(unit.get("title", unit_id)),
            "statement": str(unit.get("statement") or unit.get("content") or ""),
            "sourceRef": source_ref,
            "authority": str(unit.get("authority", "PRD")),
            "status": "ACTIVE",
            "frIds": [str(item) for item in unit.get("frIds", []) or []],
            "acIds": [str(item) for item in unit.get("acIds", []) or []],
            "dependencies": [str(item) for item in unit.get("dependencies", []) or []],
            "sections": {str(k): str(v) for k, v in (unit.get("sections") or {}).items()},
            "fields": {str(k): str(v) for k, v in (unit.get("fields") or {}).items()},
            "evidenceRefs": [source_ref],
            "contentHash": canonical_hash(unit),
        })
        if kind == "FEATURE_SLICE":
            business_rules = str((unit.get("sections") or {}).get("业务规则", "")).strip()
            if business_rules:
                business_id = f"BR-{unit_id}"
                add_object({
                    "objectId": business_id,
                    "objectType": "BUSINESS_RULE",
                    "title": f"{unit.get('title', unit_id)} - 业务规则",
                    "statement": business_rules,
                    "sourceRef": source_ref,
                    "authority": "PRD",
                    "status": "ACTIVE",
                    "frIds": [str(item) for item in unit.get("frIds", []) or []],
                    "acIds": [str(item) for item in unit.get("acIds", []) or []],
                    "dependencies": [unit_id, *[str(item) for item in unit.get("dependencies", []) or []]],
                    "sections": {"businessRule": business_rules},
                    "fields": {},
                    "evidenceRefs": [source_ref],
                    "contentHash": canonical_hash({"unitId": unit_id, "businessRule": business_rules}),
                })
            interaction_rules = str((unit.get("sections") or {}).get("交互与状态", "")).strip()
            if interaction_rules:
                interaction_id = f"IR-{unit_id}"
                add_object({
                    "objectId": interaction_id,
                    "objectType": "INTERACTION_RULE",
                    "title": f"{unit.get('title', unit_id)} - 交互与状态",
                    "statement": interaction_rules,
                    "sourceRef": source_ref,
                    "authority": "PRD",
                    "status": "ACTIVE",
                    "frIds": [str(item) for item in unit.get("frIds", []) or []],
                    "acIds": [str(item) for item in unit.get("acIds", []) or []],
                    "dependencies": [unit_id],
                    "sections": {"interactionRule": interaction_rules},
                    "fields": {},
                    "evidenceRefs": [source_ref],
                    "contentHash": canonical_hash({"unitId": unit_id, "interactionRule": interaction_rules}),
                })

    relations = []
    for edge in model.get("edges", []) or []:
        from_id = str(edge.get("fromUnitId", ""))
        to_id = str(edge.get("toUnitId", ""))
        if from_id not in seen or to_id not in seen:
            continue
        relations.append({
            "fromObjectId": from_id,
            "toObjectId": to_id,
            "relation": str(edge.get("relation", "DEPENDS_ON")),
            "evidenceRefs": [str(item) for item in edge.get("evidenceRefs", []) or []],
        })
    by_type = {kind: sum(1 for item in objects if item["objectType"] == kind) for kind in {item["objectType"] for item in objects}}
    ledger_without_id = {
        "schemaVersion": 1,
        "workflowId": str(model.get("workflowId", "unknown")),
        "targetRevision": str(model.get("targetRevision", "unknown")),
        "source": {
            "semanticModelPath": str(model_path),
            "semanticModelHash": sha256_file(model_path),
            "prdPath": str(prd_path),
            "prdHash": sha256_file(prd_path),
            **({"prototypePath": str(Path(str((model.get('source') or {}).get('prototypePath'))).resolve()), "prototypeHash": str((model.get("source") or {}).get("prototypeSha256"))} if (model.get("source") or {}).get("prototypePath") else {}),
        },
        "objects": objects,
        "relations": relations,
        "metrics": {
            "objects": len(objects),
            "featureSlices": by_type.get("FEATURE_SLICE", 0),
            "acceptanceCriteria": by_type.get("AC", 0),
            "globalContracts": by_type.get("GLOBAL_CONTRACT", 0) + by_type.get("PERMISSION", 0) + by_type.get("STATE", 0),
            "relations": len(relations),
        },
        "createdAt": now(),
    }
    ledger = {"ledgerId": "semantic-ledger-" + canonical_hash(ledger_without_id)[:16], **ledger_without_id}
    errors = validate_schema_value(ledger, "semantic-ledger.schema.json")
    if errors:
        raise ValueError("; ".join(errors))
    return ledger


def _candidate(invariant_id: str, statement: str, scope: list[str], source_refs: list[str], created_from: str, owner: str) -> dict[str, Any]:
    return {
        "invariantId": invariant_id,
        "statement": statement,
        "scopeObjectIds": sorted(set(scope)),
        "sourceRefs": sorted(set(source_refs)),
        "evidenceRefs": sorted(set(source_refs)),
        "status": "CANDIDATE",
        "owner": owner,
        "createdFrom": created_from,
    }


def build_invariant_registry(ledger_path: Path, decision_impact_path: Path | None = None) -> dict[str, Any]:
    ledger_path = ledger_path.resolve()
    ledger = load(ledger_path)
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(item: dict[str, Any]) -> None:
        if item["invariantId"] in seen:
            return
        seen.add(item["invariantId"])
        candidates.append(item)

    for obj in ledger.get("objects", []) or []:
        object_id = str(obj.get("objectId", ""))
        source_ref = str(obj.get("sourceRef", ""))
        if obj.get("objectType") == "BUSINESS_RULE":
            add(_candidate(f"INV-{safe_id(object_id)}", str(obj.get("statement", "")), [object_id, *[str(item) for item in obj.get("frIds", [])]], [source_ref], "BUSINESS_RULE", "delivery-reviewer"))
        elif obj.get("objectType") == "AC":
            fields = obj.get("fields") or {}
            statement = str(fields.get("THEN") or obj.get("statement") or "").strip()
            if statement:
                add(_candidate(f"INV-{safe_id(object_id)}", statement, [object_id, *[str(item) for item in obj.get("frIds", [])]], [source_ref], "ACCEPTANCE_CRITERION", "qa-red-team"))
        elif obj.get("objectType") in {"PERMISSION", "STATE"} or (obj.get("objectType") == "GLOBAL_CONTRACT" and (obj.get("fields") or {}).get("kind") in {"PERMISSION", "STATE", "ENUM"}):
            statement = str(obj.get("statement", "")).strip()
            if statement:
                add(_candidate(f"INV-{safe_id(object_id)}", statement, [object_id], [source_ref], "GLOBAL_CONTRACT", "delivery-reviewer"))
    if decision_impact_path and decision_impact_path.is_file():
        impact = load(decision_impact_path.resolve())
        for decision in impact.get("decisions", []) or []:
            statement = str(decision.get("expectedInvariant", "")).strip()
            if not statement:
                continue
            decision_id = str(decision.get("decisionId", "UNKNOWN"))
            refs = [str(item) for item in decision.get("evidenceRefs", []) or []]
            scope = [str(item.get("objectId")) for item in decision.get("affectedObjects", []) or [] if item.get("objectId")]
            if refs and scope:
                add(_candidate(f"INV-DECISION-{safe_id(decision_id)}", statement, scope, refs, "DECISION_IMPACT", "product-acceptance-reviewer"))
    if not candidates:
        raise ValueError("no invariant candidates could be derived from explicit sources")
    counts = {status.lower(): sum(1 for item in candidates if item["status"] == status) for status in ("CANDIDATE", "ACTIVE", "LOCKED", "DEPRECATED")}
    registry_without_id = {
        "schemaVersion": 1,
        "workflowId": str(ledger.get("workflowId", "unknown")),
        "targetRevision": str(ledger.get("targetRevision", "unknown")),
        "source": {
            "ledgerPath": str(ledger_path),
            "ledgerHash": sha256_file(ledger_path),
            **({"decisionImpactGraphPath": str(decision_impact_path.resolve()), "decisionImpactGraphHash": sha256_file(decision_impact_path.resolve())} if decision_impact_path and decision_impact_path.is_file() else {}),
        },
        "invariants": candidates,
        "metrics": {"invariants": len(candidates), **counts},
        "createdAt": now(),
    }
    registry = {"registryId": "invariant-registry-" + canonical_hash(registry_without_id)[:16], **registry_without_id}
    errors = validate_schema_value(registry, "invariant-registry.schema.json")
    if errors:
        raise ValueError("; ".join(errors))
    return registry


def finding_identity(finding: dict[str, Any]) -> str:
    return canonical_hash({
        "rootCauseId": finding.get("rootCauseId"),
        "affectedObjectIds": sorted(str(item) for item in finding.get("affectedObjectIds", []) or []),
    })


def weighted_score(snapshot: dict[str, Any], weights: dict[str, float]) -> float:
    total = 0.0
    for finding in snapshot.get("findings", []) or []:
        if finding.get("status") != "OPEN":
            continue
        total += float(weights.get(str(finding.get("severity")), 0))
    return round(total, 4)


def evaluate_convergence(
    baseline: dict[str, Any],
    current: dict[str, Any],
    policy: dict[str, Any],
    registry: dict[str, Any],
    history: list[dict[str, Any]] | None = None,
    enforce_revision_binding: bool = True,
) -> dict[str, Any]:
    input_errors: list[str] = []
    inputs = [
        (baseline, "convergence-finding-snapshot.schema.json", "baseline"),
        (current, "convergence-finding-snapshot.schema.json", "current"),
        (policy, "convergence-policy.schema.json", "policy"),
        (registry, "invariant-registry.schema.json", "registry"),
    ]
    for index, snapshot in enumerate(history or []):
        inputs.append((snapshot, "convergence-finding-snapshot.schema.json", f"history[{index}]"))
    for value, schema_name, label in inputs:
        input_errors.extend(f"{label}: {item}" for item in validate_schema_value(value, schema_name))
    if input_errors:
        raise ValueError("; ".join(input_errors))
    checks: list[dict[str, Any]] = []
    reasons: list[str] = []

    def check(check_id: str, ok: bool, observed: Any, expected: Any) -> None:
        checks.append({"checkId": check_id, "status": "passed" if ok else "failed", "observed": observed, "expected": expected})
        if not ok:
            reasons.append(f"{check_id}: observed={observed!r}, expected={expected!r}")

    workflows = {str(baseline.get("workflowId")), str(current.get("workflowId")), str(registry.get("workflowId"))}
    workflows.update(str(item.get("workflowId")) for item in history or [])
    check("CONVERGENCE.WORKFLOW_ID", len(workflows) == 1, sorted(workflows), "one shared workflowId")
    if enforce_revision_binding:
        check("CONVERGENCE.CURRENT_REVISION", registry.get("targetRevision") == current.get("revision"), {"registry": registry.get("targetRevision"), "current": current.get("revision")}, "registry targetRevision equals current revision")
    weights = {str(k): float(v) for k, v in policy.get("severityWeights", {}).items()}
    baseline_open = {finding_identity(item): item for item in baseline.get("findings", []) or [] if item.get("status") == "OPEN" and item.get("severity") == "BLOCKING"}
    current_blocking_open = {finding_identity(item): item for item in current.get("findings", []) or [] if item.get("status") == "OPEN" and item.get("severity") == "BLOCKING"}
    new_blocking = sorted(set(current_blocking_open) - set(baseline_open))
    closed = sorted(set(baseline_open) - set(current_blocking_open))
    baseline_closed_root_causes = {
        str(item.get("rootCauseId")) for item in baseline.get("findings", []) or []
        if item.get("status") == "CLOSED"
    }
    reopened = [
        item for item in current.get("findings", []) or []
        if item.get("status") == "OPEN" and (item.get("reopened") is True or str(item.get("rootCauseId")) in baseline_closed_root_causes)
    ]
    violated = sorted(set(str(item) for item in current.get("violatedInvariantIds", []) or []))
    verified = set(str(item) for item in current.get("verifiedInvariantIds", []) or [])
    locked = {str(item.get("invariantId")) for item in registry.get("invariants", []) or [] if item.get("status") == "LOCKED"}
    missing_locked = sorted(locked - verified)
    coverage_required = bool(policy.get("requireLockedInvariantCoverage"))
    coverage_void = coverage_required and not locked
    semantic_drifts = [item for item in current.get("findings", []) or [] if item.get("status") == "OPEN" and item.get("code") == "SEMANTIC_DRIFT"]
    scope_drifts = [item for item in current.get("findings", []) or [] if item.get("status") == "OPEN" and item.get("code") == "SCOPE_DRIFT"]
    snapshots: list[dict[str, Any]] = []
    seen_snapshots: set[str] = set()
    for snapshot in [*(history or []), baseline, current]:
        snapshot_key = str(snapshot.get("snapshotId") or f"{snapshot.get('revision')}:{canonical_hash(snapshot)[:12]}")
        if snapshot_key in seen_snapshots:
            continue
        seen_snapshots.add(snapshot_key)
        snapshots.append(snapshot)
    open_revisions_by_root: dict[str, set[str]] = {}
    for snapshot in snapshots:
        revision = str(snapshot.get("revision", "unknown"))
        for finding in snapshot.get("findings", []) or []:
            if finding.get("status") != "OPEN":
                continue
            root_cause_id = str(finding.get("rootCauseId", ""))
            if root_cause_id:
                open_revisions_by_root.setdefault(root_cause_id, set()).add(revision)
    max_open_rounds = int(policy.get("maxOpenRootCauseRounds", 2))
    repeated_root_causes = [
        {"rootCauseId": root_cause_id, "openRevisions": sorted(revisions)}
        for root_cause_id, revisions in sorted(open_revisions_by_root.items())
        if len(revisions) > max_open_rounds
    ]
    metric_snapshots = [item for item in [baseline, current] if isinstance(item.get("executionMetrics"), dict)]
    complete_metrics = all(item["executionMetrics"].get("availability") == "COMPLETE" for item in metric_snapshots)
    metrics_binding_ok = True
    for label, snapshot in (("baseline", baseline), ("current", current)):
        metrics = snapshot.get("executionMetrics")
        if not isinstance(metrics, dict):
            continue
        input_tokens = metrics.get("inputTokens")
        output_tokens = metrics.get("outputTokens")
        total_tokens = metrics.get("totalTokens")
        if input_tokens is not None and output_tokens is not None and total_tokens is not None:
            metrics_binding_ok = metrics_binding_ok and total_tokens == int(input_tokens) + int(output_tokens)
        if metrics.get("availability") == "COMPLETE":
            metrics_binding_ok = metrics_binding_ok and all(metrics.get(key) is not None for key in ("elapsedMs", "inputTokens", "outputTokens", "totalTokens"))
    baseline_score = weighted_score(baseline, weights)
    current_score = weighted_score(current, weights)
    delta = round(current_score - baseline_score, 4)
    check("CONVERGENCE.NO_NEW_BLOCKING", not new_blocking or not policy.get("requireNoNewBlocking"), len(new_blocking), 0)
    check("CONVERGENCE.NO_REOPENED_ROOT_CAUSE", not reopened or not policy.get("requireNoReopenedRootCause"), len(reopened), 0)
    check("CONVERGENCE.NO_INVARIANT_VIOLATION", not violated or not policy.get("requireNoInvariantViolation"), violated, [])
    check("CONVERGENCE.NO_SEMANTIC_DRIFT", not semantic_drifts or not policy.get("requireNoSemanticDrift"), len(semantic_drifts), 0)
    check("CONVERGENCE.NO_SCOPE_DRIFT", not scope_drifts or not policy.get("requireNoScopeDrift"), len(scope_drifts), 0)
    check("CONVERGENCE.NO_REPEATED_ROOT_CAUSE", not repeated_root_causes, repeated_root_causes, f"each rootCause open in <= {max_open_rounds} revisions")
    check("CONVERGENCE.EXECUTION_METRICS_BINDING", metrics_binding_ok, {"baseline": baseline.get("executionMetrics"), "current": current.get("executionMetrics")}, "token totals and status are internally consistent")
    if policy.get("requireCompleteExecutionMetrics"):
        check("CONVERGENCE.EXECUTION_METRICS_COMPLETE", bool(metric_snapshots) and complete_metrics, [item["executionMetrics"].get("availability") for item in metric_snapshots], "baseline and current metrics COMPLETE")
    check(
        "CONVERGENCE.LOCKED_INVARIANT_COVERAGE",
        (not missing_locked and not coverage_void) or not coverage_required,
        {"lockedCount": len(locked), "missingLockedInvariantIds": missing_locked, "vacuous": coverage_void},
        "at least one locked invariant and all locked invariants verified",
    )
    if policy.get("requireWeightedDecrease"):
        check("CONVERGENCE.WEIGHTED_DECREASE", current_score < baseline_score or current_score == 0, {"baseline": baseline_score, "current": current_score}, "strict decrease or zero")
    integrity_failures = bool(new_blocking or reopened or violated or semantic_drifts or scope_drifts or repeated_root_causes or not metrics_binding_ok)
    if integrity_failures:
        status = "BLOCKED"
    elif missing_locked or coverage_void:
        status = "INCOMPLETE"
    elif current_score > baseline_score:
        status = "REGRESSED"
    elif reasons:
        status = "BLOCKED"
    elif current_score == baseline_score and current_score > 0:
        status = "STALLED"
    elif current_score > 0:
        status = "IMPROVING"
    else:
        status = "PASS"
    report_without_id = {
        "schemaVersion": 1,
        "workflowId": current.get("workflowId", baseline.get("workflowId", "unknown")),
        "baselineRevision": str(baseline.get("revision", "unknown")),
        "currentRevision": str(current.get("revision", "unknown")),
        "status": status,
        "metrics": {
            "baselineWeightedScore": baseline_score,
            "currentWeightedScore": current_score,
            "weightedDelta": delta,
            "baselineOpenBlocking": len(baseline_open),
            "currentOpenBlocking": len(current_blocking_open),
            "newBlockingFindings": len(new_blocking),
            "closedFindings": len(closed),
            "reopenedRootCauses": len(reopened),
            "invariantViolations": len(violated),
            "semanticDrifts": len(semantic_drifts),
            "scopeDrifts": len(scope_drifts),
            "repeatedRootCauseCount": len(repeated_root_causes),
            "repeatedRootCauses": repeated_root_causes,
            "missingLockedInvariantIds": missing_locked,
            "lockedInvariantCount": len(locked),
            "baselineMetricsAvailability": str((baseline.get("executionMetrics") or {}).get("availability", "MISSING")),
            "currentMetricsAvailability": str((current.get("executionMetrics") or {}).get("availability", "MISSING")),
        },
        "checks": checks,
        "blockingReasons": reasons,
        "createdAt": now(),
    }
    report = {"reportId": "convergence-" + canonical_hash(report_without_id)[:16], **report_without_id}
    errors = validate_schema_value(report, "convergence-report.schema.json")
    if errors:
        raise ValueError("; ".join(errors))
    return report
