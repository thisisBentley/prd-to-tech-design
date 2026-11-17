#!/usr/bin/env python3
"""Normalize external Skill findings into stable Finding Ledger input."""
from __future__ import annotations

import argparse
import hashlib
import json
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from validate_json_schemas import load, validate

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_ROOT = ROOT / "schemas" if (ROOT / "schemas").exists() else ROOT / "references"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_severity(value: Any) -> str:
    text = str(value or "BLOCKING").upper().replace("-", "_")
    if text in {"BLOCKING", "P0", "P1", "ERROR", "FAIL", "CRITICAL"}: return "BLOCKING"
    if text in {"INFO", "SUGGESTION", "NOTE"}: return "INFO"
    return "NON_BLOCKING"


def normalize_repair_class(value: Any, title: str) -> str:
    text = str(value or "").upper().replace("-", "_").replace(" ", "_")
    aliases = {"DESIGN": "VISIBLE_INTERACTION", "CONTRACT": "ARTIFACT_CONTRACT", "QA": "RUNTIME"}
    text = aliases.get(text, text)
    if text in {"SEMANTIC", "ARTIFACT_CONTRACT", "VISIBLE_INTERACTION", "RUNTIME", "EVIDENCE"}: return text
    lowered = title.casefold()
    if any(token in lowered for token in ("原型", "交互", "prototype", "interaction")): return "VISIBLE_INTERACTION"
    if any(token in lowered for token in ("结构", "合同", "metadata", "overview", "diagram")): return "ARTIFACT_CONTRACT"
    if any(token in lowered for token in ("运行", "runtime", "queue", "日志", "log")): return "RUNTIME"
    if any(token in lowered for token in ("证据", "evidence", "定位", "fragment")): return "EVIDENCE"
    return "SEMANTIC"


def stable_id(skill_id: str, external_id: str, rule_id: str, artifact: str, root_cause: str) -> str:
    basis = "|".join([skill_id, external_id, rule_id, artifact, root_cause])
    return "EXT-" + hashlib.sha256(basis.encode()).hexdigest()[:16].upper()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--skill-id", required=True)
    parser.add_argument("--workflow-id", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    raw = load(args.input.resolve())
    values = raw.get("findings") if isinstance(raw, dict) else raw
    if not isinstance(values, list):
        raise SystemExit("external finding input must be a list or contain a findings array")
    findings: list[dict[str, Any]] = []
    for index, item in enumerate(values, start=1):
        if not isinstance(item, dict):
            continue
        external_id = str(item.get("findingId") or item.get("id") or item.get("ruleId") or f"finding-{index}")
        title = str(item.get("title") or item.get("message") or item.get("ruleId") or external_id)
        rule_values = item.get("policyRuleIds") or ([item.get("policyRuleId")] if item.get("policyRuleId") else []) or ([item.get("ruleId")] if item.get("ruleId") else [])
        rule_ids = [str(rule) for rule in rule_values if rule]
        root_cause = str(item.get("rootCauseId") or item.get("rootCause") or item.get("category") or rule_ids[0] if rule_ids else title)
        artifact = str(item.get("artifact") or item.get("path") or "external-report")
        evidence_refs = [str(ref) for ref in item.get("evidenceRefs") or [] if ref] or [str(args.input.resolve())]
        findings.append({
            "findingId": str(item.get("stableFindingId") or stable_id(args.skill_id, external_id, rule_ids[0] if rule_ids else "", artifact, root_cause)),
            "title": title,
            "severity": normalize_severity(item.get("severity") or item.get("priority")),
            "rootCauseId": root_cause,
            "repairClass": normalize_repair_class(item.get("repairClass") or item.get("category"), title),
            "owner": str(item.get("owner") or "delivery-repair-agent"),
            "policyRuleIds": rule_ids,
            "evidenceRefs": evidence_refs,
            "impact": str(item.get("impact") or item.get("message") or title),
            "closeCondition": str(item.get("closeCondition") or item.get("remedy") or "Repair the finding and pass a full re-audit."),
            **({"artifact": artifact} if artifact else {}),
            "externalSkillId": args.skill_id,
            "externalFindingId": external_id,
        })
    batch = {
        "schemaVersion": 1,
        "batchId": "external-findings-" + secrets.token_hex(4),
        "workflowId": args.workflow_id,
        "revision": args.revision,
        "skillId": args.skill_id,
        "findings": findings,
        "metrics": {
            "total": len(findings),
            "blocking": sum(1 for item in findings if item["severity"] == "BLOCKING"),
            "nonBlocking": sum(1 for item in findings if item["severity"] == "NON_BLOCKING"),
            "info": sum(1 for item in findings if item["severity"] == "INFO"),
        },
        "generatedAt": now(),
    }
    schema = load(SCHEMA_ROOT / "external-skill-finding-batch.schema.json")
    errors = validate(batch, schema, schema)
    if errors:
        print(json.dumps({"status": "BLOCKED", "errors": errors[:20]}, ensure_ascii=False))
        return 1
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(batch, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "findings": len(findings), "blocking": batch["metrics"]["blocking"], "out": str(args.out)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
