#!/usr/bin/env python3
"""Shared Agent contract loading, normalization and validation helpers.

The canonical result is Digital Worker Task Result V2: task execution status and
review verdict are independent, and both are contract-bound.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from validate_json_schemas import load as schema_load, validate as schema_validate

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "schemas" if (ROOT / "schemas").exists() else ROOT / "references"
TASK_STATUSES = {"COMPLETED", "BLOCKED", "UNKNOWN"}
VERDICTS = {"PASS", "FINDINGS", "REPAIR_PLAN", "NOT_APPLICABLE"}
SECTION_FIELDS = {
    "evidence": "evidence",
    "conclusions": "conclusions",
    "findings": "findings",
    "unknowns": "unknowns",
    "boundary": "boundary",
}
SEVERITIES = {"BLOCKING", "NONBLOCKING", "INFO"}


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


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def canonical_hash(value: Any) -> str:
    return sha256_text(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def schema(name: str) -> dict[str, Any]:
    return schema_load(SCHEMA_DIR / name)


def validate_schema_value(value: Any, schema_name: str) -> list[str]:
    document = schema(schema_name)
    return schema_validate(value, document, document)


def validate_contract_release(release: dict[str, Any]) -> list[str]:
    errors = validate_schema_value(release, "agent-contract-release.schema.json")
    if errors:
        return errors
    ids: set[str] = set()
    for contract in release.get("contracts", []):
        contract_errors = validate_schema_value(contract, "agent-task-contract.schema.json")
        errors.extend(f"contract {contract.get('contractId', '<unknown>')}: {item}" for item in contract_errors)
        contract_id = str(contract.get("contractId", ""))
        if contract_id in ids:
            errors.append(f"duplicate contractId: {contract_id}")
        ids.add(contract_id)
        expected = release.get("contractHashes", {}).get(contract_id)
        actual = canonical_hash(contract)
        if expected != actual:
            errors.append(f"contract hash mismatch: {contract_id}")
    return errors


def contract_index(release: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(item.get("contractId")): item for item in release.get("contracts", [])}


def select_contract(release: dict[str, Any], contract_id: str | None = None, capability_mode: str | None = None) -> dict[str, Any]:
    contracts = release.get("contracts", [])
    if contract_id:
        for item in contracts:
            if item.get("contractId") == contract_id:
                return item
        raise KeyError(f"contract not found: {contract_id}")
    if capability_mode:
        for item in contracts:
            if item.get("capabilityMode") == capability_mode:
                return item
    raise KeyError("contractId or known capabilityMode is required")


def _normalize_severity(value: Any) -> str:
    severity = str(value or "NONBLOCKING").upper()
    if severity == "NON_BLOCKING":
        severity = "NONBLOCKING"
    return severity if severity in SEVERITIES else "NONBLOCKING"


def _normalize_finding(finding: Any, fallback_refs: list[str], index: int) -> dict[str, Any]:
    if isinstance(finding, str):
        finding = {"title": finding}
    if not isinstance(finding, dict):
        finding = {"title": str(finding)}
    refs = [str(item) for item in finding.get("evidenceRefs", []) if str(item).strip()]
    if not refs:
        refs = fallback_refs[:1]
    result = {
        "findingId": str(finding.get("findingId") or finding.get("id") or f"F-{index:03d}"),
        "severity": _normalize_severity(finding.get("severity")),
        "title": str(finding.get("title") or finding.get("summary") or "Unspecified finding"),
        "evidenceRefs": refs,
    }
    if finding.get("rootCauseId"):
        result["rootCauseId"] = str(finding["rootCauseId"])
    if finding.get("closeCondition"):
        result["closeCondition"] = str(finding["closeCondition"])
    return result


def _derive_task_state(source: dict[str, Any], unknowns: list[str], verdict: str) -> str:
    explicit = str(source.get("taskStatus") or "").upper()
    if explicit in TASK_STATUSES:
        return explicit
    legacy = str(source.get("status") or "").upper()
    if legacy in {"BLOCKED", "UNKNOWN"}:
        return legacy
    if verdict == "FINDINGS" and not source.get("findings"):
        return "UNKNOWN"
    if legacy == "DRAFT_REFERENCE" and unknowns:
        return "UNKNOWN"
    return "COMPLETED"


def _derive_verdict(source: dict[str, Any], findings: list[dict[str, Any]], task_status: str) -> str:
    explicit = str(source.get("reviewVerdict") or "").upper()
    if explicit == "NOT_APPLICABLE":
        return "NOT_APPLICABLE"
    if explicit in VERDICTS:
        return explicit
    legacy = str(source.get("status") or "").upper()
    if legacy in VERDICTS:
        return legacy
    if findings:
        return "FINDINGS"
    if str(source.get("decisionType") or "").upper() in {"REPAIR", "PROTOTYPE_REPAIR"}:
        return "REPAIR_PLAN"
    if task_status in {"BLOCKED", "UNKNOWN"}:
        return "NOT_APPLICABLE"
    return "PASS"


def normalize_result(
    raw: Any,
    contract: dict[str, Any],
    task_id: str,
    fallback_evidence_refs: Iterable[str] = (),
) -> dict[str, Any]:
    """Convert legacy or draft output into Digital Worker Task Result V2.

    The normalizer never invents evidence. A FINDINGS verdict without structured
    findings fails closed to UNKNOWN / NOT_APPLICABLE and records why.
    """
    source = raw if isinstance(raw, dict) else {}
    refs = list(dict.fromkeys(str(item) for item in fallback_evidence_refs if str(item).strip()))
    evidence: list[dict[str, Any]] = []
    for item in source.get("evidence", []) or []:
        if isinstance(item, str):
            evidence.append({"ref": item, "claim": "Frozen evidence supplied in the task context."})
        elif isinstance(item, dict):
            ref = str(item.get("ref") or item.get("path") or "").strip()
            if not ref:
                continue
            normalized = {
                "ref": ref,
                "claim": str(item.get("claim") or item.get("reason") or "Frozen evidence supplied in the task context."),
            }
            if item.get("quote"):
                normalized["quote"] = str(item["quote"])
            evidence.append(normalized)
    if not evidence and refs:
        evidence = [{"ref": ref, "claim": "Frozen evidence supplied in the task context."} for ref in refs]
    evidence_refs = [item["ref"] for item in evidence]

    findings = [_normalize_finding(item, evidence_refs or refs, index) for index, item in enumerate(source.get("findings", []) or [], 1)]
    unknowns = [str(item) for item in source.get("unknowns", []) or [] if str(item).strip()]
    conclusions = [str(item) for item in source.get("conclusions", []) or [] if str(item).strip()]
    if not conclusions:
        conclusions = ["The task stopped at the declared evidence or decision boundary."]
    boundary = [str(item) for item in source.get("boundary", []) or [] if str(item).strip()]
    if not boundary:
        boundary = [str(item) for item in contract.get("constraints", [])] or ["Use only frozen inputs and declared evidence."]

    task_status = _derive_task_state(source, unknowns, str(source.get("reviewVerdict") or "").upper())
    verdict = _derive_verdict(source, findings, task_status)
    if verdict == "FINDINGS" and not findings:
        unknowns.append("The review verdict was FINDINGS but no structured finding was supplied.")
        verdict = "NOT_APPLICABLE"
        task_status = "UNKNOWN"
    if task_status in {"BLOCKED", "UNKNOWN"} and not unknowns:
        unknowns.append("The available evidence is insufficient to establish a trustworthy result.")
    allowed_statuses = set(contract.get("allowedTaskStatus", []))
    allowed_verdicts = set(contract.get("allowedVerdicts", []))
    if task_status not in allowed_statuses:
        task_status = "UNKNOWN" if "UNKNOWN" in allowed_statuses else sorted(allowed_statuses)[0]
    if verdict not in allowed_verdicts:
        verdict = "NOT_APPLICABLE" if "NOT_APPLICABLE" in allowed_verdicts else sorted(allowed_verdicts)[0]
    return {
        "schemaVersion": 2,
        "contractId": contract["contractId"],
        "contractVersion": contract["contractVersion"],
        "taskId": task_id,
        "taskStatus": task_status,
        "decisionType": str(source.get("decisionType") or contract.get("capabilityMode") or contract.get("taskType")),
        "reviewVerdict": verdict,
        "evidence": evidence or [{"ref": "UNRESOLVED-EVIDENCE", "claim": "No resolvable evidence was supplied."}],
        "conclusions": conclusions,
        "findings": findings,
        "unknowns": unknowns,
        "boundary": boundary,
    }


def allowed_evidence_refs(context_pack: dict[str, Any] | None) -> set[str]:
    if not context_pack:
        return set()
    refs: set[str] = set()
    for item in context_pack.get("evidence", []) or []:
        if isinstance(item, dict) and item.get("ref"):
            refs.add(str(item["ref"]))
    for item in context_pack.get("sourceArtifacts", []) or []:
        if isinstance(item, dict) and item.get("path"):
            refs.add(str(item["path"]))
    for item in context_pack.get("facts", []) or []:
        if isinstance(item, dict) and item.get("sourceRef"):
            refs.add(str(item["sourceRef"]))
    return refs


def _ref_matches(ref: str, allowed: set[str]) -> bool:
    if not allowed:
        return True
    if ref in allowed:
        return True
    normalized = ref.replace("\\", "/").split("#", 1)[0].lstrip("./")
    for candidate in allowed:
        candidate_norm = str(candidate).replace("\\", "/").split("#", 1)[0].lstrip("./")
        if normalized == candidate_norm:
            return True
        if normalized.endswith("/" + candidate_norm) or candidate_norm.endswith("/" + normalized):
            return True
    return False


def validate_agent_result(
    result: Any,
    contract: dict[str, Any],
    context_pack: dict[str, Any] | None = None,
    require_contract_binding: bool = True,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    errors: list[str] = []

    def add(check_id: str, ok: bool, observed: Any, expected: Any) -> None:
        checks.append({"checkId": check_id, "status": "passed" if ok else "failed", "observed": observed, "expected": expected})
        if not ok:
            errors.append(f"{check_id}: expected {expected}; observed {observed}")

    schema_errors = validate_schema_value(result, "agent-result.schema.json")
    add("AGENT_RESULT.SCHEMA", not schema_errors, schema_errors or "valid", "agent-result.schema.json")
    if not isinstance(result, dict):
        return {"schemaVersion": 1, "status": "FAIL", "checks": checks, "errors": errors, "result": result}
    if require_contract_binding:
        add("AGENT_RESULT.CONTRACT_ID", result.get("contractId") == contract.get("contractId"), result.get("contractId"), contract.get("contractId"))
        add("AGENT_RESULT.CONTRACT_VERSION", result.get("contractVersion") == contract.get("contractVersion"), result.get("contractVersion"), contract.get("contractVersion"))
    add("AGENT_RESULT.TASK_STATUS_ALLOWED", result.get("taskStatus") in set(contract.get("allowedTaskStatus", [])), result.get("taskStatus"), contract.get("allowedTaskStatus"))
    add("AGENT_RESULT.VERDICT_ALLOWED", result.get("reviewVerdict") in set(contract.get("allowedVerdicts", [])), result.get("reviewVerdict"), contract.get("allowedVerdicts"))
    for section in contract.get("requiredSections", []):
        field = SECTION_FIELDS.get(section, section)
        add(f"AGENT_RESULT.SECTION.{section}", field in result, "present" if field in result else "missing", field)
    evidence = result.get("evidence", []) if isinstance(result.get("evidence"), list) else []
    result_refs = [str(item.get("ref")) for item in evidence if isinstance(item, dict) and item.get("ref")]
    policy = contract.get("evidencePolicy", {})
    min_refs = int(policy.get("minEvidenceRefs", 1))
    add("AGENT_RESULT.EVIDENCE_MIN", len(result_refs) >= min_refs, len(result_refs), f">={min_refs}")
    allowed = allowed_evidence_refs(context_pack)
    if policy.get("mustCite") and allowed:
        invalid = [ref for ref in result_refs if not _ref_matches(ref, allowed)]
        add("AGENT_RESULT.EVIDENCE_ALLOWED", not invalid, invalid, "all refs from contextPack")
    verdict = result.get("reviewVerdict")
    findings = result.get("findings", []) if isinstance(result.get("findings"), list) else []
    if verdict == "FINDINGS":
        add("AGENT_RESULT.FINDINGS_PRESENT", bool(findings), len(findings), ">=1")
        for index, finding in enumerate(findings):
            refs = finding.get("evidenceRefs", []) if isinstance(finding, dict) else []
            add(f"AGENT_RESULT.FINDING_EVIDENCE.{index}", bool(refs), len(refs), ">=1")
    if result.get("taskStatus") in {"BLOCKED", "UNKNOWN"}:
        add("AGENT_RESULT.UNKNOWN_PRESENT", bool(result.get("unknowns")), len(result.get("unknowns", [])), ">=1")
    return {"schemaVersion": 1, "status": "PASS" if not errors else "FAIL", "checks": checks, "errors": errors, "contractId": contract.get("contractId"), "checkedAt": now()}
