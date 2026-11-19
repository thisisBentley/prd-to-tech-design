#!/usr/bin/env python3
"""Audit compiled training records for contract and evidence integrity."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from agent_contracts import load, now, save, select_contract, validate_agent_result, validate_contract_release


def read_records(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".jsonl":
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    value = load(path)
    return value if isinstance(value, list) else [value]


def resolve_ref(dataset_root: Path | None, sample_id: str, ref: str) -> bool:
    candidate = Path(ref)
    if candidate.is_absolute():
        return candidate.exists()
    if dataset_root is None:
        return True
    sample_root = dataset_root / "issues" / sample_id
    return (sample_root / ref).exists() or (sample_root / "00-source" / ref).exists() or (dataset_root / ref).exists()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--dataset-root", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    release = load(args.release.resolve())
    release_errors = validate_contract_release(release)
    records = read_records(args.input.resolve())
    dataset_root = args.dataset_root.resolve() if args.dataset_root else None
    results: list[dict[str, Any]] = []
    global_errors: list[str] = list(release_errors)
    for record in records:
        record_id = str(record.get("recordId") or record.get("taskId") or "UNKNOWN")
        sample_id = str(record.get("sampleId") or "UNKNOWN")
        result = record.get("referenceCompletion") or {}
        contract_id = str(record.get("contractId") or result.get("contractId") or "")
        errors: list[str] = []
        warnings: list[str] = []
        validation: dict[str, Any] = {"status": "FAIL", "errors": ["contract unavailable"], "checks": []}
        try:
            contract = select_contract(release, contract_id=contract_id)
        except KeyError as exc:
            errors.append(str(exc))
        else:
            context = None
            context_path = record.get("contextPackPath")
            if context_path:
                path = Path(context_path)
                if path.exists():
                    context = load(path)
                else:
                    errors.append(f"context pack missing: {context_path}")
            validation = validate_agent_result(result, contract, context)
            errors.extend(validation.get("errors", []))
            if result.get("status") == "DRAFT_REFERENCE":
                errors.append("legacy DRAFT_REFERENCE status remains in target")
            prompt_payload: dict[str, Any] = {}
            for message in record.get("messages", []) or []:
                if message.get("role") == "user":
                    try:
                        value = json.loads(str(message.get("content", "{}")))
                        if isinstance(value, dict):
                            prompt_payload = value
                    except json.JSONDecodeError:
                        pass
                    break
            output_contract = prompt_payload.get("outputContract", {}) if isinstance(prompt_payload, dict) else {}
            if output_contract.get("contractId") != contract_id:
                errors.append("prompt outputContract.contractId does not match target contract")
            if output_contract.get("requiredSections") != contract.get("requiredSections"):
                errors.append("prompt outputContract.requiredSections does not match target contract")
            prompt_statuses = str(output_contract.get("taskStatus", "")).split(" | ")
            if set(prompt_statuses) != set(contract.get("allowedTaskStatus", [])):
                errors.append("prompt outputContract.taskStatus does not match target contract")
            prompt_verdicts = str(output_contract.get("reviewVerdict", "")).split(" | ")
            if set(prompt_verdicts) != set(contract.get("allowedVerdicts", [])):
                errors.append("prompt outputContract.reviewVerdict does not match target contract")
        unresolved: list[str] = []
        context = record.get("contextPack")
        if not context and record.get("contextPackPath"):
            context = load(Path(record["contextPackPath"])) if Path(record["contextPackPath"]).exists() else None
        if context:
            for item in context.get("evidence", []) or []:
                ref = str(item.get("ref", "")) if isinstance(item, dict) else ""
                if ref and not resolve_ref(dataset_root, sample_id, ref):
                    unresolved.append(ref)
        elif record.get("evidencePack"):
            for item in record["evidencePack"].get("allowedArtifacts", []) or []:
                ref = str(item.get("ref", "")) if isinstance(item, dict) else ""
                if ref and not resolve_ref(dataset_root, sample_id, ref):
                    unresolved.append(ref)
        if unresolved:
            errors.append("unresolved evidence refs: " + ", ".join(sorted(set(unresolved))))
        if record.get("approval", {}).get("trainingApproved") is False:
            warnings.append("training approval remains pending")
        audit_status = "PASS" if not errors else "FAIL"
        results.append({
            "recordId": record_id,
            "sampleId": sample_id,
            "contractId": contract_id,
            "taskStatus": result.get("taskStatus"),
            "reviewVerdict": result.get("reviewVerdict"),
            "auditStatus": audit_status,
            "validationStatus": validation.get("status"),
            "errors": errors,
            "warnings": warnings,
            "unresolvedEvidenceRefs": sorted(set(unresolved)),
        })
    status = "PASS" if not global_errors and all(item["auditStatus"] == "PASS" for item in results) else "FAIL"
    report = {
        "schemaVersion": 1,
        "status": status,
        "checkedAt": now(),
        "records": len(results),
        "passed": sum(1 for item in results if item["auditStatus"] == "PASS"),
        "failed": sum(1 for item in results if item["auditStatus"] != "PASS"),
        "taskStatusCounts": dict(Counter(item["taskStatus"] for item in results)),
        "verdictCounts": dict(Counter(item["reviewVerdict"] for item in results)),
        "warningCounts": dict(Counter(item for row in results for item in row["warnings"])),
        "globalErrors": global_errors,
        "results": results,
    }
    if args.out:
        save(args.out, report)
    print(json.dumps({key: report[key] for key in ("status", "records", "passed", "failed", "taskStatusCounts", "verdictCounts", "warningCounts")}, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" or not args.strict else 1


if __name__ == "__main__":
    raise SystemExit(main())
