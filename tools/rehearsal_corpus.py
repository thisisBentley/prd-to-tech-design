#!/usr/bin/env python3
"""Build deterministic negative-test scenarios from normative and measured evidence."""
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


def source(kind: str, path: Path) -> dict[str, Any]:
    return {"kind": kind, "path": str(path.resolve()), "sha256": digest(path)}


def make_scenario(
    *, scenario_type: str, title: str, classification: str, source_ref: dict[str, Any],
    rule_ids: list[str], root_cause_ids: list[str], revision_refs: list[str],
    negative_condition: str, failure_kind: str, failure_description: str,
    replay_mode: str, forbidden: list[str],
) -> dict[str, Any]:
    identity = {
        "type": scenario_type,
        "source": source_ref["path"],
        "sourceHash": source_ref["sha256"],
        "ruleIds": sorted(set(rule_ids)),
        "rootCauseIds": sorted(set(root_cause_ids)),
        "negativeCondition": negative_condition,
    }
    return {
        "scenarioId": "RS-" + canonical_hash(identity)[:16],
        "scenarioType": scenario_type,
        "title": title,
        "classification": classification,
        "sourceRefs": [source_ref],
        "ruleIds": sorted(set(rule_ids)),
        "rootCauseIds": sorted(set(root_cause_ids)),
        "revisionRefs": sorted(set(revision_refs)),
        "negativeCondition": negative_condition,
        "expectedFailureSignal": {"kind": failure_kind, "description": failure_description},
        "forbiddenOutcomes": sorted(set(forbidden)),
        "replay": {"mode": replay_mode, "frozen": True, "reproducible": True},
    }


