#!/usr/bin/env python3
"""Replay historical delivery packages against current consumer readiness checks."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from semantic_convergence import canonical_hash, load, save, sha256_file
from trust_kernel import now, validate_schema_value

FR_RE = re.compile(r"\bFR-[0-9]{3}\b")
AC_RE = re.compile(r"\bAC-[0-9]{3}\b")
TAG_RE = re.compile(r"<[^>]+>", re.DOTALL)
HEADING_RE = re.compile(r"<h[1-6][^>]*>(.*?)</h[1-6]>", re.IGNORECASE | re.DOTALL)
PRD_SECTION_ALIASES = {
    "background": ["需求背景", "background"],
    "goals": ["需求目标", "目标 (goal)", "目标"],
    "scope": ["本期范围", "范围", "scope"],
    "requirements": ["详细需求", "功能需求", "functional requirements"],
    "business_rules": ["业务规则", "business rules", "规则"],
    "states": ["状态", "state", "status"],
    "exceptions": ["异常", "exception", "失败"],
    "acceptance": ["测试验收", "验收标准", "acceptance criteria"],
    "non_goals": ["非目标", "non-goals", "本期不包含"],
    "permissions": ["权限", "permission"],
}
OVERVIEW_ALIASES = {
    "summary": ["方案摘要", "背景与总览", "背景与现状"],
    "goal_scope": ["目标与范围"],
    "rules": ["功能与规则"],
    "flow": ["方案与流程", "流程与状态", "原型与交互"],
    "acceptance": ["验收与保障", "验收与风险"],
}


def visible(html: str) -> str:
    return re.sub(r"\s+", " ", TAG_RE.sub(" ", html)).strip()


def section_content(html: str, aliases: list[str]) -> str:
    for alias in aliases:
        pattern = rf"<(h[1-6])[^>]*>[^<]*{re.escape(alias)}[^<]*</\1>"
        match = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
        if not match:
            continue
        level = int(match.group(1)[1])
        end = len(html)
        for next_match in re.finditer(r"<(h[1-6])[^>]*>.*?</\1>", html[match.end():], re.IGNORECASE | re.DOTALL):
            if int(next_match.group(1)[1]) <= level:
                end = match.end() + next_match.start()
                break
        return visible(html[match.end():end])
    return ""


def add_check(checks: list[dict[str, Any]], check_id: str, passed: bool, observed: Any, expected: Any, refs: list[str]) -> None:
    checks.append({"checkId": check_id, "status": "passed" if passed else "failed", "observed": observed, "expected": expected, "evidenceRefs": refs})


def add_gap(gaps: list[dict[str, Any]], code: str, severity: str, message: str, refs: list[str]) -> None:
    payload = {"code": code, "severity": severity, "message": message, "evidenceRefs": refs}
    gaps.append({"gapId": "HIST-GAP-" + canonical_hash(payload)[:12], **payload})


def parse_gate_statuses(gates_dir: Path | None) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if not gates_dir or not gates_dir.is_dir():
        return result
    for path in sorted(gates_dir.glob('*.json')):
        try:
            data = load(path)
        except Exception:
            continue
        status = data.get("result") or data.get("status") or data.get("verdict")
        if status:
            result[path.stem] = status
    return result


def replay_sample(sample: dict[str, Any]) -> dict[str, Any]:
    case_id = str(sample["caseId"])
    root = Path(sample["sourceRoot"]).resolve()
    artifacts = {name: Path(value).resolve() if value else None for name, value in sample.get("artifacts", {}).items()}
    checks: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    required = ["prd", "overview", "prototype"]
    missing = [name for name in required if not artifacts.get(name) or not artifacts[name].is_file()]
    add_check(checks, "HISTORY.CORE_ARTIFACTS", not missing, missing, [], [str(path) for path in artifacts.values() if path])
    for name in missing:
        add_gap(gaps, "CORE_ARTIFACT_MISSING", "BLOCKING", f"Historical case is missing {name}.", [str(root)])
    if missing:
        return build_result(case_id, root, artifacts, checks, gaps, {}, compatibility_partial=False)

    prd_text = artifacts["prd"].read_text(encoding="utf-8", errors="replace")
    overview_html = artifacts["overview"].read_text(encoding="utf-8", errors="replace")
    prototype_html = artifacts["prototype"].read_text(encoding="utf-8", errors="replace")
    prd_lower = prd_text.lower()
    missing_topics = [topic for topic, aliases in PRD_SECTION_ALIASES.items() if not any(alias.lower() in prd_lower for alias in aliases)]
    add_check(checks, "HISTORY.PRD.LEGACY_SECTIONS", not missing_topics, missing_topics, [], [str(artifacts["prd"])])
    if missing_topics:
        add_gap(gaps, "PRD_REQUIRED_TOPICS_MISSING", "BLOCKING", "PRD lacks required consumer topics: " + ", ".join(missing_topics), [str(artifacts["prd"])])
    frs = sorted(set(FR_RE.findall(prd_text)))
    acs = sorted(set(AC_RE.findall(prd_text)))
    weak_acs = []
    for ac in acs:
        match = re.search(rf"\b{re.escape(ac)}\b", prd_text)
        window = prd_text[max(0, match.start() - 400): match.end() + 1800] if match else ""
        if not FR_RE.search(window) or len(window) < 180:
            weak_acs.append(ac)
    add_check(checks, "HISTORY.PRD.FR_AC", bool(frs) and bool(acs) and not weak_acs, {"frCount": len(frs), "acCount": len(acs), "weakAcs": weak_acs}, {"minFr": 1, "minAc": 1, "weakAcs": []}, [str(artifacts["prd"])])
    if not frs or not acs or weak_acs:
        add_gap(gaps, "PRD_TRACEABILITY_GAP", "BLOCKING", "FR/AC are missing or weak: " + ", ".join(weak_acs), [str(artifacts["prd"])])

    overview_sections = {key: section_content(overview_html, aliases) for key, aliases in OVERVIEW_ALIASES.items()}
    thin_tabs = [key for key, value in overview_sections.items() if len(value) < 30]
    add_check(checks, "HISTORY.OVERVIEW.LEGACY_TABS", not thin_tabs, {key: len(value) for key, value in overview_sections.items()}, {key: ">=30" for key in overview_sections}, [str(artifacts["overview"])])
    if thin_tabs:
        add_gap(gaps, "OVERVIEW_CONTENT_THIN", "BLOCKING", "Overview sections are missing or thin: " + ", ".join(thin_tabs), [str(artifacts["overview"])])
    source_meta = bool(re.search(r'name=["\']source-prd', overview_html, re.IGNORECASE))
    source_hash = bool(re.search(r'source-prd-sha256', overview_html, re.IGNORECASE))
    add_check(checks, "HISTORY.OVERVIEW.SOURCE_METADATA", source_meta, {"sourceRef": source_meta, "sourceHash": source_hash}, {"sourceRef": True, "sourceHash": "optional-legacy"}, [str(artifacts["overview"])])
    if not source_meta:
        add_gap(gaps, "OVERVIEW_SOURCE_REF_MISSING", "BLOCKING", "Overview does not declare its source PRD.", [str(artifacts["overview"])])
    if source_meta and not source_hash and sample.get("sourceFormat", "LEGACY") == "LEGACY":
        add_gap(gaps, "OVERVIEW_HASH_NOT_BOUND", "QUALITY", "Legacy Overview has a source reference but no source hash.", [str(artifacts["overview"])])

    modern_bindings = len(re.findall(r'data-ai-(?:id|fr|ac)=', prototype_html, re.IGNORECASE))
    legacy_bindings = len(re.findall(r'data-(?:testid|page-menu-sn|business-zone|metric-key)=', prototype_html, re.IGNORECASE))
    behavioral_markers = len(re.findall(r'unauthorized|forbidden|empty|error|timeout|loading|denied|无权限|空态|异常|超时|加载', prototype_html, re.IGNORECASE))
    add_check(checks, "HISTORY.PROTOTYPE.LEGACY_BINDINGS", modern_bindings > 0 or legacy_bindings > 0, {"modern": modern_bindings, "legacy": legacy_bindings, "behaviorMarkers": behavioral_markers}, {"bindings": ">0", "behaviorMarkers": ">0"}, [str(artifacts["prototype"])])
    if modern_bindings == 0 and legacy_bindings == 0:
        add_gap(gaps, "PROTOTYPE_BINDING_MISSING", "BLOCKING", "Prototype has no recognizable machine or legacy bindings.", [str(artifacts["prototype"])])
    if behavioral_markers == 0:
        add_gap(gaps, "PROTOTYPE_BEHAVIOR_EVIDENCE_MISSING", "BLOCKING", "Prototype does not expose exception, permission, loading or empty-state evidence.", [str(artifacts["prototype"])])
    if modern_bindings == 0:
        add_gap(gaps, "MODERN_FR_AC_BINDING_MISSING", "QUALITY", "Historical Prototype uses legacy bindings and cannot prove current FR/AC machine coverage.", [str(artifacts["prototype"])])

    gate_statuses = parse_gate_statuses(artifacts.get("gatesDir"))
    runtime = None
    runtime_path = artifacts.get("runtime")
    if runtime_path and runtime_path.is_file():
        try:
            runtime = load(runtime_path)
        except Exception as exc:
            add_gap(gaps, "RUNTIME_INVALID", "BLOCKING", f"Runtime evidence is invalid: {exc}", [str(runtime_path)])
    runtime_errors = []
    runtime_loaded = False
    if runtime is not None:
        runtime_errors = runtime.get("errors") or runtime.get("consoleErrors") or runtime.get("pageErrors") or runtime.get("requestFailures") or []
        checks_obj = runtime.get("checks") or {}
        runtime_loaded = runtime.get("status") == "PASS" or any(
            isinstance(value, dict) and (value.get("loaded") or value.get("mount") or value.get("status") == "PASS")
            for value in checks_obj.values()
        ) if isinstance(checks_obj, dict) else runtime.get("status") == "PASS"
    add_check(checks, "HISTORY.RUNTIME.LEGACY_EVIDENCE", runtime is None or (not runtime_errors and runtime_loaded), {"present": runtime is not None, "loaded": runtime_loaded, "errors": runtime_errors}, "optional legacy runtime evidence must be error-free", [str(runtime_path) if runtime_path else str(root)])
    if runtime is None:
        add_gap(gaps, "RUNTIME_EVIDENCE_MISSING", "QUALITY", "No historical runtime evidence is available.", [str(root)])
    elif runtime_errors or not runtime_loaded:
        add_gap(gaps, "RUNTIME_EVIDENCE_NOT_USABLE", "BLOCKING", "Historical runtime evidence is error-bearing or cannot prove load.", [str(runtime_path)])

    jira_path = artifacts.get("jira")
    jira_ok = bool(jira_path and jira_path.is_file() and jira_path.read_text(encoding="utf-8", errors="replace").strip())
    add_check(checks, "HISTORY.JIRA.PROJECTION", jira_ok, str(jira_path) if jira_path else None, "present", [str(jira_path) if jira_path else str(root)])
    if not jira_ok:
        add_gap(gaps, "JIRA_PROJECTION_MISSING", "QUALITY", "Historical package has no Jira projection.", [str(root)])

    passed_gates = {gate: status for gate, status in gate_statuses.items() if str(status).upper() in {"PASS", "ACCEPTED", "PASS_WITH_NONBLOCKING"}}
    add_check(checks, "HISTORY.GATES.LEGACY_RESULTS", bool(gate_statuses), {"available": gate_statuses, "passing": passed_gates}, [], [str(artifacts["gatesDir"]) if artifacts.get("gatesDir") else str(root)])
    if not gate_statuses:
        add_gap(gaps, "LEGACY_GATE_RESULTS_MISSING", "QUALITY", "No historical gate results were supplied.", [str(root)])

    metrics = {
        "prdChars": len(prd_text),
        "overviewChars": len(overview_html),
        "frCount": len(frs),
        "acCount": len(acs),
        "modernBindings": modern_bindings,
        "legacyBindings": legacy_bindings,
        "behaviorMarkers": behavioral_markers,
        "runtimePresent": runtime is not None,
        "legacyGateCount": len(gate_statuses),
    }
    return build_result(case_id, root, artifacts, checks, gaps, metrics, compatibility_partial=(modern_bindings == 0 or not source_hash))


def build_result(case_id: str, root: Path, artifacts: dict[str, Path | None], checks: list[dict[str, Any]], gaps: list[dict[str, Any]], metrics: dict[str, Any], compatibility_partial: bool) -> dict[str, Any]:
    blocking = [item for item in gaps if item["severity"] == "BLOCKING"]
    quality = [item for item in gaps if item["severity"] == "QUALITY"]
    if blocking:
        status = "REPLAY_BLOCKED"
        readiness = "BLOCKED"
    elif quality:
        status = "REPLAY_PARTIAL"
        readiness = "PARTIAL"
    else:
        status = "REPLAY_PASS"
        readiness = "READY"
    compatibility = "PARTIAL" if compatibility_partial else ("PASS" if not blocking else "PARTIAL")
    payload = {
        "schemaVersion": 1,
        "caseId": case_id,
        "caseClassification": "HISTORICAL_REPLAY",
        "sourceRoot": str(root),
        "status": status,
        "versionCompatibility": compatibility,
        "contentReadiness": readiness,
        "m7ExitEvidenceEligible": False,
        "artifacts": {name: str(path) if path else None for name, path in artifacts.items()},
        "checks": checks,
        "gaps": gaps,
        "metrics": metrics,
    }
    digest = canonical_hash(payload)
    result = {"reportId": "HISTORICAL-REPLAY-" + digest[:16], **payload, "contentSha256": digest, "createdAt": now()}
    errors = validate_schema_value(result, "historical-replay-result.schema.json")
    if errors:
        raise ValueError("invalid historical replay result: " + "; ".join(errors))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    spec = load(args.spec.resolve())
    out_dir = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    reports = []
    for sample in spec.get("samples", []):
        report = replay_sample(sample)
        path = out_dir / f"{sample['caseId']}.historical-replay.json"
        save(path, report)
        reports.append(report)
    summary = {
        "schemaVersion": 1,
        "policyId": spec.get("policyId", "HISTORICAL_REPLAY"),
        "caseCount": len(reports),
        "statusCounts": {status: sum(1 for item in reports if item["status"] == status) for status in ("REPLAY_PASS", "REPLAY_PARTIAL", "REPLAY_BLOCKED")},
        "versionCompatibilityCounts": {status: sum(1 for item in reports if item["versionCompatibility"] == status) for status in ("PASS", "PARTIAL", "FAIL")},
        "cases": [{"caseId": item["caseId"], "status": item["status"], "versionCompatibility": item["versionCompatibility"], "contentReadiness": item["contentReadiness"], "gapCount": len(item["gaps"]), "report": str(out_dir / f"{item['caseId']}.historical-replay.json")} for item in reports],
        "m7ExitEvidenceEligible": False,
        "checkedAt": now(),
    }
    save(out_dir / "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
