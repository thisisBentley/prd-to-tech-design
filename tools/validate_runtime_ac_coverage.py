#!/usr/bin/env python3
"""Validate configuration/runtime AC pairing and evidence contracts for runtime FRs.

The parser accepts both heading-based and flat PRD layouts. Runtime relevance is
never inferred from the existence of an AC alone: a runtime-relevant FR must
declare both a configuration-state AC and a runtime-state AC. Every runtime AC
must name at least one evidence type.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from validate_json_schemas import load, validate

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_ROOT = ROOT / "schemas" if (ROOT / "schemas").exists() else ROOT / "references"
DEFAULT_POLICY = ROOT / "config" / "runtime-ac" / "runtime-ac-policy.json"
FR_ID_RE = re.compile(r"\bFR-[0-9]{3}\b")
AC_ID_RE = re.compile(r"\bAC-[0-9]{3}\b")
FR_CANDIDATE_RE = re.compile(r"^\s*(?:#{1,6}\s+(?:(?:\d+(?:\.\d+)*)\s+)?|[-*]\s*)(FR-[0-9]{3})(?:\s*[：:]\s*|\s+)(.+?)\s*$", re.M)
FR_HEADING_RE = re.compile(r"^\s*(#{1,6})\s+(?:(?:\d+(?:\.\d+)*)\s+)?(FR-[0-9]{3})(?:\s*[：:]\s*|\s+)(.+?)\s*$", re.M)
AC_LINE_RE = re.compile(r"^\s*(?:#{1,6}\s+(?:(?:\d+(?:\.\d+)*)\s+)?|[-*]\s*)?(AC-[0-9]{3})\s*(?:[：:]\s*)?(.+?)\s*$", re.M)
LABEL_RE = re.compile(r"(?:验收类型|AC类型|类型)\s*[：:]\s*(配置态|运行态|CONFIG|RUNTIME|配置|运行)", re.IGNORECASE)
EVIDENCE_LABEL_RE = re.compile(r"(?:证据契约|证据类型|evidence(?:-type)?)\s*[：:]\s*([^\n；;]+)", re.IGNORECASE)
RUNTIME_TYPE_RE = re.compile(r"(?:运行类型|运行态功能|runtime-type)\s*[：:]\s*(RUNTIME|NON_RUNTIME|运行态|非运行态|运行时|非运行时)", re.IGNORECASE)
AC_TAG_RE = re.compile(r"\[(配置态|运行态|CONFIG|RUNTIME)\]", re.IGNORECASE)
EVIDENCE_TOKEN_RE = re.compile(r"\b(STATE|LOG|QUEUE|ALERT|API|AUDIT_EVENT|DB|METRIC)\b", re.IGNORECASE)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def any_pattern(text: str, values: list[str]) -> bool:
    return any(re.search(value, text, re.IGNORECASE) for value in values)


def fr_blocks(text: str) -> list[dict[str, Any]]:
    headings = list(FR_HEADING_RE.finditer(text))
    if headings:
        blocks: list[dict[str, Any]] = []
        for index, match in enumerate(headings):
            level = len(match.group(1))
            end = len(text)
            for following in headings[index + 1:]:
                if len(following.group(1)) <= level:
                    end = following.start()
                    break
            blocks.append({"frId": match.group(2), "title": match.group(3).strip(), "text": text[match.start():end]})
        return blocks
    return [{"frId": match.group(1), "title": match.group(2).strip(), "text": match.group(0)} for match in FR_CANDIDATE_RE.finditer(text)]


def ac_entries(text: str) -> list[dict[str, Any]]:
    matches = list(AC_LINE_RE.finditer(text))
    entries: list[dict[str, Any]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        block = text[match.start():end]
        next_heading = re.search(r"\n#{1,2}\s+", block[match.end() - match.start():])
        if next_heading:
            block = block[:match.end() - match.start() + next_heading.start()]
        entries.append({"acId": match.group(1), "text": block})
    return entries


def explicit_ac_type(entry_text: str) -> str | None:
    tag = AC_TAG_RE.search(entry_text)
    if tag:
        value = tag.group(1).upper()
        return "RUNTIME" if value in {"运行态", "RUNTIME"} else "CONFIG"
    label = LABEL_RE.search(entry_text)
    if label:
        value = label.group(1).upper()
        return "RUNTIME" if value in {"运行态", "RUNTIME", "运行"} else "CONFIG"
    return None


def evidence_contract(entry_text: str) -> tuple[list[str], list[str]]:
    label = EVIDENCE_LABEL_RE.search(entry_text)
    value = label.group(1) if label else entry_text
    tokens = sorted({item.upper() for item in EVIDENCE_TOKEN_RE.findall(value)})
    refs = []
    ref_match = re.search(r"(?:证据引用|evidence-refs?)\s*[：:]\s*([^\n；;]+)", entry_text, re.IGNORECASE)
    if ref_match:
        refs = [item.strip() for item in re.split(r"[,，;；\s]+", ref_match.group(1)) if item.strip()]
    return tokens, refs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prd", type=Path, required=True)
    parser.add_argument("--workflow-id", required=True)
    parser.add_argument("--revision", default="r1")
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--coverage-input", type=Path, help="Supplemental machine-readable AC classification and evidence contract.")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    prd_path = args.prd.resolve()
    policy_path = args.policy.resolve()
    if not prd_path.is_file():
        print(json.dumps({"status": "BLOCKED", "error": f"PRD not found: {prd_path}"}, ensure_ascii=False))
        return 1
    if not policy_path.is_file():
        print(json.dumps({"status": "BLOCKED", "error": f"runtime AC policy not found: {policy_path}"}, ensure_ascii=False))
        return 1
    text = prd_path.read_text(encoding="utf-8", errors="replace")
    policy = load(policy_path)
    supplemental = load(args.coverage_input.resolve()) if args.coverage_input and args.coverage_input.is_file() else {}
    supplemental_by_fr = {
        str(item.get("frId")): item
        for item in supplemental.get("requirements", [])
        if isinstance(item, dict) and item.get("frId")
    }
    blocks = fr_blocks(text)
    entries = ac_entries(text)
    all_fr_ids = {block["frId"] for block in blocks}
    mapped: dict[str, list[dict[str, Any]]] = {fr_id: [] for fr_id in all_fr_ids}
    for entry in entries:
        refs = set(FR_ID_RE.findall(entry["text"]))
        if not refs:
            refs = {block["frId"] for block in blocks if entry["acId"] in block["text"]}
        if not refs and len(all_fr_ids) == 1:
            refs = set(all_fr_ids)
        for fr_id in refs & all_fr_ids:
            mapped[fr_id].append(entry)

    requirements: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    for block in blocks:
        fr_id = block["frId"]
        fr_text = block["text"]
        type_match = RUNTIME_TYPE_RE.search(fr_text)
        explicit_runtime = bool(type_match and type_match.group(1).upper() in {"RUNTIME", "运行态", "运行时"})
        explicit_non_runtime = bool(type_match and type_match.group(1).upper() in {"NON_RUNTIME", "非运行态", "非运行时"})
        keyword_runtime = any_pattern(fr_text, policy["runtimeFrKeywords"])
        runtime_relevant = explicit_runtime or (keyword_runtime and not explicit_non_runtime)
        configuration_acs: list[str] = []
        runtime_acs: list[str] = []
        unclassified_acs: list[str] = []
        evidence_contracts: list[dict[str, Any]] = []
        errors: list[str] = []
        explicit = supplemental_by_fr.get(fr_id, {})
        if explicit:
            runtime_relevant = bool(explicit.get("runtimeRelevant", runtime_relevant))
            configuration_acs = [str(item) for item in explicit.get("configurationAcs", [])]
            runtime_acs = [str(item) for item in explicit.get("runtimeAcs", [])]
            unclassified_acs = []
            evidence_contracts = [
                {
                    "acId": str(item.get("acId")),
                    "evidenceTypes": [str(value) for value in item.get("evidenceTypes", []) if str(value)],
                    "evidenceRefs": [str(value) for value in item.get("evidenceRefs", []) if str(value)],
                }
                for item in explicit.get("evidenceContracts", [])
                if isinstance(item, dict) and item.get("acId")
            ]
            allowed = set(policy.get("evidenceTypes", []))
            known_acs = {entry["acId"] for entry in mapped[fr_id]}
            for ac_id in configuration_acs + runtime_acs:
                if ac_id not in known_acs:
                    errors.append(f"{ac_id}: supplemental AC is not mapped to {fr_id} in the PRD")
            contract_ids = {item["acId"] for item in evidence_contracts}
            for ac_id in runtime_acs:
                if ac_id not in contract_ids:
                    errors.append(f"{ac_id}: runtime AC must have a supplemental evidence contract")
            for item in evidence_contracts:
                invalid = [value for value in item["evidenceTypes"] if value not in allowed]
                if invalid:
                    errors.append(f"{item['acId']}: unsupported evidence types in supplemental contract: {invalid}")
                if not item["evidenceTypes"]:
                    errors.append(f"{item['acId']}: runtime AC must declare an evidence contract using one of {sorted(allowed)}")
            if runtime_relevant:
                if not mapped[fr_id]:
                    errors.append("runtime-relevant FR has no acceptance criteria")
                if not configuration_acs:
                    errors.append("runtime-relevant FR is missing a configuration-state AC")
                if not runtime_acs:
                    errors.append("runtime-relevant FR is missing a runtime-state AC")
            status = "BLOCKED" if errors else ("PASS" if runtime_relevant else "NOT_APPLICABLE")
            requirements.append({
                "frId": fr_id,
                "title": block["title"],
                "runtimeRelevant": runtime_relevant,
                "runtimeReason": str(explicit.get("runtimeReason") or "supplemental classification"),
                "configurationAcs": sorted(set(configuration_acs)),
                "runtimeAcs": sorted(set(runtime_acs)),
                "unclassifiedAcs": unclassified_acs,
                "evidenceContracts": evidence_contracts,
                "status": status,
                "errors": errors,
            })
            for index, message in enumerate(errors, start=1):
                findings.append({
                    "findingId": f"RAC-{fr_id}-{index:03d}",
                    "frId": fr_id,
                    "severity": "BLOCKING",
                    "code": "RUNTIME_AC_GAP",
                    "message": message,
                    "evidenceRefs": [str(prd_path)],
                })
            continue
        for entry in mapped[fr_id]:
            ac_id = entry["acId"]
            ac_type = explicit_ac_type(entry["text"])
            if ac_type is None:
                if any_pattern(entry["text"], policy["runtimeAcKeywords"]):
                    ac_type = "RUNTIME"
                elif any_pattern(entry["text"], policy["configurationAcKeywords"]):
                    ac_type = "CONFIG"
            if ac_type == "CONFIG":
                configuration_acs.append(ac_id)
            elif ac_type == "RUNTIME":
                runtime_acs.append(ac_id)
                evidence_types, evidence_refs = evidence_contract(entry["text"])
                allowed = set(policy.get("evidenceTypes", []))
                evidence_types = [item for item in evidence_types if item in allowed]
                if not evidence_types:
                    errors.append(f"{ac_id}: runtime AC must declare an evidence contract using one of {sorted(allowed)}")
                evidence_contracts.append({"acId": ac_id, "evidenceTypes": evidence_types, "evidenceRefs": evidence_refs})
            else:
                unclassified_acs.append(ac_id)
        if runtime_relevant:
            if not mapped[fr_id]:
                errors.append("runtime-relevant FR has no acceptance criteria")
            if not configuration_acs:
                errors.append("runtime-relevant FR is missing a configuration-state AC")
            if not runtime_acs:
                errors.append("runtime-relevant FR is missing a runtime-state AC")
            if unclassified_acs:
                errors.append("runtime-relevant FR contains ACs without a configuration/runtime classification: " + ", ".join(unclassified_acs))
        else:
            errors = []
            evidence_contracts = []
        status = "BLOCKED" if errors else ("PASS" if runtime_relevant else "NOT_APPLICABLE")
        requirements.append({
            "frId": fr_id,
            "title": block["title"],
            "runtimeRelevant": runtime_relevant,
            "runtimeReason": "explicit marker" if explicit_runtime else ("runtime keyword" if keyword_runtime else ("explicit non-runtime" if explicit_non_runtime else "no runtime marker")),
            "configurationAcs": sorted(set(configuration_acs)),
            "runtimeAcs": sorted(set(runtime_acs)),
            "unclassifiedAcs": sorted(set(unclassified_acs)),
            "evidenceContracts": evidence_contracts,
            "status": status,
            "errors": errors,
        })
        for index, message in enumerate(errors, start=1):
            findings.append({
                "findingId": f"RAC-{fr_id}-{index:03d}",
                "frId": fr_id,
                "severity": "BLOCKING",
                "code": "RUNTIME_AC_GAP",
                "message": message,
                "evidenceRefs": [str(prd_path)],
            })
    status = "BLOCKED" if findings else "PASS"
    payload = {
        "schemaVersion": 1,
        "coverageId": "RAC-" + hashlib.sha256((args.workflow_id + args.revision + digest(prd_path)).encode()).hexdigest()[:16],
        "workflowId": args.workflow_id,
        "targetRevision": args.revision,
        "prdPath": str(prd_path),
        "prdSha256": digest(prd_path),
        "policyPath": str(policy_path),
        "policySha256": digest(policy_path),
        **({"coverageInputPath": str(args.coverage_input.resolve()), "coverageInputSha256": digest(args.coverage_input.resolve())} if args.coverage_input and args.coverage_input.is_file() else {}),
        "status": status,
        "requirements": requirements,
        "findings": findings,
        "metrics": {
            "functionalRequirements": len(requirements),
            "runtimeRequirements": sum(1 for item in requirements if item["runtimeRelevant"]),
            "runtimeAcs": sum(len(item["runtimeAcs"]) for item in requirements),
            "coveredRuntimeAcs": sum(len(item["evidenceContracts"]) for item in requirements),
            "blocked": sum(1 for item in requirements if item["status"] == "BLOCKED"),
        },
        "checkedAt": datetime.now(timezone.utc).isoformat(),
    }
    schema = load(SCHEMA_ROOT / "runtime-ac-coverage.schema.json")
    schema_errors = validate(payload, schema, schema)
    if schema_errors:
        status = "BLOCKED"
        payload["status"] = status
    save(args.out, payload)
    print(json.dumps({"status": status, "runtimeRequirements": payload["metrics"]["runtimeRequirements"], "blocked": payload["metrics"]["blocked"], "schemaErrors": schema_errors[:10], "out": str(args.out)}, ensure_ascii=False))
    return 0 if status == "PASS" and not schema_errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