def build(
    *, workflow_id: str, revision: str, gate_policy_path: Path,
    finding_ledger_path: Path, audit_results_dir: Path,
    tool_failure_path: Path | None, manual_scenarios_path: Path | None,
) -> dict[str, Any]:
    gate_policy = load(gate_policy_path, {}) or {}
    if not gate_policy.get("rules"):
        raise ValueError("gate policy has no rules")
    sources: list[dict[str, Any]] = [source("GATE_POLICY", gate_policy_path)]
    scenarios: list[dict[str, Any]] = []
    gap: list[str] = []
    warnings: list[str] = []
    policy_ref = source("GATE_POLICY", gate_policy_path)
    blocking_rules = [rule for rule in gate_policy.get("rules", []) if rule.get("severity") == "BLOCKING"]
    for rule in blocking_rules:
        rule_id = str(rule.get("ruleId"))
        scenarios.append(make_scenario(
            scenario_type="GATE_RULE_NEGATIVE",
            title=f"Negative evidence test for {rule_id}",
            classification="DERIVED_FROM_NORMATIVE",
            source_ref=policy_ref,
            rule_ids=[rule_id],
            root_cause_ids=[],
            revision_refs=[],
            negative_condition=f"Remove or contradict the evidence required to prove {rule_id}: {rule.get('passCondition', '')}",
            failure_kind="RULE_NOT_PROVEN",
            failure_description=f"Replay must not accept {rule_id} without its required evidence.",
            replay_mode="AUDIT_JOB",
            forbidden=["PASS_WITHOUT_EVIDENCE", "RELEASE_EVIDENCE_PROMOTION", "TRAINING_PROMOTION"],
        ))

    historical_count = 0
    findings = load(finding_ledger_path, {}) or {}
    if findings:
        finding_ref = source("FINDING_LEDGER", finding_ledger_path)
        sources.append(finding_ref)
        for entry in findings.get("entries") or []:
            if entry.get("severity") != "BLOCKING":
                continue
            historical_count += 1
            scenarios.append(make_scenario(
                scenario_type="HISTORICAL_FINDING_REPLAY",
                title=f"Replay historical finding {entry.get('findingId')}: {entry.get('title', '')}",
                classification="HISTORICAL_EVIDENCE",
                source_ref=finding_ref,
                rule_ids=list(entry.get("ruleIds") or []),
                root_cause_ids=[str(entry.get("rootCauseId"))],
                revision_refs=[str(entry.get("firstSeenRevision")), str(entry.get("lastSeenRevision"))],
                negative_condition=f"Reintroduce the condition behind {entry.get('findingId')} and verify it is detected again.",
                failure_kind="FINDING_REOBSERVED",
                failure_description="The same root cause must remain observable; it may not be silently closed.",
                replay_mode="AUDIT_JOB",
                forbidden=["SILENT_FINDING_CLOSE", "RELEASE_EVIDENCE_PROMOTION", "TRAINING_PROMOTION"],
            ))
    else:
        gap.append("finding ledger: NOT_PRESENT")

    audit_count = 0
    if audit_results_dir.is_dir():
        for path in sorted(audit_results_dir.glob("*.result.json")):
            data = load(path, {}) or {}
            if data.get("workflowId") != workflow_id:
                warnings.append(f"ignored audit result from another workflow: {path.name}")
                continue
            for finding in data.get("findings") or []:
                if finding.get("severity") != "BLOCKING":
                    continue
                audit_count += 1
                ref = source("AUDIT_RESULT", path)
                sources.append(ref)
                scenarios.append(make_scenario(
                    scenario_type="AUDIT_FINDING_REPLAY",
                    title=f"Replay audit finding {finding.get('findingId')}: {finding.get('title', '')}",
                    classification="MEASURED_FAILURE",
                    source_ref=ref,
                    rule_ids=list(finding.get("policyRuleIds") or []),
                    root_cause_ids=[str(finding.get("rootCauseId") or finding.get("findingId"))],
                    revision_refs=[str(data.get("revision"))],
                    negative_condition=f"Recreate the failing evidence state for {finding.get('findingId')}.",
                    failure_kind="GATE_BLOCKED",
                    failure_description="The failed rule must remain blocked until evidence is repaired and fully re-audited.",
                    replay_mode="AUDIT_JOB",
                    forbidden=["PASS_WITHOUT_EVIDENCE", "SILENT_FINDING_CLOSE", "RELEASE_EVIDENCE_PROMOTION", "TRAINING_PROMOTION"],
                ))
    if not audit_count:
        gap.append("audit result findings: NONE")

    tool_failure_count = 0
    if tool_failure_path and tool_failure_path.is_file():
        report = load(tool_failure_path, {}) or {}
        ref = source("TOOL_FAILURE_REPORT", tool_failure_path)
        sources.append(ref)
        for failure in report.get("failures") or []:
            tool_failure_count += 1
            scenarios.append(make_scenario(
                scenario_type="TOOL_FAILURE_REPLAY",
                title=f"Replay tool failure {failure.get('failureId')}: {failure.get('toolId', 'TOOL')}",
                classification="MEASURED_FAILURE",
                source_ref=ref,
                rule_ids=list(failure.get("ruleIds") or []),
                root_cause_ids=[str(failure.get("rootCauseId") or failure.get("failureId"))],
                revision_refs=[str(failure.get("revision"))],
                negative_condition=str(failure.get("negativeCondition") or "Repeat the failed tool request under the same domain and authorization conditions."),
                failure_kind=str(failure.get("expectedFailureKind") or "TOOL_ROUTE_BLOCKED"),
                failure_description=str(failure.get("expectedFailure") or "The tool route must block or escalate instead of silently switching domains."),
                replay_mode="TOOL_ROUTER",
                forbidden=["CROSS_DOMAIN_TOOL_USE", "RELEASE_EVIDENCE_PROMOTION", "TRAINING_PROMOTION"],
            ))
    else:
        gap.append("tool failure report: NOT_PRESENT")

    manual_count = 0
    if manual_scenarios_path and manual_scenarios_path.is_file():
        manual = load(manual_scenarios_path, {}) or {}
        ref = source("MANUAL_SCENARIO", manual_scenarios_path)
        sources.append(ref)
        for item in manual.get("scenarios") or []:
            manual_count += 1
            scenarios.append(make_scenario(
                scenario_type="MANUAL_SCENARIO",
                title=str(item.get("title") or item.get("scenarioId")),
                classification="MANUAL_FIXTURE",
                source_ref=ref,
                rule_ids=list(item.get("ruleIds") or []),
                root_cause_ids=list(item.get("rootCauseIds") or []),
                revision_refs=[revision],
                negative_condition=str(item.get("negativeCondition") or "Apply the manually declared negative condition."),
                failure_kind=str(item.get("expectedFailureKind") or "EVIDENCE_GAP"),
                failure_description=str(item.get("expectedFailure") or "Manual negative scenario must not be accepted as evidence."),
                replay_mode=str(item.get("replayMode") or "EVALUATOR"),
                forbidden=list(item.get("forbiddenOutcomes") or ["RELEASE_EVIDENCE_PROMOTION", "TRAINING_PROMOTION"]),
            ))
    else:
        gap.append("manual scenarios: NOT_PRESENT")

    # Deduplicate deterministic scenarios.
    unique = {item["scenarioId"]: item for item in scenarios}
    scenarios = sorted(unique.values(), key=lambda item: item["scenarioId"])
    covered_rules = sorted({rule for item in scenarios for rule in item["ruleIds"]})
    blocking_rule_ids = sorted(str(rule.get("ruleId")) for rule in blocking_rules)
    uncovered = sorted(set(blocking_rule_ids) - set(covered_rules))
    sources_unique = {item["path"]: item for item in sources}
    sources = sorted(sources_unique.values(), key=lambda item: (item["kind"], item["path"]))
    status = "BLOCKED" if not scenarios else ("PARTIAL" if gap or uncovered else "READY")
    payload_without_id = {
        "schemaVersion": 1,
        "workflowId": workflow_id,
        "revision": revision,
        "status": status,
        "authority": {"purpose": "NEGATIVE_TEST_INPUT", "resultAuthority": "NONE", "releaseEligible": False, "trainingEligible": False},
        "sources": sources,
        "scenarios": scenarios,
        "coverage": {
            "policyRules": len(blocking_rule_ids),
            "coveredPolicyRules": len(set(blocking_rule_ids) & set(covered_rules)),
            "uncoveredPolicyRules": uncovered,
            "historicalFindings": historical_count,
            "toolFailures": tool_failure_count,
            "manualScenarios": manual_count,
        },
        "metrics": {
            "sourceCount": len(sources),
            "scenarioCount": len(scenarios),
            "blockingRuleScenarios": sum(1 for item in scenarios if item["scenarioType"] == "GATE_RULE_NEGATIVE"),
            "historicalScenarios": historical_count + audit_count,
            "toolFailureScenarios": tool_failure_count,
            "manualScenarioCount": manual_count,
        },
        "evidenceGaps": sorted(set(gap)),
        "warnings": sorted(set(warnings)),
        "createdAt": now(),
    }
    corpus = {"corpusId": "RC-" + canonical_hash(payload_without_id)[:16], **payload_without_id}
    errors = validate_schema_value(corpus, "rehearsal-corpus.schema.json")
    if errors:
        raise ValueError("; ".join(errors))
    return corpus


def render_markdown(corpus: dict[str, Any]) -> str:
    lines = [
        f"# Rehearsal Corpus — {corpus['workflowId']}",
        "",
        f"- Revision: `{corpus['revision']}`",
        f"- Status: `{corpus['status']}`",
        f"- Scenarios: `{corpus['metrics']['scenarioCount']}`",
        "- Authority: negative-test inputs only; no release or training eligibility.",
        "",
        "## Coverage",
        "",
        f"- Blocking rules: {corpus['coverage']['coveredPolicyRules']} / {corpus['coverage']['policyRules']}",
        f"- Historical findings: {corpus['coverage']['historicalFindings']}",
        f"- Tool failures: {corpus['coverage']['toolFailures']}",
        f"- Manual scenarios: {corpus['coverage']['manualScenarios']}",
        "",
        "## Scenarios",
        "",
    ]
    for item in corpus["scenarios"]:
        rules = ", ".join(item["ruleIds"]) or "none"
        lines.append(f"- `{item['scenarioId']}` **{item['scenarioType']}** — {item['title']} (rules={rules})")
    if corpus["evidenceGaps"]:
        lines += ["", "## Evidence Gaps", ""]
        lines.extend(f"- {item}" for item in corpus["evidenceGaps"])
    if corpus["warnings"]:
        lines += ["", "## Warnings", ""]
        lines.extend(f"- {item}" for item in corpus["warnings"])
    lines += ["", "## Boundary", "", "Scenarios are replay inputs, not PASS results. Fixtures and historical replay never count as release evidence or training approval.", ""]
    return "\n".join(lines)
